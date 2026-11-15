"""Observations des stations Météo-France : relevé, copie en base.

SOURCE
API « DonneesPubliquesPaquetObservation » du portail public de Météo-France (même clé que la
vigilance, voir core/meteo_france.py), Licence Ouverte 2.0. Environ 2 000 stations, métropole ET
outre-mer -- c'est la seule source de la veille qui couvre La Réunion.

CE QU'ON RELÈVE
Deux « paquets » nationaux, chacun en UN appel pour toutes les stations :
- le paquet 6 minutes : température, humidité, vent moyen, rafale, pluie de la période ;
- le paquet horaire : pluie de l'heure et rafale maximale de l'heure.
S'y ajoute, une fois par jour, la liste des stations (nom, altitude).

Le cumul de pluie sur 24 heures n'est pas publié à l'échelle nationale : on le construit en
additionnant les paquets horaires au fil des relevés. Il est donc partiel pendant les premières
24 heures, et `heures_cumulees` dit sur combien d'heures il porte -- l'écran l'affiche, pour
qu'un cumul de trois heures ne soit pas lu comme un cumul d'une journée.

Même règle que le reste de la veille : seul le serveur appelle, pour la France entière, depuis
la tâche planifiée. Les unités de la source (kelvins, mètres par seconde) sont converties ici,
une fois, en degrés Celsius et kilomètres par heure.
"""
import csv
import datetime
import io
import logging

import requests
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import meteo_france

logger = logging.getLogger(__name__)

URL_BASE = "https://public-api.meteofrance.fr/public/DPPaquetObs/v2"
DELAI_REPONSE_S = 60

# Un paquet 6 minutes paraît une douzaine de minutes après son heure. On part de là et on
# recule tant que le créneau n'est pas encore publié.
RETARD_6_MIN = datetime.timedelta(minutes=12)
CRENEAUX_6_MIN_ESSAYES = 8
RETARD_HORAIRE = datetime.timedelta(minutes=15)
HEURES_ESSAYEES = 3

FENETRE_CUMUL = datetime.timedelta(hours=24)
# Une station muette depuis deux jours est retirée : sa dernière mesure ne dit plus rien.
OUBLI_APRES = datetime.timedelta(days=2)
RAFRAICHIR_STATIONS_APRES = datetime.timedelta(hours=24)
TRACE_STATIONS = "STATIONS_METEO"

# En dessous, le paquet est tronqué : on garde la copie précédente.
MINIMUM_PLAUSIBLE = 500


def _appeler(chemin, parametres=None):
    cle = meteo_france.lire_cle()
    if cle is None:
        raise meteo_france.CleAbsente()
    reponse = requests.get(f"{URL_BASE}/{chemin}", params=parametres,
                           headers={"apikey": cle, "accept": "*/*"}, timeout=DELAI_REPONSE_S)
    reponse.raise_for_status()
    return reponse


def _instant_api(instant):
    return instant.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dernier_paquet(chemin, creneaux):
    """Le paquet le plus récent parmi `creneaux` (du plus récent au plus ancien), ou None.

    Un créneau pas encore publié répond par un refus ou une liste vide : on recule. Une panne
    (autre code, réseau) remonte à l'appelant."""
    for creneau in creneaux:
        try:
            donnees = _appeler(chemin, {"date": _instant_api(creneau), "format": "json"}).json()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (400, 404):
                continue
            raise
        if isinstance(donnees, list) and donnees:
            return donnees
    return None


def telecharger_6_minutes(maintenant=None):
    depart = (maintenant or timezone.now()) - RETARD_6_MIN
    depart = depart.replace(minute=depart.minute - depart.minute % 6, second=0, microsecond=0)
    return _dernier_paquet("paquet/stations/infrahoraire-6m", [
        depart - datetime.timedelta(minutes=6 * i) for i in range(CRENEAUX_6_MIN_ESSAYES)])


def telecharger_horaire(maintenant=None):
    depart = ((maintenant or timezone.now()) - RETARD_HORAIRE).replace(minute=0, second=0, microsecond=0)
    return _dernier_paquet("paquet/stations/horaire", [
        depart - datetime.timedelta(hours=i) for i in range(HEURES_ESSAYEES)])


def telecharger_stations():
    """Liste des stations : {identifiant: (nom, altitude)}. Le fichier est en ISO-8859-1."""
    texte = _appeler("liste-stations").content.decode("iso-8859-1")
    stations = {}
    for ligne in csv.DictReader(io.StringIO(texte), delimiter=";"):
        identifiant = (ligne.get("Id_station") or "").strip()
        if not identifiant:
            continue
        try:
            altitude = int(float(ligne.get("Altitude") or ""))
        except ValueError:
            altitude = None
        nom = (ligne.get("Nom_usuel") or "").strip().replace("_", " ")
        stations[identifiant] = (nom[:80], altitude)
    return stations


# ── Conversions ─────────────────────────────────────────────────────────────────────────────

def _nombre(valeur):
    return float(valeur) if isinstance(valeur, (int, float)) and not isinstance(valeur, bool) else None


def _celsius(kelvin):
    kelvin = _nombre(kelvin)
    return None if kelvin is None else round(kelvin - 273.15, 1)


def _kmh(metres_par_seconde):
    vitesse = _nombre(metres_par_seconde)
    return None if vitesse is None else round(vitesse * 3.6)


def _arrondi(valeur, decimales=1):
    valeur = _nombre(valeur)
    return None if valeur is None else round(valeur, decimales)


def departement_de(station):
    """Département lu dans l'identifiant de la station (ses premiers chiffres sont ceux de la
    commune). Outre-mer : trois chiffres (974 pour La Réunion). La Corse est publiée sous « 20 »,
    sans distinguer ses deux départements."""
    if len(station) != 8 or not station.isdigit():
        return None
    return station[:3] if station[:2] in ("97", "98") else station[:2]


def analyser_6_minutes(paquet):
    """Paquet 6 minutes -> {station: champs de mesure}. Une ligne sans position est ignorée."""
    mesures = {}
    for brut in paquet or []:
        station = str(brut.get("geo_id_insee") or "")
        instant = parse_datetime(brut.get("validity_time") or "")
        try:
            position = Point(float(brut["lon"]), float(brut["lat"]), srid=4326)
        except (KeyError, TypeError, ValueError):
            continue
        if len(station) != 8 or instant is None:
            continue
        neige = _nombre(brut.get("sss"))
        mesures[station] = {
            "location": position,
            "departement_code": departement_de(station),
            "mesure_le": instant,
            "temperature_c": _celsius(brut.get("t")),
            "humidite_pct": _arrondi(brut.get("u"), 0),
            "vent_kmh": _kmh(brut.get("ff")),
            "vent_direction": _arrondi(brut.get("dd"), 0),
            "rafale_kmh": _kmh(brut.get("raf10")),
            "pluie_6min_mm": _arrondi(brut.get("rr_per")),
            "neige_cm": None if neige is None else round(neige * 100),
        }
    return mesures


def analyser_horaire(paquet):
    """Paquet horaire -> (heure, {station: {"pluie_1h_mm", "rafale_1h_kmh"}})."""
    heure, mesures = None, {}
    for brut in paquet or []:
        station = str(brut.get("geo_id_insee") or "")
        instant = parse_datetime(brut.get("validity_time") or "")
        if len(station) != 8 or instant is None:
            continue
        heure = heure or instant
        mesures[station] = {
            "pluie_1h_mm": _arrondi(brut.get("rr1")),
            "rafale_1h_kmh": _kmh(brut.get("raf")),
        }
    return heure, mesures


def ajouter_au_cumul(cumuls, heure, pluie_mm, maintenant):
    """Ajoute la pluie d'une heure à l'historique d'une station et rend
    (historique, cumul sur 24 h, nombre d'heures qu'il couvre).

    L'historique est une liste de {"h": instant ISO, "rr": mm}, bornée à la fenêtre de 24 h.
    Une heure déjà connue n'est pas comptée deux fois (le même paquet horaire est relu à chaque
    passage tant que le suivant n'est pas paru)."""
    limite = maintenant - FENETRE_CUMUL
    garde = []
    for entree in cumuls or []:
        instant = parse_datetime(entree.get("h") or "")
        if instant is not None and instant > limite:
            garde.append(entree)
    cle = heure.isoformat() if heure else None
    if cle and pluie_mm is not None and heure > limite and all(e["h"] != cle for e in garde):
        garde.append({"h": cle, "rr": pluie_mm})
    garde.sort(key=lambda e: e["h"])
    if not garde:
        return [], None, 0
    return garde, round(sum(e["rr"] for e in garde), 1), len(garde)


# ── La copie en base ────────────────────────────────────────────────────────────────────────

def enregistrer(mesures, heure, horaires, maintenant=None):
    """Écrit l'état courant de chaque station. `horaires=None` (paquet horaire non relevé)
    laisse les valeurs horaires et les cumuls déjà connus en place."""
    from .models import ObservationMeteo

    if len(mesures) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(mesures)} stations seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    connues = {o.station: o for o in ObservationMeteo.objects.filter(station__in=list(mesures))}

    lignes = []
    for station, champs in mesures.items():
        ligne = connues.get(station) or ObservationMeteo(station=station)
        for champ, valeur in champs.items():
            setattr(ligne, champ, valeur)
        horaire = (horaires or {}).get(station)
        if horaire is not None:
            ligne.heure_le = heure
            ligne.pluie_1h_mm = horaire["pluie_1h_mm"]
            ligne.rafale_1h_kmh = horaire["rafale_1h_kmh"]
            ligne.cumuls, ligne.pluie_24h_mm, ligne.heures_cumulees = ajouter_au_cumul(
                ligne.cumuls, heure, horaire["pluie_1h_mm"], maintenant)
        ligne.releve_le = maintenant
        lignes.append(ligne)

    champs = ["location", "departement_code", "mesure_le", "temperature_c", "humidite_pct",
              "vent_kmh", "vent_direction", "rafale_kmh", "pluie_6min_mm", "neige_cm", "heure_le",
              "pluie_1h_mm", "rafale_1h_kmh", "cumuls", "pluie_24h_mm", "heures_cumulees",
              "releve_le"]
    with transaction.atomic():
        ObservationMeteo.objects.bulk_create(
            lignes, batch_size=500, update_conflicts=True, unique_fields=["station"],
            update_fields=champs,
        )
        ObservationMeteo.objects.filter(mesure_le__lt=maintenant - OUBLI_APRES).delete()
    return len(lignes)


def _rafraichir_stations(maintenant):
    """Noms et altitudes, une fois par jour. Un échec est sans gravité : les mesures restent
    lisibles par leur position, les noms viendront au passage suivant."""
    from .models import ObservationMeteo, ReleveSourceOuverte

    trace, _ = ReleveSourceOuverte.objects.get_or_create(pk=TRACE_STATIONS)
    if trace.dernier_succes and maintenant - trace.dernier_succes < RAFRAICHIR_STATIONS_APRES:
        return
    trace.dernier_essai = maintenant
    try:
        stations = telecharger_stations()
    except (requests.RequestException, ValueError, UnicodeDecodeError) as exc:
        logger.warning("Observations : liste des stations non relevée (%s).", exc)
        trace.save(update_fields=["dernier_essai"])
        return
    a_modifier = []
    for ligne in ObservationMeteo.objects.only("station", "nom", "altitude_m"):
        nom, altitude = stations.get(ligne.station, (None, None))
        if nom and (ligne.nom != nom or ligne.altitude_m != altitude):
            ligne.nom, ligne.altitude_m = nom, altitude
            a_modifier.append(ligne)
    ObservationMeteo.objects.bulk_update(a_modifier, ["nom", "altitude_m"], batch_size=500)
    trace.dernier_succes, trace.lignes = maintenant, len(stations)
    trace.save()


def relever(maintenant=None):
    """Un relevé complet. Le paquet 6 minutes est indispensable ; le paquet horaire et la liste
    des stations sont un complément dont l'échec est journalisé sans faire échouer le relevé."""
    maintenant = maintenant or timezone.now()
    paquet = telecharger_6_minutes(maintenant)
    if paquet is None:
        raise ValueError("aucun paquet 6 minutes publié sur les créneaux essayés")
    mesures = analyser_6_minutes(paquet)

    heure, horaires = None, None
    try:
        heure, horaires = analyser_horaire(telecharger_horaire(maintenant))
        if heure is None:
            horaires = None
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Observations : paquet horaire non relevé (%s).", exc)

    nombre = enregistrer(mesures, heure, horaires, maintenant)
    _rafraichir_stations(maintenant)
    return nombre
