"""Manifestations d'association : calendrier, postes, auto-inscription, pointage (26/11/2026).

Demande de Sylvain après l'annonce de FCBA 33 (Floirac Citizen Band Amitié) : « gestion des
plannings et inscriptions — calendrier des manifestations, des dispositifs de signalisation
radio et des exercices, inscription directe sur les créneaux selon ses disponibilités ».

- **Qui voit** : les membres actifs de l'association (ciblage_benevoles.membres_mobilisables),
  son bureau et l'administrateur. Un brouillon n'est visible que du bureau.
- **Qui organise** : le bureau (ContactInstitution.membre_bureau) et l'administrateur — comme
  recrutement_association.peut_instruire.
- **Inscription** : sur un poste complet, la personne passe en liste d'attente ; un désistement
  fait monter la première de la liste, qui est prévenue.
- **Pointage** : après coup, le bureau marque présents et absents. Un présent reçoit sa ligne
  de relevé d'heures (EngagementPersonnel, source PLANNING), qu'il peut corriger et compléter
  de ses kilomètres. Jamais deux lignes pour la même inscription.
"""
import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    ContactInstitution, EngagementPersonnel, InscriptionPoste, Manifestation, PosteManifestation,
    SourceEngagement, StatutInscriptionPoste, StatutManifestation, UserRole,
)

ACTIVES = (StatutInscriptionPoste.INSCRIT, StatutInscriptionPoste.PRESENT)


class ErreurManifestation(ValueError):
    """Geste refusé ; le message est fait pour être lu."""


def est_admin(utilisateur) -> bool:
    return getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR


def associations_organisees_par(utilisateur) -> set:
    """Les associations dont la personne est au bureau."""
    return set(ContactInstitution.objects.filter(
        utilisateur=utilisateur, actif=True, membre_bureau=True).values_list("institution_id", flat=True))


def associations_de(utilisateur) -> set:
    """Les associations dont la personne est membre actif (ou bureau)."""
    membre = set(ContactInstitution.objects.filter(
        utilisateur=utilisateur, actif=True, statut=ContactInstitution.StatutMembre.ACTIF,
    ).values_list("institution_id", flat=True))
    return membre | associations_organisees_par(utilisateur)


def organise(utilisateur, institution_id) -> bool:
    return est_admin(utilisateur) or institution_id in associations_organisees_par(utilisateur)


def visibles_par(utilisateur, environment):
    """Les manifestations que la personne voit : publiées (ou terminées, annulées) de ses
    associations, et tous les brouillons des associations qu'elle organise."""
    qs = Manifestation.objects.filter(environment=environment)
    if est_admin(utilisateur):
        return qs
    bureau = associations_organisees_par(utilisateur)
    membre = associations_de(utilisateur)
    return qs.filter(Q(institution_id__in=bureau) | (Q(institution_id__in=membre) & ~Q(statut=StatutManifestation.BROUILLON)))


def _prevenir(utilisateurs, titre, corps, manifestation, urgent=False):
    from .notifications_application import prevenir
    for u in utilisateurs:
        prevenir(u, titre, corps, urgent=urgent, lien=f"/manifestations?m={manifestation.id}",
                 institution=manifestation.institution, environment=manifestation.environment)


def _membres(manifestation):
    from django.contrib.auth import get_user_model

    from .ciblage_benevoles import membres_mobilisables
    return get_user_model().objects.filter(id__in=membres_mobilisables(manifestation.institution))


def _inscrits(manifestation):
    return {i.utilisateur for i in InscriptionPoste.objects.filter(
        poste__manifestation=manifestation, statut__in=ACTIVES + (StatutInscriptionPoste.LISTE_ATTENTE,),
    ).select_related("utilisateur")}


def _quand(m) -> str:
    debut = timezone.localtime(m.debut)
    return f"le {debut:%d/%m} à {debut:%H:%M}".replace(":", " h ")


def publier(manifestation, par):
    if not organise(par, manifestation.institution_id):
        raise ErreurManifestation("Seul le bureau de l'association publie ses manifestations.")
    if manifestation.statut != StatutManifestation.BROUILLON:
        raise ErreurManifestation("Cette manifestation n'est plus un brouillon.")
    if not manifestation.postes.exists():
        raise ErreurManifestation("Ajoutez au moins un poste avant de publier : il faut où s'inscrire.")
    manifestation.statut = StatutManifestation.PUBLIEE
    manifestation.save(update_fields=["statut", "date_maj"])
    # Les communes traversées sont invitées, avec les demandes de l'association (26/11/2026).
    from . import partage_manifestation
    # Sans demande enregistrée à la création : les quatre demandes par défaut.
    partage_manifestation.preparer(manifestation, demandes=[] if manifestation.partages.exists() else None)
    _prevenir(_membres(manifestation), f"Nouvelle manifestation : {manifestation.titre}",
              f"{manifestation.get_type_display()} {_quand(manifestation)}. Inscrivez-vous sur un poste.", manifestation)
    return manifestation


def annuler(manifestation, par, motif=""):
    if not organise(par, manifestation.institution_id):
        raise ErreurManifestation("Seul le bureau de l'association annule ses manifestations.")
    if manifestation.statut in (StatutManifestation.ANNULEE, StatutManifestation.TERMINEE):
        raise ErreurManifestation("Cette manifestation est déjà close.")
    etait_publiee = manifestation.statut == StatutManifestation.PUBLIEE
    manifestation.statut = StatutManifestation.ANNULEE
    manifestation.save(update_fields=["statut", "date_maj"])
    from . import partage_manifestation
    partage_manifestation.tout_retirer(manifestation)
    if etait_publiee:
        _prevenir(_inscrits(manifestation), f"Annulée : {manifestation.titre}",
                  f"La manifestation prévue {_quand(manifestation)} est annulée." + (f" {motif.strip()}" if motif.strip() else ""),
                  manifestation, urgent=True)
    return manifestation


def horaires_changes(manifestation):
    """Après une modification d'horaire ou de lieu d'une manifestation publiée : les inscrits sont prévenus."""
    if manifestation.statut == StatutManifestation.PUBLIEE:
        _prevenir(_inscrits(manifestation), f"Modifiée : {manifestation.titre}",
                  f"Horaires ou lieu modifiés : désormais {_quand(manifestation)}. Vérifiez votre poste.", manifestation)


def occupes(poste) -> int:
    return poste.inscriptions.filter(statut__in=ACTIVES).count()


@transaction.atomic
def inscrire(poste, utilisateur):
    """Inscrit la personne sur le poste, ou en liste d'attente s'il est complet."""
    poste = PosteManifestation.objects.select_for_update().select_related("manifestation").get(pk=poste.pk)
    m = poste.manifestation
    if m.statut != StatutManifestation.PUBLIEE:
        raise ErreurManifestation("On ne s'inscrit que sur une manifestation publiée.")
    if poste.fin <= timezone.now():
        raise ErreurManifestation("Ce poste est passé.")
    if m.institution_id not in associations_de(utilisateur):
        raise ErreurManifestation("Cette manifestation est réservée aux membres de l'association.")
    ligne, _ = InscriptionPoste.objects.get_or_create(
        poste=poste, utilisateur=utilisateur, defaults={"environment": m.environment, "statut": StatutInscriptionPoste.DESISTE})
    if ligne.statut in ACTIVES + (StatutInscriptionPoste.LISTE_ATTENTE,):
        return ligne
    ligne.statut = StatutInscriptionPoste.INSCRIT if occupes(poste) < poste.places else StatutInscriptionPoste.LISTE_ATTENTE
    ligne.inscrit_le = timezone.now()
    ligne.save(update_fields=["statut", "inscrit_le"])
    return ligne


@transaction.atomic
def desister(poste, utilisateur):
    poste = PosteManifestation.objects.select_for_update().select_related("manifestation").get(pk=poste.pk)
    ligne = InscriptionPoste.objects.filter(poste=poste, utilisateur=utilisateur).first()
    if ligne is None or ligne.statut not in (StatutInscriptionPoste.INSCRIT, StatutInscriptionPoste.LISTE_ATTENTE):
        raise ErreurManifestation("Vous n'êtes pas inscrit sur ce poste.")
    liberait = ligne.statut == StatutInscriptionPoste.INSCRIT
    ligne.statut = StatutInscriptionPoste.DESISTE
    ligne.save(update_fields=["statut"])
    if liberait:
        monter_la_liste(poste)
    return ligne


def monter_la_liste(poste):
    """Les premiers de la liste d'attente prennent les places libres, et en sont prévenus."""
    libres = poste.places - occupes(poste)
    for suivant in poste.inscriptions.filter(statut=StatutInscriptionPoste.LISTE_ATTENTE).order_by("inscrit_le")[:max(0, libres)]:
        suivant.statut = StatutInscriptionPoste.INSCRIT
        suivant.save(update_fields=["statut"])
        _prevenir([suivant.utilisateur], f"Place libérée : {poste.manifestation.titre}",
                  f"Vous passez de la liste d'attente au poste « {poste.intitule} » {_quand(poste)}.", poste.manifestation)


@transaction.atomic
def pointer(inscription, present: bool, par):
    """Présent : crée (une seule fois) la ligne de relevé d'heures de la personne, aux horaires
    du poste. Absent : retire une ligne créée par un pointage précédent, si personne ne l'a
    encore validée ni modifiée."""
    poste = inscription.poste
    m = poste.manifestation
    if not organise(par, m.institution_id):
        raise ErreurManifestation("Seul le bureau de l'association pointe les présences.")
    if inscription.statut not in ACTIVES + (StatutInscriptionPoste.ABSENT,):
        raise ErreurManifestation("Cette personne n'est pas (ou plus) inscrite sur ce poste.")
    inscription.pointe_par, inscription.pointe_le = par, timezone.now()
    if present:
        inscription.statut = StatutInscriptionPoste.PRESENT
        if inscription.engagement_id is None:
            inscription.engagement = EngagementPersonnel.objects.create(
                utilisateur=inscription.utilisateur, manifestation=m, institution=m.institution,
                parti_le=poste.debut, rentre_le=poste.fin, source=SourceEngagement.PLANNING,
                environment=m.environment,
            )
    else:
        inscription.statut = StatutInscriptionPoste.ABSENT
        ligne = inscription.engagement
        if ligne is not None and ligne.valide_le is None and not ligne.saisie_manuelle:
            inscription.engagement = None
            inscription.save(update_fields=["engagement"])
            ligne.delete()
    inscription.save(update_fields=["statut", "pointe_par", "pointe_le", "engagement"])
    return inscription


def du_jour_pour(utilisateur, environment):
    """Les manifestations où la personne est inscrite et qui ont lieu aujourd'hui (± la nuit) :
    ce que « je pars » lui propose."""
    maintenant = timezone.now()
    return (Manifestation.objects.filter(
        environment=environment, statut=StatutManifestation.PUBLIEE,
        debut__lte=maintenant + datetime.timedelta(hours=12), fin__gte=maintenant - datetime.timedelta(hours=6),
        postes__inscriptions__utilisateur=utilisateur, postes__inscriptions__statut__in=ACTIVES,
    ).distinct().order_by("debut"))


def ical(manifestations) -> str:
    """Calendrier iCalendar (RFC 5545) des manifestations données."""
    def esc(t):
        return str(t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def dt(d):
        return d.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Assista-Crise//Manifestations//FR", "CALSCALE:GREGORIAN"]
    maintenant = dt(timezone.now())
    for m in manifestations:
        statut = "CANCELLED" if m.statut == StatutManifestation.ANNULEE else "CONFIRMED"
        lignes += ["BEGIN:VEVENT", f"UID:{m.id}@assista-crise", f"DTSTAMP:{maintenant}", f"DTSTART:{dt(m.debut)}",
                   f"DTEND:{dt(m.fin)}", f"SUMMARY:{esc(m.titre)}", f"LOCATION:{esc(m.lieu)}", f"STATUS:{statut}", "END:VEVENT"]
    lignes.append("END:VCALENDAR")
    return "\r\n".join(lignes) + "\r\n"
