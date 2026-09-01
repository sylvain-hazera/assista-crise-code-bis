import json
import urllib.parse
import urllib.request

from django.core.cache import cache

CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 jours : un nom de commune ne change pas


def _fetch_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def commune_from_code(commune_code: str) -> str | None:
    """Résout un code commune INSEE en nom via geo.api.gouv.fr. Caché longtemps : le
    mapping code -> nom ne change pas."""
    if not commune_code:
        return None
    cache_key = f"commune_nom:{commune_code}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None
    url = f"https://geo.api.gouv.fr/communes/{urllib.parse.quote(commune_code)}?fields=nom"
    data = _fetch_json(url)
    nom = data.get("nom") if isinstance(data, dict) else None
    cache.set(cache_key, nom or "", CACHE_TTL_SECONDS)
    return nom


def commune_center_from_code(commune_code: str) -> dict:
    """Centroïde d'une commune (lat/lon) résolu via geo.api.gouv.fr — sens inverse de
    commune_code_from_point (point -> commune), utilisé pour centrer une minimap sur une
    commune quand on n'a qu'un code INSEE et aucun point réel (ex: zone d'intervention d'une
    équipe). Caché longtemps, comme commune_from_code : un centroïde de commune ne change pas."""
    if not commune_code:
        return {"latitude": None, "longitude": None}
    cache_key = f"commune_centre:{commune_code}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    url = f"https://geo.api.gouv.fr/communes/{urllib.parse.quote(commune_code)}?fields=centre"
    data = _fetch_json(url)
    result = {"latitude": None, "longitude": None}
    if isinstance(data, dict):
        centre = data.get("centre") or {}
        coordinates = centre.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) == 2:
            result = {"latitude": coordinates[1], "longitude": coordinates[0]}
    cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result


def _reverse_geocode_point(point) -> dict:
    """Reverse-géocode un point (lon/lat) via api-adresse.data.gouv.fr — même API que
    GeolocationService.reverseGeocode côté frontend (modal détail), déplacée côté serveur pour
    être appelable en liste sans multiplier les appels client. Clé de cache arrondie à 4
    décimales (~11m) : suffisant pour identifier une commune, réduit le taux de cache-miss par
    rapport aux coordonnées brutes. Retourne {"nom": ..., "citycode": ...} (valeurs None si
    non résolu), les deux mis en cache ensemble pour ne faire qu'un seul appel API."""
    if point is None:
        return {"nom": None, "citycode": None}
    lon, lat = round(point.x, 4), round(point.y, 4)
    cache_key = f"commune_point_v2:{lat}:{lon}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    url = f"https://api-adresse.data.gouv.fr/reverse/?lon={lon}&lat={lat}"
    data = _fetch_json(url)
    result = {"nom": None, "citycode": None}
    if isinstance(data, dict):
        features = data.get("features") or []
        if features:
            props = features[0].get("properties", {})
            result["nom"] = props.get("city") or props.get("label")
            result["citycode"] = props.get("citycode")
    cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result


def commune_from_point(point) -> str | None:
    """Nom de commune résolu par reverse-géocodage — voir _reverse_geocode_point."""
    return _reverse_geocode_point(point)["nom"]


def commune_code_from_point(point) -> str | None:
    """Code commune INSEE résolu par reverse-géocodage — voir _reverse_geocode_point. Utilisé
    pour comparer par code exact (ex: filtrage vue mairie) plutôt que par nom, plus fiable
    (accents, casse, doublons de noms de commune)."""
    return _reverse_geocode_point(point)["citycode"]
