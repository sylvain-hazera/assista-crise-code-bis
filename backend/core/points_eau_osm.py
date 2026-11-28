"""Points d'eau incendie d'OpenStreetMap : relevé département par département (24/11/2026).

SOURCE
OpenStreetMap, via l'API Overpass, licence ODbL : « © contributeurs OpenStreetMap ». Des
saisies bénévoles, non validées par les SDIS, sans état de disponibilité (sauf un hydrant
marqué désaffecté) : une couche INDICATIVE. Elle n'est jamais fusionnée avec une base de SDIS
(une base fusionnée devrait être publiée sous ODbL) : chaque point garde `source = OSM`.

LA ROTATION (décision de Sylvain : « France entière, en parsant département par département sur
plusieurs jours »)
Un département par passage, toutes les deux heures : le jamais relevé d'abord, puis ceux en
échec dont l'attente est écoulée (6, 12, 24 puis 48 h), puis le plus anciennement relevé. La
France (101 départements) se parcourt en neuf jours environ.

SERVEURS DE SECOURS ET DÉCOUPAGE (28/11/2026)
Le serveur principal saturait (55 départements sur 99 en échec au premier tour) : la requête
part ensuite vers deux serveurs publics de secours, puis, si aucun ne répond, en quatre
rectangles plus petits (voir SERVEURS et interroger_par_morceaux).

POURQUOI UN RECTANGLE, ET PAS LA LIMITE DU DÉPARTEMENT
Les serveurs Overpass publics saturent souvent (constaté le 24/11/2026), et une requête sur une
limite administrative leur coûte plus qu'un rectangle. Le découpage OSM a aussi ses exceptions
(Rhône et Métropole de Lyon, Paris, outre-mer). Le rectangle est donc celui des centres de nos
communes du département, un peu élargi ; chaque point est ensuite rattaché à la commune dont
le centre est le plus proche, et n'est gardé que s'il tombe dans le département demandé.

TRADUCTION DES BALISES
Celle du wiki OSM (FR:Tag:emergency=fire_hydrant, « Correspondance avec le modèle PEI ») :
pillar → PI ; underground, wall, pipe → BI ; une source d'eau naturelle (lac, étang, piscine,
puits, cours d'eau) → PA ; une citerne → CI ; `ref` → référence terrain ; `ref:FR:SIS` →
identifiant du SDIS ; `operator` → gestionnaire ; `disused:emergency=fire_hydrant` →
indisponible. Un débit sans unité n'est pas cru (le wiki recommande les l/min, l'usage français
les m3/h) : il est laissé vide plutôt que faux.

Même règle que les autres sources ouvertes : seul le serveur appelle, depuis la tâche
planifiée ; rien de ce qui part ne désigne une personne, une commune ou une institution.
"""
import datetime
import logging
import math
import re
import time

import requests
import urllib3
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

URL_OVERPASS = "https://overpass-api.de/api/interpreter"
#: Serveurs Overpass publics, mondiaux, gratuits et sans clé, dans l'ordre d'essai (28/11/2026).
#: Le principal (FOSSGIS) est saturé : du 24 au 26/11, 55 départements sur 99 y ont échoué (502).
#: Les deux autres, d'après le tableau des instances publiques du wiki OSM lu le 28/11/2026 :
#: private.coffee (« pas de limite », prévenir pour un gros projet) et VK Maps (« pas de
#: limite »). Notre usage — une requête toutes les deux heures, quatre au pire — reste très en
#: deçà de la règle du principal (10 000 requêtes par jour, divisées par 100 pour un usage
#: régulier). Pas d'appels en parallèle : un serveur après l'autre.
SERVEURS = (
    ("overpass-api.de", URL_OVERPASS),
    ("overpass.private.coffee", "https://overpass.private.coffee/api/interpreter"),
    ("VK Maps", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"),
)
PAUSE_ENTRE_SERVEURS_S = 5
#: Attente avant de réessayer un département en échec : 6 h, puis 12, 24, 48 h au plus.
REESSAI_MAX = datetime.timedelta(hours=48)
ENTETES = {"User-Agent": "Assista-Crise/1.0 (points d'eau incendie)"}
DELAI_REQUETE_S = 180
DELAI_REPONSE_S = 240
TAILLE_MAX = 80 * 1024 * 1024
MARGE_DEGRES = 0.05
REESSAI_APRES = datetime.timedelta(hours=6)
#: En dessous de la moitié de la copie précédente, la réponse est suspecte : copie conservée.
BAISSE_MAX = 0.5
ATTRIBUTION = "© contributeurs OpenStreetMap (ODbL)"

DEPARTEMENTS = (
    "01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 21 22 23 24 25 26 27 28 29 2A 2B "
    "30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 "
    "60 61 62 63 64 65 66 67 68 69 70 71 72 73 74 75 76 77 78 79 80 81 82 83 84 85 86 87 88 89 "
    "90 91 92 93 94 95 971 972 973 974 976"
).split()

_SOURCES_NATURELLES = {
    "lake": "plan_eau", "pond": "plan_eau", "swimming_pool": "piscine", "well": "puits",
    "river": "cours_eau", "stream": "cours_eau", "canal": "cours_eau",
}
_SOURCES = {**_SOURCES_NATURELLES, "main": "reseau_aep", "groundwater": "reseau_irrigation",
            "water_tank": "citerne"}
_NOMBRE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _nombre(texte):
    m = _NOMBRE.search(str(texte or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def debit_m3h(valeur):
    """« 1000 l/min » → 60.0 ; « 60 m3/h » → 60.0 ; « 60 » (sans unité) → None."""
    texte = str(valeur or "").lower().replace(" ", "").replace("³", "3")
    nombre = _nombre(texte)
    if nombre is None:
        return None
    if "l/min" in texte or "lpm" in texte:
        return round(nombre * 0.06, 1)
    if "m3/h" in texte:
        return nombre
    return None


def volume_m3(valeur):
    """« 120 » ou « 120 m3 » → 120.0 ; « 30000 l » → 30.0."""
    texte = str(valeur or "").lower().replace(" ", "")
    nombre = _nombre(texte)
    if nombre is None:
        return None
    if texte.endswith("l") and not texte.endswith("ml"):
        return round(nombre / 1000, 1)
    return nombre


def traduire(tags):
    """Balises d'un nœud OSM → champs de PointEauIncendie (sans position ni département)."""
    emergency = tags.get("emergency") or ""
    desaffecte = tags.get("disused:emergency") == "fire_hydrant"
    if desaffecte and not emergency:
        emergency = "fire_hydrant"
    source = tags.get("water_source", "")
    genre = tags.get("fire_hydrant:type", "")
    if emergency == "fire_hydrant":
        if source in _SOURCES_NATURELLES:
            type_pei = "PA"
        elif source == "water_tank":
            type_pei = "CI"
        elif genre == "pillar":
            type_pei = "PI"
        elif genre in ("underground", "wall", "pipe"):
            type_pei = "BI"
        else:
            type_pei = ""
    elif emergency in ("suction_point", "fire_water_pond"):
        type_pei = "PA"
    elif emergency == "water_tank":
        type_pei = "CI"
    else:
        type_pei = ""
    diametre = _nombre(tags.get("fire_hydrant:diameter"))
    pression = _nombre(tags.get("pressure") or tags.get("fire_hydrant:pressure"))
    return {
        "type_pei": type_pei,
        "source_eau": _SOURCES.get(source, "plan_eau" if emergency == "fire_water_pond" else ""),
        "diametre": int(diametre) if diametre and 0 < diametre < 1000 else None,
        "debit": debit_m3h(tags.get("flow_rate") or tags.get("fire_hydrant:flow_capacity")),
        "volume": volume_m3(tags.get("water_volume") or tags.get("water_tank:volume")),
        "pression": pression if pression is not None and 0 <= pression < 50 else None,
        "ref_terrain": (tags.get("ref") or tags.get("ref:FR:SIS") or "")[:40],
        "type_rd": (tags.get("ref:FR:SIS") or "")[:60],
        "gestionnaire": (tags.get("operator") or "")[:120],
        "disponible": False if desaffecte else None,
    }


# ── Rotation ─────────────────────────────────────────────────────────────────

def attente_apres_echec(echecs):
    """6 h après un échec, puis le double à chaque échec de plus, 48 h au plus."""
    return min(REESSAI_APRES * (2 ** max(0, (echecs or 1) - 1)), REESSAI_MAX)


def prochain_departement(maintenant=None):
    """Le département à relever maintenant, dans cet ordre (28/11/2026) :
    0. jamais essayé ;
    1. en échec, et son attente écoulée — le plus anciennement essayé d'abord : un département
       sans données passe avant la remise à jour d'un département déjà relevé ;
    2. relevé avec succès, le plus ancien d'abord ;
    3. en échec, encore dans son attente (6, 12, 24 puis 48 h)."""
    from .models import ReleveDepartementPEI

    maintenant = maintenant or timezone.now()
    etats = {r.departement_code: r for r in ReleveDepartementPEI.objects.all()}

    def rang(code):
        r = etats.get(code)
        if r is None or (r.releve_le is None and r.essaye_le is None):
            return (0, datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), code)
        if r.essaye_le and (r.releve_le is None or r.essaye_le > r.releve_le):
            if maintenant - r.essaye_le < attente_apres_echec(r.echecs):
                return (3, r.essaye_le, code)
            return (1, r.essaye_le, code)
        return (2, r.releve_le or r.essaye_le, code)

    return min(DEPARTEMENTS, key=rang)


def communes_autour(departement):
    """(rectangle ouest, sud, est, nord ; communes [(code, département, lat, lon)]) : les
    centres des communes du département, et ceux des communes voisines dans le rectangle
    élargi, pour rattacher un point situé près d'une limite au bon département."""
    from .models import Commune

    centres = list(Commune.objects.filter(departement_code=departement, centre_latitude__isnull=False,
                                          centre_longitude__isnull=False)
                   .values_list("centre_latitude", "centre_longitude"))
    if not centres:
        raise ValueError(f"aucune commune connue pour le département {departement}")
    sud = min(c[0] for c in centres) - MARGE_DEGRES
    nord = max(c[0] for c in centres) + MARGE_DEGRES
    ouest = min(c[1] for c in centres) - MARGE_DEGRES
    est = max(c[1] for c in centres) + MARGE_DEGRES
    marge = MARGE_DEGRES * 4
    communes = list(Commune.objects.filter(
        centre_latitude__gte=sud - marge, centre_latitude__lte=nord + marge,
        centre_longitude__gte=ouest - marge, centre_longitude__lte=est + marge,
    ).values_list("code", "departement_code", "centre_latitude", "centre_longitude"))
    return (ouest, sud, est, nord), communes


class _Grille:
    """La commune dont le centre est le plus proche, par cases de 0,1°."""

    PAS = 0.1

    def __init__(self, communes):
        self.cases = {}
        for commune in communes:
            self.cases.setdefault(self._case(commune[2], commune[3]), []).append(commune)

    def _case(self, lat, lon):
        return (math.floor(lat / self.PAS), math.floor(lon / self.PAS))

    def plus_proche(self, lat, lon):
        i, j = self._case(lat, lon)
        cos = math.cos(math.radians(lat))
        for rayon in range(1, 6):
            candidats = [c for di in range(-rayon, rayon + 1) for dj in range(-rayon, rayon + 1)
                         for c in self.cases.get((i + di, j + dj), ())]
            if candidats:
                return min(candidats, key=lambda c: (c[2] - lat) ** 2 + ((c[3] - lon) * cos) ** 2)
        return None


def requete(ouest, sud, est, nord):
    return (f"[out:json][timeout:{DELAI_REQUETE_S}][bbox:{sud:.5f},{ouest:.5f},{nord:.5f},{est:.5f}];"
            '(node["emergency"~"^(fire_hydrant|water_tank|suction_point|fire_water_pond)$"];'
            'node["disused:emergency"="fire_hydrant"];);out body;')


class OverpassIndisponible(RuntimeError):
    """Aucun serveur n'a répondu correctement ; le message les nomme tous."""


def interroger(rectangle):
    """La requête, au premier serveur qui répond correctement (SERVEURS, dans l'ordre)."""
    echecs = []
    for rang, (nom, url) in enumerate(SERVEURS):
        if rang:
            time.sleep(PAUSE_ENTRE_SERVEURS_S)
        try:
            donnees = _interroger_un(url, rectangle)
        except (RuntimeError, ValueError, requests.RequestException, urllib3.exceptions.HTTPError) as erreur:
            echecs.append(f"{nom} : {erreur}"[:80])
            logger.info("Points d'eau OSM : %s indisponible (%s).", nom, erreur)
            continue
        if rang:
            logger.info("Points d'eau OSM : réponse du serveur de secours %s.", nom)
        return donnees
    raise OverpassIndisponible(" ; ".join(echecs))


def interroger_par_morceaux(rectangle):
    """Le rectangle entier, sinon ses quatre quarts réunis (28/11/2026) : une requête plus petite
    passe souvent là où la grande expire. Un quart en échec fait échouer le tout — un
    département à moitié relevé passerait pour complet."""
    try:
        return interroger(rectangle)
    except OverpassIndisponible as erreur:
        logger.info("Points d'eau OSM : rectangle entier impossible (%s), essai en quatre morceaux.", erreur)
    ouest, sud, est, nord = rectangle
    milieu_lon, milieu_lat = (ouest + est) / 2, (sud + nord) / 2
    elements = {}
    for morceau in ((ouest, sud, milieu_lon, milieu_lat), (milieu_lon, sud, est, milieu_lat),
                    (ouest, milieu_lat, milieu_lon, nord), (milieu_lon, milieu_lat, est, nord)):
        for element in interroger(morceau).get("elements", []):
            elements[(element.get("type"), element.get("id"))] = element
    return {"elements": list(elements.values())}


def _interroger_un(url, rectangle):
    reponse = requests.post(url, data={"data": requete(*rectangle)}, headers=ENTETES,
                            timeout=DELAI_REPONSE_S, stream=True)
    if reponse.status_code != 200:
        raise RuntimeError(f"Overpass a répondu {reponse.status_code}")
    contenu = reponse.raw.read(TAILLE_MAX + 1, decode_content=True)
    if len(contenu) > TAILLE_MAX:
        raise RuntimeError("réponse Overpass trop volumineuse")
    import json
    donnees = json.loads(contenu)
    remarque = str(donnees.get("remark") or "")
    if "error" in remarque.lower():
        raise RuntimeError(f"Overpass : {remarque[:200]}")
    return donnees


def lire(donnees, departement, communes, rectangle=None):
    """Éléments Overpass → points du département demandé (dictionnaires prêts à enregistrer)."""
    grille = _Grille(communes)
    points = {}
    for element in donnees.get("elements", []):
        if element.get("type") != "node" or "lat" not in element or "lon" not in element:
            continue
        lat, lon = float(element["lat"]), float(element["lon"])
        if rectangle and not (rectangle[0] <= lon <= rectangle[2] and rectangle[1] <= lat <= rectangle[3]):
            continue
        commune = grille.plus_proche(lat, lon)
        if commune is None or commune[1] != departement:
            continue
        champs = traduire(element.get("tags") or {})
        points[str(element["id"])] = {**champs, "insee": commune[0], "location": Point(lon, lat, srid=4326)}
    return points


def enregistrer(departement, points, maintenant=None):
    from .models import PointEauIncendie, SourcePEI

    maintenant = maintenant or timezone.now()
    existants = PointEauIncendie.objects.filter(source=SourcePEI.OSM, departement_code=departement)
    avant = existants.count()
    if avant >= 20 and len(points) < avant * BAISSE_MAX:
        raise ValueError(f"{len(points)} points au lieu de {avant} : copie précédente conservée")
    champs = ["departement_code", "insee", "type_pei", "type_rd", "source_eau", "diametre", "debit", "volume",
              "pression", "ref_terrain", "gestionnaire", "disponible", "location", "releve_le"]
    objets = [PointEauIncendie(source=SourcePEI.OSM, ref_source=ref, departement_code=departement,
                               releve_le=maintenant, **valeurs) for ref, valeurs in points.items()]
    with transaction.atomic():
        for debut in range(0, len(objets), 2000):
            PointEauIncendie.objects.bulk_create(objets[debut:debut + 2000], update_conflicts=True,
                                                 unique_fields=["source", "ref_source"], update_fields=champs)
        # Ce qui n'a pas été réécrit à l'instant n'est plus dans OSM pour ce département.
        existants.filter(releve_le__lt=maintenant).delete()
    return len(objets)


def relever(departement=None, maintenant=None):
    """Relève un département (le prochain de la rotation par défaut). Rend le nombre de points ;
    lève en cas d'échec (la trace de la source le dit, le département est réessayé plus tard)."""
    from .models import ReleveDepartementPEI

    maintenant = maintenant or timezone.now()
    code = departement or prochain_departement(maintenant)
    etat, _ = ReleveDepartementPEI.objects.get_or_create(departement_code=code)
    etat.essaye_le = maintenant
    etat.save(update_fields=["essaye_le"])
    try:
        rectangle, communes = communes_autour(code)
        nombre = enregistrer(code, lire(interroger_par_morceaux(rectangle), code, communes, rectangle), maintenant)
    except Exception as erreur:
        etat.erreur = f"{type(erreur).__name__}: {erreur}"[:255]
        etat.echecs = (etat.echecs or 0) + 1
        etat.save(update_fields=["erreur", "echecs"])
        raise
    etat.releve_le, etat.nombre, etat.erreur, etat.echecs = maintenant, nombre, "", 0
    etat.save(update_fields=["releve_le", "nombre", "erreur", "echecs"])
    logger.info("Points d'eau OSM : %s points pour le département %s.", nombre, code)
    return nombre
