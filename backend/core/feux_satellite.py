"""Surfaces brûlées repérées par satellite : relevé d'EFFIS, copie en base.

SOURCE
EFFIS, le système européen d'information sur les feux de forêt (Copernicus, Commission
européenne) : https://forest-fire.emergency.copernicus.eu. Service WFS ouvert, sans clé ;
réutilisation libre avec mention « © Union européenne, Copernicus EFFIS ». Ce n'est pas un
service de l'État français, mais un service public européen, et il n'en existe pas
d'équivalent national.

CE QUE C'EST
Le contour des surfaces brûlées des trente derniers jours, cartographié d'après les images
satellite : date du feu, commune, surface. Seuls les feux d'une trentaine d'hectares ou plus
sont vus, et avec un jour de retard environ.

CE QUE CE N'EST PAS
Pas une alerte : un feu qui démarre n'y est pas. C'est une mémoire de ce qui a brûlé, utile
pour situer un sinistre, pas pour le détecter. L'écran doit le dire.

Même règle que le reste de la veille : seul le serveur appelle, pour la France entière.
"""
import json
import logging

import requests
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL_WFS = "https://maps.effis.emergency.copernicus.eu/effis"
COUCHE = "ms:modis.ba.poly.month"
DELAI_REPONSE_S = 90
# Métropole et Corse. WFS 1.1.0 en EPSG:4326 : la latitude d'abord.
EMPRISE = "41,-5.5,51.5,10,EPSG:4326"
PAYS = "FR"
MAXIMUM = 2000


def telecharger():
    reponse = requests.get(URL_WFS, timeout=DELAI_REPONSE_S, params={
        "service": "WFS", "version": "1.1.0", "request": "GetFeature", "typeName": COUCHE,
        "bbox": EMPRISE, "outputFormat": "geojson", "maxFeatures": MAXIMUM,
    })
    reponse.raise_for_status()
    donnees = reponse.json()
    if not isinstance(donnees, dict) or "features" not in donnees:
        raise ValueError("réponse EFFIS sans liste de zones")
    return donnees


def _nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def analyser(donnees):
    """Réponse d'EFFIS -> dictionnaires prêts pour ZoneBrulee. Seules les zones situées en
    France sont gardées (l'emprise rectangulaire déborde sur les pays voisins)."""
    zones = []
    for element in donnees.get("features") or []:
        proprietes = element.get("properties") or {}
        reference = str(proprietes.get("id") or "").strip()
        if not reference or proprietes.get("COUNTRY") != PAYS:
            continue
        try:
            geometrie = GEOSGeometry(json.dumps(element.get("geometry")), srid=4326)
        except Exception:      # noqa: BLE001 -- GEOS lève ses propres erreurs
            continue
        if geometrie.geom_type == "Polygon":
            geometrie = MultiPolygon(geometrie, srid=4326)
        if geometrie.geom_type != "MultiPolygon" or geometrie.empty:
            continue
        centre = geometrie.centroid
        zones.append({
            "reference": reference[:40],
            "date_feu": parse_datetime(str(proprietes.get("FIREDATE") or "").replace(" ", "T") + "+00:00"),
            "commune_nom": str(proprietes.get("COMMUNE") or "").strip()[:160],
            "departement_nom": str(proprietes.get("PROVINCE") or "").strip()[:120],
            "surface_ha": _nombre(proprietes.get("AREA_HA")),
            "geometrie": geometrie,
            "location": centre,
        })
    return zones


def enregistrer(zones, maintenant=None):
    """Remplace la copie. Une liste vide est une réponse normale (l'hiver, rien ne brûle) :
    elle vide la table, contrairement aux autres sources où le vide signale une panne."""
    from .models import ZoneBrulee

    maintenant = maintenant or timezone.now()
    lignes = [ZoneBrulee(releve_le=maintenant, **zone) for zone in zones]
    with transaction.atomic():
        if lignes:
            ZoneBrulee.objects.bulk_create(
                lignes, update_conflicts=True, unique_fields=["reference"],
                update_fields=["date_feu", "commune_nom", "departement_nom", "surface_ha",
                               "geometrie", "location", "releve_le"],
            )
        ZoneBrulee.objects.exclude(reference__in=[l.reference for l in lignes]).delete()
    return len(lignes)


def relever():
    return enregistrer(analyser(telecharger()))
