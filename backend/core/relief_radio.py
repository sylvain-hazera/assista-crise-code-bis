"""Propagation radio sur le relief : bilan de liaison, couverture d'un site, calibration.

Porté de `carte-live/src/relief.js` de `sauveteur71/carte-live-meshtastic` (GPL-3.0, repris avec
l'autorisation de l'auteur). Le code est réécrit en Python sur l'infrastructure d'Assista-Crise,
mais le MODÈLE est le sien, et c'est lui qui a de la valeur.

**Ce qui n'est pas porté, et pourquoi.** Son module télécharge le modèle numérique de terrain IGN
RGE ALTI par dalles et le garde sur disque, ce qui lui permet un balayage de 1080 rayons au pas de
250 m sur tout un département. Assista-Crise, lui, a déjà un client altimétrique IGN (l'API REST
`data.geopf.fr`, voir `core/inondation.py`), avec sa limite de débit, son cache par commune et sa
reprise sur 429 — construit pour la simulation d'inondation. On le réutilise plutôt que de
rapatrier des gigaoctets de dalles : conséquence directe, la couverture se calcule **par site**
(quelques milliers de points, quelques secondes) et non en raster départemental. C'est ce dont une
commune a besoin — « jusqu'où porte mon relais ? » — et ça évite d'introduire une dépendance de
données d'un tout autre ordre. Le plan de couverture départemental (son `planDepartement`,
`planBudget`, `simuler`) reste donc chez lui.

**Le modèle, point par point** (constantes et formules reprises telles quelles) :

- Terre équivalente `k = 4/3` : la réfraction atmosphérique courbe le faisceau vers le sol, ce qui
  revient à aplatir la Terre d'un tiers. Sans cette correction, toute liaison de plus de ~15 km
  est déclarée bloquée à tort.
- Affaiblissement en espace libre : `20·log10(d_km) + 20·log10(f_MHz) + 32,44`.
- Plancher de bruit : `-174 + 10·log10(BW_Hz) + 6` — les 6 dB sont le facteur de bruit du
  récepteur.
- Seuil de démodulation par facteur d'étalement (`SNR_LIMITE`), d'où la sensibilité
  `plancher + seuil_SF`.
- Diffraction par lame de couteau (UIT-R P.526) sur l'obstacle le plus pénalisant du profil,
  choisi par le paramètre de Fresnel `v` **et non par la hauteur** : `v = h·√(2D / (λ·d₁·d₂))`
  dépend autant de la position de l'obstacle que de sa hauteur, puisque le rayon de Fresnel
  s'élargit au milieu du trajet et se resserre près des extrémités. Trier par hauteur — ou par
  angle de site, comme le mode rapide de son module — désigne donc parfois le mauvais obstacle,
  avec cette conséquence absurde : monter l'antenne pouvait faire *diminuer* la couverture
  calculée.
- Une liaison en rasance coûte déjà ~6 dB, même au-dessus d'un terrain parfaitement plat : à
  `v = 0` la perte de diffraction vaut 6 dB, pas zéro. Ce n'est pas une approximation du modèle,
  c'est le résultat exact de la recommandation, et c'est pour cette raison qu'un dégagement au
  ras du sol ne « passe » jamais aussi bien qu'un dégagement franc.

**La vraie idée de son module**, celle qui le rend crédible : la calibration. Un bilan de liaison
théorique se trompe de 10 à 20 dB en milieu réel (végétation, bâti, désadaptation d'antenne). Il
compare donc le modèle aux liaisons RÉELLEMENT mesurées et en tire une perte d'environnement
unique. Assista-Crise mesure justement ses liaisons depuis le 06/11/2026
(`LiaisonMeshtastic`) : `calibrer()` s'appuie dessus. Sans calibration, la couverture affichée est
une indication de relief, pas une prévision.
"""
import datetime
import math

from django.utils import timezone

# --- Constantes physiques (reprises de relief.js) ---------------------------------------------
RAYON_TERRE_M = 6371000.0
# Facteur de terre équivalente : réfraction atmosphérique standard.
K_REFRACTION = 4 / 3
# Fréquence du réseau français (869,525 MHz, bande 869,4-869,65 MHz).
FREQUENCE_HZ = 869.525e6
LAMBDA_M = 299792458 / FREQUENCE_HZ
METRES_PAR_DEGRE = 111320.0

# Facteur d'étalement et largeur de bande (kHz) par preset Meshtastic, plus le réglage MeshCore
# du réseau français.
PRESETS_LORA = {
    "LONG_FAST": {"sf": 11, "bw": 250.0},
    "LONG_SLOW": {"sf": 12, "bw": 125.0},
    "VERY_LONG_SLOW": {"sf": 12, "bw": 62.5},
    "MEDIUM_SLOW": {"sf": 10, "bw": 250.0},
    "MEDIUM_FAST": {"sf": 9, "bw": 250.0},
    "SHORT_SLOW": {"sf": 8, "bw": 250.0},
    "SHORT_FAST": {"sf": 7, "bw": 250.0},
    "LONG_MODERATE": {"sf": 11, "bw": 125.0},
    "SHORT_TURBO": {"sf": 7, "bw": 500.0},
    "LONG_TURBO": {"sf": 11, "bw": 500.0},
    "MESHCORE_FR": {"sf": 8, "bw": 62.5},
}
PRESET_PAR_DEFAUT = "LONG_FAST"

# SNR minimal démodulable par facteur d'étalement, en dB.
SNR_LIMITE_PAR_SF = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}

# Facteur de bruit du récepteur, en dB.
FACTEUR_BRUIT_DB = 6.0

# Valeurs par défaut d'une installation, en l'absence de fiche de nœud.
HAUTEUR_SITE_M = 6.0
HAUTEUR_MOBILE_M = 2.0
PUISSANCE_DBM = 27.0
GAIN_ANTENNE_DBI = 2.15
PERTES_CABLE_DB = 0.75
MARGE_SECURITE_DB = 6.0
# Perte d'environnement retenue tant qu'aucune calibration n'est disponible (végétation, bâti).
PERTE_ENVIRONNEMENT_DEFAUT_DB = 12.0
RAYON_MAX_M = 40000.0

# Pas d'échantillonnage du profil d'une liaison, en mètres (le sien).
PAS_PROFIL_M = 100.0
# Au moins dix points, même sur une liaison courte : avec moins, un obstacle passe entre deux
# échantillons.
POINTS_PROFIL_MIN = 10

# --- Calibration -------------------------------------------------------------------------------
# Liaisons retenues pour calibrer. Sous 1 km le modèle n'apprend rien (tout passe) ; au-delà de
# 80 km c'est un report MQTT ou une erreur de position, pas une liaison radio.
CALIBRATION_DISTANCE_MIN_M = 1000.0
CALIBRATION_DISTANCE_MAX_M = 80000.0
# Un module LoRa plafonne son SNR autour de +10 dB : au-delà, « prédit » et « mesuré » ne sont
# plus comparables, et une liaison confortable des deux côtés n'apporte aucune information.
SNR_PLAFOND_MESURABLE_DB = 10.0
CALIBRATION_LIAISONS_MIN = 5
# Bornes de la perte d'environnement déduite : en dessous le modèle serait optimiste à coup sûr,
# au-dessus c'est qu'autre chose cloche (mauvaise position, antenne débranchée) et une correction
# aussi grosse masquerait le vrai problème.
CALIBRATION_BORNE_MIN_DB = 4
CALIBRATION_BORNE_MAX_DB = 30


def plancher_bruit_db(bande_khz):
    """Bruit thermique dans la largeur de bande, facteur de bruit du récepteur inclus."""
    return -174 + 10 * math.log10(bande_khz * 1000) + FACTEUR_BRUIT_DB


def seuil_sensibilite_db(preset=PRESET_PAR_DEFAUT):
    """Puissance reçue minimale exploitable, en dBm."""
    parametres = PRESETS_LORA.get(preset) or PRESETS_LORA[PRESET_PAR_DEFAUT]
    return plancher_bruit_db(parametres["bw"]) + SNR_LIMITE_PAR_SF[parametres["sf"]]


def fspl_db(distance_m):
    """Affaiblissement en espace libre. Jamais appelé sous 1 m (log de zéro)."""
    distance_km = max(distance_m, 1.0) / 1000
    return 20 * math.log10(distance_km) + 20 * math.log10(FREQUENCE_HZ / 1e6) + 32.44


def diffraction_db(v):
    """Perte de diffraction par lame de couteau, UIT-R P.526, en fonction du paramètre de
    Fresnel `v`.

    Sous `v = -0,78` la formule n'a plus de sens physique (l'obstacle est bien sous la ligne de
    visée) et la perte est nulle : c'est la borne de la recommandation, pas un choix."""
    if v <= -0.78:
        return 0.0
    return 6.9 + 20 * math.log10(math.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)


def distance_m(a, b):
    """Distance orthodromique entre deux (lat, lon)."""
    r = math.pi / 180
    s = (math.sin(((b[0] - a[0]) * r) / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(((b[1] - a[1]) * r) / 2) ** 2)
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(min(1.0, s)))


class ParametresRadio:
    """Jeu de paramètres d'un calcul : installation, preset, marges.

    `perte_environnement_db` est le terme que la calibration ajuste. Tout le reste décrit du
    matériel."""

    __slots__ = ("preset", "hauteur_site_m", "hauteur_cible_m", "puissance_dbm", "gains_dbi",
                 "pertes_db", "marge_securite_db", "perte_environnement_db", "rayon_max_m",
                 "seuil_dbm", "calibre")

    def __init__(self, preset=PRESET_PAR_DEFAUT, hauteur_site_m=HAUTEUR_SITE_M,
                 hauteur_cible_m=HAUTEUR_MOBILE_M, puissance_dbm=PUISSANCE_DBM,
                 gains_dbi=None, pertes_db=None, marge_securite_db=MARGE_SECURITE_DB,
                 perte_environnement_db=None, rayon_max_m=RAYON_MAX_M, calibre=False):
        self.preset = preset if preset in PRESETS_LORA else PRESET_PAR_DEFAUT
        self.hauteur_site_m = hauteur_site_m
        self.hauteur_cible_m = hauteur_cible_m
        self.puissance_dbm = puissance_dbm
        self.gains_dbi = 2 * GAIN_ANTENNE_DBI if gains_dbi is None else gains_dbi
        self.pertes_db = 2 * PERTES_CABLE_DB if pertes_db is None else pertes_db
        self.marge_securite_db = marge_securite_db
        self.perte_environnement_db = (
            PERTE_ENVIRONNEMENT_DEFAUT_DB if perte_environnement_db is None
            else perte_environnement_db
        )
        self.rayon_max_m = rayon_max_m
        self.seuil_dbm = seuil_sensibilite_db(self.preset)
        # Vrai quand `perte_environnement_db` vient d'une mesure et non d'une valeur par défaut :
        # une couverture non calibrée est une indication de relief, pas une prévision, et
        # l'interface doit pouvoir le dire.
        self.calibre = calibre

    @property
    def budget_db(self):
        """Puissance disponible au-delà de la sensibilité, avant pertes de trajet."""
        return (self.puissance_dbm + self.gains_dbi - self.pertes_db - self.seuil_dbm
                - self.marge_securite_db - self.perte_environnement_db)

    def resume(self):
        return {
            "preset": self.preset,
            "hauteur_site_m": self.hauteur_site_m,
            "hauteur_cible_m": self.hauteur_cible_m,
            "puissance_dbm": self.puissance_dbm,
            "gains_dbi": round(self.gains_dbi, 2),
            "pertes_db": round(self.pertes_db, 2),
            "marge_securite_db": self.marge_securite_db,
            "perte_environnement_db": self.perte_environnement_db,
            "calibre": self.calibre,
            "seuil_dbm": round(self.seuil_dbm, 1),
            "rayon_max_km": round(self.rayon_max_m / 1000, 1),
        }


def parametres_calibres(environment, **surcharges):
    """`ParametresRadio` avec la perte d'environnement issue de la dernière calibration de cette
    zone, si elle existe. Sinon la valeur par défaut, et `calibre=False`."""
    from .models import CalibrationRadio

    if "perte_environnement_db" not in surcharges:
        calibration = (CalibrationRadio.objects
                       .filter(environment=environment, perte_environnement_db__isnull=False)
                       .order_by('-date_calcul').first())
        if calibration is not None:
            surcharges["perte_environnement_db"] = float(calibration.perte_environnement_db)
            surcharges["calibre"] = True
    return ParametresRadio(**surcharges)


def ajuster_pour_noeuds(params, *noeuds):
    """Corrige les paramètres par les fiches des nœuds d'une liaison (son `Pinstallation`).

    Un nœud absent ou sans fiche ne change rien. Pour la puissance on garde **le sens le plus
    défavorable** (le minimum) : une liaison ne vaut que ce que vaut son maillon faible, et
    annoncer la portée du plus puissant des deux ferait croire à une liaison qui ne passe que
    dans un sens — exactement ce que `core/analyse_liaisons.py` cherche à détecter."""
    gains = params.gains_dbi
    pertes = params.pertes_db
    puissance = params.puissance_dbm
    hauteur = params.hauteur_site_m
    for i, noeud in enumerate(noeuds):
        if not noeud:
            continue
        if noeud.get("gain_dbi") is not None:
            gains += noeud["gain_dbi"] - GAIN_ANTENNE_DBI
        if noeud.get("pertes_db") is not None:
            pertes += noeud["pertes_db"] - PERTES_CABLE_DB
        if noeud.get("puissance_dbm") is not None:
            puissance = min(puissance, noeud["puissance_dbm"])
        if i == 0 and noeud.get("hauteur_m") is not None:
            hauteur = noeud["hauteur_m"]
    return ParametresRadio(
        preset=params.preset, hauteur_site_m=hauteur, hauteur_cible_m=params.hauteur_cible_m,
        puissance_dbm=puissance, gains_dbi=gains, pertes_db=pertes,
        marge_securite_db=params.marge_securite_db,
        perte_environnement_db=params.perte_environnement_db, rayon_max_m=params.rayon_max_m,
        calibre=params.calibre,
    )


def points_profil(a, b, pas_m=PAS_PROFIL_M):
    """Points intermédiaires (lat, lon) du profil direct entre `a` et `b`, extrémités exclues."""
    distance = distance_m(a, b)
    nombre = max(POINTS_PROFIL_MIN, math.ceil(distance / pas_m))
    return [
        (a[0] + (b[0] - a[0]) * (k / nombre), a[1] + (b[1] - a[1]) * (k / nombre))
        for k in range(1, nombre)
    ]


def analyser_liaison(a, b, altitude_a, altitude_b, profil, params,
                     hauteur_a=None, hauteur_b=None):
    """Bilan d'une liaison point à point sur son profil de terrain.

    `profil` est la liste des altitudes des points intermédiaires, dans l'ordre, telle que
    `points_profil` les a demandés — un trou (None) est ignoré plutôt que de faire échouer le
    calcul : mieux vaut un bilan calculé sur 98 % du profil qu'aucun bilan.

    L'obstacle retenu est celui de plus grand paramètre de Fresnel, **pas** le plus haut : à
    hauteur égale au-dessus de la ligne de visée, un obstacle proche d'une extrémité pénalise
    plus (le rayon de Fresnel y est étroit, l'obstacle traverse donc plus de zones). Trier par
    hauteur désignerait le mauvais obstacle.

    Renvoie `marge_db` : positive, la liaison passe avec la marge annoncée ; négative, il manque
    ce nombre de dB."""
    distance = distance_m(a, b)
    hauteur_a = params.hauteur_site_m if hauteur_a is None else hauteur_a
    hauteur_b = params.hauteur_cible_m if hauteur_b is None else hauteur_b

    if altitude_a is None or altitude_b is None:
        return None
    if distance < 50:
        # Deux nœuds à moins de 50 m : le bilan n'a pas de sens (champ proche), et la liaison
        # passe de toute façon.
        return {"marge_db": 99.0, "distance_m": round(distance), "diffraction_db": 0.0,
                "obstacle": None, "parametres": params.resume()}

    hauteur_depart = altitude_a + hauteur_a
    hauteur_arrivee = altitude_b + hauteur_b
    nombre = len(profil) + 1

    pire = {"v": -math.inf, "distance_m": 0.0, "hauteur_m": 0.0}
    for k, altitude in enumerate(profil, start=1):
        if altitude is None:
            continue
        fraction = k / nombre
        d = distance * fraction
        if d <= 0 or d >= distance:
            continue
        # Terre équivalente : l'altitude vue par le faisceau baisse avec la distance aux deux
        # extrémités.
        altitude_equivalente = altitude - (d * (distance - d)) / (2 * K_REFRACTION * RAYON_TERRE_M)
        visee = hauteur_depart + (hauteur_arrivee - hauteur_depart) * fraction
        hauteur_obstacle = altitude_equivalente - visee
        v = hauteur_obstacle * math.sqrt((2 * distance) / (LAMBDA_M * d * (distance - d)))
        if v > pire["v"]:
            pire = {"v": v, "distance_m": d, "hauteur_m": hauteur_obstacle}

    perte_diffraction = diffraction_db(pire["v"]) if pire["v"] > -math.inf else 0.0
    marge = params.budget_db - fspl_db(distance) - perte_diffraction
    return {
        "marge_db": round(marge, 1),
        "distance_m": round(distance),
        "diffraction_db": round(perte_diffraction, 1),
        "obstacle": (
            {"distance_km": round(pire["distance_m"] / 1000, 1),
             "hauteur_m": round(pire["hauteur_m"])}
            if pire["hauteur_m"] > 0 else None
        ),
        "parametres": params.resume(),
    }


def points_balayage(site, params, nb_rayons, pas_m):
    """Points (lat, lon) d'un balayage radial depuis `site`, rayon par rayon.

    Renvoyés à plat pour pouvoir demander toutes les altitudes en une fois : l'API IGN travaille
    par lots de 200 points, un aller-retour par point serait inexploitable."""
    cos_lat = math.cos(math.radians(site[0]))
    if abs(cos_lat) < 1e-9:          # pôle : aucun sens, et division par zéro juste après
        return []
    nb_pas = max(1, int(params.rayon_max_m // pas_m))
    points = []
    for r in range(nb_rayons):
        azimut = 2 * math.pi * r / nb_rayons
        d_lat = math.cos(azimut) / METRES_PAR_DEGRE
        d_lon = math.sin(azimut) / (METRES_PAR_DEGRE * cos_lat)
        for k in range(1, nb_pas + 1):
            d = k * pas_m
            points.append((site[0] + d * d_lat, site[1] + d * d_lon))
    return points


def balayer(site, altitude_site, params, nb_rayons, pas_m, altitudes):
    """Couverture par balayage radial — son `balayer`, avec la diffraction sur l'obstacle le plus
    pénalisant du rayon (son mode « précis »).

    Pourquoi le mode précis plutôt que le plus rapide : avec l'obstacle le plus HAUT en angle,
    monter l'antenne pouvait faire *diminuer* la couverture affichée, ce qui est absurde et
    décrédibilise tout le calcul. En retenant le plus grand paramètre de Fresnel, la couverture ne
    peut que croître quand on monte l'antenne.

    `altitudes` est la liste plate des altitudes des points de `points_balayage`, dans le même
    ordre. Renvoie la liste des points atteints : (lat, lon, marge_db, distance_m)."""
    if altitude_site is None:
        return []
    hauteur_site = altitude_site + params.hauteur_site_m
    nb_pas = max(1, int(params.rayon_max_m // pas_m))
    budget = params.budget_db
    atteints = []
    points = points_balayage(site, params, nb_rayons, pas_m)

    for r in range(nb_rayons):
        # Angles de site du terrain déjà parcouru sur CE rayon, pour le calcul de Fresnel.
        thetas = []
        for k in range(1, nb_pas + 1):
            indice = r * nb_pas + (k - 1)
            if indice >= len(points) or indice >= len(altitudes):
                break
            altitude = altitudes[indice]
            if altitude is None:
                # Trou de données : on arrête le rayon là. Continuer reviendrait à déclarer
                # couvert ce qu'on n'a pas pu calculer.
                break
            d = k * pas_m
            altitude_equivalente = altitude - (d * d) / (2 * K_REFRACTION * RAYON_TERRE_M)
            theta_cible = (altitude_equivalente + params.hauteur_cible_m - hauteur_site) / d
            perte = 0.0
            if thetas:
                v_max = -math.inf
                for o, theta_sol in enumerate(thetas):
                    d_obstacle = (o + 1) * pas_m
                    if d_obstacle >= d:
                        break
                    v = (theta_sol - theta_cible) * math.sqrt(
                        (2 * d * d_obstacle) / (LAMBDA_M * (d - d_obstacle))
                    )
                    if v > v_max:
                        v_max = v
                if v_max > -math.inf:
                    perte = diffraction_db(v_max)
            marge = budget - fspl_db(d) - perte
            if marge >= 0:
                lat, lon = points[indice]
                atteints.append((lat, lon, round(marge, 1), d))
            thetas.append((altitude_equivalente - hauteur_site) / d)
    return atteints


def calibrer(environment, maintenant=None):
    """Compare le modèle aux liaisons réellement mesurées et en déduit la perte d'environnement.

    C'est l'idée qui rend tout le reste crédible : un bilan théorique se trompe de 10 à 20 dB en
    milieu réel. On prend la MÉDIANE de l'écart (modèle − mesure) sur les liaisons exploitables,
    pas la moyenne : une seule liaison aberrante (position fausse, antenne débranchée) tirerait la
    moyenne et fausserait toutes les couvertures.

    Trois précautions, toutes reprises de son implémentation :

    1. **Fenêtre de distance** (1 à 80 km) : sous 1 km tout passe et le modèle n'apprend rien ;
       au-delà de 80 km ce n'est plus une liaison radio directe.
    2. **Plafond de mesurabilité** : un module LoRa plafonne son SNR vers +10 dB. Une liaison
       confortable des deux côtés (prédit ≥ 9 et mesuré ≥ 8) est donc écartée — elle ne porte
       aucune information sur l'écart réel.
    3. **Bornes sur le résultat** et minimum de liaisons : en dessous de cinq liaisons on ne
       conclut pas, et une correction hors de [4, 30] dB signale autre chose qu'un environnement.

    Renvoie un dictionnaire, et l'enregistre dans `CalibrationRadio`."""
    from .models import CalibrationRadio, ContactMeshtastic, LiaisonMeshtastic

    maintenant = maintenant or timezone.now()
    # Paramètres NUS : on cherche l'écart que l'environnement explique, donc sans perte
    # d'environnement ni marge de sécurité, sinon on mesurerait nos propres hypothèses.
    params = ParametresRadio(perte_environnement_db=0.0, marge_securite_db=0.0)
    bruit = params.seuil_dbm - SNR_LIMITE_PAR_SF[PRESETS_LORA[params.preset]["sf"]]

    positions = {}
    for contact in ContactMeshtastic.objects.filter(
        environment=environment, location__isnull=False,
    ).only('node_num', 'location'):
        positions.setdefault(contact.node_num, (contact.location.y, contact.location.x))

    ecarts = []
    for liaison in LiaisonMeshtastic.objects.filter(
        environment=environment, snr__isnull=False,
    ).order_by('-dernier_vu')[:2000]:
        a = positions.get(liaison.emetteur)
        b = positions.get(liaison.recepteur)
        if not a or not b:
            continue
        distance = distance_m(a, b)
        if distance < CALIBRATION_DISTANCE_MIN_M or distance > CALIBRATION_DISTANCE_MAX_M:
            continue
        altitudes_profil = altitudes_points(points_profil(a, b))
        resultat = analyser_liaison(
            a, b, altitude_point(a), altitude_point(b), altitudes_profil, params,
            hauteur_a=3, hauteur_b=3,
        )
        if resultat is None:
            continue
        snr_predit = (params.puissance_dbm + params.gains_dbi - params.pertes_db
                      - fspl_db(distance) - resultat["diffraction_db"] - bruit)
        comparable = min(snr_predit, SNR_PLAFOND_MESURABLE_DB)
        if comparable >= 9 and liaison.snr >= 8:
            continue
        ecarts.append({
            "ecart_db": round(comparable - liaison.snr, 1),
            "emetteur": liaison.emetteur, "recepteur": liaison.recepteur,
            "distance_km": round(distance / 1000, 1),
            "snr_mesure": liaison.snr, "snr_predit": round(snr_predit, 1),
        })

    ecarts.sort(key=lambda e: e["ecart_db"])
    mediane = ecarts[len(ecarts) // 2]["ecart_db"] if ecarts else None
    perte = None
    if len(ecarts) >= CALIBRATION_LIAISONS_MIN and mediane is not None:
        perte = int(round(min(CALIBRATION_BORNE_MAX_DB, max(CALIBRATION_BORNE_MIN_DB, mediane))))

    calibration = CalibrationRadio.objects.create(
        environment=environment, preset=params.preset, liaisons_retenues=len(ecarts),
        ecart_median_db=mediane, perte_environnement_db=perte,
        exemples=ecarts[:40], date_calcul=maintenant,
    )
    return {
        "id": str(calibration.id),
        "liaisons_retenues": len(ecarts),
        "ecart_median_db": mediane,
        "perte_environnement_db": perte,
        "exemples": ecarts[:40],
        "date_calcul": maintenant.isoformat(),
    }


# --- Accès aux altitudes -----------------------------------------------------------------------
# Arrondi de la clé de cache, en degrés : 1e-4° vaut ~11 m en latitude. Assez fin pour ne rien
# perdre d'un profil au pas de 100 m, assez grossier pour que deux calculs sur le même site
# retombent sur les mêmes points — c'est ce qui rend un recalcul quasi gratuit.
ARRONDI_CACHE = 4


def _cle(point):
    """Clé de cache d'un point : « lat,lon » arrondis. Une chaîne et non un couple de décimaux,
    pour pouvoir relire quelques milliers de points par un seul `cle__in` indexé (voir
    PointAltitude)."""
    return f"{round(point[0], ARRONDI_CACHE):.4f},{round(point[1], ARRONDI_CACHE):.4f}"


def altitudes_points(points, utiliser_cache=True):
    """Altitudes d'une liste de (lat, lon), dans le même ordre, `None` pour un point non résolu.

    Lit d'abord le cache (`PointAltitude`), ne demande à l'IGN que ce qui manque, et enregistre
    ce qui revient. Le relief ne change pas : un point lu une fois n'a pas à être redemandé, et
    le service d'altimétrie est limité en débit (2,5 requêtes/s, voir core/inondation.py)."""
    from .inondation import _altitudes_ign_par_lots
    from .models import PointAltitude

    if not points:
        return []
    cles = [_cle(p) for p in points]
    connues = {}
    if utiliser_cache:
        # Par paquets : une requête avec 40 000 valeurs dans un IN dépasse ce que PostgreSQL
        # accepte confortablement en paramètres.
        distinctes = list(dict.fromkeys(cles))
        for debut in range(0, len(distinctes), 2000):
            connues.update(PointAltitude.objects.filter(
                cle__in=distinctes[debut:debut + 2000],
            ).values_list('cle', 'altitude_m'))

    manquantes = []
    vues = set()
    for cle in cles:
        if cle in connues or cle in vues:
            continue
        vues.add(cle)
        manquantes.append(cle)

    if manquantes:
        coordonnees = [tuple(float(v) for v in cle.split(',')) for cle in manquantes]
        obtenues = _altitudes_ign_par_lots([c[1] for c in coordonnees], [c[0] for c in coordonnees])
        nouvelles = []
        for cle, altitude in zip(manquantes, obtenues):
            if altitude is None:
                continue
            connues[cle] = altitude
            nouvelles.append(PointAltitude(cle=cle, altitude_m=altitude))
        if nouvelles and utiliser_cache:
            # ignore_conflicts : deux calculs simultanés peuvent demander le même point.
            PointAltitude.objects.bulk_create(nouvelles, ignore_conflicts=True, batch_size=500)

    return [connues.get(cle) for cle in cles]


def altitude_point(point):
    """Altitude d'un seul point, ou None."""
    return altitudes_points([point])[0]


# --- Calcul d'une couverture -------------------------------------------------------------------
# Un balayage radial coûte `nb_rayons x (rayon / pas)` interrogations d'altitude. Les valeurs par
# défaut (72 rayons, pas de 500 m, 40 km) font 5 760 points, soit ~29 lots IGN et une dizaine de
# secondes la première fois, puis presque rien grâce au cache de points. Lui en utilise 1080 au
# pas de 250 m, ce qu'un modèle de terrain local permet et pas une API à 2,5 requêtes/s.
COUVERTURE_RAYONS_DEFAUT = 72
COUVERTURE_PAS_M_DEFAUT = 500
# Au-delà, le calcul dépasse le budget de temps de la tâche Celery sans rien apporter de plus.
COUVERTURE_POINTS_MAX = 40000
# Part de points sans altitude au-delà de laquelle le résultat n'est pas fiable : l'IGN n'a pas
# répondu pour une bonne partie du balayage, la couverture est donc sous-estimée.
COUVERTURE_TROUS_MAX = 0.10


class CouvertureIncomplete(Exception):
    """Trop de points sans altitude : la couverture serait sous-estimée sans qu'on le voie."""


def calculer_couverture(couverture):
    """Calcule et enregistre la couverture d'un site (`CouvertureRadioSite`).

    Appelée depuis une tâche Celery, jamais dans une requête HTTP : la première passe sur un site
    neuf prend de l'ordre d'une minute (limite de débit de l'API d'altimétrie).

    La surface est estimée par la part de rayons atteints, et non en comptant des cellules : un
    balayage radial échantillonne beaucoup plus densément près du site que loin, donc compter les
    points surestimerait massivement le centre. On prend la portée atteinte par rayon et on somme
    les secteurs angulaires correspondants -- une approximation, annoncée comme telle."""
    from django.utils import timezone as tz
    from .models import StatutCouvertureRadio

    site = (couverture.location.y, couverture.location.x)
    params = ParametresRadio(
        preset=couverture.preset,
        hauteur_site_m=couverture.hauteur_antenne_m,
        hauteur_cible_m=couverture.hauteur_cible_m,
        puissance_dbm=couverture.puissance_dbm,
        perte_environnement_db=couverture.perte_environnement_db,
        rayon_max_m=couverture.rayon_max_km * 1000,
        calibre=couverture.calibre,
    )
    nb_rayons = couverture.nb_rayons
    pas_m = couverture.pas_m
    nb_pas = max(1, int(params.rayon_max_m // pas_m))
    if nb_rayons * nb_pas > COUVERTURE_POINTS_MAX:
        raise CouvertureIncomplete(
            f"Balayage trop dense : {nb_rayons * nb_pas} points demandés, "
            f"{COUVERTURE_POINTS_MAX} au plus."
        )

    points = points_balayage(site, params, nb_rayons, pas_m)
    altitudes = altitudes_points(points)
    sans_altitude = sum(1 for a in altitudes if a is None)
    if points and sans_altitude / len(points) > COUVERTURE_TROUS_MAX:
        raise CouvertureIncomplete(
            f"{sans_altitude} points sur {len(points)} sans altitude : le service d'altimétrie "
            "IGN n'a pas assez répondu, la couverture serait sous-estimée."
        )

    altitude_site = altitude_point(site)
    atteints = balayer(site, altitude_site, params, nb_rayons, pas_m, altitudes)

    # Portée maximale atteinte par rayon -> somme des secteurs. Un rayon interrompu par un
    # obstacle garde la portée du dernier point atteint, ce qui est bien ce qu'on veut : la
    # couverture s'arrête à l'obstacle.
    portees = {}
    for lat, lon, marge, distance in atteints:
        azimut = math.atan2(
            (lon - site[1]) * math.cos(math.radians(site[0])), lat - site[0],
        )
        rayon = int(round((azimut % (2 * math.pi)) / (2 * math.pi) * nb_rayons)) % nb_rayons
        portees[rayon] = max(portees.get(rayon, 0.0), distance)
    secteur = (2 * math.pi) / nb_rayons
    surface_km2 = sum(0.5 * secteur * (d ** 2) for d in portees.values()) / 1e6

    couverture.points = [[round(lat, 5), round(lon, 5), marge, round(d)]
                         for lat, lon, marge, d in atteints]
    couverture.surface_estimee_km2 = round(surface_km2, 1)
    couverture.points_sans_altitude = sans_altitude
    couverture.statut = StatutCouvertureRadio.TERMINEE
    couverture.erreur = None
    couverture.date_calcul = tz.now()
    couverture.save(update_fields=[
        "points", "surface_estimee_km2", "points_sans_altitude", "statut", "erreur", "date_calcul",
    ])
    return couverture
