"""Grille de mobilisation d'une association : qui est disponible, créneau par créneau.

Extraite de `views.DisponibiliteOperationnelleViewSet.grille` le 12/11/2026, en même temps
qu'on lui a ajouté les campagnes. La raison de l'extraction est la même que pour
`annuaire_association.py` : l'action assemblait cinq tables dans le corps d'une vue, et la
fenêtre de campagne y ajoutait deux sources de plus.

**Le moteur reste unique.** Les cases viennent de `DisponibiliteOffre` — quatre créneaux par
jour portés par la RESSOURCE du bénévole (son offre « Bénévolat » interne), les mêmes lignes
que lit la constitution d'équipe. Sa règle est « pas de ligne = indisponible » : en base, une
grille vierge et une grille entièrement décochée sont identiques. C'est `a_declare` qui les
sépare, et lui seul dit qui relancer.

**Ce que les campagnes changent, et pourquoi il le fallait.** La grille s'ouvrait sur les
quinze prochains jours, plafonnés à trente et un. Une campagne, elle, interroge une période
nommée — « êtes-vous disponible du 12 au 26 janvier ? » — qui est souvent hors de cette
fenêtre. Les réponses étaient donc écrites en base, lues par le planificateur de tours de
garde, et **invisibles sur l'écran qui sert à armer une mobilisation**. Demande de Sylvain du
12/11/2026 : « on doit pouvoir voir aussi les disponibilités à plus long terme si demandées
lors d'une campagne ».

Trois conséquences, toutes voulues :

1. La fenêtre devient celle de la campagne (`periode_debut` → `periode_fin`), plafonnée à
   `PLAFOND_JOURS_CAMPAGNE`. Au-delà, la réponse le **dit** (`tronquee`) plutôt que de couper
   en silence.
2. Les créneaux servis deviennent ceux que la campagne a réellement posés
   (`creneaux_effectifs`). Interroger sur quatre créneaux quand la campagne n'en demandait
   qu'un ferait lire comme des refus trois colonnes auxquelles personne n'a été invité à
   répondre.
3. `a_declare` tient compte de l'état de la cible. **Zéro créneau déclaré par quelqu'un qui a
   répondu n'est pas un silence** : c'est un « je ne suis pas disponible », et le modèle le
   sait (`CibleCampagne.creneaux_declares`, dont la docstring dit exactement cela). Les
   confondre ferait relancer quelqu'un qui a déjà répondu non.

Et une quatrième, qui n'est pas un détail : un membre **non ciblé** par la campagne n'est pas
un silencieux non plus. On ne lui a rien demandé. Sa ligne porte `cible: null`, que l'écran
distingue de « sollicité, sans réponse ».
"""
import datetime

from django.db.models import Count, Q
from django.utils import timezone

#: Les quatre créneaux, dans l'ordre de la journée. Déclaré ici plutôt que déduit de
#: `Creneau.choices` : l'ordre d'un TextChoices est celui de l'écriture du code, et une
#: réorganisation du modèle réordonnerait silencieusement toutes les grilles.
CRENEAUX_ORDONNES = ["MATIN", "MIDI", "SOIR", "NUIT"]

#: Fenêtre par défaut. Quinze jours : c'est l'horizon sur lequel une association se projette
#: pour armer une garde — au-delà, les gens ne savent pas encore, et une case remplie trop tôt
#: donne une fausse certitude.
JOURS_PAR_DEFAUT = 15
#: Plafond de la fenêtre libre. Une grille de six mois n'est pas une grille, c'est un export.
PLAFOND_JOURS = 31
#: Plafond de la fenêtre d'une campagne. Plus haut que le précédent parce que la période n'est
#: pas choisie par le lecteur mais par la campagne : la tronquer à trente et un jours ferait
#: disparaître la fin d'une période de rétablissement sans que personne ne l'ait demandé.
PLAFOND_JOURS_CAMPAGNE = 92


def campagnes_consultables(institution, environnement):
    """Les campagnes dont la grille peut montrer la période.

    Les brouillons sont exclus : personne n'a encore été sollicité, il n'y a donc rien à lire —
    une fenêtre vide présentée comme une campagne ferait croire à un silence général."""
    from .models import CampagneDisponibilite, StatutCampagne

    return CampagneDisponibilite.objects.filter(
        institution=institution, environment=environnement,
        statut__in=[StatutCampagne.ENVOYEE, StatutCampagne.CLOTUREE],
    ).order_by("-periode_debut", "-date_creation")


def _resume_campagnes(campagnes):
    """Ce que le sélecteur de fenêtre affiche, et de quoi juger ce qu'on va lire.

    Le nombre de réponses est servi avec le nombre de cibles : « 8 réponses » ne veut rien dire
    sans savoir si on a écrit à dix personnes ou à quatre cents."""
    from .models import CibleCampagne, EtatCible

    campagnes = list(campagnes)
    compteurs = {
        ligne["campagne"]: ligne
        for ligne in CibleCampagne.objects.filter(
            campagne__in=[c.id for c in campagnes],
        ).values("campagne").annotate(
            total=Count("id"),
            reponses=Count("id", filter=Q(etat=EtatCible.A_REPONDU)),
        )
    }
    resumes = []
    for campagne in campagnes:
        compte = compteurs.get(campagne.id, {})
        resumes.append({
            "id": campagne.id,
            "intitule": campagne.intitule,
            "motif": campagne.motif,
            "motif_libelle": campagne.get_motif_display(),
            "statut": campagne.statut,
            "periode_debut": campagne.periode_debut,
            "periode_fin": campagne.periode_fin,
            "creneaux": campagne.creneaux_effectifs,
            "nombre_cibles": compte.get("total", 0),
            "nombre_reponses": compte.get("reponses", 0),
        })
    return resumes


def _fenetre(campagne, jours_demandes):
    """Les jours à afficher, et si on a dû couper.

    Hors campagne, la fenêtre part d'aujourd'hui : on arme une garde pour les jours qui
    viennent. Avec une campagne, elle part de SA période — qui peut être entièrement dans le
    futur, et c'est tout l'intérêt."""
    if campagne is not None:
        total = campagne.nombre_de_jours
        nb_jours = min(total, PLAFOND_JOURS_CAMPAGNE)
        debut = campagne.periode_debut
        return ([debut + datetime.timedelta(days=i) for i in range(nb_jours)],
                total > nb_jours)

    try:
        jours_demandes = int(jours_demandes)
    except (TypeError, ValueError):
        jours_demandes = JOURS_PAR_DEFAUT
    nb_jours = max(1, min(jours_demandes, PLAFOND_JOURS))
    debut = timezone.localdate()
    return [debut + datetime.timedelta(days=i) for i in range(nb_jours)], False


def grille(institution, request, jours=None, campagne=None):
    """La grille complète, telle que l'API la rend.

    `campagne` est déjà chargée et vérifiée par l'appelant (elle doit appartenir à
    l'institution) : ce module ne fait pas de contrôle d'accès, il assemble."""
    from .fiches_benevoles import TYPE_OFFRE_BENEVOLE
    from .models import (
        CibleCampagne, ContactInstitution, DisponibiliteOffre, EtatCible, Offer,
        QualificationMembre,
    )
    from .permissions import get_active_environment, nom_affichable

    environnement = get_active_environment(request)
    jours_affiches, tronquee = _fenetre(campagne, jours)
    creneaux = campagne.creneaux_effectifs if campagne is not None else list(CRENEAUX_ORDONNES)
    # L'ordre reste celui de la journée même quand la campagne a listé ses créneaux dans un
    # autre ordre : une colonne « nuit » au-dessus de « matin » se lirait de travers.
    creneaux = [c for c in CRENEAUX_ORDONNES if c in creneaux] or list(CRENEAUX_ORDONNES)

    rattachements = ContactInstitution.objects.filter(
        institution=institution, actif=True,
    ).exclude(
        statut__in=[ContactInstitution.StatutMembre.SORTI,
                    ContactInstitution.StatutMembre.CONGE],
    ).select_related("utilisateur")
    en_conge = ContactInstitution.objects.filter(
        institution=institution, actif=True,
        statut=ContactInstitution.StatutMembre.CONGE,
    ).count()

    utilisateurs = [c.utilisateur_id for c in rattachements]

    # Le MOTEUR UNIQUE : les créneaux portés par la ressource de chaque membre (son offre
    # « Bénévolat » interne). Deux requêtes pour toute la grille — les ressources, puis leurs
    # créneaux — plutôt qu'une par membre et par jour, qui ferait 15 × l'effectif.
    ressources = dict(
        Offer.objects.filter(
            author_id__in=utilisateurs, institution=institution,
            offer_type__type=TYPE_OFFRE_BENEVOLE, environment=environnement,
        ).values_list("id", "author_id")
    )
    par_utilisateur = {}
    for date_jour, creneau, offre_id in DisponibiliteOffre.objects.filter(
            offer_id__in=ressources.keys(),
            date__gte=jours_affiches[0], date__lte=jours_affiches[-1],
    ).values_list("date", "creneau", "offer_id"):
        utilisateur_id = ressources.get(offre_id)
        if utilisateur_id is None:
            continue
        par_utilisateur.setdefault(utilisateur_id, set()).add((date_jour, creneau))

    cibles = {}
    if campagne is not None:
        cibles = {
            cible.utilisateur_id: cible
            for cible in CibleCampagne.objects.filter(campagne=campagne)
        }

    aujourdhui = timezone.localdate()
    qualifications_expirees = {}
    for qualif in QualificationMembre.objects.filter(
            utilisateur_id__in=utilisateurs, environment=environnement,
            date_expiration__lt=aujourdhui):
        qualifications_expirees[qualif.utilisateur_id] = \
            qualifications_expirees.get(qualif.utilisateur_id, 0) + 1

    membres = []
    for contact in rattachements:
        siennes = par_utilisateur.get(contact.utilisateur_id, set())
        cible = cibles.get(contact.utilisateur_id)
        ligne = {
            "utilisateur": contact.utilisateur_id,
            "nom": nom_affichable(contact.utilisateur, request) or contact.utilisateur.email,
            "fonction": contact.fonction,
            "membre_bureau": contact.membre_bureau,
            # Deux signaux qui décident d'une mobilisation autant que la disponibilité : un
            # titre périmé vaut un titre absent, une aptitude échue interdit le terrain.
            "qualifications_expirees": qualifications_expirees.get(contact.utilisateur_id, 0),
            "aptitude_valide_jusquau": contact.aptitude_valide_jusquau,
            # `a_declare` distingue le silence du refus, que ce moteur ne sait pas stocker.
            # Dans une campagne, une réponse SANS aucun créneau en est une : c'est « je ne
            # suis pas disponible », et le confondre avec un silence ferait relancer quelqu'un
            # qui a déjà répondu non.
            "a_declare": bool(siennes) or (
                cible is not None and cible.etat == EtatCible.A_REPONDU),
            "jours": [
                {
                    "date": jour,
                    "creneaux": {
                        creneau: (jour, creneau) in siennes for creneau in creneaux
                    },
                }
                for jour in jours_affiches
            ],
        }
        if campagne is not None:
            # `None` et non un état par défaut : on ne lui a RIEN demandé, ce n'est pas un
            # silencieux. L'écran doit pouvoir dire lequel des deux il montre.
            ligne["cible"] = None if cible is None else {
                "etat": cible.etat,
                "etat_libelle": cible.get_etat_display(),
                "creneaux_declares": cible.creneaux_declares,
                "date_envoi": cible.date_envoi,
                "date_reponse": cible.date_reponse,
            }
        membres.append(ligne)
    membres.sort(key=lambda m: m["nom"].lower())

    return {
        "institution": institution.id,
        "institution_nom": institution.nom,
        "debut": jours_affiches[0],
        "fin": jours_affiches[-1],
        "jours": jours_affiches,
        "creneaux": creneaux,
        "membres": membres,
        # Dit, et non tu : une liste qui omet des gens sans le signaler laisse chercher.
        "membres_en_conge": en_conge,
        # Les campagnes sont servies avec la grille, et non par un second appel : le sélecteur
        # de fenêtre en a besoin dès l'ouverture de l'onglet.
        "campagnes": _resume_campagnes(campagnes_consultables(institution, environnement)),
        "campagne": None if campagne is None else campagne.id,
        # Une période plus longue que le plafond est COUPÉE, et l'écran le dit.
        "tronquee": tronquee,
    }
