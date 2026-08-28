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


def commune_from_point(point) -> str | None:
    """Reverse-géocode un point (lon/lat) en nom de commune via api-adresse.data.gouv.fr —
    même API que GeolocationService.reverseGeocode côté frontend (modal détail), déplacée
    côté serveur pour être appelable en liste sans multiplier les appels client. Clé de cache
    arrondie à 4 décimales (~11m) : suffisant pour identifier une commune, réduit le taux de
    cache-miss par rapport aux coordonnées brutes."""
    if point is None:
        return None
    lon, lat = round(point.x, 4), round(point.y, 4)
    cache_key = f"commune_point:{lat}:{lon}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None
    url = f"https://api-adresse.data.gouv.fr/reverse/?lon={lon}&lat={lat}"
    data = _fetch_json(url)
    nom = None
    if isinstance(data, dict):
        features = data.get("features") or []
        if features:
            props = features[0].get("properties", {})
            nom = props.get("city") or props.get("label")
    cache.set(cache_key, nom or "", CACHE_TTL_SECONDS)
    return nom
