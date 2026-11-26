"""Ce que la commune partage avec l'association pour une manifestation (26/11/2026).

Demande de Sylvain : « quand une association crée une manifestation il faut qu'elle invite la
commune et demande à la commune les droits pour voir les éléments intéressants […] un tableau de
ce que l'association demande à voir et que la commune accepte. L'enjeu n'est pas fort,
l'association, hors crise, ne devrait pas demander le PCS. » Puis : ce qui est exclu pour
l'association « doit pouvoir être rajouté au cas par cas si la mairie décide de profiter de
l'association pour leur demander d'intervenir et d'aider à la gestion de crise ».

- L'association DEMANDE au plus quatre éléments (DEMANDABLES) ; seule la mairie accepte ou refuse.
- La mairie seule OFFRE les éléments sensibles (OFFRABLES) : intervenir sur une crise, PCS en
  lecture, registre des personnes vulnérables (qui renvoie à la désignation nominative existante).
- Tout ne vaut que de la veille du début au lendemain de la fin de la manifestation ; une
  manifestation annulée retire tout.
"""
import datetime

from django.db import transaction
from django.utils import timezone

from .models import (
    ContactInstitution, ElementPartage, InvitationCommune, LignePartage, OriginePartage, PartageManifestation,
    StatutLignePartage, StatutManifestation,
)

DEMANDABLES = [ElementPartage.CONTACT_JOUR_J, ElementPartage.ALERTES_COMMUNE, ElementPartage.CRISE_COMMUNE,
               ElementPartage.CONSIGNES_ARRETE]
OFFRABLES = [ElementPartage.INTERVENTION_CRISE, ElementPartage.PCS_LECTURE, ElementPartage.REGISTRE_VULNERABLES]

#: Ce que chaque élément ouvre, dit à la mairie avant qu'elle décide.
EXPLICATIONS = {
    ElementPartage.CONTACT_JOUR_J: "Le nom et le téléphone de la personne que vous désignez, joignable pendant la manifestation.",
    ElementPartage.ALERTES_COMMUNE: "Vos alertes automatiques (météo, crue, orage…) vont aussi au bureau et aux inscrits pendant la manifestation.",
    ElementPartage.CRISE_COMMUNE: "Si une crise s'ouvre sur la commune pendant la manifestation, l'association en est prévenue et voit son nom et son état.",
    ElementPartage.CONSIGNES_ARRETE: "Vos consignes et votre arrêté (circulation, stationnement) sont joints à la manifestation, visibles des inscrits.",
    ElementPartage.INTERVENTION_CRISE: "L'association devient acteur de la crise que vous choisissez, pour votre commune : dossiers et main courante selon les règles habituelles.",
    ElementPartage.PCS_LECTURE: "Le bureau de l'association peut télécharger votre plan communal de sauvegarde (annuaire compris) pendant la manifestation.",
    ElementPartage.REGISTRE_VULNERABLES: "Vous désignez nommément des membres de l'association sur le registre (engagement au secret compris) : rien n'est ouvert sans cette désignation.",
}


class ErreurPartage(ValueError):
    """Geste refusé ; le message est fait pour être lu."""


def fenetre(manifestation):
    """De la veille du début au lendemain de la fin."""
    return manifestation.debut - datetime.timedelta(days=1), manifestation.fin + datetime.timedelta(days=1)


def en_vigueur(manifestation, maintenant=None) -> bool:
    if manifestation.statut not in (StatutManifestation.PUBLIEE, StatutManifestation.TERMINEE):
        return False
    debut, fin = fenetre(manifestation)
    return debut <= (maintenant or timezone.now()) <= fin


def accorde(partage, element, maintenant=None) -> bool:
    """L'élément est-il ouvert, maintenant, pour ce partage ?"""
    return en_vigueur(partage.manifestation, maintenant) and partage.lignes.filter(
        element=element, statut=StatutLignePartage.ACCEPTE).exists()


def mairie_de(commune_code):
    from .models import Institution
    return Institution.objects.filter(type__code__iexact="mairie", commune_code=commune_code, actif=True).first()


def communes_de(manifestation) -> list:
    communes = [c for c in (manifestation.communes or []) if c]
    if not communes and manifestation.commune_code:
        communes = [manifestation.commune_code]
    return list(dict.fromkeys(communes))


def membres_actifs_de(institution):
    from django.contrib.auth import get_user_model
    ids = ContactInstitution.objects.filter(institution=institution, actif=True).values_list("utilisateur_id", flat=True)
    return list(get_user_model().objects.filter(id__in=[i for i in ids if i], is_active=True))


def _libelle_demandes(elements) -> str:
    return ", ".join(ElementPartage(e).label.lower() for e in elements) or "aucune demande particulière"


@transaction.atomic
def preparer(manifestation, demandes=None, request=None):
    """Un partage par commune traversée, avec les demandes de l'association (toutes par défaut).
    Rejouable : ne recrée rien, n'ajoute que les demandes et communes nouvelles. Les communes ne sont
    invitées qu'une fois la manifestation publiée (voir inviter_les_communes)."""
    demandes = [d for d in (demandes if demandes is not None else DEMANDABLES) if d in DEMANDABLES]
    for code in communes_de(manifestation):
        partage, _ = PartageManifestation.objects.get_or_create(
            manifestation=manifestation, commune_code=code,
            defaults={"mairie": mairie_de(code), "environment": manifestation.environment})
        for element in demandes:
            LignePartage.objects.get_or_create(partage=partage, element=element, defaults={
                "origine": OriginePartage.DEMANDE_ASSOCIATION, "environment": manifestation.environment})
    if manifestation.statut == StatutManifestation.PUBLIEE:
        inviter_les_communes(manifestation, request)
    return list(manifestation.partages.all())


def inviter_les_communes(manifestation, request=None):
    """À la publication : chaque commune pas encore invitée l'est."""
    for partage in manifestation.partages.filter(invitation="").select_related("mairie"):
        demandes = list(partage.lignes.filter(origine=OriginePartage.DEMANDE_ASSOCIATION).values_list("element", flat=True))
        partage.invitation = inviter(partage, demandes, request)
        partage.save(update_fields=["invitation"])


def inviter(partage, demandes, request=None) -> str:
    """Prévient la mairie (membres actifs), ou l'invite par courriel à rejoindre la plateforme."""
    m = partage.manifestation
    mairie = partage.mairie
    quand = timezone.localtime(m.debut).strftime("%d/%m/%Y")
    texte = (f"{m.institution.nom} organise « {m.titre} » le {quand} sur votre commune"
             + (f" ({m.lieu})" if m.lieu else "") + f". Elle vous demande : {_libelle_demandes(demandes)}. "
             "Vous décidez ligne par ligne dans « Manifestations sur ma commune ».")
    if mairie is not None:
        membres = membres_actifs_de(mairie)
        if membres:
            from .notifications_application import prevenir
            for u in membres:
                prevenir(u, f"Manifestation sur votre commune : {m.titre}", texte, lien="/admin/manifestations-commune",
                         institution=mairie, environment=m.environment)
            return InvitationCommune.PREVENUE
        destinataire = mairie.email
        try:
            from .models import ReferentCollectivite
            referent = ReferentCollectivite.objects.filter(institution=mairie).first()
            destinataire = (referent.email if referent and referent.email else None) or mairie.email
        except Exception:  # noqa: BLE001 -- un référent illisible n'empêche pas l'adresse officielle
            pass
        if destinataire:
            from . import invitation_collectivite
            from .branding import send_branded_mail
            invitation = invitation_collectivite.invitation_pour(mairie, None, destinataire, getattr(request, "user", None)
                                                                 or m.cree_par)
            message = (f"Bonjour,\n\n{texte.replace(' Vous décidez ligne par ligne dans « Manifestations sur ma commune ».', '')}\n\n"
                       f"Pour lui répondre, ouvrez l'espace de {mairie.nom} sur la plateforme avec ce lien, puis "
                       f"« Manifestations sur ma commune » :\n{invitation_collectivite.lien(invitation)}\n\n{{signature}}")
            try:
                send_branded_mail(request, m.institution, subject=f"{m.institution.nom} : manifestation sur votre commune",
                                  message=message, recipient_list=[destinataire], fail_silently=True)
            except Exception:  # noqa: BLE001 -- l'invitation reste enregistrée, relançable
                pass
            return InvitationCommune.INVITEE
    return InvitationCommune.INJOIGNABLE


def _peut_decider(partage, utilisateur) -> bool:
    from .models import UserRole
    if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
        return True
    return partage.mairie_id is not None and ContactInstitution.objects.filter(
        institution_id=partage.mairie_id, utilisateur=utilisateur, actif=True).exists()


@transaction.atomic
def decider(ligne, utilisateur, geste, crise=None):
    """La mairie : accepter / refuser une demande ; offrir / retirer un élément."""
    partage = ligne.partage if isinstance(ligne, LignePartage) else ligne
    if not _peut_decider(partage, utilisateur):
        raise ErreurPartage("Seule la mairie de la commune décide de ce qu'elle partage.")
    if partage.manifestation.statut == StatutManifestation.ANNULEE:
        raise ErreurPartage("Cette manifestation est annulée.")
    maintenant = timezone.now()
    if geste in ("accepter", "refuser"):
        if ligne.statut not in (StatutLignePartage.DEMANDE, StatutLignePartage.REFUSE, StatutLignePartage.ACCEPTE):
            raise ErreurPartage("Cette ligne a été retirée.")
        ligne.statut = StatutLignePartage.ACCEPTE if geste == "accepter" else StatutLignePartage.REFUSE
    elif geste == "retirer":
        ligne.statut = StatutLignePartage.RETIRE
    else:
        raise ErreurPartage("Geste inconnu.")
    ligne.decide_par, ligne.decide_le = utilisateur, maintenant
    ligne.save(update_fields=["statut", "decide_par", "decide_le"])
    return ligne


@transaction.atomic
def offrir(partage, utilisateur, element, crise=None):
    """La mairie ouvre un élément réservé (ou rouvre un élément retiré)."""
    if element not in OFFRABLES:
        raise ErreurPartage("Cet élément ne s'offre pas : l'association le demande, vous l'acceptez.")
    if not _peut_decider(partage, utilisateur):
        raise ErreurPartage("Seule la mairie de la commune décide de ce qu'elle partage.")
    if partage.manifestation.statut == StatutManifestation.ANNULEE:
        raise ErreurPartage("Cette manifestation est annulée.")
    if element == ElementPartage.INTERVENTION_CRISE:
        if crise is None or crise.end_date is not None:
            raise ErreurPartage("Choisissez une crise ouverte sur votre commune.")
        if partage.commune_code not in (crise.zone_communes or []):
            raise ErreurPartage("Cette crise ne touche pas votre commune.")
        engager(partage, crise, utilisateur)
    ligne, _ = LignePartage.objects.get_or_create(partage=partage, element=element, defaults={
        "origine": OriginePartage.OFFERT_MAIRIE, "environment": partage.environment})
    ligne.origine = OriginePartage.OFFERT_MAIRIE
    ligne.statut, ligne.decide_par, ligne.decide_le, ligne.crise = StatutLignePartage.ACCEPTE, utilisateur, timezone.now(), crise
    ligne.save()
    from .notifications_application import prevenir
    for u in _bureau(partage.manifestation.institution):
        prevenir(u, f"{partage.mairie.nom if partage.mairie else 'La mairie'} vous ouvre : {ElementPartage(element).label.lower()}",
                 EXPLICATIONS[element], lien=f"/manifestations?m={partage.manifestation_id}",
                 institution=partage.manifestation.institution, environment=partage.environment)
    return ligne


def engager(partage, crise, utilisateur):
    """L'association devient acteur validé de la crise, pour cette commune."""
    from .models import ImplicationInstitution, StatutImplication, TypeImplication
    association = partage.manifestation.institution
    implication = ImplicationInstitution.objects.filter(crise=crise, institution=association,
                                                        type_implication=TypeImplication.ACTEUR).first()
    if implication is None:
        implication = ImplicationInstitution.objects.create(
            crise=crise, institution=association, utilisateur=utilisateur, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE, communes=[partage.commune_code], environment=crise.environment,
            commentaire=f"Engagée par {partage.mairie.nom if partage.mairie else 'la mairie'} depuis la manifestation « {partage.manifestation.titre} »",
        )
    else:
        communes = list(dict.fromkeys(list(implication.communes or []) + [partage.commune_code]))
        implication.communes, implication.statut, implication.actif = communes, StatutImplication.VALIDEE, True
        implication.save(update_fields=["communes", "statut", "actif"])
    return implication


def _bureau(institution):
    from django.contrib.auth import get_user_model
    ids = ContactInstitution.objects.filter(institution=institution, actif=True, membre_bureau=True).values_list("utilisateur_id", flat=True)
    return list(get_user_model().objects.filter(id__in=[i for i in ids if i], is_active=True))


def personnes_de_la_manifestation(manifestation):
    """Le bureau de l'association et les inscrits (inscrits, présents) de la manifestation."""
    from django.contrib.auth import get_user_model

    from .manifestations import ACTIVES
    from .models import InscriptionPoste
    ids = set(u.id for u in _bureau(manifestation.institution))
    ids |= set(InscriptionPoste.objects.filter(poste__manifestation=manifestation, statut__in=ACTIVES)
               .values_list("utilisateur_id", flat=True))
    return list(get_user_model().objects.filter(id__in=ids, is_active=True))


def personnes_alertees(mairie, maintenant=None):
    """Pour les alertes automatiques d'une mairie : les personnes des manifestations en cours qui
    ont obtenu « alertes de la commune »."""
    personnes = {}
    for partage in PartageManifestation.objects.filter(mairie=mairie).select_related("manifestation__institution"):
        if accorde(partage, ElementPartage.ALERTES_COMMUNE, maintenant):
            for u in personnes_de_la_manifestation(partage.manifestation):
                personnes[u.id] = u
    return list(personnes.values())


def crise_enregistree(sender, instance, **kwargs):
    """Signal : une crise ouverte touche une commune où une manifestation a obtenu « crise sur la
    commune » → bureau et inscrits prévenus, une seule fois par crise et par commune."""
    if instance.end_date is not None:
        return
    communes = set(instance.zone_communes or [])
    if not communes:
        return
    from .notifications_application import prevenir
    for partage in PartageManifestation.objects.filter(commune_code__in=communes).select_related("manifestation__institution", "mairie"):
        if str(instance.id) in (partage.crises_signalees or []) or not accorde(partage, ElementPartage.CRISE_COMMUNE):
            continue
        partage.crises_signalees = list(partage.crises_signalees or []) + [str(instance.id)]
        partage.save(update_fields=["crises_signalees"])
        for u in personnes_de_la_manifestation(partage.manifestation):
            prevenir(u, f"Crise sur la commune : {instance.name}",
                     f"Une crise est ouverte sur une commune de « {partage.manifestation.titre} ». Suivez les consignes de la mairie.",
                     urgent=True, lien=f"/manifestations?m={partage.manifestation_id}",
                     institution=partage.manifestation.institution, environment=partage.environment)


def tout_retirer(manifestation):
    """Manifestation annulée : plus rien n'est partagé."""
    LignePartage.objects.filter(partage__manifestation=manifestation).exclude(statut=StatutLignePartage.RETIRE) \
        .update(statut=StatutLignePartage.RETIRE, decide_le=timezone.now())


# --- Ce que voit l'association, ce que voit la mairie ------------------------------------------

def tableau(partage, pour_mairie=False) -> dict:
    lignes = {l.element: l for l in partage.lignes.all()}
    elements = DEMANDABLES + OFFRABLES if pour_mairie else [e for e in DEMANDABLES + OFFRABLES if e in lignes]
    vigueur = en_vigueur(partage.manifestation)
    rangs = []
    for e in elements:
        l = lignes.get(e)
        rangs.append({
            "element": e, "libelle": ElementPartage(e).label, "explication": EXPLICATIONS[e],
            "reserve_mairie": e in OFFRABLES, "origine": l.origine if l else None,
            "statut": l.statut if l else None, "statut_libelle": l.get_statut_display() if l else "Non demandé",
            "en_vigueur": bool(l and l.statut == StatutLignePartage.ACCEPTE and vigueur),
            "crise": str(l.crise_id) if l and l.crise_id else None, "id": str(l.id) if l else None,
        })
    return {
        "id": str(partage.id), "commune_code": partage.commune_code,
        "mairie": partage.mairie.nom if partage.mairie else None, "invitation": partage.invitation,
        "invitation_libelle": partage.get_invitation_display(), "lignes": rangs,
    }


def ce_qui_est_ouvert(partage) -> dict:
    """Pour la fiche de la manifestation, côté association : seulement ce qui est accordé et en vigueur."""
    ouvert = {}
    if accorde(partage, ElementPartage.CONTACT_JOUR_J) and (partage.referent_nom or partage.referent_telephone):
        ouvert["contact"] = {"nom": partage.referent_nom, "telephone": partage.referent_telephone}
    if accorde(partage, ElementPartage.CONSIGNES_ARRETE):
        ouvert["consignes"] = partage.consignes
        ouvert["arrete"] = partage.arrete_nom if partage.arrete else ""
    if accorde(partage, ElementPartage.CRISE_COMMUNE):
        from .models import Crisis
        crises = [c for c in Crisis.objects.filter(end_date__isnull=True, environment=partage.environment)
                  if partage.commune_code in (c.zone_communes or [])]
        ouvert["crises"] = [{"id": str(c.id), "nom": c.name} for c in crises]
    ouvert["pcs"] = accorde(partage, ElementPartage.PCS_LECTURE)
    return ouvert
