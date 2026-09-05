import json
import urllib.parse
import urllib.request

from django.utils import timezone

# Un code/point sans correspondance (coordonnées de test imprécises, zone sans adresse
# répertoriée...) n'est retenté qu'après ce délai, jamais à chaque lecture — mesuré en direct :
# sans cooldown, 119 points DEMO non résolus sur 225 suffisaient à ajouter ~15-20s à
# /api/demandes/ (un appel externe par point non résolu, à CHAQUE requête). Assez court pour
# qu'une adresse nouvellement répertoriée finisse par se résoudre, assez long pour ne jamais
# dominer le temps de réponse d'une liste.
RETRY_COOLDOWN = timezone.timedelta(hours=6)


def _fetch_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _should_attempt(derniere_tentative) -> bool:
    if derniere_tentative is None:
        return True
    return timezone.now() - derniere_tentative > RETRY_COOLDOWN


def _resolve_commune(commune) -> None:
    """Complète commune.nom/centre_latitude/centre_longitude/departement_code/epci_code/
    region_code/population en un seul appel externe si l'un des champs manque encore et que le
    cooldown le permet — évite plusieurs appels séparés qui se marcheraient sinon dessus via le
    même derniere_tentative."""
    has_nom = commune.nom is not None
    has_centre = commune.centre_latitude is not None or commune.centre_longitude is not None
    has_secteur = commune.departement_code is not None and commune.region_code is not None
    if (has_nom and has_centre and has_secteur) or not _should_attempt(commune.derniere_tentative):
        return
    url = (
        f"https://geo.api.gouv.fr/communes/{urllib.parse.quote(commune.code)}"
        "?fields=nom,centre,codeDepartement,codeEpci,codeRegion,population"
    )
    data = _fetch_json(url)
    commune.derniere_tentative = timezone.now()
    if isinstance(data, dict):
        nom = data.get("nom")
        if nom:
            commune.nom = nom
        coordinates = (data.get("centre") or {}).get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) == 2:
            commune.centre_longitude, commune.centre_latitude = coordinates
        departement_code = data.get("codeDepartement")
        if departement_code:
            commune.departement_code = departement_code
        epci_code = data.get("codeEpci")
        if epci_code:
            commune.epci_code = epci_code
        region_code = data.get("codeRegion")
        if region_code:
            commune.region_code = region_code
        population = data.get("population")
        if population is not None:
            commune.population = population
    commune.save(update_fields=[
        "nom", "centre_latitude", "centre_longitude", "departement_code", "epci_code",
        "region_code", "population", "derniere_tentative", "date_maj",
    ])


def commune_from_code(commune_code: str) -> str | None:
    """Résout un code commune INSEE en nom via geo.api.gouv.fr. Stocké durablement en base
    (Commune) : le mapping code -> nom ne change pratiquement jamais."""
    from core.models import Commune

    if not commune_code:
        return None
    commune, _ = Commune.objects.get_or_create(code=commune_code)
    _resolve_commune(commune)
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
    _resolve_commune(commune)
    return {"latitude": commune.centre_latitude, "longitude": commune.centre_longitude}


def epci_nom_from_code(epci_code: str) -> str | None:
    """Nom d'un EPCI (communauté de communes/métropole) — résolu à la demande, sans mise en
    cache en base contrairement à Commune : appelé uniquement depuis Institution.save(), sur
    un événement bien plus rare (modification d'institution) qu'un reverse-géocodage de point."""
    if not epci_code:
        return None
    url = f"https://geo.api.gouv.fr/epcis/{urllib.parse.quote(epci_code)}?fields=nom"
    data = _fetch_json(url)
    return data.get("nom") if isinstance(data, dict) else None


def commune_secteur_codes(commune_code: str) -> dict:
    """(epci_code, departement_code, region_code) d'une commune — utilisé pour dénormaliser le
    secteur d'une institution (Institution.save()) ou d'une offre (OfferViewSet.perform_create)
    à partir de son seul commune_code, une seule fois, plutôt que de rejoindre Commune à chaque
    lecture (voir OfferViewSet.vue_secteur)."""
    from core.models import Commune

    if not commune_code:
        return {"epci_code": None, "departement_code": None, "region_code": None}
    commune, _ = Commune.objects.get_or_create(code=commune_code)
    _resolve_commune(commune)
    return {
        "epci_code": commune.epci_code,
        "departement_code": commune.departement_code,
        "region_code": commune.region_code,
    }


def _reverse_geocode_point(point) -> dict:
    """Reverse-géocode un point (lon/lat) via api-adresse.data.gouv.fr — même API que
    GeolocationService.reverseGeocode côté frontend (modal détail), déplacée côté serveur pour
    être appelable en liste sans multiplier les appels client. Clé arrondie à 4 décimales
    (~11m) : suffisant pour identifier une commune, réduit le taux de requête manquante par
    rapport aux coordonnées brutes. Résultat stocké durablement en base (PointCommune +
    Commune) plutôt qu'en cache : cette correspondance ne change jamais, et un cache qui expire
    ou se vide à chaque redémarrage provoquait plusieurs secondes de latence sur les listes
    d'offres/demandes (jusqu'à 5s de timeout par appel externe non résolu). Un point sans
    correspondance n'est retenté qu'après RETRY_COOLDOWN, jamais à chaque lecture."""
    from core.models import Commune, PointCommune

    if point is None:
        return {"nom": None, "citycode": None}
    lat, lon = round(point.y, 4), round(point.x, 4)
    point_commune, _ = PointCommune.objects.select_related("commune").get_or_create(lat=lat, lon=lon)
    if point_commune.commune_id is None and _should_attempt(point_commune.derniere_tentative):
        url = f"https://api-adresse.data.gouv.fr/reverse/?lon={lon}&lat={lat}"
        data = _fetch_json(url)
        point_commune.derniere_tentative = timezone.now()
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
        point_commune.save(update_fields=["commune", "derniere_tentative", "date_maj"])
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
