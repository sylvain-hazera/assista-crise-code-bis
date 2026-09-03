import json
import urllib.parse
import urllib.request


def _fetch_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def commune_from_code(commune_code: str) -> str | None:
    """Résout un code commune INSEE en nom via geo.api.gouv.fr. Stocké durablement en base
    (Commune) : le mapping code -> nom ne change pratiquement jamais."""
    from core.models import Commune

    if not commune_code:
        return None
    commune, _ = Commune.objects.get_or_create(code=commune_code)
    if commune.nom is None:
        url = f"https://geo.api.gouv.fr/communes/{urllib.parse.quote(commune_code)}?fields=nom"
        data = _fetch_json(url)
        nom = data.get("nom") if isinstance(data, dict) else None
        if nom:
            commune.nom = nom
            commune.save(update_fields=["nom", "date_maj"])
    return commune.nom


def commune_center_from_code(commune_code: str) -> dict:
    """Centroïde d'une commune (lat/lon) résolu via geo.api.gouv.fr — sens inverse de
    commune_code_from_point (point -> commune), utilisé pour centrer une minimap sur une
    commune quand on n'a qu'un code INSEE et aucun point réel (ex: zone d'intervention d'une
    équipe). Stocké durablement en base (Commune), comme commune_from_code."""
    from core.models import Commune

    if not commune_code:
        return {"latitude": None, "longitude": None}
    commune, _ = Commune.objects.get_or_create(code=commune_code)
    if commune.centre_latitude is None and commune.centre_longitude is None:
        url = f"https://geo.api.gouv.fr/communes/{urllib.parse.quote(commune_code)}?fields=centre"
        data = _fetch_json(url)
        if isinstance(data, dict):
            centre = data.get("centre") or {}
            coordinates = centre.get("coordinates")
            if isinstance(coordinates, list) and len(coordinates) == 2:
                commune.centre_longitude, commune.centre_latitude = coordinates
                commune.save(update_fields=["centre_latitude", "centre_longitude", "date_maj"])
    return {"latitude": commune.centre_latitude, "longitude": commune.centre_longitude}


def _reverse_geocode_point(point) -> dict:
    """Reverse-géocode un point (lon/lat) via api-adresse.data.gouv.fr — même API que
    GeolocationService.reverseGeocode côté frontend (modal détail), déplacée côté serveur pour
    être appelable en liste sans multiplier les appels client. Clé arrondie à 4 décimales
    (~11m) : suffisant pour identifier une commune, réduit le taux de requête manquante par
    rapport aux coordonnées brutes. Résultat stocké durablement en base (PointCommune +
    Commune) plutôt qu'en cache : cette correspondance ne change jamais, et un cache qui expire
    ou se vide à chaque redémarrage provoquait plusieurs secondes de latence sur les listes
    d'offres/demandes (jusqu'à 5s de timeout par appel externe non résolu)."""
    from core.models import Commune, PointCommune

    if point is None:
        return {"nom": None, "citycode": None}
    lat, lon = round(point.y, 4), round(point.x, 4)
    point_commune, _ = PointCommune.objects.select_related("commune").get_or_create(lat=lat, lon=lon)
    if point_commune.commune_id is None:
        url = f"https://api-adresse.data.gouv.fr/reverse/?lon={lon}&lat={lat}"
        data = _fetch_json(url)
        nom, citycode = None, None
        if isinstance(data, dict):
            features = data.get("features") or []
            if features:
                props = features[0].get("properties", {})
                nom = props.get("city") or props.get("label")
                citycode = props.get("citycode")
        if citycode:
            commune, _ = Commune.objects.get_or_create(code=citycode)
            if nom and not commune.nom:
                commune.nom = nom
                commune.save(update_fields=["nom", "date_maj"])
            point_commune.commune = commune
            point_commune.save(update_fields=["commune", "date_maj"])
    if point_commune.commune_id:
        return {"nom": point_commune.commune.nom, "citycode": point_commune.commune_id}
    return {"nom": None, "citycode": None}


def commune_from_point(point) -> str | None:
    """Nom de commune résolu par reverse-géocodage — voir _reverse_geocode_point."""
    return _reverse_geocode_point(point)["nom"]


def commune_code_from_point(point) -> str | None:
    """Code commune INSEE résolu par reverse-géocodage — voir _reverse_geocode_point. Utilisé
    pour comparer par code exact (ex: filtrage vue mairie) plutôt que par nom, plus fiable
    (accents, casse, doublons de noms de commune)."""
    return _reverse_geocode_point(point)["citycode"]
