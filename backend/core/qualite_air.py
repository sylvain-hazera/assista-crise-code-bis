"""Qualité de l'air estimée dans les grandes villes : relevé d'OpenWeather, copie en base.

SOURCE
API « Air Pollution » d'OpenWeather (https://openweathermap.org/api/air-pollution), avec la clé
gratuite du porteur du projet. Données sous licence CC BY-SA 4.0 : la mention « Données météo
fournies par OpenWeather » est OBLIGATOIRE partout où elles s'affichent. Pour un point donné :
un indice de 1 à 5 et les concentrations des principaux polluants, heure par heure, de
maintenant à quatre jours.

CE QUE C'EST, ET CE QUE CE N'EST PAS
- Une ESTIMATION PAR MODÈLE, pas la mesure d'une station : les mesures officielles sont celles
  des associations agréées (Atmo), dont l'accès demande un compte que le projet n'a pas. Un
  modèle mondial ne voit ni un panache d'incendie local, ni une rue encaissée.
- L'indice d'OpenWeather (1 « bon » à 5 « très mauvais »), qui n'est PAS l'indice ATMO français :
  les deux ne se comparent pas.
- Pas une alerte : les épisodes de pollution sont déclarés par les préfectures.

OÙ, ET POURQUOI CES POINTS-LÀ
Ce service s'interroge lieu par lieu. Interroger la commune de chaque institution dirait à
OpenWeather où la plateforme est utilisée ; la règle de la veille l'interdit. Le serveur
interroge donc une liste FIXE, la même pour tous et écrite dans ce fichier : la commune la plus
peuplée de chaque département et collectivité d'outre-mer, plus toutes les communes de plus de
100 000 habitants (112 points, tirés de geo.api.gouv.fr le 15/11/2026). Un écran montre le
point le plus proche et dit à quelle distance il se trouve.

LA CLÉ
Lue dans un secret Docker (`/run/secrets/openweathermap_cle_api`), comme celle de Météo-France :
jamais dans le dépôt, jamais dans un journal. Le service la veut dans l'adresse de la requête ;
toute erreur est donc rapportée par son type, jamais par son texte, qui contiendrait l'adresse.

RIEN N'EST ARCHIVÉ
Seul l'état courant et la prévision à venir sont gardés, réécrits à chaque relevé : la licence
distingue l'usage des données de la constitution d'une base réutilisable.
"""
import datetime
import logging
import os
import time
from pathlib import Path

import requests
from django.contrib.gis.geos import Point
from django.utils import timezone

logger = logging.getLogger(__name__)

URL_PREVISION = "https://api.openweathermap.org/data/2.5/air_pollution/forecast"
ATTRIBUTION = "Données météo fournies par OpenWeather"
DELAI_REPONSE_S = 20
# Le plan gratuit borne le débit ; un appel par seconde reste loin de toute limite.
PAUSE_ENTRE_POINTS_S = 1.1
# Heures de prévision gardées par point.
HEURES_GARDEES = 48
MESURE_VALABLE = datetime.timedelta(hours=3)
# Si plus de la moitié des points échouent, le relevé est compté en échec.
PART_DE_PANNES_TOLEREE = 0.5

LIBELLES = {1: "bon", 2: "correct", 3: "moyen", 4: "mauvais", 5: "très mauvais"}
POLLUANTS = ("pm2_5", "pm10", "no2", "o3", "so2", "co")

# (code INSEE, nom, département, latitude, longitude) -- voir l'en-tête, « Où ».
POINTS = (
    ("01053", "Bourg-en-Bresse", "01", 46.2027, 5.2469),
    ("02691", "Saint-Quentin", "02", 49.8475, 3.2790),
    ("03185", "Montluçon", "03", 46.3428, 2.6080),
    ("04112", "Manosque", "04", 43.8293, 5.7896),
    ("05061", "Gap", "05", 44.5797, 6.0616),
    ("06088", "Nice", "06", 43.7032, 7.2528),
    ("07010", "Annonay", "07", 45.2449, 4.6419),
    ("08105", "Charleville-Mézières", "08", 49.7802, 4.7304),
    ("09225", "Pamiers", "09", 43.1278, 1.6168),
    ("10387", "Troyes", "10", 48.2924, 4.0761),
    ("11262", "Narbonne", "11", 43.1493, 3.0337),
    ("12202", "Rodez", "12", 44.3591, 2.5699),
    ("13055", "Marseille", "13", 43.2803, 5.3806),
    ("13001", "Aix-en-Provence", "13", 43.5360, 5.3879),
    ("14118", "Caen", "14", 49.1846, -0.3722),
    ("15014", "Aurillac", "15", 44.9281, 2.4416),
    ("16015", "Angoulême", "16", 45.6458, 0.1450),
    ("17300", "La Rochelle", "17", 46.1620, -1.1765),
    ("18033", "Bourges", "18", 47.0780, 2.3983),
    ("19031", "Brive-la-Gaillarde", "19", 45.1450, 1.5144),
    ("21231", "Dijon", "21", 47.3319, 5.0322),
    ("22278", "Saint-Brieuc", "22", 48.5108, -2.7657),
    ("23096", "Guéret", "23", 46.1585, 1.8705),
    ("24322", "Périgueux", "24", 45.1939, 0.7105),
    ("25056", "Besançon", "25", 47.2602, 6.0123),
    ("26362", "Valence", "26", 44.9234, 4.9164),
    ("27229", "Évreux", "27", 49.0180, 1.1406),
    ("28085", "Chartres", "28", 48.4481, 1.5046),
    ("29019", "Brest", "29", 48.4085, -4.4996),
    ("2A004", "Ajaccio", "2A", 41.9228, 8.7058),
    ("2B033", "Bastia", "2B", 42.6861, 9.4240),
    ("30189", "Nîmes", "30", 43.8322, 4.3429),
    ("31555", "Toulouse", "31", 43.6007, 1.4328),
    ("32013", "Auch", "32", 43.6602, 0.5673),
    ("33063", "Bordeaux", "33", 44.8624, -0.5848),
    ("34172", "Montpellier", "34", 43.6100, 3.8742),
    ("35238", "Rennes", "35", 48.1159, -1.6884),
    ("36044", "Châteauroux", "36", 46.8023, 1.6903),
    ("37261", "Tours", "37", 47.3943, 0.6949),
    ("38185", "Grenoble", "38", 45.1842, 5.7155),
    ("39198", "Dole", "39", 47.0739, 5.5024),
    ("40192", "Mont-de-Marsan", "40", 43.8931, -0.5009),
    ("41018", "Blois", "41", 47.5813, 1.3049),
    ("42218", "Saint-Étienne", "42", 45.4241, 4.3665),
    ("43157", "Le Puy-en-Velay", "43", 45.0283, 3.8973),
    ("44109", "Nantes", "44", 47.2382, -1.5603),
    ("45234", "Orléans", "45", 47.8734, 1.9122),
    ("46042", "Cahors", "46", 44.4565, 1.4390),
    ("47001", "Agen", "47", 44.2010, 0.6302),
    ("48095", "Mende", "48", 44.5349, 3.4909),
    ("49007", "Angers", "49", 47.4819, -0.5629),
    ("50129", "Cherbourg-en-Cotentin", "50", 49.6277, -1.6356),
    ("51454", "Reims", "51", 49.2535, 4.0551),
    ("52448", "Saint-Dizier", "52", 48.6319, 4.9399),
    ("53130", "Laval", "53", 48.0578, -0.7692),
    ("54395", "Nancy", "54", 48.6881, 6.1734),
    ("55545", "Verdun", "55", 49.1440, 5.3609),
    ("56121", "Lorient", "56", 47.7494, -3.3799),
    ("57463", "Metz", "57", 49.1048, 6.1962),
    ("58194", "Nevers", "58", 46.9852, 3.1598),
    ("59350", "Lille", "59", 50.6311, 3.0468),
    ("60057", "Beauvais", "60", 49.4425, 2.0877),
    ("61001", "Alençon", "61", 48.4310, 0.0923),
    ("62193", "Calais", "62", 50.9523, 1.8690),
    ("63113", "Clermont-Ferrand", "63", 45.7870, 3.1127),
    ("64445", "Pau", "64", 43.3219, -0.3435),
    ("65440", "Tarbes", "65", 43.2387, 0.0653),
    ("66136", "Perpignan", "66", 42.6990, 2.9045),
    ("67482", "Strasbourg", "67", 48.5691, 7.7621),
    ("68224", "Mulhouse", "68", 47.7526, 7.3255),
    ("69123", "Lyon", "69", 45.7580, 4.8351),
    ("69266", "Villeurbanne", "69", 45.7719, 4.8898),
    ("70550", "Vesoul", "70", 47.6323, 6.1523),
    ("71076", "Chalon-sur-Saône", "71", 46.7896, 4.8509),
    ("72181", "Le Mans", "72", 47.9819, 0.1957),
    ("73065", "Chambéry", "73", 45.5822, 5.9064),
    ("74010", "Annecy", "74", 45.9024, 6.1264),
    ("75056", "Paris", "75", 48.8589, 2.3470),
    ("76351", "Le Havre", "76", 49.4958, 0.1312),
    ("76540", "Rouen", "76", 49.4412, 1.0912),
    ("77284", "Meaux", "77", 48.9573, 2.9035),
    ("78646", "Versailles", "78", 48.8039, 2.1191),
    ("79191", "Niort", "79", 46.3274, -0.4613),
    ("80021", "Amiens", "80", 49.8987, 2.2847),
    ("81004", "Albi", "81", 43.9290, 2.1323),
    ("82121", "Montauban", "82", 44.0217, 1.3646),
    ("83137", "Toulon", "83", 43.1364, 5.9334),
    ("84007", "Avignon", "84", 43.9416, 4.8333),
    ("85191", "La Roche-sur-Yon", "85", 46.6659, -1.4162),
    ("86194", "Poitiers", "86", 46.5846, 0.3715),
    ("87085", "Limoges", "87", 45.8567, 1.2260),
    ("88160", "Épinal", "88", 48.1637, 6.4867),
    ("89024", "Auxerre", "89", 47.7939, 3.5821),
    ("90010", "Belfort", "90", 47.6458, 6.8410),
    ("91228", "Évry-Courcouronnes", "91", 48.6287, 2.4313),
    ("92012", "Boulogne-Billancourt", "92", 48.8375, 2.2429),
    ("93066", "Saint-Denis", "93", 48.9378, 2.3657),
    ("93048", "Montreuil", "93", 48.8637, 2.4491),
    ("94081", "Vitry-sur-Seine", "94", 48.7893, 2.3951),
    ("95018", "Argenteuil", "95", 48.9501, 2.2478),
    ("97101", "Les Abymes", "971", 16.2678, -61.4967),
    ("97209", "Fort-de-France", "972", 14.6492, -61.0686),
    ("97302", "Cayenne", "973", 4.9464, -52.3319),
    ("97411", "Saint-Denis", "974", -20.9434, 55.4444),
    ("97415", "Saint-Paul", "974", -21.0366, 55.3402),
    ("97502", "Saint-Pierre", "975", 46.7880, -56.1805),
    ("97611", "Mamoudzou", "976", -12.7875, 45.1964),
    ("97701", "Saint-Barthélemy", "977", 17.9204, -62.8601),
    ("97801", "Saint-Martin", "978", 18.0855, -63.0620),
    ("98613", "Uvea", "986", -13.2846, -176.2065),
    ("98715", "Faaa", "987", -17.5843, -149.5600),
    ("98818", "Nouméa", "988", -22.3363, 166.4076),
)


class CleAbsente(Exception):
    """Aucune clé OpenWeather sur cette machine : rien à relever."""


def lire_cle():
    chemin = Path(os.environ.get("OPENWEATHERMAP_CLE_API_FILE", "/run/secrets/openweathermap_cle_api"))
    try:
        cle = chemin.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return cle or None


def analyser(corps, maintenant):
    """Réponse du service -> {"indice", "composants", "mesure_le", "prevision"} ou None si elle
    ne porte aucune heure exploitable. `prevision` : [[instant ISO, indice]…] pour les heures à
    venir ; l'état courant est l'heure la plus proche de maintenant."""
    heures = []
    for pas in (corps or {}).get("list") or []:
        try:
            instant = datetime.datetime.fromtimestamp(int(pas["dt"]), tz=datetime.timezone.utc)
            indice = int(pas["main"]["aqi"])
        except (KeyError, TypeError, ValueError):
            continue
        if indice not in LIBELLES:
            continue
        composants = {nom: round(float(valeur), 1) for nom, valeur in (pas.get("components") or {}).items()
                      if nom in POLLUANTS and isinstance(valeur, (int, float))}
        heures.append((instant, indice, composants))
    if not heures:
        return None
    heures.sort(key=lambda heure: heure[0])
    instant, indice, composants = min(heures, key=lambda heure: abs(heure[0] - maintenant))
    limite = maintenant + datetime.timedelta(hours=HEURES_GARDEES)
    return {
        "indice": indice, "composants": composants, "mesure_le": instant,
        "prevision": [[h.isoformat(), i] for h, i, _composants in heures if instant < h <= limite],
    }


def pire_a_venir(prevision, maintenant=None, heures=24):
    """Le plus mauvais indice prévu dans les `heures` qui viennent : (indice, instant de sa
    première heure), ou (None, None) sans prévision."""
    from django.utils.dateparse import parse_datetime

    maintenant = maintenant or timezone.now()
    limite = maintenant + datetime.timedelta(hours=heures)
    a_venir = [(indice, instant) for instant, indice in
               ((parse_datetime(texte), indice) for texte, indice in prevision or [])
               if instant is not None and maintenant < instant <= limite]
    if not a_venir:
        return None, None
    pire = max(indice for indice, _instant in a_venir)
    return pire, min(instant for indice, instant in a_venir if indice == pire)


def relever(maintenant=None):
    """Relève tous les points de la liste. Rend le nombre de points à jour."""
    from .models import PointQualiteAir

    cle = lire_cle()
    if cle is None:
        raise CleAbsente()
    maintenant = maintenant or timezone.now()
    reussis, pannes = 0, 0
    for code, nom, departement, latitude, longitude in POINTS:
        time.sleep(PAUSE_ENTRE_POINTS_S)
        try:
            reponse = requests.get(URL_PREVISION, timeout=DELAI_REPONSE_S,
                                   params={"lat": latitude, "lon": longitude, "appid": cle})
            reponse.raise_for_status()
            etat = analyser(reponse.json(), maintenant)
        except (requests.RequestException, ValueError) as exc:
            # Jamais le texte de l'erreur : il porte l'adresse de la requête, donc la clé.
            pannes += 1
            logger.warning("Qualité de l'air : %s non relevé (%s).", nom, type(exc).__name__)
            continue
        if etat is None:
            pannes += 1
            continue
        PointQualiteAir.objects.update_or_create(code=code, defaults={
            "nom": nom, "departement": departement, "location": Point(longitude, latitude, srid=4326),
            "indice": etat["indice"], "composants": etat["composants"], "mesure_le": etat["mesure_le"],
            "prevision": etat["prevision"], "releve_le": maintenant})
        reussis += 1
    PointQualiteAir.objects.exclude(code__in=[point[0] for point in POINTS]).delete()
    if pannes > len(POINTS) * PART_DE_PANNES_TOLEREE:
        raise ValueError(f"{pannes} points sur {len(POINTS)} n'ont pas pu être relevés")
    return reussis
