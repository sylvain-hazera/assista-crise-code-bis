"""Simulation grossière d'inondation par commune (outil de planification préventive pour les
mairies -- pas une prévision hydraulique) : grille d'altitude IGN, remplissage par connexité par
palier de niveau d'eau, puis profondeur simulée par adresse BAN. Voir le plan de conception
"Simulation d'inondation" pour le détail des compromis retenus.

Même style que habitations.py/geo_lookup.py : appels externes en urllib.request pur (jamais
requests/httpx), jamais d'exception qui remonte -- un échec d'appel externe donne un résultat
partiel/vide, jamais une 500.

Trois briques calculées, mises en cache en base (voir models.py) :
1. `grille_altitude_commune` -- grille régulière de points + altitude (IGN), une fois par commune.
2. `calculer_paliers_inondation` -- un polygone par niveau d'eau testé, remplissage par
   connexité DEPUIS LA BORDURE DE LA GRILLE (limite assumée : faute d'une géométrie de cours
   d'eau en base, on part du principe que l'eau entre par les bords de la commune -- correct pour
   une commune traversée par un cours d'eau qui en sort/y entre, trompeur si le vrai risque vient
   d'un point isolé au milieu de la commune sans lien avec sa bordure).
3. `seuils_inondation_adresses` -- pour chaque adresse BAN (scanner_ban_commune, réutilisé tel
   quel), le plus petit niveau simulé qui l'atteint.

IMPORTANT -- exécution : `simuler_inondation_commune` (le calcul complet) ne doit JAMAIS être
appelée en synchrone dans une requête HTTP -- mesuré en conditions réelles (Le Porge, une petite
commune) à ~30s, une grande ville (des dizaines de milliers d'adresses BAN, boucle de test
géométrique non plafonnée) dépasserait largement le timeout gunicorn. Seule
`tasks.calculer_simulation_inondation_task` (Celery) l'appelle ; la vue HTTP
(`SimulationInondationView`) ne fait que lire le cache via `resultat_en_cache` ou déclencher la
tâche, jamais calculer elle-même.
"""
import fcntl
import json
import math
import time
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from scipy import ndimage

# Plage calée sur une crue historique réelle, pas un chiffre arbitraire (constaté le 2026-09-29 :
# 3m ne couvrait pas du tout la crue de référence de la Garonne à Portets). Repère retenu :
# crue de mars 1930 (crue de référence de la Garonne, ~200 victimes) -- à la station Cadillac
# (juste à côté de Portets), hauteur relevée 11,77 m à l'échelle, zéro d'échelle à -0,232 m NGF
# (source : hydro.eaufrance.fr, fiche station O960 0010 01) => crête de crue ≈ 11,54 m NGF.
# Vérifié cohérent avec la grille IGN réelle de Portets (altitude mini -0,74 m NGF côté Garonne,
# jusqu'à ~80 m côté coteaux) : la crue de 1930 représente donc une montée d'environ 12 m
# au-dessus du lit habituel. Plage élargie à 0-12m (pas 0,5m, 25 paliers) pour couvrir cette
# crue de référence avec de la marge. Le calcul étant maintenant asynchrone (Celery, voir
# tasks.py), le nombre de paliers n'est plus contraint par le timeout gunicorn (60s) comme
# lors du premier réglage (Le Porge, 2026-09-29) -- seule limite désormais : CELERY_TASK_TIME_LIMIT
# (10 min, voir settings.py), largement suffisant même pour une grande commune.
NIVEAUX_PAR_DEFAUT = [round(n * 0.5, 2) for n in range(0, 25)]  # 0 à 12m par pas de 0,5m
PAS_METRES_PAR_DEFAUT = 75
METRES_PAR_DEGRE_LAT = 111_320


def _fetch_json(url: str, timeout: int = 8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _bbox_commune(commune_code: str):
    """Boîte englobante (lon_min, lat_min, lon_max, lat_max) de la commune, depuis son contour
    geo.api.gouv.fr (jamais stocké en base contrairement à Commune.centre* -- seulement utile le
    temps de construire la grille, voir grille_altitude_commune)."""
    url = f"https://geo.api.gouv.fr/communes/{urllib.parse.quote(commune_code)}?fields=contour"
    data = None
    for tentative in range(3):   # geo.api.gouv.fr a des ratés passagers (constaté le 20/10/2026)
        if tentative:
            time.sleep(1)
        data = _fetch_json(url)
        if data:
            break
    if not data:
        return None
    contour = data.get("contour")
    if not contour:
        return None
    coords_type = contour.get("type")
    rings = contour.get("coordinates") or []
    if coords_type == "Polygon":
        anneaux = rings
    elif coords_type == "MultiPolygon":
        anneaux = [anneau for polygone in rings for anneau in polygone]
    else:
        return None
    lons, lats = [], []
    for anneau in anneaux:
        for point in anneau:
            lons.append(point[0])
            lats.append(point[1])
    if not lons:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def _grille_points_bbox(bbox, pas_metres: int):
    """Points régulièrement espacés (lon, lat) dans `bbox`, pas exprimé en mètres -- converti en
    degrés via une approximation locale (suffisante à l'échelle d'une commune, jamais utilisée
    au-delà)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    lat_ref = (lat_min + lat_max) / 2
    pas_lat = pas_metres / METRES_PAR_DEGRE_LAT
    pas_lon = pas_metres / (METRES_PAR_DEGRE_LAT * max(math.cos(math.radians(lat_ref)), 0.1))

    lats = np.arange(lat_min, lat_max + pas_lat, pas_lat)
    lons = np.arange(lon_min, lon_max + pas_lon, pas_lon)
    # Grille plafonnée -- une commune très étendue avec un petit pas ferait exploser le nombre
    # d'appels IGN par lot ; 120x120 (14400 points) reste largement dans le raisonnable pour un
    # outil "grossier" par commune.
    MAX_COTE = 120
    if len(lats) > MAX_COTE:
        lats = np.linspace(lat_min, lat_max, MAX_COTE)
    if len(lons) > MAX_COTE:
        lons = np.linspace(lon_min, lon_max, MAX_COTE)
    return lons, lats


# Débit maximal vers l'API d'altimétrie IGN, partagé par tous les processus du conteneur (les
# tâches paliers et ruissellement tournent en même temps) : mesuré le 20/10/2026, l'IGN renvoie
# 429 (Retry-After) dès ~5 requêtes/s par IP, 3/s passent sans refus. Avant cette limite, 8 lots
# parallèles se faisaient refuser à ~90 % et toute simulation échouait (grille à ~10 %).
IGN_REQUETES_PAR_SECONDE = 2.5
_FICHIER_DEBIT_IGN = "/tmp/assista-ign-debit"
IGN_TENTATIVES_429 = 6


def _attendre_creneau_ign():
    """Réserve le prochain créneau d'appel IGN (verrou fichier : vaut entre processus Celery)."""
    intervalle = 1 / IGN_REQUETES_PAR_SECONDE
    with open(_FICHIER_DEBIT_IGN, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            prochain = float(f.read() or 0)
        except ValueError:
            prochain = 0.0
        maintenant = time.time()
        creneau = max(maintenant, prochain)
        f.seek(0)
        f.truncate()
        f.write(str(creneau + intervalle))
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    if creneau > maintenant:
        time.sleep(creneau - maintenant)


def _altitudes_lot(lons: list, lats: list, debut: int):
    lon_str = "|".join(str(v) for v in lons)
    lat_str = "|".join(str(v) for v in lats)
    url = (
        "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
        f"?lon={lon_str}&lat={lat_str}&resource=ign_rge_alti_wld&indent=false"
    )
    data = None
    for _ in range(IGN_TENTATIVES_429):
        _attendre_creneau_ign()
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                break
            # trop de requêtes : attendre ce que l'IGN demande, puis réessayer ce lot
            try:
                attente = float(exc.headers.get("Retry-After") or 2)
            except ValueError:
                attente = 2
            time.sleep(min(max(attente, 1), 10))
        except Exception:
            break
    resultat = {}
    if not data:
        return resultat
    for i, elevation in enumerate(data.get("elevations") or []):
        valeur = elevation.get("z") if isinstance(elevation, dict) else None
        if valeur is not None:
            resultat[debut + i] = valeur
    return resultat


def _altitudes_ign_par_lots(lons: list, lats: list, taille_lot: int = 200, max_workers: int = 4,
                            tentatives: int = 3) -> list:
    """Altitude IGN (RGE ALTI, API https://data.geopf.fr/altimetrie) pour une liste de points,
    par lots parallélisés (même patron que habitations.scanner_ban_commune -- mesuré en
    conditions réelles le 2026-09-29 : une grille de commune peut représenter des dizaines de
    lots, du séquentiel serait bien trop long). Un point non résolu vaut None, jamais une
    exception.

    Les lots EN ÉCHEC (réponse absente : délai dépassé, service surchargé) sont relancés,
    jusqu'à `tentatives` passes, avec moins de parallélisme et une pause croissante -- constaté
    le 20/10/2026 : l'IGN, lent ce jour-là, n'avait renvoyé que ~10 % des lots, et la grille
    trouée faussait toute la simulation (Portets : 0,2 km² inondés au lieu de 7)."""
    altitudes = [None] * len(lons)
    a_faire = [(debut, min(debut + taille_lot, len(lons))) for debut in range(0, len(lons), taille_lot)]

    for tentative in range(tentatives):
        if tentative:
            time.sleep(2 * tentative)
        echoues = []
        with ThreadPoolExecutor(max_workers=max_workers if tentative == 0 else 2) as executor:
            futures = {
                executor.submit(_altitudes_lot, lons[debut:fin], lats[debut:fin], debut): (debut, fin)
                for debut, fin in a_faire
            }
            for future in as_completed(futures):
                resultat = future.result()
                if not resultat:
                    echoues.append(futures[future])
                    continue
                for i, valeur in resultat.items():
                    altitudes[i] = valeur
        a_faire = echoues
        if not a_faire:
            break
    return altitudes


# Part minimale de la grille effectivement renvoyée par l'IGN pour la juger exploitable (et la
# mettre en cache). En dessous, la simulation échoue avec un message clair plutôt que de produire
# -- et de garder pour toujours -- une zone inondée fausse.
COUVERTURE_MIN_GRILLE = 0.98


class GrilleAltitudeIncomplete(Exception):
    """Le service d'altimétrie IGN n'a pas répondu pour une trop grande partie de la commune."""


def grille_altitude_commune(commune_code: str, pas_metres: int = PAS_METRES_PAR_DEFAUT, forcer: bool = False, environment=None):
    """Grille d'altitude d'une commune -- mise en cache (GrilleAltimetrieCommune), recalculée
    seulement si `forcer=True` (le relief ne change pas, pas la peine de réinterroger IGN à
    chaque ouverture de la page)."""
    from .models import Environment, GrilleAltimetrieCommune

    environment = environment or Environment.PROD
    if not forcer:
        existante = GrilleAltimetrieCommune.objects.filter(commune_code=commune_code, environment=environment).first()
        if existante is not None:
            return existante.points

    # Les tâches paliers et ruissellement demandent la même grille en même temps : la seconde
    # attend la première puis lit le cache, au lieu de doubler les appels IGN (débit limité).
    with open(f"/tmp/assista-grille-{commune_code}-{pas_metres}.lock", "a") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        if not forcer:
            existante = GrilleAltimetrieCommune.objects.filter(commune_code=commune_code, environment=environment).first()
            if existante is not None:
                return existante.points
        return _calculer_grille_altitude(commune_code, pas_metres, forcer, environment)


def _calculer_grille_altitude(commune_code: str, pas_metres: int, forcer: bool, environment):
    from .models import GrilleAltimetrieCommune

    bbox = _bbox_commune(commune_code)
    if bbox is None:
        return []

    lons, lats = _grille_points_bbox(bbox, pas_metres)
    grille_lon, grille_lat = np.meshgrid(lons, lats)
    lons_plats = grille_lon.ravel().tolist()
    lats_plats = grille_lat.ravel().tolist()
    attendus = len(lons_plats)

    # Le relief ne dépend pas de l'environnement : une grille COMPLÈTE déjà calculée en PROD (ou
    # en DÉMO) sert telle quelle à l'autre, sans réinterroger l'IGN -- évite aussi que les deux
    # divergent (cas Portets du 20/10/2026).
    if not forcer:
        for autre in GrilleAltimetrieCommune.objects.filter(commune_code=commune_code, pas_metres=pas_metres).exclude(environment=environment):
            if len(autre.points or []) >= attendus * COUVERTURE_MIN_GRILLE:
                GrilleAltimetrieCommune.objects.update_or_create(
                    commune_code=commune_code, environment=environment,
                    defaults={"points": autre.points, "pas_metres": pas_metres},
                )
                return autre.points

    altitudes = _altitudes_ign_par_lots(lons_plats, lats_plats)

    points = [
        {"lon": lon, "lat": lat, "altitude": alt}
        for lon, lat, alt in zip(lons_plats, lats_plats, altitudes)
        if alt is not None
    ]
    if attendus and len(points) < attendus * COUVERTURE_MIN_GRILLE:
        # Jamais mise en cache : un nouvel essai réinterrogera l'IGN.
        raise GrilleAltitudeIncomplete(
            f"Le service d'altimétrie IGN n'a répondu que pour {len(points) * 100 // attendus} % de la "
            "commune (service lent ou indisponible). Réessayez dans quelques minutes."
        )

    GrilleAltimetrieCommune.objects.update_or_create(
        commune_code=commune_code, environment=environment,
        defaults={"points": points, "pas_metres": pas_metres},
    )
    return points


def _tableau_depuis_grille(points: list):
    """Reconstruit la grille de points (lon, lat, altitude) en tableau numpy 2D (lignes = lat
    croissante, colonnes = lon croissante) -- la grille est régulière par construction (voir
    _grille_points_bbox), donc le nombre de lon/lat distincts suffit à retrouver les dimensions,
    sans avoir à stocker nx/ny séparément."""
    lons_uniques = sorted(set(round(p["lon"], 8) for p in points))
    lats_uniques = sorted(set(round(p["lat"], 8) for p in points))
    index_lon = {v: i for i, v in enumerate(lons_uniques)}
    index_lat = {v: i for i, v in enumerate(lats_uniques)}

    altitude = np.full((len(lats_uniques), len(lons_uniques)), np.nan)
    for p in points:
        altitude[index_lat[round(p["lat"], 8)], index_lon[round(p["lon"], 8)]] = p["altitude"]

    return altitude, lons_uniques, lats_uniques


def _polygone_cellule(lon: float, lat: float, pas_metres: int):
    """Petit carré GEOS centré sur (lon, lat), taille = un pas de grille -- brique de base des
    polygones de palier (voir _polygone_paliers_depuis_masque), jamais affichée seule."""
    from django.contrib.gis.geos import Polygon

    lat_ref = lat
    demi_lat = (pas_metres / 2) / METRES_PAR_DEGRE_LAT
    demi_lon = (pas_metres / 2) / (METRES_PAR_DEGRE_LAT * max(math.cos(math.radians(lat_ref)), 0.1))
    return Polygon((
        (lon - demi_lon, lat - demi_lat), (lon + demi_lon, lat - demi_lat),
        (lon + demi_lon, lat + demi_lat), (lon - demi_lon, lat + demi_lat),
        (lon - demi_lon, lat - demi_lat),
    ), srid=4326)


def _polygone_depuis_masque(masque: np.ndarray, lons_uniques: list, lats_uniques: list, pas_metres: int):
    """Union des cellules de `masque` (True = inondée ET connectée à la bordure) en un seul
    (Multi)Polygon GEOS -- aucune dépendance raster/shapely, uniquement GEOS (déjà utilisé
    partout dans ce projet via GeoDjango).

    `unary_union` (algorithme GEOS dédié, cascade/arbre) plutôt qu'une boucle `union.union(...)`
    cellule par cellule -- cette dernière re-traite l'accumulateur déjà complexe à chaque
    itération (repéré en conditions réelles sur Bordeaux le 2026-09-29 : tué par le time limit
    Celery à 540s en pleine union, jamais arrivé jusqu'au calcul des adresses -- voir traceback
    dans les logs, `_polygone_depuis_masque` était le point bloqué, pas le scan BAN)."""
    from django.contrib.gis.geos import MultiPolygon

    indices = np.argwhere(masque)
    if indices.size == 0:
        return None
    polygones = [
        _polygone_cellule(lons_uniques[j], lats_uniques[i], pas_metres)
        for i, j in indices
    ]
    union = MultiPolygon(polygones).unary_union
    if union.geom_type == "Polygon":
        return MultiPolygon(union)
    return union


def calculer_paliers_inondation(
    commune_code: str, niveaux: list | None = None, pas_metres: int = PAS_METRES_PAR_DEFAUT,
    forcer: bool = False, environment=None,
):
    """Un polygone de zone inondée par niveau testé -- remplissage par connexité DEPUIS LA
    BORDURE DE LA GRILLE (voir docstring du module pour la limite assumée). Mis en cache
    (PalierInondationSimule), un par (commune, niveau) -- recalculé seulement si `forcer=True`."""
    from .models import Environment, PalierInondationSimule

    environment = environment or Environment.PROD
    niveaux = niveaux or NIVEAUX_PAR_DEFAUT

    if not forcer:
        deja_calcules = set(
            PalierInondationSimule.objects.filter(commune_code=commune_code, environment=environment)
            .values_list("niveau_metres", flat=True)
        )
        if all(n in deja_calcules for n in niveaux):
            existants = PalierInondationSimule.objects.filter(
                commune_code=commune_code, environment=environment, niveau_metres__in=niveaux,
            )
            return {p.niveau_metres: p.polygone for p in existants}

    points = grille_altitude_commune(commune_code, pas_metres=pas_metres, forcer=forcer, environment=environment)
    if not points:
        return {n: None for n in niveaux}

    altitude, lons_uniques, lats_uniques = _tableau_depuis_grille(points)

    # Bordure de la grille = points de départ de l'inondation (voir docstring du module) : un
    # masque booléen "sur la bordure" réutilisé pour chaque niveau plutôt que recalculé.
    bordure = np.zeros_like(altitude, dtype=bool)
    bordure[0, :] = bordure[-1, :] = True
    bordure[:, 0] = bordure[:, -1] = True

    resultats = {}
    for niveau in niveaux:
        sous_le_niveau = np.where(np.isnan(altitude), False, altitude <= niveau)
        etiquettes, _ = ndimage.label(sous_le_niveau)
        etiquettes_bordure = set(etiquettes[bordure & sous_le_niveau].tolist()) - {0}
        masque_connecte = np.isin(etiquettes, list(etiquettes_bordure)) if etiquettes_bordure else np.zeros_like(sous_le_niveau)

        polygone = _polygone_depuis_masque(masque_connecte, lons_uniques, lats_uniques, pas_metres)
        PalierInondationSimule.objects.update_or_create(
            commune_code=commune_code, niveau_metres=niveau, environment=environment,
            defaults={"polygone": polygone},
        )
        resultats[niveau] = polygone

    return resultats


def _altitude_plus_proche(lon: float, lat: float, points: list):
    """Altitude du point de grille le plus proche (lon, lat) -- grille assez dense (pas de 50m
    par défaut) pour que le plus proche voisin suffise, pas besoin d'interpolation bilinéaire
    pour un outil "grossier"."""
    meilleure_distance, meilleure_altitude = None, None
    for p in points:
        d = (p["lon"] - lon) ** 2 + (p["lat"] - lat) ** 2
        if meilleure_distance is None or d < meilleure_distance:
            meilleure_distance, meilleure_altitude = d, p["altitude"]
    return meilleure_altitude


# Circuit-breaker si la commune est "trop grande" (voir docstring de seuils_inondation_adresses)
# -- pas une limite mesurée finement, un plafond pragmatique : Bordeaux (2509 rues) est le cas
# réel qui a fait tomber le chargement (constaté le 2026-09-29, voir tasks.py). Choisi pour
# rejeter clairement et vite une très grande ville plutôt que de tourner longtemps pour finir
# par échouer quand même -- à ajuster si l'expérience montre qu'il coupe trop tôt ou trop tard.
SEUIL_VOIES_MAX = 1500


def _nombre_voies_commune(commune_code: str) -> int | None:
    """Nombre de rues BAN de la commune -- UN SEUL appel léger (même endpoint que
    scanner_ban_commune, mais sans jamais aller chercher le détail des adresses), pour décider
    d'abandonner AVANT de lancer le scan complet plutôt qu'après (voir SEUIL_VOIES_MAX). None si
    l'appel échoue -- dans ce cas on laisse scanner_ban_commune retenter et échouer normalement,
    plutôt que de bloquer sur un simple échec réseau transitoire de CETTE vérification."""
    data = _fetch_json(f"https://plateforme.adresse.data.gouv.fr/lookup/{urllib.parse.quote(commune_code)}")
    if not data:
        return None
    return len(data.get("voies", []))


def seuils_inondation_adresses(
    commune_code: str, niveaux: list | None = None, pas_metres: int = PAS_METRES_PAR_DEFAUT,
    forcer: bool = False, environment=None,
):
    """Scanne la BAN pour TOUTE la commune (scanner_ban_commune, réutilisé tel quel -- jamais de
    zone_module ici, cet outil est utilisable hors contexte de crise) puis calcule, pour chaque
    adresse, le plus petit niveau simulé qui l'atteint (None = jamais atteinte dans la plage
    testée). Mis en cache (AdresseSimuleeInondation).

    Volontairement plafonné (SEUIL_VOIES_MAX) : une très grande ville (des milliers de rues,
    ex: Bordeaux, 2509) peut représenter des dizaines/centaines de milliers d'adresses -- testé
    en conditions réelles le 2026-09-30, le vrai coût dominant s'est révélé être l'union des
    polygones de la grille (corrigé, voir _polygone_depuis_masque), pas le scan BAN lui-même,
    mais le nombre d'adresses reste un facteur multiplicatif direct de la boucle de test
    géométrique ci-dessous -- un plafond explicite (échec clair et rapide) est plus honnête
    qu'une tentative qui tournerait longtemps pour finir par échouer quand même sur une commune
    réellement démesurée. L'API BAN ne permet pas de filtrer par code postal AVANT de scanner
    (vérifié le 2026-09-30 : /lookup/<code postal> renvoie 404, seul le code commune INSEE
    fonctionne) -- un filtrage par code postal reste possible côté affichage une fois les
    adresses chargées, pas en amont du chargement lui-même."""
    from django.contrib.gis.geos import Point

    from .habitations import scanner_ban_commune
    from .models import AdresseSimuleeInondation, Environment

    environment = environment or Environment.PROD
    niveaux = sorted(niveaux or NIVEAUX_PAR_DEFAUT)

    if not forcer:
        existantes = list(AdresseSimuleeInondation.objects.filter(commune_code=commune_code, environment=environment))
        if existantes:
            return existantes

    nb_voies = _nombre_voies_commune(commune_code)
    if nb_voies is not None and nb_voies > SEUIL_VOIES_MAX:
        raise RuntimeError(
            f"Commune trop grande pour charger les adresses ({nb_voies} rues, plafond {SEUIL_VOIES_MAX}) -- "
            "la simulation du niveau d'eau reste disponible, seul le chargement des adresses est refusé."
        )

    # Supprimé AVANT le (long) recalcul, jamais après : sinon adresses_en_cache() peut lire des
    # paliers déjà à jour (nouvelle plage de niveaux) mais des adresses encore de l'ancien calcul
    # -- fenêtre de plusieurs dizaines de secondes constatée en direct le 2026-09-29 juste après
    # un élargissement de NIVEAUX_PAR_DEFAUT (un poll a lu des seuil_inondation obsolètes,
    # calculés sur l'ancienne plage 0-3m, alors que les paliers 0-12m étaient déjà tous en base).
    AdresseSimuleeInondation.objects.filter(commune_code=commune_code, environment=environment).delete()

    paliers = calculer_paliers_inondation(
        commune_code, niveaux=niveaux, pas_metres=pas_metres, forcer=forcer, environment=environment,
    )
    # Géométries "préparées" (index spatial interne GEOS) construites UNE fois, réutilisées pour
    # chaque adresse -- un .contains() répété sur un polygone brut ré-analyse sa géométrie à
    # chaque appel, coûteux dès que le polygone est complexe (beaucoup de cellules unionnées) et
    # qu'il y a beaucoup d'adresses à tester (grande ville).
    paliers_prepares = {niveau: (polygone.prepared if polygone else None) for niveau, polygone in paliers.items()}
    points_grille = grille_altitude_commune(commune_code, pas_metres=pas_metres, environment=environment)

    resultat_ban = scanner_ban_commune(commune_code)
    if resultat_ban["erreur"]:
        # Ne JAMAIS renvoyer silencieusement une liste vide ici : adresses_en_cache() la
        # confondrait avec "pas encore calculé" (boucle infinie côté tâche Celery, jamais
        # marquée ECHEC) -- une exception fait remonter un vrai échec explicite (voir
        # tasks.charger_adresses_task).
        raise RuntimeError(f"Échec du scan BAN pour {commune_code} : {resultat_ban['erreur']}")

    lignes = []
    for adresse in resultat_ban["adresses"]:
        lon, lat = adresse["lon"], adresse["lat"]
        altitude = _altitude_plus_proche(lon, lat, points_grille)
        point = Point(lon, lat, srid=4326)

        seuil = None
        for niveau in niveaux:
            prepare = paliers_prepares.get(niveau)
            if prepare is not None and prepare.contains(point):
                seuil = niveau
                break

        lignes.append(AdresseSimuleeInondation(
            commune_code=commune_code, ban_id=adresse.get("ban_id"), adresse=adresse["adresse"],
            location=point, altitude_metres=altitude, seuil_inondation_metres=seuil,
            environment=environment,
        ))

    AdresseSimuleeInondation.objects.bulk_create(lignes)
    return lignes


def paliers_en_cache(commune_code: str, niveaux: list | None = None, environment=None) -> dict | None:
    """Lit les paliers DÉJÀ calculés, sans déclencher aucun calcul ni appel externe -- None si
    pas encore (entièrement) en cache. Volontairement SÉPARÉ des adresses (voir
    adresses_en_cache) : la simulation du niveau d'eau doit rester utilisable même sur une
    commune où le chargement des adresses échouerait ou serait trop long (demande explicite du
    2026-09-30, suite à l'échec du chargement complet sur Bordeaux)."""
    from .models import Environment, PalierInondationSimule

    environment = environment or Environment.PROD
    niveaux = niveaux or NIVEAUX_PAR_DEFAUT

    paliers_existants = list(
        PalierInondationSimule.objects.filter(commune_code=commune_code, environment=environment, niveau_metres__in=niveaux)
    )
    if len(paliers_existants) != len(niveaux):
        return None

    return {
        "commune_code": commune_code,
        "niveaux": niveaux,
        "paliers": [
            {"niveau": p.niveau_metres, "polygone_geojson": json.loads(p.polygone.geojson) if p.polygone else None}
            for p in paliers_existants
        ],
    }


def adresses_en_cache(commune_code: str, environment=None) -> dict | None:
    """Lit les adresses DÉJÀ chargées, sans déclencher aucun calcul ni appel externe -- None si
    pas encore chargées. Voir paliers_en_cache pour pourquoi c'est séparé."""
    from .models import AdresseSimuleeInondation, Environment

    environment = environment or Environment.PROD
    adresses = AdresseSimuleeInondation.objects.filter(commune_code=commune_code, environment=environment)
    if not adresses.exists():
        return None

    return {
        "commune_code": commune_code,
        "adresses": [
            {
                "adresse": a.adresse, "lon": a.location.x, "lat": a.location.y,
                "altitude": a.altitude_metres, "seuil_inondation": a.seuil_inondation_metres,
            }
            for a in adresses
        ],
    }
