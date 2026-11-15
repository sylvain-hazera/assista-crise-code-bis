"""Vigilance crues par tronçon de cours d'eau : relevé de la carte Vigicrues, copie en base.

SOURCE
Vigicrues (https://www.vigicrues.gouv.fr), service central d'hydrométéorologie -- réseau des
services de prévision des crues, Licence Ouverte 2.0. Aucune clé. Un fichier national d'environ
2 Mo : les 337 tronçons surveillés, leur tracé, et leur niveau de vigilance (1 vert, 2 jaune,
3 orange, 4 rouge). Publié deux fois par jour, et à chaque aggravation.

POURQUOI EN PLUS DE LA VIGILANCE MÉTÉO-FRANCE
La vigilance « crues » de Météo-France est donnée par DÉPARTEMENT : elle dit qu'un cours d'eau
du département est en vigilance, pas lequel. Ici, c'est le tronçon lui-même, tracé sur la
carte : une mairie voit si c'est sa rivière.

CE QUE LA CARTE NE DIT PAS
Vigicrues ne surveille qu'une partie du réseau hydrographique (23 000 km de cours d'eau). Un
ruisseau, un torrent, un petit affluent n'y figurent pas : l'absence de tronçon près d'une
commune ne veut pas dire qu'elle est à l'abri. L'écran doit le rappeler.

core/hydrometrie.py lit le même fichier pour la simulation d'inondation d'une commune, avec son
propre cache ; ce module-ci en tient la copie nationale pour la carte et la veille. Même règle
que le reste de la veille : seul le serveur appelle, pour la France entière.
"""
import logging

import requests
from django.contrib.gis.geos import GEOSGeometry, MultiLineString
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL_FLUX = "https://www.vigicrues.gouv.fr/services/InfoVigiCru.geojson"
DELAI_REPONSE_S = 60
COULEURS = {1: "vert", 2: "jaune", 3: "orange", 4: "rouge"}
# En dessous, le fichier est tronqué : on garde la copie précédente.
MINIMUM_PLAUSIBLE = 100


def telecharger():
    reponse = requests.get(URL_FLUX, timeout=DELAI_REPONSE_S)
    reponse.raise_for_status()
    return reponse.json()


def analyser(donnees):
    """Fichier Vigicrues -> (heure de publication, [dictionnaires prêts pour
    TronconVigilanceCrues]). Un tronçon sans code, sans tracé ou au niveau illisible est ignoré."""
    import json

    publie_le = parse_datetime(str(donnees.get("DtHrInfoVigiCru") or ""))
    troncons = []
    for element in donnees.get("features") or []:
        proprietes = element.get("properties") or {}
        code = str(proprietes.get("CdEntCru") or "").strip()
        try:
            niveau = int(proprietes.get("NivInfViCr"))
            geometrie = GEOSGeometry(json.dumps(element.get("geometry")), srid=4326)
        except (TypeError, ValueError, Exception):   # noqa: B014 -- GEOS lève ses propres erreurs
            continue
        if not code or niveau not in COULEURS:
            continue
        if geometrie.geom_type == "LineString":
            geometrie = MultiLineString(geometrie, srid=4326)
        if geometrie.geom_type != "MultiLineString" or geometrie.empty:
            continue
        troncons.append({
            "code": code[:20],
            "nom": str(proprietes.get("lbentcru") or "").strip()[:160],
            "niveau": niveau,
            # Tracé allégé : le fichier d'origine porte un point tous les quelques mètres, ce
            # qui n'apporte rien à l'échelle d'une carte (tolérance ~50 m) et pèse 2 Mo.
            "geometrie": _alleger(geometrie),
        })
    return publie_le, troncons


def _alleger(geometrie):
    allegee = geometrie.simplify(0.0005, preserve_topology=True)
    if allegee.empty:
        return geometrie
    return MultiLineString(allegee, srid=4326) if allegee.geom_type == "LineString" else allegee


def enregistrer(publie_le, troncons, maintenant=None):
    """Remplace la copie : écrit les tronçons du fichier, retire ceux qui n'y sont plus."""
    from .models import TronconVigilanceCrues

    if len(troncons) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(troncons)} tronçons seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    lignes = [TronconVigilanceCrues(publie_le=publie_le, releve_le=maintenant, **t) for t in troncons]
    with transaction.atomic():
        TronconVigilanceCrues.objects.bulk_create(
            lignes, update_conflicts=True, unique_fields=["code"],
            update_fields=["nom", "niveau", "geometrie", "publie_le", "releve_le"],
        )
        TronconVigilanceCrues.objects.exclude(code__in=[l.code for l in lignes]).delete()
    return len(lignes)


def relever():
    publie_le, troncons = analyser(telecharger())
    return enregistrer(publie_le, troncons)
