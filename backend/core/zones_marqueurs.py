"""Où un marqueur de l'application peut se poser (28/11/2026).

Décision de Sylvain : depuis l'application, un marqueur ne se pose qu'en phase de crise ou de
manifestation, rattaché à l'une ou à l'autre, ET à un endroit qui est dans sa zone. Hors zone,
le clic long ne le propose pas ; le serveur le refuse aussi.

- Zone d'une crise : le polygone dessiné, sinon l'union des communes ou départements tamponnés
  (`zone_secteurs`), sinon un cercle de `radius` km autour de son lieu.
- Zone d'une manifestation : à moins de RAYON_MANIFESTATION_KM de son lieu, d'un poste placé,
  ou, faute de position, du centre d'une de ses communes.

L'application fait le même calcul avec ce que le serveur lui sert (`zone_effective` pour une
crise, `points_de_manifestation` pour une manifestation).
"""
import math

RAYON_MANIFESTATION_KM = 5.0
#: Contour servi à l'application : simplifié à ~100 m, assez pour décider d'un clic long.
TOLERANCE_DEGRES = 0.001


def _km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def contour_de_crise(crise):
    """La géométrie de la zone (GEOS), ou None quand seule la règle du rayon s'applique."""
    if crise.zone is not None:
        return crise.zone
    return crise.zone_secteurs


def zone_effective(crise):
    """Pour l'application : {"zone": GeoJSON simplifié ou None, "rayon_km": float}."""
    import json

    contour = contour_de_crise(crise)
    return {
        "zone": json.loads(contour.simplify(TOLERANCE_DEGRES, preserve_topology=True).geojson) if contour is not None else None,
        "rayon_km": float(crise.radius or 10),
    }


def dans_la_crise(crise, latitude, longitude):
    from django.contrib.gis.geos import Point

    contour = contour_de_crise(crise)
    if contour is not None:
        return contour.covers(Point(longitude, latitude, srid=4326))
    if crise.location is None:
        return False
    return _km(latitude, longitude, crise.location.y, crise.location.x) <= float(crise.radius or 10)


def points_de_manifestation(manifestation):
    """[(lat, lon)] : le lieu, les postes placés, sinon les centres des communes."""
    from .models import Commune

    points = []
    if manifestation.location is not None:
        points.append((manifestation.location.y, manifestation.location.x))
    points += [(p.location.y, p.location.x) for p in manifestation.postes.exclude(location__isnull=True).only("location")]
    if not points:
        codes = [c for c in (manifestation.communes or []) if c] or ([manifestation.commune_code] if manifestation.commune_code else [])
        points = [(c.centre_latitude, c.centre_longitude) for c in Commune.objects.filter(code__in=codes)
                  .exclude(centre_latitude=None).exclude(centre_longitude=None).only("centre_latitude", "centre_longitude")]
    return points


def pres_de_la_manifestation(manifestation, latitude, longitude):
    return any(_km(latitude, longitude, la, lo) <= RAYON_MANIFESTATION_KM for la, lo in points_de_manifestation(manifestation))
