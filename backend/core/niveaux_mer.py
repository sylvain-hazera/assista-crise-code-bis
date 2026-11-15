"""Niveau de la mer mesuré par les marégraphes, et surcote estimée : relevé du service du Shom,
copie en base.

SOURCE
Réseaux de référence des observations marégraphiques (REFMAR), service
https://services.data.shom.fr/maregraphie -- Shom et partenaires, Licence Ouverte 2.0, aucune
clé. Environ 140 marégraphes en service, en métropole et outre-mer (Antilles, Guyane, La Réunion,
Mayotte, Saint-Pierre-et-Miquelon, Pacifique, Terres australes). Mesures BRUTES, une toutes les
une à dix minutes, non validées.

LE PROBLÈME
Le service donne le niveau de l'eau, pas l'écart avec la marée attendue. Or un niveau brut ne
dit rien à une cellule de crise : à Brest, 5,70 m est une mer ordinaire à mi-marée. Ce qui
compte, c'est la SURCOTE -- de combien la mer est plus haute que la marée seule ne l'explique
(vent, basse pression) -- et les prédictions de marée du Shom ne sont pas ouvertes.

CE QUE FAIT CE MODULE
Il calcule lui-même la marée attendue de chaque marégraphe, par la méthode classique : six mois
de mesures de la station, sur lesquels on ajuste par moindres carrés une somme de vingt-deux
ondes de marée (leurs périodes sont astronomiques, donc connues ; seules l'amplitude et la phase
de chacune sont propres au port). La surcote estimée est la mesure moins cette marée.

CE QUE ÇA VAUT -- mesuré le 15/11/2026 sur Brest et Marseille : ajustée sur 60 à 75 jours, la
marée calculée s'écarte de la mesure de 12 à 14 cm (écart-type) sur les semaines SUIVANTES,
surcotes réelles comprises. C'est assez pour voir une surcote de 40 cm, pas pour discuter 10 cm.
Trente jours ne suffisent pas (des ondes voisines ne se séparent pas, la prédiction diverge) :
`JOURS_MINIMUM` l'interdit. Chaque station porte sa propre incertitude, mesurée en ajustant sur
les deux premiers tiers de son historique et en vérifiant sur le dernier ; au-delà de
`INCERTITUDE_MAX_CM`, rien n'est estimé pour elle.

Ce n'est donc ni une prédiction officielle de marée, ni une alerte : la vigilance
« vagues-submersion » reste celle de Météo-France. L'écran doit dire « estimée » et donner
l'incertitude.

Même règle que le reste de la veille : seul le serveur appelle, pour tous les marégraphes,
depuis la tâche planifiée. Rien de ce qui part ne désigne un utilisateur ni un territoire.
"""
import datetime
import logging
import math
import time

import requests
from django.contrib.gis.geos import Point
from django.utils import timezone

logger = logging.getLogger(__name__)

URL_STATIONS = "https://services.data.shom.fr/maregraphie/service/tidegauges"
URL_OBSERVATIONS = "https://services.data.shom.fr/maregraphie/observation/json/{code}"
DELAI_REPONSE_S = 45
SOURCE_BRUTE = 1                 # seule source du service qui porte du temps réel
ETATS_EN_SERVICE = ("OK", "ASYNC")
PAUSE_ENTRE_STATIONS_S = 0.15
REFERENTIEL_VALABLE = datetime.timedelta(hours=24)

# Mesures relues à chaque passage pour chaque station.
FENETRE = datetime.timedelta(hours=3)
MESURE_VALABLE = datetime.timedelta(hours=2)
# La surcote est la médiane des écarts de la dernière heure : une vague ou une seiche ne doit pas
# la faire sauter.
LISSAGE = datetime.timedelta(minutes=60)

# ── Ajustement de la marée ──
# Vitesse angulaire des ondes retenues, en degrés par heure (constantes astronomiques).
ONDES = {
    "M2": 28.9841042, "S2": 30.0, "N2": 28.4397295, "K2": 30.0821373, "K1": 15.0410686,
    "O1": 13.9430356, "P1": 14.9589314, "Q1": 13.3986609, "M4": 57.9682084, "MS4": 58.9841042,
    "MN4": 57.4238337, "M6": 86.9523127, "2N2": 27.8953548, "MU2": 27.9682084, "NU2": 28.5125831,
    "L2": 29.5284789, "T2": 29.9589333, "MSF": 1.0158958, "MM": 0.5443747, "2MS6": 87.9682084,
    "M3": 43.4761563, "MK3": 44.0251729,
}
ORIGINE = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
# Le service rend au plus 31 jours par demande.
JOURS_PAR_DEMANDE = 30
JOURS_D_HISTORIQUE = 180
PAS_HISTORIQUE_MIN = 10
JOURS_MINIMUM = 75               # en dessous, l'ajustement diverge hors de sa période
MESURES_MINIMUM = 6000           # 42 jours pleins à dix minutes : tolère des trous, pas un désert
INCERTITUDE_MAX_CM = 25
AJUSTEMENT_VALABLE = datetime.timedelta(days=30)
# Stations (ré)ajustées par passage : six demandes chacune, on étale.
AJUSTEMENTS_PAR_PASSAGE = 5
NIVEAU_PLAUSIBLE_M = (-5.0, 20.0)

NORMALE, MARQUEE, FORTE, INCONNUE = "NORMALE", "MARQUEE", "FORTE", "INCONNUE"
ORDRE_ETATS = (FORTE, MARQUEE, NORMALE, INCONNUE)
# Une surcote est « marquée » au-delà de 30 cm ET de deux fois et demie l'incertitude de la
# station ; « forte » au-delà de 50 cm et de quatre fois l'incertitude.
SEUIL_MARQUEE_CM, FACTEUR_MARQUEE = 30, 2.5
SEUIL_FORTE_CM, FACTEUR_FORTE = 50, 4.0
# Horizon de la prochaine pleine mer : une marée semi-diurne revient en 12 h 25.
HORIZON_PLEINE_MER = datetime.timedelta(hours=13)


def _heures(instant):
    return (instant - ORIGINE).total_seconds() / 3600


def _instant(texte):
    """« 2026/11/15 19:30:00 » (temps universel) -> instant, ou None."""
    try:
        return datetime.datetime.strptime(texte, "%Y/%m/%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def analyser_stations(lignes):
    """Liste du service -> {code: {"nom", "reseau", "etat", "longitude", "latitude"}}, pour les
    marégraphes en service seulement."""
    stations = {}
    for ligne in lignes or []:
        code, etat = str(ligne.get("shom_id") or "").strip(), ligne.get("state")
        longitude, latitude = ligne.get("longitude"), ligne.get("latitude")
        if not code or etat not in ETATS_EN_SERVICE or longitude is None or latitude is None:
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        stations[code] = {"nom": str(ligne.get("name") or "").replace("_", " ").strip()[:120],
                          "reseau": str(ligne.get("reseau") or "")[:20], "etat": etat,
                          "longitude": longitude, "latitude": latitude}
    return stations


def analyser_observations(corps):
    """Réponse du service -> [(instant, niveau en mètres)…] trié, valeurs aberrantes écartées."""
    mesures = []
    for point in (corps or {}).get("data") or []:
        instant, valeur = _instant(point.get("timestamp")), point.get("value")
        if instant is None or valeur is None:
            continue
        if not (NIVEAU_PLAUSIBLE_M[0] <= valeur <= NIVEAU_PLAUSIBLE_M[1]):
            continue
        mesures.append((instant, float(valeur)))
    mesures.sort()
    return mesures


def telecharger_observations(code, debut, fin, pas_min=None):
    params = {"sources": SOURCE_BRUTE, "dtStart": debut.strftime("%Y-%m-%dT%H:%M:%S"),
              "dtEnd": fin.strftime("%Y-%m-%dT%H:%M:%S")}
    if pas_min:
        params["interval"] = pas_min
    reponse = requests.get(URL_OBSERVATIONS.format(code=code), params=params, timeout=DELAI_REPONSE_S)
    reponse.raise_for_status()
    return analyser_observations(reponse.json())


# ── La marée calculée ──

def _matrice(heures):
    import numpy

    colonnes = [numpy.ones_like(heures)]
    for vitesse in ONDES.values():
        angle = numpy.radians(vitesse) * heures
        colonnes += [numpy.cos(angle), numpy.sin(angle)]
    return numpy.stack(colonnes, axis=1)


def ajuster(mesures):
    """Ajuste la marée d'une station sur son historique. Rend le dictionnaire à garder
    ({"coefficients", "incertitude_cm", "jours", "mesures", "maximum_m", "maximum_le"}), ou None
    si l'historique est trop court, trop troué, ou si la marée calculée n'est pas assez fidèle.

    L'incertitude est mesurée honnêtement : on ajuste sur les deux premiers tiers, on compare au
    dernier tiers (que cet ajustement-là n'a pas vu), et c'est cet écart-type qui est retenu.
    Les coefficients gardés, eux, sont ajustés sur tout l'historique."""
    import numpy

    if len(mesures) < MESURES_MINIMUM:
        return None
    heures = numpy.array([_heures(instant) for instant, _niveau in mesures])
    niveaux = numpy.array([niveau for _instant_, niveau in mesures])
    jours = (heures[-1] - heures[0]) / 24
    if jours < JOURS_MINIMUM:
        return None

    coupure = heures[0] + (heures[-1] - heures[0]) * 2 / 3
    appris, verifie = heures <= coupure, heures > coupure
    if verifie.sum() < 500 or (heures[appris][-1] - heures[appris][0]) / 24 < JOURS_MINIMUM * 2 / 3:
        return None
    partiel, *_ = numpy.linalg.lstsq(_matrice(heures[appris]), niveaux[appris], rcond=None)
    ecarts = niveaux[verifie] - _matrice(heures[verifie]) @ partiel
    # L'écart moyen (niveau moyen qui dérive avec la saison) n'est pas de l'incertitude sur la
    # marée : il est absorbé par l'ajustement complet, qui voit toute la période.
    incertitude_cm = float(numpy.std(ecarts) * 100)
    if not math.isfinite(incertitude_cm) or incertitude_cm > INCERTITUDE_MAX_CM:
        return None

    coefficients, *_ = numpy.linalg.lstsq(_matrice(heures), niveaux, rcond=None)
    rang_max = int(numpy.argmax(niveaux))
    return {
        "coefficients": [round(float(c), 5) for c in coefficients],
        "incertitude_cm": round(incertitude_cm, 1),
        "jours": round(float(jours)), "mesures": len(mesures),
        "maximum_m": round(float(niveaux[rang_max]), 2),
        "maximum_le": mesures[rang_max][0].isoformat(),
    }


def maree_attendue(ajustement, instants):
    """Niveau de marée calculé (mètres) à chacun des instants."""
    import numpy

    heures = numpy.array([_heures(instant) for instant in instants])
    return _matrice(heures) @ numpy.array(ajustement["coefficients"])


def estimer(ajustement, mesures, maintenant):
    """D'après les mesures récentes et l'ajustement d'une station : {"surcote_cm",
    "maree_attendue_m", "pleine_mer_le", "pleine_mer_niveau_m"}. La surcote est la médiane des
    écarts de la dernière heure ; la pleine mer est la prochaine, avec la surcote du moment
    ajoutée -- c'est le niveau que l'on verra si rien ne change d'ici là."""
    import numpy

    if not ajustement or not mesures:
        return None
    dernier = mesures[-1][0]
    recentes = [(instant, niveau) for instant, niveau in mesures if dernier - instant <= LISSAGE]
    attendues = maree_attendue(ajustement, [instant for instant, _niveau in recentes])
    surcote = float(numpy.median(numpy.array([niveau for _instant_, niveau in recentes]) - attendues))

    pas = [maintenant + datetime.timedelta(minutes=5 * rang)
           for rang in range(int(HORIZON_PLEINE_MER.total_seconds() // 300) + 1)]
    courbe = maree_attendue(ajustement, pas)
    # Premier sommet de la courbe ; à défaut (mer sans marée nette), son point le plus haut.
    sommets = [rang for rang in range(1, len(courbe) - 1)
               if courbe[rang] >= courbe[rang - 1] and courbe[rang] > courbe[rang + 1]]
    rang = sommets[0] if sommets else int(numpy.argmax(courbe))
    return {
        "surcote_cm": round(surcote * 100),
        "maree_attendue_m": round(float(attendues[-1]), 2),
        "pleine_mer_le": pas[rang],
        "pleine_mer_niveau_m": round(float(courbe[rang]) + surcote, 2),
    }


def etat(station, maintenant=None):
    """Palier d'affichage d'un marégraphe d'après sa surcote estimée et sa propre incertitude."""
    maintenant = maintenant or timezone.now()
    if (station.surcote_cm is None or station.niveau_le is None
            or maintenant - station.niveau_le > MESURE_VALABLE or not station.ajustement):
        return INCONNUE
    incertitude = station.ajustement.get("incertitude_cm")
    if incertitude is None:
        incertitude = INCERTITUDE_MAX_CM
    if station.surcote_cm >= max(SEUIL_FORTE_CM, FACTEUR_FORTE * incertitude):
        return FORTE
    if station.surcote_cm >= max(SEUIL_MARQUEE_CM, FACTEUR_MARQUEE * incertitude):
        return MARQUEE
    return NORMALE


# ── Relevé ──

def _mettre_a_jour_le_referentiel(maintenant):
    from .models import Maregraphe

    reponse = requests.get(URL_STATIONS, timeout=DELAI_REPONSE_S)
    reponse.raise_for_status()
    stations = analyser_stations(reponse.json())
    if not stations:
        raise ValueError("liste des marégraphes vide")
    connues = {station.code: station for station in Maregraphe.objects.all()}
    for code, description in stations.items():
        champs = {"nom": description["nom"], "reseau": description["reseau"],
                  "location": Point(description["longitude"], description["latitude"], srid=4326),
                  "referentiel_le": maintenant}
        station = connues.get(code)
        if station is None:
            Maregraphe.objects.create(code=code, **champs)
        else:
            Maregraphe.objects.filter(pk=code).update(**champs)
    # Un marégraphe sorti du service (panne longue, dépose) part avec son ajustement.
    Maregraphe.objects.exclude(code__in=stations).delete()


def _ajuster_une_station(station, maintenant):
    """Relit six mois de mesures de la station et (ré)ajuste sa marée. L'essai est daté même s'il
    échoue : une station sans historique suffisant n'est pas retentée à chaque passage."""
    mesures = []
    for tranche in range(JOURS_D_HISTORIQUE // JOURS_PAR_DEMANDE):
        fin = maintenant - datetime.timedelta(days=JOURS_PAR_DEMANDE * tranche)
        time.sleep(PAUSE_ENTRE_STATIONS_S)
        mesures += telecharger_observations(station.code, fin - datetime.timedelta(days=JOURS_PAR_DEMANDE),
                                            fin, pas_min=PAS_HISTORIQUE_MIN)
    station.ajustement = ajuster(sorted(set(mesures))) or {}
    station.ajuste_le = maintenant
    station.save(update_fields=["ajustement", "ajuste_le"])


def relever(maintenant=None):
    """Relit la liste des marégraphes si elle a plus d'un jour, copie le niveau de chacun,
    estime sa surcote, puis (ré)ajuste la marée de quelques stations. Rend le nombre de
    marégraphes qui ont donné une mesure."""
    from .models import Maregraphe

    maintenant = maintenant or timezone.now()
    plus_recent = Maregraphe.objects.order_by("-referentiel_le").values_list("referentiel_le", flat=True).first()
    if plus_recent is None or maintenant - plus_recent > REFERENTIEL_VALABLE:
        _mettre_a_jour_le_referentiel(maintenant)

    mesurees, pannes = 0, 0
    stations = list(Maregraphe.objects.all())
    for station in stations:
        time.sleep(PAUSE_ENTRE_STATIONS_S)
        try:
            mesures = telecharger_observations(station.code, maintenant - FENETRE, maintenant)
        except (requests.RequestException, ValueError) as exc:
            pannes += 1
            logger.warning("Marégraphe %s : mesures non relevées (%s).", station.nom, type(exc).__name__)
            continue
        if not mesures:
            continue
        station.niveau_le, station.niveau_m = mesures[-1][0], round(mesures[-1][1], 2)
        estimation = estimer(station.ajustement, mesures, maintenant)
        station.surcote_cm = estimation["surcote_cm"] if estimation else None
        station.maree_attendue_m = estimation["maree_attendue_m"] if estimation else None
        station.pleine_mer_le = estimation["pleine_mer_le"] if estimation else None
        station.pleine_mer_niveau_m = estimation["pleine_mer_niveau_m"] if estimation else None
        station.save(update_fields=["niveau_le", "niveau_m", "surcote_cm", "maree_attendue_m",
                                    "pleine_mer_le", "pleine_mer_niveau_m"])
        mesurees += 1
    if stations and pannes == len(stations):
        raise ValueError("aucun marégraphe n'a répondu")

    # Les stations jamais ajustées d'abord, puis celles dont l'ajustement a vieilli.
    a_ajuster = sorted(
        (station for station in stations
         if station.ajuste_le is None or maintenant - station.ajuste_le > AJUSTEMENT_VALABLE),
        key=lambda station: (station.ajuste_le is not None, station.ajuste_le or maintenant, station.code),
    )[:AJUSTEMENTS_PAR_PASSAGE]
    for station in a_ajuster:
        try:
            _ajuster_une_station(station, maintenant)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Marégraphe %s : marée non ajustée (%s).", station.nom, type(exc).__name__)
    return mesurees
