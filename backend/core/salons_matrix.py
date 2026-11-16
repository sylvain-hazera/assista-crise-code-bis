"""Création automatique des salons Matrix : « une institution = un canal pour ses cadres et un
pour ses intervenants ; une équipe = un canal ; une mission = un canal ».

LA RÈGLE (posée par Sylvain le 16/11/2026)
Les équipes créées depuis l'écran naissent déjà avec leurs salons (13/11/2026, voir
matrix.provisionner_salons_equipe). Restaient trois retards : les institutions, qui n'en avaient
que par un bouton que personne ne pressait ; les missions, qui ne pouvaient pas en avoir ; et tout
ce qui existait avant. Ce module les comble :

- institution : le salon de ses cadres (PERMANENTS) et celui de ses intervenants (BENEVOLES),
  dès son premier rattachement. Le salon ANNONCES reste à la demande : c'est une diffusion
  d'association, pas un canal de travail.
- mission : son salon, dès qu'une équipe lui est affectée et tant qu'elle n'est pas terminée.
- équipe : rien de neuf à la création (c'est déjà fait) ; le rattrapage donne leurs deux salons
  aux équipes anciennes qui ont des membres.

UN SALON NE NAÎT QUE S'IL Y A QUELQU'UN À Y METTRE
C'est la décision du 11/11/2026, prise pour l'arborescence de coordination (127 équipes auraient
fait 254 salons, presque tous vides et tous affichés dans Element), et elle vaut ici pour les
trois natures : pas de salon d'institution sans membre, pas de salon d'équipe sans équipier, pas
de salon de mission sans équipe. Un salon vide n'est pas un canal, c'est du bruit.

Ce module ne crée que la LIGNE côté Django ; c'est le pont matrix-bridge qui crée le salon côté
Synapse à son passage suivant et en tient la composition à jour (voir matrix-bridge/bridge.py).

AUTRE GARDE-FOU
Production seulement. La zone de démonstration garde ses salons à la demande : y créer d'office
un salon par objet fictif encombrerait le serveur Matrix de centaines de salons vides.

Tout est idempotent : appeler deux fois ne crée rien de plus.
"""
import logging

from .models import (
    ContactInstitution, Environment, Institution, Mission, SalonMatrixEquipe,
    SalonMatrixInstitution, SalonMatrixMission, Team, TypeSalonEquipe, TypeSalonInstitution,
)

logger = logging.getLogger(__name__)

TYPES_INSTITUTION = (TypeSalonInstitution.PERMANENTS, TypeSalonInstitution.BENEVOLES)
TYPES_EQUIPE = (TypeSalonEquipe.INTERVENANTS, TypeSalonEquipe.ENCADREMENT)


def _en_production(objet) -> bool:
    return getattr(objet, "environment", Environment.PROD) == Environment.PROD


def assurer_salons_institution(institution) -> int:
    """Crée les salons de cadres et d'intervenants d'une institution, s'ils manquent et si
    quelqu'un y est rattaché. Rend le nombre de salons créés."""
    if institution is None or not _en_production(institution) or not institution.actif:
        return 0
    if not ContactInstitution.objects.filter(institution=institution, actif=True).exists():
        return 0
    crees = 0
    for type_salon in TYPES_INSTITUTION:
        _salon, cree = SalonMatrixInstitution.objects.get_or_create(
            institution=institution, type=type_salon, defaults={"environment": institution.environment})
        crees += cree
    return crees


def assurer_salons_equipe(equipe) -> int:
    """Crée les deux salons d'une équipe active qui a des membres, s'ils manquent."""
    if equipe is None or not _en_production(equipe) or not equipe.actif:
        return 0
    if not (equipe.members.exists() or equipe.membres_encadrement.exists()):
        return 0
    crees = 0
    for type_salon in TYPES_EQUIPE:
        # `crise=None` : les salons de tous les jours. Une équipe peut en avoir d'autres, un
        # par crise (core/salons_de_crise.py), et sans ce critère get_or_create en trouverait
        # plusieurs.
        _salon, cree = SalonMatrixEquipe.objects.get_or_create(
            equipe=equipe, type=type_salon, crise=None, defaults={"environment": equipe.environment})
        crees += cree
    return crees


def assurer_salon_mission(mission) -> int:
    """Crée le salon d'une mission non terminée à laquelle une équipe est affectée, s'il manque."""
    if mission is None or not _en_production(mission) or mission.statut == Mission.Statut.TERMINEE:
        return 0
    if not mission.equipes.exists():
        return 0
    _salon, cree = SalonMatrixMission.objects.get_or_create(
        mission=mission, defaults={"environment": mission.environment})
    return int(cree)


def rattraper() -> dict:
    """Crée tout ce qui manque pour l'existant. Rend le nombre de salons créés par nature."""
    bilan = {"institutions": 0, "equipes": 0, "missions": 0}
    avec_membres = ContactInstitution.objects.filter(actif=True).values("institution_id")
    for institution in Institution.objects.filter(
            actif=True, environment=Environment.PROD, id__in=avec_membres):
        bilan["institutions"] += assurer_salons_institution(institution)
    for equipe in Team.objects.filter(actif=True, environment=Environment.PROD):
        bilan["equipes"] += assurer_salons_equipe(equipe)
    for mission in Mission.objects.filter(environment=Environment.PROD).exclude(
            statut=Mission.Statut.TERMINEE):
        bilan["missions"] += assurer_salon_mission(mission)
    return bilan


# ── Signaux : chaque objet naît avec ses salons ──
#
# Un échec ici ne doit jamais empêcher de créer une équipe ou une mission : le salon est un
# confort, l'objet est l'essentiel. On journalise et on laisse passer ; le rattrapage planifié
# (commande `rattraper_salons_matrix`) reprendra ce qui a manqué.

def _sans_bloquer(action, objet):
    try:
        action(objet)
    except Exception:       # noqa: BLE001 -- voir le commentaire ci-dessus
        logger.exception("Salons Matrix : création automatique impossible pour %r.", objet)


def equipes_de_mission_modifiees(sender, instance, action, reverse, pk_set=None, **kwargs):
    """Une équipe vient d'être affectée à une mission : la mission a quelqu'un à réunir, donc
    son salon. Le signal vaut dans les deux sens de la relation (mission.equipes.add ou
    equipe.missions.add)."""
    if action != "post_add":
        return
    if reverse:
        for mission in Mission.objects.filter(pk__in=pk_set or ()):
            _sans_bloquer(assurer_salon_mission, mission)
    else:
        _sans_bloquer(assurer_salon_mission, instance)


def rattachement_enregistre(sender, instance, created, **kwargs):
    """Le premier membre d'une institution lui donne ses salons."""
    if not kwargs.get("raw") and instance.actif:
        _sans_bloquer(assurer_salons_institution, instance.institution)
