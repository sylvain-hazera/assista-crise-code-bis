"""Potentiel d'orage de feu (pyrocumulonimbus) : NOS ESTIMATIONS, qui ne sont pas des prévisions.

CE QUE C'EST
Un grand feu chauffe l'air au-dessus de lui ; si l'atmosphère s'y prête, le panache monte assez
haut pour condenser, puis devient un nuage d'orage : foudre qui rallume des feux en avant,
rafales descendantes qui font tourner le front. Le premier observé en France l'a été au-dessus du
feu de Saumos (Gironde), le 24/07/2026.

On ne peut pas annoncer « un orage de feu va se former ici ». On peut dire que l'atmosphère s'y
prête, et combien un feu devrait dégager pour y parvenir. Deux indicateurs, calculés pour toute
la France sur le profil vertical du modèle ARPEGE de Météo-France :

1. Le C-Haines (Mills et McCaw, 2010) : instabilité (écart de température entre 850 et 700 hPa)
   et sécheresse (écart au point de rosée à 850 hPa). Au-delà de 8 à 9, l'air favorise les feux
   violents.
2. Le seuil de puissance d'un pyrocumulonimbus (PFT, Tory et Kepert, Weather and Forecasting,
   2021), conçu par le Bureau of Meteorology australien : la puissance de feu, en GW, qu'il
   faudrait pour que le panache devienne un orage. VERSION APPROCHÉE, écrite ici sans le code
   d'origine : panache issu de la couche de mélange, sans dilution, chauffé de Δθ et humidifié
   par le feu dans le rapport de 15 K par g/kg ; Δθ est le plus petit réchauffement qui porte le
   panache, une fois condensé, plus haut que le niveau à -20 °C (assez froid pour la foudre) sans
   jamais redevenir plus lourd que l'air ambiant ; z est la hauteur de condensation, U le vent
   moyen en dessous. PFT ≈ 0,3 · z(km)² · U(m/s) · Δθ(K).

Le PFT seul ne suffit pas : il est au plus bas les jours humides, où les orages se forment de
toute façon. Le potentiel n'est donc peint que là où l'air est sec et instable (C-Haines ≥ 8 et
humidité au sol ≤ 40 %), par paliers de PFT.

COMMENT LES SEUILS ONT ÉTÉ CHOISIS (20/11/2026)
Sur trois cas rejoués avec l'archive des modèles (Open-Meteo) : Saumos le 24/07/2026 (orage de
feu observé : PFT 255 puis 152 GW de 15 h à 18 h TU, C-Haines 9 à 10, 14 à 31 % d'humidité),
Landiras le 11/08/2022 (gros pyrocumulus : PFT 40 à 80 GW, C-Haines 9), l'Aude le 5/08/2025 (feu
poussé par la tramontane, sans orage : PFT 650 à 950 GW, C-Haines 5). Trois cas ne valident
rien : ce sont des repères, à revoir à chaque saison. La puissance d'un feu se lit dans
core/feux_mtg.py (satellite MTG), où chaque feu suivi est comparé au seuil de son endroit.

AUCUNE ALERTE N'EST ENVOYÉE : affichage seulement, étiqueté « nos estimations ».
Même règle que le reste de la veille : seul le serveur appelle Météo-France, pour toute
l'emprise, depuis la tâche planifiée.
"""
import datetime
import io
import logging
import time
import zlib

import requests
from django.db import transaction
from django.utils import timezone

from . import meteo_france, pluie, rafales

logger = logging.getLogger(__name__)

URL_WCS = ("https://public-api.meteofrance.fr/public/arpege/1.0/wcs/"
           "MF-NWP-GLOBAL-ARPEGE-01-EUROPE-WCS/GetCoverage")
DELAI_REPONSE_S = 60
# Environ vingt appels par minute : la clé Météo-France est partagée avec le radar, le Doppler et
# les prévisions. Le 20/11/2026, une cinquantaine d'appels en une minute (premier calcul, et les
# essais qui l'ont précédé) a coïncidé avec des refus de connexion du Doppler et du radar.
PAUSE_ENTRE_GRILLES_S = 3.0

# Métropole et Corse (ouest, sud, est, nord), au pas d'ARPEGE : 156 × 106 points.
EMPRISE = (-5.5, 41.0, 10.0, 51.5)
PAS_DEGRES = 0.1
# Chaque valeur vaut pour le carré centré sur son point.
EMPRISE_IMAGE = (EMPRISE[0] - PAS_DEGRES / 2, EMPRISE[1] - PAS_DEGRES / 2,
                 EMPRISE[2] + PAS_DEGRES / 2, EMPRISE[3] + PAS_DEGRES / 2)
# Niveaux de pression lus (hPa), jusqu'à 250 hPa (≈ 10 km). Ceux du prototype validé sur le
# rejeu de Saumos : les 17 niveaux d'ARPEGE donneraient le même seuil à quelques pour cent près,
# pour 40 % d'appels en plus (mesuré le 20/11/2026 : 67 s par heure calculée avec 17 niveaux).
NIVEAUX = (1000, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250)
CHAMPS_NIVEAUX = {
    "t": "TEMPERATURE__ISOBARIC_SURFACE",                 # °C
    "hr": "RELATIVE_HUMIDITY__ISOBARIC_SURFACE",          # %
    "geo": "GEOPOTENTIAL__ISOBARIC_SURFACE",              # m²/s²
    "vent": "WIND_SPEED__ISOBARIC_SURFACE",               # m/s
}
CHAMPS_SOL = {
    "t2": ("TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2),
    "hr2": ("RELATIVE_HUMIDITY__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 2),
    "vent10": ("WIND_SPEED__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", 10),
    "ps": ("PRESSURE__GROUND_OR_WATER_SURFACE", None),               # Pa
    "blh": ("PLANETARY_BOUNDARY_LAYER_HEIGHT__GROUND_OR_WATER_SURFACE", None),
    "zsol": ("GEOMETRIC_HEIGHT__GROUND_OR_WATER_SURFACE", None),
}
GRAVITE = 9.80665

# Heures de l'après-midi (TU) calculées, aujourd'hui et demain : les feux violents sont diurnes.
HEURES_TU = (12, 15, 18)
# Heures calculées au plus par relevé : 54 grilles, environ trois minutes au rythme ci-dessus.
# Le relevé suivant (19 minutes plus tard) prend la suite : un nouveau calcul d'ARPEGE est
# intégré en deux heures environ, ce qui suffit pour quatre calculs par jour.
HEURES_PAR_RELEVE = 1
JOURS = 2
ECART_ENTRE_CALCULS = datetime.timedelta(hours=6)
CALCULS_ESSAYES = 4
GARDER_APRES = datetime.timedelta(hours=3)

# ── Physique ──
RD, CP, LV, EPS = 287.04, 1004.0, 2.5e6, 0.622
KAPPA = RD / CP
RAPPORT_K_PAR_GKG = 15.0
T_GLACE_C = -20.0
PAS_VERTICAL_M = 50.0
SOMMET_M = 12000.0
DTHETA_MAX = 40.0
ITERATIONS = 10          # bissection sur Δθ : 40 K / 2^10 ≈ 0,04 K

# ── Potentiel ──
C_HAINES_SEC = 8.0
# Le C-Haines lit le niveau 850 hPa : sous le relief (montagne), il ne veut plus rien dire.
PRESSION_SOL_MIN_HPA = 870
HUMIDITE_SOL_MAX = 40.0
#: Paliers de PFT (GW, jusqu'à) du plus fort au plus faible potentiel, rapportés à la puissance
#: d'un grand feu : le satellite MTG a mesuré 65 à 230 GW (rayonnement × 5 à 10) pour Saumos le
#: 24/07/2026. Très élevé : un feu de forêt vigoureux suffit ; élevé : il faut un très grand feu ;
#: modéré : seul un feu exceptionnel y parviendrait.
PALIERS = ((100, 3, "très élevé"), (250, 2, "élevé"), (500, 1, "modéré"))
LIBELLES = {0: None, 1: "modéré", 2: "élevé", 3: "très élevé"}
TEINTES = ((253, 186, 116), (234, 88, 12), (127, 29, 29))
OPACITES = (150, 190, 215)
PFT_ABSENT = 65535


def c_haines(t850, td850, t700):
    """C-Haines (Mills et McCaw 2010), sur des grilles ou des nombres (°C)."""
    import numpy

    ca = 0.5 * (numpy.asarray(t850) - t700) - 2
    ecart = numpy.minimum(numpy.asarray(t850) - td850, 30)
    cb = ecart / 3 - 1
    cb = numpy.where(cb > 5, 5 + (cb - 5) / 2, cb)
    return ca + cb


def point_de_rosee(t, hr):
    import numpy

    a = numpy.log(numpy.clip(hr, 1, 100) / 100) + 17.67 * t / (t + 243.5)
    return 243.5 * a / (17.67 - a)


def _es(tc):
    import numpy

    return 6.112 * numpy.exp(17.67 * tc / (tc + 243.5))


def _rmel(tc, p):
    e = _es(tc)
    return EPS * e / (p - e)


def profils(sol, niveaux):
    """Profils verticaux sur une grille régulière en hauteur au-dessus du sol, colonne par
    colonne : (P hPa, Z m, T °C, q kg/kg, vent m/s), chacun de forme (colonnes, hauteurs).

    `sol` : grilles ps (Pa), zsol (m), t2, hr2, vent10 ; `niveaux` : {hPa: {t, hr, geo, vent}}.
    Les niveaux sous le relief (pression supérieure à celle du sol) sont ignorés."""
    import numpy

    ps = sol["ps"].ravel() / 100
    zsol = sol["zsol"].ravel()
    n = ps.size
    zz = numpy.arange(0, SOMMET_M + 1, PAS_VERTICAL_M)
    sortie = [numpy.empty((n, zz.size)) for _ in range(5)]
    t2, hr2, v10 = sol["t2"].ravel(), sol["hr2"].ravel(), sol["vent10"].ravel()
    plats = {p: {k: v.ravel() for k, v in champs.items()} for p, champs in niveaux.items()}
    for i in range(n):
        p, z, t, q, v = [ps[i]], [0.0], [t2[i]], [_rmel(t2[i], ps[i]) * hr2[i] / 100], [v10[i]]
        for niveau in sorted(plats, reverse=True):
            champ = plats[niveau]
            hauteur = champ["geo"][i] / GRAVITE - zsol[i]
            if niveau >= ps[i] - 5 or hauteur <= z[-1]:
                continue
            p.append(niveau); z.append(hauteur); t.append(champ["t"][i])
            q.append(_rmel(champ["t"][i], niveau) * champ["hr"][i] / 100); v.append(champ["vent"][i])
        sortie[0][i] = numpy.exp(numpy.interp(zz, z, numpy.log(p)))
        sortie[2][i] = numpy.interp(zz, z, t)
        sortie[3][i] = numpy.interp(zz, z, q)
        sortie[4][i] = numpy.interp(zz, z, v)
    sortie[1][:] = zz
    return sortie


def _profond(P, Z, T, Q, theta_p, q_p):
    """Pour chaque colonne : le panache (theta_p, q_p) devient-il un orage ? Rend (profond,
    hauteur de condensation en m). Vectorisé sur les colonnes, pas à pas en hauteur."""
    import numpy

    n, k_max = P.shape
    tvenv = (T + 273.15) * (1 + 0.61 * Q)
    vivant = numpy.ones(n, bool)
    sature = numpy.zeros(n, bool)
    profond = numpy.zeros(n, bool)
    zlcl = numpy.full(n, numpy.nan)
    tk = theta_p * (P[:, 0] / 1000) ** KAPPA
    for k in range(k_max):
        sec = ~sature
        t_sec = theta_p * (P[:, k] / 1000) ** KAPPA
        if k > 0:
            r = _rmel(tk - 273.15, P[:, k - 1])
            gamma = (RD * tk + LV * r) / (CP + LV ** 2 * r * EPS / (RD * tk ** 2)) / P[:, k - 1]
            t_humide = tk + gamma * (P[:, k] - P[:, k - 1])
        else:
            t_humide = t_sec
        tk = numpy.where(sec, t_sec, t_humide)
        condense = sec & (_rmel(tk - 273.15, P[:, k]) <= q_p)
        zlcl = numpy.where(condense, Z[:, k], zlcl)
        sature |= condense
        qp = numpy.where(sature, _rmel(tk - 273.15, P[:, k]), q_p)
        vivant &= (tk * (1 + 0.61 * qp) >= tvenv[:, k]) | profond
        profond |= vivant & sature & (T[:, k] <= T_GLACE_C)
    return profond, zlcl


def pft(P, Z, T, Q, V, blh):
    """(PFT en GW, Δθ en K, hauteur de condensation en m) par colonne ; NaN là où même 40 K de
    réchauffement ne suffiraient pas."""
    import numpy

    theta = (T + 273.15) * (1000 / P) ** KAPPA
    couche = Z <= numpy.maximum(blh, 200)[:, None]
    theta_ml = (theta * couche).sum(1) / couche.sum(1)
    q_ml = (Q * couche).sum(1) / couche.sum(1)

    def essai(dtheta):
        return _profond(P, Z, T, Q, theta_ml + dtheta, q_ml + dtheta / RAPPORT_K_PAR_GKG / 1000)

    bas = numpy.full(P.shape[0], 0.1)
    haut = numpy.full(P.shape[0], DTHETA_MAX)
    deja, _ = essai(bas)
    possible, _ = essai(haut)
    for _ in range(ITERATIONS):
        milieu = (bas + haut) / 2
        ok, _ = essai(milieu)
        haut = numpy.where(ok, milieu, haut)
        bas = numpy.where(ok, bas, milieu)
    dtheta = numpy.where(deja, 0.1, haut)
    _, zfc = essai(dtheta)
    vent = numpy.array([V[i, Z[i] <= zfc[i]].mean() if numpy.isfinite(zfc[i]) else numpy.nan
                        for i in range(P.shape[0])])
    valeur = 0.3 * (zfc / 1000) ** 2 * vent * dtheta
    return (numpy.where(possible, valeur, numpy.nan), numpy.where(possible, dtheta, numpy.nan),
            numpy.where(possible, zfc, numpy.nan))


def masque_france(largeur, hauteur, ouest, nord):
    """Grille booléenne : vrai pour les mailles de la France (une commune dedans ou dans une maille
    voisine, soit les terres et les communes frontalières). La grille d'ARPEGE déborde sur la mer
    et les pays voisins : le 20/11/2026, les seuls paliers peints étaient en Ligurie, en Espagne
    et au large de la Corse. None s'il n'y a aucune commune en base (rien n'est alors masqué)."""
    import numpy

    from .models import Commune

    masque = numpy.zeros((hauteur, largeur), bool)
    for latitude, longitude in (Commune.objects.exclude(centre_latitude=None).exclude(centre_longitude=None)
                                .values_list("centre_latitude", "centre_longitude")):
        ligne, colonne = round((nord - latitude) / PAS_DEGRES), round((longitude - ouest) / PAS_DEGRES)
        if 0 <= ligne < hauteur and 0 <= colonne < largeur:
            masque[max(0, ligne - 1):ligne + 2, max(0, colonne - 1):colonne + 2] = True
    return masque if masque.any() else None


def potentiel(pft_gw, ch, hr2):
    """Palier du potentiel (0 à 3) : seulement là où l'air est sec et instable."""
    import numpy

    sec = (ch >= C_HAINES_SEC) & (hr2 <= HUMIDITE_SOL_MAX)
    rang = numpy.zeros(pft_gw.shape, numpy.uint8)
    for jusqua, palier, _ in sorted(PALIERS, reverse=True):
        rang = numpy.where(sec & numpy.isfinite(pft_gw) & (pft_gw <= jusqua), palier, rang)
    return rang.astype(numpy.uint8)


def calculer(sol, niveaux):
    """Toutes les grilles d'une échéance : {pft, ch, rang} de la forme de la grille d'entrée."""
    import numpy

    forme = sol["ps"].shape
    P, Z, T, Q, V = profils(sol, niveaux)
    valeur, _dtheta, _zfc = pft(P, Z, T, Q, V, sol["blh"].ravel())
    t850, t700 = niveaux[850]["t"], niveaux[700]["t"]
    ch = c_haines(t850, point_de_rosee(t850, niveaux[850]["hr"]), t700)
    ch = numpy.where(sol["ps"] / 100 >= PRESSION_SOL_MIN_HPA, ch, numpy.nan)
    valeur = valeur.reshape(forme)
    return {"pft": valeur, "ch": numpy.asarray(ch, float), "rang": potentiel(valeur, ch, sol["hr2"])}


# ── Stockage compact ──

def coder(grilles):
    """Octets compressés : PFT en GW entiers (uint16, 65535 = aucun orage possible), C-Haines
    au dixième (uint8), palier (uint8)."""
    import numpy

    pft_gw = grilles["pft"]
    entiers = numpy.where(numpy.isfinite(pft_gw), numpy.clip(numpy.round(pft_gw), 0, PFT_ABSENT - 1), PFT_ABSENT)
    ch = numpy.clip(numpy.round(numpy.nan_to_num(grilles["ch"], nan=0) * 10), 0, 255)
    return zlib.compress(entiers.astype("<u2").tobytes() + ch.astype(numpy.uint8).tobytes()
                         + grilles["rang"].astype(numpy.uint8).tobytes())


def decoder(octets, largeur, hauteur):
    import numpy

    brut = zlib.decompress(bytes(octets))
    n = largeur * hauteur
    pft_gw = numpy.frombuffer(brut[:2 * n], dtype="<u2").reshape(hauteur, largeur).astype(float)
    pft_gw[pft_gw == PFT_ABSENT] = numpy.nan
    ch = numpy.frombuffer(brut[2 * n:3 * n], dtype=numpy.uint8).reshape(hauteur, largeur) / 10
    rang = numpy.frombuffer(brut[3 * n:4 * n], dtype=numpy.uint8).reshape(hauteur, largeur)
    return {"pft": pft_gw, "ch": ch, "rang": rang}


def peindre(rang, agrandir=4):
    """PNG en projection Mercator du potentiel (0 transparent, 1 à 3 un palier)."""
    import numpy
    from PIL import Image

    grand = numpy.kron(rang, numpy.ones((agrandir, agrandir), numpy.uint8))
    hauteur, largeur = grand.shape
    ouest, sud, est, nord = EMPRISE_IMAGE
    grand = grand[pluie.lignes_mercator(hauteur, largeur, sud, nord, ouest, est)]
    image = Image.fromarray(grand)
    image.putpalette([0, 0, 0] + [c for teinte in TEINTES for c in teinte])
    sortie = io.BytesIO()
    image.save(sortie, format="PNG", optimize=True, transparency=bytes((0,) + OPACITES))
    return sortie.getvalue()


def legende():
    return [{"palier": palier, "libelle": libelle, "pft_jusqua_gw": jusqua,
             "couleur": "#%02x%02x%02x" % TEINTES[palier - 1]} for jusqua, palier, libelle in PALIERS]


def valeur_au_point(grille, latitude, longitude):
    """{pft_gw, c_haines, palier, potentiel} au point de grille le plus proche, ou None hors
    de l'emprise. `grille` : un PotentielOrageFeu."""
    import math

    if not (EMPRISE[0] - PAS_DEGRES <= longitude <= EMPRISE[2] + PAS_DEGRES
            and EMPRISE[1] - PAS_DEGRES <= latitude <= EMPRISE[3] + PAS_DEGRES):
        return None
    valeurs = decoder(grille.grilles, grille.largeur, grille.hauteur)
    colonne = min(grille.largeur - 1, max(0, round((longitude - grille.ouest) / PAS_DEGRES)))
    ligne = min(grille.hauteur - 1, max(0, round((grille.nord - latitude) / PAS_DEGRES)))
    pft_gw = valeurs["pft"][ligne, colonne]
    palier = int(valeurs["rang"][ligne, colonne])
    return {"pft_gw": None if math.isnan(pft_gw) else int(pft_gw),
            "c_haines": round(float(valeurs["ch"][ligne, colonne]), 1),
            "palier": palier, "potentiel": LIBELLES[palier]}


# ── Relevé ──

def echeances_voulues(maintenant):
    jour = maintenant.astimezone(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    limite = maintenant - GARDER_APRES
    return [jour + datetime.timedelta(days=j, hours=h) for j in range(JOURS) for h in HEURES_TU
            if jour + datetime.timedelta(days=j, hours=h) >= limite]


def calculs_candidats(maintenant):
    heure = maintenant.astimezone(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    dernier = heure.replace(hour=heure.hour - heure.hour % 6)
    return [dernier - ECART_ENTRE_CALCULS * rang for rang in range(CALCULS_ESSAYES)]


def _telecharger(couverture, calcul, echeance, extra):
    cle = meteo_france.lire_cle()
    if cle is None:
        raise meteo_france.CleAbsente()
    ouest, sud, est, nord = EMPRISE
    identifiant = f"{couverture}___{calcul.astimezone(datetime.timezone.utc):%Y-%m-%dT%H.%M.%SZ}"
    reponse = meteo_france.avec_reprise(lambda: requests.get(
        URL_WCS, headers={"apikey": cle}, timeout=DELAI_REPONSE_S, params=[
            ("service", "WCS"), ("version", "2.0.1"), ("coverageid", identifiant),
            ("subset", f"time({pluie._instant_api(echeance)})"),
            ("subset", f"lat({sud},{nord})"), ("subset", f"long({ouest},{est})"),
            *extra, ("format", "image/tiff"),
        ]))
    if reponse.status_code in (400, 404):
        return None
    reponse.raise_for_status()
    if reponse.content[:4] not in (b"II*\x00", b"MM\x00*"):
        return None
    grille, ouest_lu, nord_lu, pas = rafales.lire_grille_tiff(reponse.content)
    if abs(pas - PAS_DEGRES) > 1e-6:
        raise ValueError(f"grille au pas de {pas}°, {PAS_DEGRES}° attendu")
    return grille, ouest_lu, nord_lu


def telecharger_echeance(calcul, echeance):
    """(sol, niveaux, ouest, nord) d'une échéance, ou None si ce calcul ne la propose pas."""
    sol, niveaux, coin = {}, {}, None
    for nom, (couverture, hauteur) in CHAMPS_SOL.items():
        time.sleep(PAUSE_ENTRE_GRILLES_S)
        lu = _telecharger(couverture, calcul, echeance, [("subset", f"height({hauteur})")] if hauteur else [])
        if lu is None:
            return None
        sol[nom], coin = lu[0], lu[1:]
    for niveau in NIVEAUX:
        niveaux[niveau] = {}
        for nom, couverture in CHAMPS_NIVEAUX.items():
            time.sleep(PAUSE_ENTRE_GRILLES_S)
            lu = _telecharger(couverture, calcul, echeance, [("subset", f"pressure({niveau})")])
            if lu is None:
                return None
            if lu[0].shape != sol["ps"].shape:
                raise ValueError("les champs d'ARPEGE ne sont pas sur la même grille")
            niveaux[niveau][nom] = lu[0]
    return sol, niveaux, coin[0], coin[1]


def relever(maintenant=None):
    """Calcule les échéances qui manquent pour le calcul ARPEGE le plus récent, retire les
    passées. Rend le nombre d'échéances en base."""
    import numpy

    from .models import PotentielOrageFeu

    maintenant = maintenant or timezone.now()
    voulues = echeances_voulues(maintenant)
    PotentielOrageFeu.objects.filter(echeance__lt=maintenant - GARDER_APRES).delete()
    if not voulues:
        return PotentielOrageFeu.objects.count()
    connues = {p.echeance: p.calcul for p in PotentielOrageFeu.objects.only("echeance", "calcul")}

    calcul, premier = None, None
    for candidat in calculs_candidats(maintenant):
        if connues.get(voulues[0]) == candidat:
            calcul = candidat
            break
        premier = telecharger_echeance(candidat, voulues[0])
        if premier is not None:
            calcul = candidat
            break
    if calcul is None:
        raise ValueError("aucun calcul du modèle ARPEGE ne répond pour la première échéance")

    calculees = 0
    masque = None
    for echeance in voulues:
        if connues.get(echeance) == calcul:
            continue
        if calculees >= HEURES_PAR_RELEVE:
            break
        calculees += 1
        lu = premier if echeance == voulues[0] and premier is not None else telecharger_echeance(calcul, echeance)
        if lu is None:
            continue
        sol, niveaux, ouest, nord = lu
        grilles = calculer(sol, niveaux)
        hauteur, largeur = sol["ps"].shape
        masque = masque if masque is not None else masque_france(largeur, hauteur, ouest, nord)
        if masque is not None:
            grilles["rang"] = numpy.where(masque, grilles["rang"], 0).astype(numpy.uint8)
        with transaction.atomic():
            PotentielOrageFeu.objects.update_or_create(echeance=echeance, defaults={
                "calcul": calcul, "largeur": largeur, "hauteur": hauteur, "ouest": ouest, "nord": nord,
                "grilles": coder(grilles), "image": peindre(grilles["rang"]), "releve_le": timezone.now(),
            })
    return PotentielOrageFeu.objects.count()
