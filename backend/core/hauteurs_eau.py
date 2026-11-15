"""Hauteurs d'eau et débits mesurés en rivière : relevé de Hub'Eau, copie en base.

SOURCE
API « Hydrométrie » de Hub'Eau (https://hubeau.eaufrance.fr/page/api-hydrometrie), qui rediffuse
les mesures quasi temps réel de la plate-forme nationale d'hydrométrie (celle de Vigicrues).
Licence Ouverte, aucune clé. Environ 4 200 stations en service, OUTRE-MER COMPRIS (Guadeloupe,
Martinique, Guyane, La Réunion, Mayotte), une mesure toutes les 5 à 60 minutes selon la station.

CE QUE C'EST, ET CE QUE CE N'EST PAS
Une MESURE, là où la vigilance crues (core/vigilance_crues.py) est un niveau d'alerte par
tronçon. Les deux se complètent : la vigilance ne couvre que les principaux cours d'eau de
métropole, les stations vont bien au-delà.

La hauteur est celle lue à l'échelle de la station : elle n'a de sens que comparée à elle-même.
Un mètre vingt ne dit ni « normal » ni « en crue » -- la source ne publie pas les seuils de
débordement. Ce que ce relevé apporte, c'est la TENDANCE : de combien l'eau a monté en une heure
et en trois heures. Les paliers de tendance (voir `tendance`) sont de l'affichage, pas une
alerte ; dix centimètres par heure n'ont pas le même sens sur un torrent et sur un fleuve.

Les mesures sont brutes, non validées : une sonde en panne peut donner n'importe quoi.

Même règle que le reste de la veille : seul le serveur appelle, pour la France entière, depuis
la tâche planifiée. Rien de ce qui part ne désigne un utilisateur ni un territoire.
"""
import datetime
import logging

import requests
from django.contrib.gis.geos import Point
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL_STATIONS = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations"
URL_OBSERVATIONS = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr"
DELAI_REPONSE_S = 90
TAILLE_PAGE = 20000
# Une heure de mesures nationales tient en trois pages ; au-delà, quelque chose ne va pas.
PAGES_MAX = 6
REFERENTIEL_VALABLE = datetime.timedelta(hours=24)
# Fenêtre relue à chaque passage : plus large que l'intervalle entre deux relevés, pour qu'un
# passage manqué ne laisse pas de trou.
FENETRE = datetime.timedelta(minutes=60)

# Historique gardé par station, pour calculer la tendance sans rien redemander à la source.
HISTORIQUE_GARDE = datetime.timedelta(hours=6, minutes=30)
ECART_MIN_ENTRE_POINTS = datetime.timedelta(minutes=9)
# Une mesure plus vieille que cela n'est plus « la hauteur de l'eau ».
MESURE_VALABLE = datetime.timedelta(hours=3)
# On compare à la mesure la plus proche d'« il y a une heure », à cette tolérance près.
TOLERANCE_1H = datetime.timedelta(minutes=25)
TOLERANCE_3H = datetime.timedelta(minutes=45)

HAUSSE_RAPIDE, HAUSSE, STABLE, BAISSE, INCONNUE = "HAUSSE_RAPIDE", "HAUSSE", "STABLE", "BAISSE", "INCONNUE"
# De ce qui presse le plus à ce qui presse le moins : l'ordre d'affichage.
ORDRE_TENDANCES = (HAUSSE_RAPIDE, HAUSSE, STABLE, BAISSE, INCONNUE)
# Centimètres par heure.
SEUIL_HAUSSE_RAPIDE, SEUIL_HAUSSE, SEUIL_BAISSE = 30, 10, -10
# Une variation plus forte que cela en une heure est un défaut de sonde, pas une rivière.
VARIATION_PLAUSIBLE_CM = 800


def _pages(adresse, params):
    """Toutes les lignes d'une lecture de Hub'Eau, en suivant le lien « next »."""
    lignes, suivante = [], None
    for _page in range(PAGES_MAX):
        reponse = (requests.get(suivante, timeout=DELAI_REPONSE_S) if suivante
                   else requests.get(adresse, params=params, timeout=DELAI_REPONSE_S))
        reponse.raise_for_status()
        corps = reponse.json()
        lignes.extend(corps.get("data") or [])
        suivante = corps.get("next")
        if not suivante:
            return lignes
    raise ValueError(f"plus de {PAGES_MAX} pages : lecture abandonnée")


def analyser_stations(lignes):
    """Référentiel -> {code: {"nom", "cours_eau", "departement", "longitude", "latitude"}}."""
    stations = {}
    for ligne in lignes:
        code = (ligne.get("code_station") or "").strip()
        longitude, latitude = ligne.get("longitude_station"), ligne.get("latitude_station")
        if not code or longitude is None or latitude is None:
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        stations[code] = {
            "nom": (ligne.get("libelle_station") or "").strip()[:200],
            "cours_eau": (ligne.get("libelle_cours_eau") or "").strip()[:120],
            "departement": (ligne.get("code_departement") or "").strip()[:3],
            "longitude": longitude, "latitude": latitude,
        }
    return stations


def analyser_observations(lignes):
    """Mesures -> {code: {"hauteurs": [(instant, mm)…] triées, "debit": (instant, l/s) ou None}}.
    Hauteur en millimètres et débit en litres par seconde, comme la source."""
    stations = {}
    for ligne in lignes:
        code, valeur = ligne.get("code_station"), ligne.get("resultat_obs")
        instant = parse_datetime(ligne.get("date_obs") or "")
        if not code or valeur is None or instant is None:
            continue
        station = stations.setdefault(code, {"hauteurs": [], "debit": None})
        if ligne.get("grandeur_hydro") == "H":
            station["hauteurs"].append((instant, float(valeur)))
        elif ligne.get("grandeur_hydro") == "Q":
            if station["debit"] is None or instant > station["debit"][0]:
                station["debit"] = (instant, float(valeur))
    for station in stations.values():
        station["hauteurs"].sort()
    return stations


def fusionner_historique(historique, hauteurs, maintenant):
    """Historique d'une station après ajout de nouvelles mesures : [[instant ISO, mm]…] trié,
    borné à HISTORIQUE_GARDE et éclairci (un point toutes les dix minutes suffit à une tendance).
    La dernière mesure est toujours gardée."""
    points = {}
    for instant_iso, mm in historique or []:
        instant = parse_datetime(instant_iso)
        if instant is not None:
            points[instant] = mm
    points.update(dict(hauteurs))
    limite = maintenant - HISTORIQUE_GARDE
    tries = sorted((instant, mm) for instant, mm in points.items() if instant >= limite)
    gardes = []
    for rang, (instant, mm) in enumerate(tries):
        dernier = rang == len(tries) - 1
        if gardes and instant - gardes[-1][0] < ECART_MIN_ENTRE_POINTS:
            if not dernier:
                continue
            gardes.pop()        # la toute dernière mesure remplace sa voisine trop proche
        gardes.append((instant, mm))
    return [[instant.isoformat(), mm] for instant, mm in gardes]


def variation_cm(historique, duree, tolerance):
    """De combien de centimètres l'eau a varié sur `duree`, d'après l'historique : la dernière
    mesure moins celle qui est la plus proche de « dernière - duree ». None si aucune mesure
    n'en est assez proche, ou si l'écart n'est pas plausible."""
    if not historique or len(historique) < 2:
        return None
    points = [(parse_datetime(instant), mm) for instant, mm in historique]
    dernier_instant, derniere = points[-1]
    cible = dernier_instant - duree
    instant, valeur = min(points[:-1], key=lambda point: abs(point[0] - cible))
    if abs(instant - cible) > tolerance:
        return None
    variation = round((derniere - valeur) / 10, 1)
    heures = duree.total_seconds() / 3600
    return variation if abs(variation) <= VARIATION_PLAUSIBLE_CM * heures else None


def tendance(station, maintenant=None):
    """Palier de tendance d'une station : d'après la variation sur une heure, à défaut sur trois
    heures ramenée à l'heure. INCONNUE sans mesure récente ou sans point de comparaison."""
    maintenant = maintenant or timezone.now()
    if station.hauteur_le is None or maintenant - station.hauteur_le > MESURE_VALABLE:
        return INCONNUE
    par_heure = station.variation_1h_cm
    if par_heure is None and station.variation_3h_cm is not None:
        par_heure = station.variation_3h_cm / 3
    if par_heure is None:
        return INCONNUE
    if par_heure >= SEUIL_HAUSSE_RAPIDE:
        return HAUSSE_RAPIDE
    if par_heure >= SEUIL_HAUSSE:
        return HAUSSE
    return BAISSE if par_heure <= SEUIL_BAISSE else STABLE


def _mettre_a_jour_le_referentiel(maintenant):
    from .models import StationHydrometrique

    stations = analyser_stations(_pages(URL_STATIONS, {
        "en_service": "true", "size": 10000,
        "fields": "code_station,libelle_station,libelle_cours_eau,longitude_station,latitude_station,code_departement"}))
    if not stations:
        raise ValueError("référentiel des stations hydrométriques vide")
    connues = {station.code: station for station in StationHydrometrique.objects.all()}
    a_creer, a_modifier = [], []
    for code, description in stations.items():
        champs = {"nom": description["nom"], "cours_eau": description["cours_eau"],
                  "departement": description["departement"],
                  "location": Point(description["longitude"], description["latitude"], srid=4326),
                  "referentiel_le": maintenant}
        station = connues.get(code)
        if station is None:
            a_creer.append(StationHydrometrique(code=code, **champs))
        else:
            for nom, valeur in champs.items():
                setattr(station, nom, valeur)
            a_modifier.append(station)
    StationHydrometrique.objects.bulk_create(a_creer, batch_size=500)
    StationHydrometrique.objects.bulk_update(
        a_modifier, ["nom", "cours_eau", "departement", "location", "referentiel_le"], batch_size=500)
    # Une station sortie du référentiel n'est plus en service.
    StationHydrometrique.objects.exclude(code__in=stations).delete()


def relever(maintenant=None):
    """Relit le référentiel s'il a plus d'un jour, puis copie les mesures de la dernière heure.
    Rend le nombre de stations qui ont reçu une mesure de hauteur."""
    from .models import StationHydrometrique

    maintenant = maintenant or timezone.now()
    plus_recent = (StationHydrometrique.objects.order_by("-referentiel_le")
                   .values_list("referentiel_le", flat=True).first())
    if plus_recent is None or maintenant - plus_recent > REFERENTIEL_VALABLE:
        _mettre_a_jour_le_referentiel(maintenant)

    debut = (maintenant - FENETRE).astimezone(datetime.timezone.utc)
    mesures = analyser_observations(_pages(URL_OBSERVATIONS, {
        "date_debut_obs": debut.strftime("%Y-%m-%dT%H:%M:%S"), "size": TAILLE_PAGE,
        "fields": "code_station,date_obs,resultat_obs,grandeur_hydro"}))
    if not mesures:
        raise ValueError("aucune mesure hydrométrique dans la dernière heure")

    a_modifier, avec_hauteur = [], 0
    for station in StationHydrometrique.objects.filter(code__in=mesures):
        mesure = mesures[station.code]
        if mesure["hauteurs"]:
            station.historique = fusionner_historique(station.historique, mesure["hauteurs"], maintenant)
            if station.historique:
                dernier_instant, derniere = station.historique[-1]
                station.hauteur_m, station.hauteur_le = round(derniere / 1000, 3), parse_datetime(dernier_instant)
                station.variation_1h_cm = variation_cm(
                    station.historique, datetime.timedelta(hours=1), TOLERANCE_1H)
                station.variation_3h_cm = variation_cm(
                    station.historique, datetime.timedelta(hours=3), TOLERANCE_3H)
                avec_hauteur += 1
        if mesure["debit"] is not None and (station.debit_le is None or mesure["debit"][0] >= station.debit_le):
            station.debit_le, station.debit_m3s = mesure["debit"][0], round(mesure["debit"][1] / 1000, 3)
        a_modifier.append(station)
    StationHydrometrique.objects.bulk_update(
        a_modifier, ["historique", "hauteur_m", "hauteur_le", "variation_1h_cm", "variation_3h_cm",
                     "debit_m3s", "debit_le"], batch_size=500)
    return avec_hauteur
