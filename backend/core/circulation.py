"""Circulation sur le réseau routier national : vitesses et débits mesurés, état du trafic
autour des grandes agglomérations. Relevé des flux « Bison Futé ouvert », copie en base.

SOURCE
https://tipi.bison-fute.gouv.fr/bison-fute-ouvert/publicationsDIR/ -- publications des
directions interdépartementales des routes, Licence Ouverte 2.0, aucune clé. Trois fichiers :

- `QTV-DIR/refDir.csv` : le référentiel des stations de comptage (environ 1 400). Chaque station
  vaut pour un tronçon d'un sens de circulation : axe, sens, début et fin en Lambert-93.
- `QTV-DIR/qtvDir.xml` : pour chaque station, la vitesse moyenne et le débit des six dernières
  minutes (DATEX II v2, 1,4 Mo, republié toutes les six minutes).
- `TRAFICOLOR-DIR/<agglomération>/` : l'état du trafic (fluide, dense, saturé, bloqué) estimé
  par l'exploitant autour de seize agglomérations, un fichier par minute ou par trois minutes.

CE QUE C'EST, ET CE QUE CE N'EST PAS
Le réseau routier NATIONAL non concédé seulement : routes nationales et autoroutes de l'État.
Ni les autoroutes concédées, ni les départementales, ni la voirie communale. Et seulement là où
il y a une station : un tronçon sans mesure n'est pas un tronçon fluide. L'écran doit le dire.

DEUX ORIGINES POUR L'ÉTAT D'UN TRONÇON
1. OFFICIEL : l'état publié par l'exploitant (Traficolor), quand il existe et qu'il est récent.
2. ESTIMÉ : ailleurs, la vitesse mesurée comparée à la vitesse HABITUELLE du tronçon, que ce
   serveur apprend lui-même (voir `apprendre_vitesse`) -- aucune source ouverte ne donne la
   limitation de vitesse de chaque station. Constat du 15/11/2026 à Saint-Étienne : les
   tronçons que l'exploitant disait saturés roulaient à 8, 10 et 26 km/h, les fluides entre 60
   et 110. Les seuils d'ESTIMATION (40 % et 65 % de l'habitude) en découlent. Tant que
   l'habitude n'est pas apprise (deux jours environ), rien n'est estimé.

Une vitesse de zéro n'est pas un bouchon : c'est ainsi que le flux note une station qui ne
mesure pas la vitesse (elle a souvent un débit non nul). Elle est lue comme « inconnue ».

Même règle que le reste de la veille : seul le serveur appelle, pour la France entière, depuis
la tâche planifiée. Rien de ce qui part ne désigne un utilisateur ni un territoire.
"""
import csv
import datetime
import io
import logging
import re
import time
import xml.etree.ElementTree as ET

import requests
from django.contrib.gis.geos import LineString, Point
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL_BASE = "https://tipi.bison-fute.gouv.fr/bison-fute-ouvert/publicationsDIR/"
URL_REFERENTIEL = URL_BASE + "QTV-DIR/refDir.csv"
URL_MESURES = URL_BASE + "QTV-DIR/qtvDir.xml"
URL_ETATS = URL_BASE + "TRAFICOLOR-DIR/"
DELAI_REPONSE_S = 45
# Les mesures pèsent 1,4 Mo, un fichier d'état 200 Ko. Dix fois plus n'est pas ce flux.
TAILLE_MAX = 20 * 1024 * 1024
# Le référentiel bouge quand une station est posée ou retirée : une relecture par jour.
REFERENTIEL_VALABLE = datetime.timedelta(hours=24)
# Une trentaine de petits fichiers à chaque passage sur un serveur de fichiers public.
PAUSE_ENTRE_FICHIERS_S = 0.3
DOSSIERS_MAX = 40

_NS = "{http://datex2.eu/schema/2/2_0}"
LAMBERT_93 = 2154

FLUIDE, DENSE, SATURE, BLOQUE, INCONNU = "FLUIDE", "DENSE", "SATURE", "BLOQUE", "INCONNU"
# Du plus gênant au moins gênant : l'ordre d'affichage.
ORDRE_ETATS = (BLOQUE, SATURE, DENSE, FLUIDE, INCONNU)
_ETAT_PAR_VALEUR = {"freeFlow": FLUIDE, "heavy": DENSE, "congested": SATURE, "impossible": BLOQUE}
OFFICIEL, ESTIME = "OFFICIEL", "ESTIME"

# Un état de l'exploitant plus vieux que cela n'est plus « l'état du trafic » : on retombe sur
# l'estimation. Une mesure de vitesse plus vieille n'est plus montrée comme actuelle.
ETAT_VALABLE = datetime.timedelta(minutes=25)
MESURE_VALABLE = datetime.timedelta(minutes=30)

# ── Vitesse habituelle ──
# On suit, station par station, la vitesse en dessous de laquelle se trouvent 85 % des mesures :
# c'est la vitesse de circulation libre, peu sensible au chauffard isolé comme aux bouchons.
# À chaque mesure l'estimation monte d'un pas pondéré si elle est dépassée, descend sinon ; elle
# se stabilise là où 15 % des mesures la dépassent.
QUANTILE_HABITUEL = 0.85
PAS_APPRENTISSAGE_KMH = 0.5
# Sous ce débit (véhicules par heure) la vitesse moyenne est celle de trois voitures : elle
# n'apprend rien et ne prouve rien.
DEBIT_SIGNIFICATIF = 200
# Nombre de mesures avant de se fier à l'habitude apprise : deux jours de relevés.
MESURES_POUR_ESTIMER = 280
PART_SATUREE, PART_DENSE = 0.40, 0.65


def _telecharger(adresse):
    reponse = requests.get(adresse, timeout=DELAI_REPONSE_S, headers={"User-Agent": "veille-territoire"})
    reponse.raise_for_status()
    if len(reponse.content) > TAILLE_MAX:
        raise ValueError(f"{len(reponse.content)} octets : ce n'est pas le flux attendu")
    return reponse


def _nombre(texte):
    try:
        return float(texte)
    except (TypeError, ValueError):
        return None


# ── Référentiel des stations ──

def analyser_referentiel(texte):
    """Stations du référentiel -> {code: description}.

    L'en-tête du fichier annonce une colonne `code_insee_commune` que les lignes ne portent pas
    (constaté le 15/11/2026) : tout serait décalé d'un cran. On la retire quand les lignes ont
    une colonne de moins que l'en-tête, et l'on garde l'en-tête tel quel le jour où ce sera
    corrigé à la source."""
    lignes = list(csv.reader(io.StringIO(texte), delimiter=";"))
    if not lignes:
        return {}
    entete = lignes[0]
    stations = {}
    for ligne in lignes[1:]:
        colonnes = entete
        if len(ligne) == len(entete) - 1 and "code_insee_commune" in entete:
            colonnes = [colonne for colonne in entete if colonne != "code_insee_commune"]
        if len(ligne) != len(colonnes):
            continue
        valeurs = dict(zip(colonnes, ligne))
        code = (valeurs.get("code_pme") or "").strip()
        if not code:
            continue
        debut = (_nombre(valeurs.get("x_deb")), _nombre(valeurs.get("y_deb")))
        fin = (_nombre(valeurs.get("x_fin")), _nombre(valeurs.get("y_fin")))
        stations[code] = {
            "gestionnaire": (valeurs.get("source") or "").strip()[:20],
            "axe": (valeurs.get("axe") or "").strip()[:20],
            "sens": (valeurs.get("sens_cardinal") or "").strip()[:20],
            "longueur_m": int(_nombre(valeurs.get("longueur")) or 0),
            "agglomeration": (valeurs.get("code_traficolor") or "").strip()[:20],
            "debut": debut if None not in debut else None,
            "fin": fin if None not in fin else None,
        }
    return stations


def trace_d_une_station(station):
    """Trait du début à la fin du tronçon, en longitude/latitude, ou None sans coordonnées.
    Le référentiel ne donne que les deux bouts : le trait est droit, la route ne l'est pas."""
    debut, fin = station["debut"], station["fin"]
    if debut is None:
        return None
    if fin is None or fin == debut:
        # Un seul bout connu : un trait de quelques mètres, pour rester une ligne sur la carte.
        fin = (debut[0] + 5, debut[1] + 5)
    trace = LineString(debut, fin, srid=LAMBERT_93)
    trace.transform(4326)
    return trace


_VERS = {"NORD_SUD": (0, -1), "SUD_NORD": (0, 1), "OUEST_EST": (1, 0), "EST_OUEST": (-1, 0)}


def cote_de_la_chaussee(station):
    """De quel côté du trait dessiner ce sens de circulation : +1 à droite, -1 à gauche, 0 si
    l'on ne sait pas.

    Les deux sens d'une même route portent les MÊMES deux bouts dans le référentiel : tracés
    tels quels, ils se recouvriraient et l'on ne verrait que l'un des deux. On compare donc le
    sens déclaré (« EST_OUEST ») à la direction du trait : s'ils s'accordent, la chaussée est à
    droite du trait (on roule à droite), sinon à gauche."""
    vers, debut, fin = _VERS.get(station["sens"]), station["debut"], station["fin"]
    if vers is None or debut is None or fin is None:
        return 0
    accord = (fin[0] - debut[0]) * vers[0] + (fin[1] - debut[1]) * vers[1]
    return 1 if accord > 0 else -1 if accord < 0 else 0


# ── Mesures et états (DATEX II) ──

def _sites(contenu):
    """Chaque `siteMeasurements` d'une publication : (code de la station, heure, élément)."""
    racine = ET.fromstring(contenu)
    for site in racine.iter(f"{_NS}siteMeasurements"):
        reference = site.find(f"{_NS}measurementSiteReference")
        code = reference.get("id") if reference is not None else None
        if not code:
            continue
        yield code, parse_datetime(site.findtext(f"{_NS}measurementTimeDefault") or ""), site


def analyser_mesures(contenu):
    """Vitesses et débits -> {code: {"vitesse_kmh", "debit_veh_h", "mesure_le"}}.
    Une vitesse nulle ou absente vaut None (station sans mesure de vitesse)."""
    mesures = {}
    for code, instant, site in _sites(contenu):
        vitesse = _nombre(site.findtext(f".//{_NS}averageVehicleSpeed/{_NS}speed"))
        debit = _nombre(site.findtext(f".//{_NS}vehicleFlow/{_NS}vehicleFlowRate"))
        mesures[code] = {
            "vitesse_kmh": round(vitesse, 1) if vitesse and 0 < vitesse < 250 else None,
            "debit_veh_h": int(debit) if debit is not None and 0 <= debit < 30000 else None,
            "mesure_le": instant,
        }
    return mesures


def analyser_etats(contenu):
    """États du trafic d'une agglomération -> {code: (état, heure)}. Les stations que
    l'exploitant dit « unknown » ne sont pas rendues : pas d'état vaut mieux qu'un faux."""
    etats = {}
    for code, instant, site in _sites(contenu):
        etat = _ETAT_PAR_VALEUR.get((site.findtext(f".//{_NS}trafficStatusValue") or "").strip())
        if etat:
            etats[code] = (etat, instant)
    return etats


_LIEN = re.compile(r'href="([^"?/][^"]*)"')


def dossiers_d_etats(page):
    """Noms des dossiers d'agglomération dans la page d'index du serveur de fichiers."""
    return sorted({lien for lien in _LIEN.findall(page) if lien.endswith("/") and "." not in lien})[:DOSSIERS_MAX]


def dernier_fichier(page):
    """Le fichier le plus récent d'un dossier d'agglomération : leurs noms finissent par la
    date et l'heure (`…_AAAAMMJJ_HHMMSS.xml`), le plus récent est le dernier dans cet ordre."""
    fichiers = [lien for lien in _LIEN.findall(page) if re.search(r"_\d{8}_\d{6}\.xml$", lien)]
    return max(fichiers, key=lambda nom: nom[-19:]) if fichiers else None


def relever_etats():
    """États du trafic de toutes les agglomérations -> {code: (état, heure)}. Un dossier en
    panne n'est qu'un avertissement : les autres agglomérations sont relevées quand même."""
    etats = {}
    for dossier in dossiers_d_etats(_telecharger(URL_ETATS).text):
        try:
            time.sleep(PAUSE_ENTRE_FICHIERS_S)
            fichier = dernier_fichier(_telecharger(URL_ETATS + dossier).text)
            if fichier is None:
                continue
            time.sleep(PAUSE_ENTRE_FICHIERS_S)
            etats.update(analyser_etats(_telecharger(URL_ETATS + dossier + fichier).content))
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            logger.warning("Circulation : état du trafic de %s non relevé (%s).", dossier, type(exc).__name__)
    return etats


# ── Vitesse habituelle et état affiché ──

def apprendre_vitesse(habituelle, comptees, vitesse, debit):
    """Nouvelle vitesse habituelle et nouveau compte de mesures après une mesure (voir l'en-tête
    « Vitesse habituelle »). Une mesure sans vitesse, ou à débit trop faible, n'apprend rien."""
    if vitesse is None or (debit or 0) < DEBIT_SIGNIFICATIF:
        return habituelle, comptees
    if habituelle is None:
        return vitesse, 1
    if vitesse > habituelle:
        habituelle += PAS_APPRENTISSAGE_KMH * QUANTILE_HABITUEL
    else:
        habituelle -= PAS_APPRENTISSAGE_KMH * (1 - QUANTILE_HABITUEL)
    # Trois décimales : les deux pas (0,425 et 0,075) doivent rester exacts, sans quoi
    # l'arrondi fausserait peu à peu le quantile visé.
    return round(habituelle, 3), comptees + 1


def etat_affiche(station, maintenant=None):
    """(état, origine) d'une station à l'instant : l'état de l'exploitant s'il est récent,
    sinon l'estimation par la vitesse, sinon (INCONNU, "")."""
    maintenant = maintenant or timezone.now()
    if station.etat and station.etat_le and maintenant - station.etat_le <= ETAT_VALABLE:
        return station.etat, OFFICIEL
    if (station.vitesse_kmh is None or station.mesure_le is None
            or maintenant - station.mesure_le > MESURE_VALABLE):
        return INCONNU, ""
    if (station.vitesse_habituelle_kmh is None or station.mesures_comptees < MESURES_POUR_ESTIMER
            or (station.debit_veh_h or 0) < DEBIT_SIGNIFICATIF):
        return INCONNU, ""
    part = station.vitesse_kmh / station.vitesse_habituelle_kmh
    if part < PART_SATUREE:
        return SATURE, ESTIME
    if part < PART_DENSE:
        return DENSE, ESTIME
    return FLUIDE, ESTIME


# ── Relevé ──

def _mettre_a_jour_le_referentiel(maintenant):
    from .models import StationCirculation

    stations = analyser_referentiel(_telecharger(URL_REFERENTIEL).content.decode("utf-8", errors="replace"))
    if not stations:
        raise ValueError("référentiel des stations vide")
    connues = {station.code: station for station in StationCirculation.objects.all()}
    a_creer, a_modifier = [], []
    for code, description in stations.items():
        trace = trace_d_une_station(description)
        champs = {
            "gestionnaire": description["gestionnaire"], "axe": description["axe"],
            "sens": description["sens"], "longueur_m": description["longueur_m"],
            "agglomeration": description["agglomeration"], "trace": trace,
            "cote": cote_de_la_chaussee(description),
            "location": Point(*trace.interpolate_normalized(0.5).coords, srid=4326) if trace else None,
            "referentiel_le": maintenant,
        }
        station = connues.get(code)
        if station is None:
            a_creer.append(StationCirculation(code=code, **champs))
        else:
            for nom, valeur in champs.items():
                setattr(station, nom, valeur)
            a_modifier.append(station)
    StationCirculation.objects.bulk_create(a_creer, batch_size=500)
    StationCirculation.objects.bulk_update(
        a_modifier, ["gestionnaire", "axe", "sens", "longueur_m", "agglomeration", "trace",
                     "cote", "location", "referentiel_le"], batch_size=500)
    # Une station sortie du référentiel n'est plus mesurée : elle part, avec son habitude.
    StationCirculation.objects.exclude(code__in=stations).delete()


def relever(maintenant=None):
    """Relit le référentiel s'il a plus d'un jour, puis copie les mesures et les états du
    trafic. Rend le nombre de stations qui portent une mesure de ce relevé."""
    from .models import StationCirculation

    maintenant = maintenant or timezone.now()
    plus_recent = (StationCirculation.objects.order_by("-referentiel_le")
                   .values_list("referentiel_le", flat=True).first())
    if plus_recent is None or maintenant - plus_recent > REFERENTIEL_VALABLE:
        _mettre_a_jour_le_referentiel(maintenant)

    mesures = analyser_mesures(_telecharger(URL_MESURES).content)
    if not mesures:
        raise ValueError("aucune mesure de circulation dans le flux")
    try:
        etats = relever_etats()
    except requests.RequestException as exc:
        # Les vitesses valent sans les états : ceux-ci vieilliront, et l'estimation prendra le relais.
        logger.warning("Circulation : états du trafic non relevés (%s).", type(exc).__name__)
        etats = {}

    a_modifier = []
    for station in StationCirculation.objects.all():
        mesure, etat = mesures.get(station.code), etats.get(station.code)
        if mesure is None and etat is None:
            continue
        # Une même mesure relue (le flux n'a pas été republié) ne doit pas compter deux fois
        # dans l'habitude.
        if mesure is not None and mesure["mesure_le"] and mesure["mesure_le"] != station.mesure_le:
            station.vitesse_habituelle_kmh, station.mesures_comptees = apprendre_vitesse(
                station.vitesse_habituelle_kmh, station.mesures_comptees,
                mesure["vitesse_kmh"], mesure["debit_veh_h"])
            station.vitesse_kmh, station.debit_veh_h = mesure["vitesse_kmh"], mesure["debit_veh_h"]
            station.mesure_le = mesure["mesure_le"]
        if etat is not None:
            station.etat, station.etat_le = etat[0], etat[1] or maintenant
        a_modifier.append(station)
    StationCirculation.objects.bulk_update(
        a_modifier, ["vitesse_kmh", "debit_veh_h", "mesure_le", "etat", "etat_le",
                     "vitesse_habituelle_kmh", "mesures_comptees"], batch_size=500)
    return sum(1 for station in a_modifier if station.code in mesures)
