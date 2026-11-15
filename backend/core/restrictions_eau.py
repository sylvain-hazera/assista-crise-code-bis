"""Restrictions d'usage de l'eau (sécheresse) : relevé de VigiEau, copie en base.

SOURCE
VigiEau (https://vigieau.gouv.fr), ministère de la Transition écologique, Licence Ouverte 2.0.
Aucune clé. Les arrêtés préfectoraux de restriction en vigueur, résumés par département : le
niveau de gravité le plus élevé pour les eaux superficielles, les eaux souterraines et l'eau
potable. Quatre niveaux : vigilance, alerte, alerte renforcée, crise.

CE QU'ON RELÈVE, ET CE QU'ON NE RELÈVE PAS
Un appel national par relevé, qui rend les 101 départements. Le détail par commune existe chez
VigiEau, mais il faudrait le demander commune par commune -- donc dire à un service extérieur
quelles communes utilisent cette plateforme. On s'en tient au département, et l'écran renvoie
vers vigieau.gouv.fr pour le détail d'une adresse : le niveau le plus élevé du département ne
s'applique pas forcément à toute commune, il faut le dire.

Les données du jour paraissent dans la matinée : tant qu'elles n'y sont pas, on prend celles de
la veille.
"""
import datetime
import logging

import requests
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

URL = "https://api.vigieau.gouv.fr/api/departements"
DELAI_REPONSE_S = 30
# Du moins grave au plus grave. L'ordre sert au tri et à la comparaison.
NIVEAUX = ("vigilance", "alerte", "alerte_renforcee", "crise")
LIBELLES = {"vigilance": "Vigilance", "alerte": "Alerte", "alerte_renforcee": "Alerte renforcée",
            "crise": "Crise"}
JOURS_ESSAYES = 3
MINIMUM_PLAUSIBLE = 90


def telecharger(maintenant=None):
    """(date des données, liste des départements). Recule d'un jour tant que la date demandée
    n'est pas encore publiée (le service répond alors 404)."""
    jour = (maintenant or timezone.now()).date()
    for recul in range(JOURS_ESSAYES):
        date = jour - datetime.timedelta(days=recul)
        reponse = requests.get(URL, params={"date": date.isoformat()}, timeout=DELAI_REPONSE_S)
        if reponse.status_code == 404:
            continue
        reponse.raise_for_status()
        donnees = reponse.json()
        if isinstance(donnees, list) and donnees:
            return date, donnees
    raise ValueError("aucune donnée VigiEau publiée sur les derniers jours")


def _niveau(valeur):
    return valeur if valeur in NIVEAUX else ""


def analyser(donnees):
    """Réponse de VigiEau -> dictionnaires prêts pour RestrictionEau."""
    departements = []
    for brut in donnees:
        code = str(brut.get("code") or "").strip()
        if not 2 <= len(code) <= 3:
            continue
        departements.append({
            "departement_code": code,
            "niveau": _niveau(brut.get("niveauGraviteMax")),
            "niveau_superficielle": _niveau(brut.get("niveauGraviteSupMax")),
            "niveau_souterraine": _niveau(brut.get("niveauGraviteSouMax")),
            "niveau_potable": _niveau(brut.get("niveauGraviteAepMax")),
        })
    return departements


def enregistrer(date, departements, maintenant=None):
    from .models import RestrictionEau

    if len(departements) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(departements)} départements seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    lignes = [RestrictionEau(date_donnees=date, releve_le=maintenant, **d) for d in departements]
    with transaction.atomic():
        RestrictionEau.objects.bulk_create(
            lignes, update_conflicts=True, unique_fields=["departement_code"],
            update_fields=["niveau", "niveau_superficielle", "niveau_souterraine", "niveau_potable",
                           "date_donnees", "releve_le"],
        )
    return len(lignes)


def relever(maintenant=None):
    date, donnees = telecharger(maintenant)
    return enregistrer(date, analyser(donnees), maintenant)
