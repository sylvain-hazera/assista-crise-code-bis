"""Stations-service : relevé du flux instantané des prix des carburants, copie en base.

SOURCE
« Prix des carburants en France - flux instantané » (ministère de l'Économie,
https://data.economie.gouv.fr), Licence Ouverte 2.0. Aucune clé. Les stations déclarent
elles-mêmes leurs prix et leurs ruptures ; le portail republie toutes les dix minutes.

CE QUI SERT ICI
Pas le prix : la RUPTURE. Une rupture temporaire dit qu'une station n'a plus un carburant
qu'elle vend d'ordinaire -- c'est le signal d'une pénurie qui s'installe, et la réponse à « où
les véhicules d'intervention peuvent-ils encore faire le plein ». Une rupture définitive dit
seulement que la station ne vend pas ce carburant : on la garde à part pour ne pas la confondre.

Un seul appel rapporte les ~9 800 stations de France (6 Mo, champs restreints au nécessaire).
Même règle que le reste de la veille : seul le serveur appelle, pour la France entière.
"""
import logging

import requests
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL_EXPORT = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
              "prix-des-carburants-en-france-flux-instantane-v2/exports/json")
DELAI_REPONSE_S = 120

# Nom affiché -> préfixe des champs `<préfixe>_prix` / `<préfixe>_maj` du jeu de données.
CARBURANTS = {
    "Gazole": "gazole", "SP95": "sp95", "SP98": "sp98", "E10": "e10", "E85": "e85", "GPLc": "gplc",
}
_CHAMPS = ["id", "geom", "cp", "adresse", "ville", "code_departement", "carburants_disponibles",
           "carburants_rupture_temporaire", "carburants_rupture_definitive",
           "horaires_automate_24_24"]
_CHAMPS += [f"{prefixe}_{suffixe}" for prefixe in CARBURANTS.values() for suffixe in ("prix", "maj")]

# En dessous, l'export est tronqué ou le portail a changé : on garde la copie précédente plutôt
# que d'effacer neuf mille stations.
MINIMUM_PLAUSIBLE = 5000


def telecharger():
    reponse = requests.get(URL_EXPORT, params={"select": ",".join(_CHAMPS)}, timeout=DELAI_REPONSE_S)
    reponse.raise_for_status()
    return reponse.json()


def _liste(valeur):
    """Le portail rend tantôt une liste, tantôt « SP95;E85 », tantôt rien."""
    if isinstance(valeur, list):
        return [str(v) for v in valeur if v]
    if isinstance(valeur, str):
        return [v.strip() for v in valeur.split(";") if v.strip()]
    return []


def analyser(enregistrements):
    """Enregistrements du portail -> dictionnaires prêts pour StationCarburant. Une station sans
    identifiant ou sans position est ignorée."""
    stations = []
    for brut in enregistrements:
        geom = brut.get("geom") or {}
        try:
            reference = str(brut["id"])
            position = Point(float(geom["lon"]), float(geom["lat"]), srid=4326)
        except (KeyError, TypeError, ValueError):
            continue
        prix, dates = {}, []
        for nom, prefixe in CARBURANTS.items():
            valeur = brut.get(f"{prefixe}_prix")
            if valeur is None:
                continue
            maj = brut.get(f"{prefixe}_maj")
            prix[nom] = {"prix": valeur, "maj": maj}
            instant = parse_datetime(maj) if maj else None
            if instant:
                dates.append(instant)
        departement = str(brut.get("code_departement") or "").strip()
        stations.append({
            "reference": reference[:20],
            "adresse": (brut.get("adresse") or "").strip()[:255],
            "ville": (brut.get("ville") or "").strip()[:120],
            "code_postal": str(brut.get("cp") or "").strip()[:10],
            "departement_code": departement if 2 <= len(departement) <= 3 else None,
            "location": position,
            "carburants_disponibles": _liste(brut.get("carburants_disponibles")),
            "ruptures_temporaires": _liste(brut.get("carburants_rupture_temporaire")),
            "ruptures_definitives": _liste(brut.get("carburants_rupture_definitive")),
            "prix": prix,
            "automate_24_24": brut.get("horaires_automate_24_24") == "Oui",
            "mis_a_jour_le": max(dates) if dates else None,
        })
    return stations


def enregistrer(stations, maintenant=None):
    """Remplace la copie : écrit les stations du flux, supprime celles qui n'y sont plus."""
    from .models import StationCarburant

    if len(stations) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(stations)} stations seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    lignes = [StationCarburant(releve_le=maintenant, **station) for station in stations]
    champs = [champ for champ in stations[0] if champ != "reference"] + ["releve_le"]
    with transaction.atomic():
        StationCarburant.objects.bulk_create(
            lignes, batch_size=1000, update_conflicts=True, unique_fields=["reference"],
            update_fields=champs,
        )
        StationCarburant.objects.exclude(reference__in=[l.reference for l in lignes]).delete()
    return len(lignes)


def relever():
    return enregistrer(analyser(telecharger()))
