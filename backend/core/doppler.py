"""Radars Doppler de Météo-France, radar par radar (19/11/2026) : rotation, grêle, divergence.

SOURCE
API « DPRadar », produit « PAG » de chaque radar : un fichier par balayage (« tour d'antenne » A
à H, de l'élévation la plus haute à la plus basse), toutes les cinq minutes. BUFR édition 2 avec
les descripteurs locaux de Météo-France (centre 85, table locale 12), décodé par `decbufr` de
BALTRAD (image du service `orages`, Dockerfile.meteo). Relevé le 19/11/2026 sur le radar de
Bollène :

- trois messages par fichier : (1) réflectivité, 720 azimuts × 256 portes d'un kilomètre ;
  (2) largeur spectrale, 360 × 256 ; (3) VITESSE RADIALE, 360 × 256, en classes de 0,5 m/s à
  partir de −60,2 m/s — DÉJÀ DÉPLIÉE par le radar (trois fréquences d'impulsion alternées) ;
  classe 255 = pas de donnée. ATTENTION : chez Météo-France la vitesse est POSITIVE VERS le radar
  (« Description des données radars individuelles (PAG et PAM) », 04/05/2026, § vitesses
  radiales) ; elle est retournée au décodage dans la convention usuelle, positive en s'éloignant ;
- produit « PAM » des radars à double polarisation : six messages dans cet ordre — réflectivité,
  corrélation copolaire ρHV, réflectivité différentielle ZDR, phase différentielle, écart-type,
  advection — en 720 azimuts × 1066 portes de 240 m. Codages par défaut de la même fiche
  (descripteurs de décalage et de pas absents des fichiers) : ρHV = 0,3 + code/100,
  ZDR = −10 + code/10 dB, 255 = manquant ;
- l'en-tête donne la position du radar, l'élévation, et l'altitude de l'isotherme 0 °C de son
  profil vertical de réflectivité.

CE QU'ON EN TIRE, ET LES CRITÈRES (prudents, à régler sur des cas réels avant toute annonce) :

- **rotation détectée** : un couple « vers le radar / depuis le radar » accolé (vitesse sortante
  du côté horaire, rotation cyclonique), vitesse de rotation (Vmax − Vmin) / 2 ≥ 15 m/s, les deux
  extrêmes à moins de 10 km l'un de l'autre, retrouvé sur au moins deux élévations à moins de
  5 km d'écart. C'est la signature d'un mésocyclone, pas la preuve d'une tornade ;
- **grêle probable** (critère de Waldvogel) : l'écho de 45 dBZ monte à plus de 1,4 km au-dessus
  de l'isotherme 0 °C ;
- **divergence forte** près du sol (rafale descendante possible) : la vitesse radiale gagne au
  moins 20 m/s sur 4 km ou moins le long d'un rayon, faisceau à moins de 2 km d'altitude ;
- **grêle détectée par la double polarisation** : au moins cinq portes où Z ≥ 50 dBZ, ZDR entre
  −1 et +1 dB (les grêlons qui culbutent paraissent ronds) et 0,70 ≤ ρHV ≤ 0,96 (milieu mêlé) ;
- **signature de débris** : à moins de 3 km d'une rotation détectée, au moins trois portes où
  Z ≥ 35 dBZ et ρHV ≤ 0,80 avec |ZDR| ≤ 1,5 dB — des objets de formes quelconques soulevés :
  le signe qu'une tornade touche probablement le sol.

Limites : un radar ne voit que la composante du vent dans l'axe du faisceau ; loin du radar, le
faisceau passe au-dessus du bas des orages ; à moins de 10 km, les élévations basses manquent.
"""
import datetime
import logging
import math
import os
import re
import subprocess
import tempfile

import requests
from django.utils import timezone

from . import meteo_france

logger = logging.getLogger(__name__)

URL = "https://public-api.meteofrance.fr/public/DPRadar/v1/stations"
DELAI_REPONSE_S = 60
RAYON_TERRE_M = 6371000.0
KE = 4 / 3                         # rayon terrestre effectif : propagation standard

#: Critères (voir la docstring du module).
VROT_MIN_MS = 15.0
DISTANCE_COUPLE_MAX_KM = 10.0
DISTANCE_COUPLE_MIN_KM = 1.0
CONTINUITE_VERTICALE_KM = 5.0
ELEVATIONS_MIN_ROTATION = 2
PORTEE_MIN_KM, PORTEE_MAX_KM = 10.0, 150.0
SEUIL_GRELE_DBZ, MARGE_WALDVOGEL_M = 45.0, 1400.0
DIVERGENCE_MIN_MS, DIVERGENCE_SUR_KM, HAUTEUR_DIVERGENCE_MAX_M = 20.0, 4.0, 2000.0
#: Balayages lus par radar : les plus bas, où vivent les rotations et les rafales.
BALAYAGES_BAS = 3
#: Garde-fous contre les artefacts (constatés le 19/11/2026 sur Cherves et Abbeville : « rotations »
#: de 58 m/s et « divergences » de 108 m/s, faites de pixels isolés et d'erreurs de dépliement) :
#: vitesse ignorée sous un écho faible, lissage par la médiane, sauts trop brusques refusés,
#: plafonds physiques.
Z_MIN_VITESSE_DBZ = 15.0
SAUT_MAX_MS = 25.0
VROT_MAX_MS = 45.0
DIVERGENCE_MAX_MS = 50.0


class Balayage:
    """Un message décodé : `valeurs` (azimuts, portes) en dBZ ou m/s, NaN là où rien n'est mesuré."""

    def __init__(self, nature, elevation, azimut0, valeurs, porte_m, latitude, longitude, altitude, isotherme0):
        self.nature, self.elevation, self.azimut0 = nature, elevation, azimut0
        self.valeurs, self.porte_m = valeurs, porte_m
        self.latitude, self.longitude, self.altitude, self.isotherme0 = latitude, longitude, altitude, isotherme0

    @property
    def pas_azimut(self):
        return 360.0 / self.valeurs.shape[0]


# ── Décodage ─────────────────────────────────────────────────────────────────

def messages(octets):
    """Découpe un fichier BUFR en messages (la longueur de chacun est dans son en-tête)."""
    resultat, i = [], 0
    while True:
        j = octets.find(b"BUFR", i)
        if j < 0 or j + 8 > len(octets):
            return resultat
        longueur = int.from_bytes(octets[j + 4:j + 7], "big")
        if longueur <= 8 or j + longueur > len(octets):
            return resultat
        resultat.append(octets[j:j + longueur])
        i = j + longueur


def _decbufr(message):
    """Texte de decbufr pour un message (outil et tables de l'image d'analyse)."""
    outil = os.environ.get("BBUFR_DECBUFR", "/opt/bbufr/bin/decbufr")
    tables = os.environ.get("BBUFR_TABLES", "/opt/bbufr/tables")
    with tempfile.TemporaryDirectory() as dossier:
        entree, sortie = os.path.join(dossier, "m.bufr"), os.path.join(dossier, "m.txt")
        with open(entree, "wb") as f:
            f.write(message)
        subprocess.run([outil, "-d", tables, entree, sortie], cwd=dossier, capture_output=True, timeout=60, check=False)
        if not os.path.exists(sortie):
            raise ValueError("decbufr n'a rien produit.")
        with open(sortie, encoding="latin-1") as f:
            return f.read()


_NOMBRE = re.compile(r"-?\d+(?:\.\d+)?")


def _valeur(lignes, libelle):
    """Valeur numérique de la première ligne portant ce libellé."""
    for ligne in lignes:
        if libelle in ligne:
            nombres = _NOMBRE.findall(ligne.split(libelle)[0])
            # « f x y valeur  libellé » ou « valeur  f x y  libellé » : la valeur est le seul
            # nombre décimal de la ligne.
            decimaux = [n for n in nombres if "." in n]
            if decimaux:
                return float(decimaux[0])
    return None


def lire_message(texte, nature_imposee=None):
    """Balayage d'un message décodé, ou None s'il n'est ni réflectivité ni vitesse. `nature_imposee`
    (« Z », « RHO », « ZDR ») vaut pour les messages PAM, que seul leur rang identifie."""
    import numpy

    lignes = texte.splitlines()
    colonnes = int(_valeur(lignes, "Number of pixels per row") or 0)       # portes par azimut
    rangees = int(_valeur(lignes, "Number of pixels per column") or 0)     # azimuts
    if not colonnes or not rangees:
        return None
    # Le message PAM de réflectivité répète deux fois : le bruit de ses 720 radiales, puis les
    # pixels. On prend la répétition dont la taille vaut azimuts × portes (la dernière à défaut).
    repetitions = [i for i, l in enumerate(lignes) if "Facteur super elargi" in l]
    if not repetitions:
        return None
    debut = next((i for i in repetitions if (_valeur([lignes[i]], "Facteur super elargi") or 0) == colonnes * rangees),
                 repetitions[-1])
    classes = []
    for ligne in lignes[debut + 1:]:
        if "Pixel value" in ligne:
            decimaux = [n for n in _NOMBRE.findall(ligne.split("Pixel value")[0]) if "." in n]
            if decimaux:
                classes.append(float(decimaux[0]))
    if len(classes) != colonnes * rangees:
        raise ValueError(f"{len(classes)} pixels lus pour {colonnes} × {rangees}.")
    brut = numpy.array(classes).reshape(rangees, colonnes)

    vmin = _valeur(lignes, "Valeur minimale de la vitesse radiale")
    if nature_imposee == "RHO":
        valeurs, nature = numpy.where(brut >= 255, numpy.nan, 0.3 + brut / 100 + 0.005), "RHO"
    elif nature_imposee == "ZDR":
        valeurs, nature = numpy.where(brut >= 255, numpy.nan, -10 + brut / 10 + 0.05), "ZDR"
    elif vmin is not None:
        pas = _valeur(lignes, "Ecart entre deux valeurs consecutives") or 0.5
        # Retournée : Météo-France compte la vitesse positive VERS le radar.
        valeurs = numpy.where(brut >= 255, numpy.nan, -(vmin + pas * brut))
        nature = "V"
    elif nature_imposee == "Z" or (nature_imposee is None and rangees == 720):
        # Table « classe -> deux bornes de réflectivité », écrite avant les pixels.
        table, classe = {}, None
        for ligne in lignes[:debut]:
            if "Pixel value" in ligne:
                decimaux = [n for n in _NOMBRE.findall(ligne.split("Pixel value")[0]) if "." in n]
                classe = int(float(decimaux[0])) if decimaux else None
                table.setdefault(classe, [])
            elif "pour la valeur du pixel" in ligne and classe is not None:
                decimaux = [n for n in _NOMBRE.findall(ligne) if "." in n]
                if decimaux:
                    table[classe].append(float(decimaux[0]))
        correspondance = numpy.full(256, numpy.nan)
        if table:
            for k, bornes in table.items():
                if k and bornes and max(bornes) > 0:
                    correspondance[k] = sum(bornes) / len(bornes)
        else:
            # Codage par défaut : classe N = [−11 + N ; −10 + N[ dBZ ; 0 et 1 trop près du bruit.
            correspondance[2:80] = numpy.arange(2, 80) - 10.5
        valeurs = correspondance[brut.astype(int).clip(0, 255)]
        nature = "Z"
    else:
        return None
    portee_fin = _valeur(lignes, "Portee de fin de traitement") or colonnes * 1000.0
    return Balayage(nature, _valeur(lignes, "Antenna elevation") or 0.0, _valeur(lignes, "Antenna beam azimuth") or 0.0,
                    valeurs, portee_fin / colonnes, _valeur(lignes, "Latitude (high accuracy)"),
                    _valeur(lignes, "Longitude (high accuracy)"), _valeur(lignes, "Height or altitude") or 0.0,
                    _valeur(lignes, "Altitude de l'isotherme 0 degre"))


def decoder(octets):
    """Balayages (réflectivité et vitesse) d'un fichier PAG. La vitesse est nettoyée : ignorée là
    où l'écho du même balayage est faible, puis lissée par la médiane des points voisins."""
    resultat = []
    for message in messages(octets):
        try:
            balayage = lire_message(_decbufr(message))
        except Exception:
            logger.warning("Message radar illisible.", exc_info=True)
            continue
        if balayage is not None:
            resultat.append(balayage)
    reflectivite = next((b for b in resultat if b.nature == "Z"), None)
    for vitesse in (b for b in resultat if b.nature == "V"):
        nettoyer_vitesse(vitesse, reflectivite)
    return resultat


def decoder_pam(octets):
    """Réflectivité, ρHV et ZDR d'un fichier PAM (les trois premiers messages, dans cet ordre)."""
    resultat = []
    for message, nature in zip(messages(octets)[:3], ("Z", "RHO", "ZDR")):
        try:
            balayage = lire_message(_decbufr(message), nature)
        except Exception:
            logger.warning("Message PAM illisible.", exc_info=True)
            continue
        if balayage is not None:
            resultat.append(balayage)
    return resultat


def nettoyer_vitesse(vitesse, reflectivite=None):
    import warnings
    import numpy
    from scipy import ndimage
    warnings.filterwarnings("ignore", message="All-NaN slice", category=RuntimeWarning)

    v = vitesse.valeurs.copy()
    if reflectivite is not None and reflectivite.valeurs.shape[1] == v.shape[1]:
        z = reflectivite.valeurs
        facteur = z.shape[0] // v.shape[0]
        if facteur >= 1 and z.shape[0] == facteur * v.shape[0]:
            z = numpy.nanmax(z.reshape(v.shape[0], facteur, z.shape[1]), axis=1) if facteur > 1 else z
            v[~(numpy.nan_to_num(z, nan=-99) >= Z_MIN_VITESSE_DBZ)] = numpy.nan
    # Médiane 3 × 3 sur les points mesurés ; un point sans au moins cinq voisins mesurés tombe.
    valides = numpy.isfinite(v)
    comptes = ndimage.uniform_filter(valides.astype(float), size=3, mode="wrap") * 9
    lissee = ndimage.generic_filter(numpy.where(valides, v, numpy.nan), numpy.nanmedian, size=3, mode="wrap")
    vitesse.valeurs = numpy.where(valides & (comptes >= 5), lissee, numpy.nan)


# ── Géométrie du faisceau ────────────────────────────────────────────────────

def hauteur_faisceau(distance_m, elevation_deg, altitude_radar_m):
    """Altitude du centre du faisceau (m), propagation standard (rayon effectif 4/3)."""
    re_eff = KE * RAYON_TERRE_M
    e = math.radians(elevation_deg)
    return math.sqrt(distance_m ** 2 + re_eff ** 2 + 2 * distance_m * re_eff * math.sin(e)) - re_eff + altitude_radar_m


def position(balayage, azimut_deg, distance_m):
    """(lon, lat) du point d'un faisceau (distance au sol approchée par la distance oblique)."""
    re_eff = KE * RAYON_TERRE_M
    e = math.radians(balayage.elevation)
    au_sol = re_eff * math.asin(distance_m * math.cos(e) / (re_eff + hauteur_faisceau(distance_m, balayage.elevation, 0)))
    d = au_sol / RAYON_TERRE_M
    lat1, lon1, az = math.radians(balayage.latitude), math.radians(balayage.longitude), math.radians(azimut_deg)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(az))
    lon2 = lon1 + math.atan2(math.sin(az) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lon2), math.degrees(lat2)


def polaire(balayage, lon, lat):
    """(azimut en degrés, distance oblique en m) d'un point vu d'un radar (approximation plane)."""
    dy = (lat - balayage.latitude) * 111320.0
    dx = (lon - balayage.longitude) * 111320.0 * math.cos(math.radians(balayage.latitude))
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360, math.hypot(dx, dy)


# ── Signatures ───────────────────────────────────────────────────────────────

def couples_de_rotation(vitesse, zone_azimuts=None, zone_portes=None):
    """Couples de rotation cyclonique d'un balayage de vitesse : [(vrot m/s, azimut, distance m)].

    Le long de chaque porte, on cherche dans une fenêtre d'azimuts couvrant au plus 10 km un
    minimum (vers le radar) suivi, dans le sens horaire, d'un maximum (s'éloignant du radar)."""
    import numpy

    v = vitesse.valeurs
    nb_az, nb_portes = v.shape
    resultat = []
    portes = range(nb_portes) if zone_portes is None else zone_portes
    for j in portes:
        r = (j + 0.5) * vitesse.porte_m
        if not (PORTEE_MIN_KM * 1000 <= r <= PORTEE_MAX_KM * 1000):
            continue
        largeur_km = r * math.radians(vitesse.pas_azimut) / 1000
        fenetre = max(2, int(DISTANCE_COUPLE_MAX_KM / largeur_km))
        minimum_az = max(1, int(math.ceil(DISTANCE_COUPLE_MIN_KM / largeur_km)))
        azimuts = range(nb_az) if zone_azimuts is None else zone_azimuts
        for i in azimuts:
            a = v[i % nb_az, j]
            if not numpy.isfinite(a) or a >= 0:
                continue
            suite = numpy.array([v[(i + k) % nb_az, j] for k in range(minimum_az, fenetre + 1)])
            if not numpy.isfinite(suite).any():
                continue
            k = int(numpy.nanargmax(suite))
            b = suite[k]
            if b <= 0:
                continue
            # Le passage de a à b doit être continu : un saut brusque est une erreur de mesure.
            trajet = numpy.array([v[(i + m) % nb_az, j] for m in range(0, k + minimum_az + 1)])
            mesures = trajet[numpy.isfinite(trajet)]
            if len(mesures) < 2 or numpy.max(numpy.abs(numpy.diff(mesures))) > SAUT_MAX_MS:
                continue
            vrot = (b - a) / 2
            if VROT_MIN_MS <= vrot <= VROT_MAX_MS:
                milieu = vitesse.azimut0 + (i + (k + minimum_az) / 2) * vitesse.pas_azimut
                resultat.append((float(vrot), milieu % 360, r))
    return resultat


def rotation(balayages_vitesse, zone):
    """Rotation retrouvée sur au moins deux élévations dans la zone (polygone géographique) :
    {"vrot_ms", "elevations", "lon", "lat"} ou None."""
    candidats = []
    for b in balayages_vitesse:
        az, portes = _zone_polaire(b, zone)
        for vrot, azimut, r in couples_de_rotation(b, az, portes):
            lon, lat = position(b, azimut, r)
            candidats.append((vrot, b.elevation, lon, lat))
    meilleur = None
    for vrot, elevation, lon, lat in sorted(candidats, reverse=True):
        elevations = {elevation}
        for vrot2, elevation2, lon2, lat2 in candidats:
            if elevation2 != elevation and _distance_km(lon, lat, lon2, lat2) <= CONTINUITE_VERTICALE_KM:
                elevations.add(elevation2)
        if len(elevations) >= ELEVATIONS_MIN_ROTATION:
            meilleur = {"vrot_ms": round(vrot, 1), "elevations": sorted(elevations), "lon": round(lon, 4), "lat": round(lat, 4)}
            break
    return meilleur


def grele(balayages_reflectivite, zone):
    """Critère de Waldvogel : {"z_max_dbz", "sommet_45_m", "isotherme0_m", "probable"}."""
    import numpy

    z_max, sommet, isotherme = None, None, None
    for b in balayages_reflectivite:
        isotherme = isotherme or b.isotherme0
        az, portes = _zone_polaire(b, zone)
        for j in portes:
            r = (j + 0.5) * b.porte_m
            if r < PORTEE_MIN_KM * 1000:       # échos du sol autour du radar (non filtrés)
                continue
            for i in az:
                z = b.valeurs[i % b.valeurs.shape[0], j]
                if not numpy.isfinite(z):
                    continue
                z_max = z if z_max is None else max(z_max, z)
                if z >= SEUIL_GRELE_DBZ:
                    h = hauteur_faisceau(r, b.elevation, b.altitude)
                    sommet = h if sommet is None else max(sommet, h)
    probable = bool(sommet is not None and isotherme is not None and sommet - isotherme >= MARGE_WALDVOGEL_M)
    return {"z_max_dbz": round(float(z_max), 1) if z_max is not None else None,
            "sommet_45_m": round(sommet) if sommet is not None else None,
            "isotherme0_m": round(isotherme) if isotherme is not None else None, "probable": probable}


def divergence(balayages_vitesse, zone):
    """Plus forte divergence près du sol dans la zone (m/s gagnés sur au plus 4 km), ou None."""
    import numpy

    meilleure = None
    for b in balayages_vitesse:
        az, portes = _zone_polaire(b, zone)
        pas = max(1, int(DIVERGENCE_SUR_KM * 1000 / b.porte_m))
        for i in az:
            rayon = b.valeurs[i % b.valeurs.shape[0]]
            for j in portes:
                if j + pas >= len(rayon) or hauteur_faisceau((j + 0.5) * b.porte_m, b.elevation, b.altitude) > HAUTEUR_DIVERGENCE_MAX_M:
                    continue
                troncon = rayon[j:j + pas + 1]
                mesures = troncon[numpy.isfinite(troncon)]
                if len(mesures) < 3 or not numpy.isfinite(troncon[0]):
                    continue
                if numpy.max(numpy.abs(numpy.diff(mesures))) > SAUT_MAX_MS:
                    continue
                ecart = float(numpy.max(mesures) - troncon[0])
                if DIVERGENCE_MIN_MS <= ecart <= DIVERGENCE_MAX_MS:
                    meilleure = max(meilleure or 0, ecart)
    return round(meilleure, 1) if meilleure is not None else None


def polarimetrie(balayages, zone, rotation_centre=None):
    """Grêle et débris selon la double polarisation : {"grele", "portes_grele", "debris"}. Les
    balayages Z, RHO et ZDR d'une même élévation sont appariés par leur élévation."""
    import numpy

    portes_grele, portes_debris = 0, 0
    par_elevation = {}
    for b in balayages:
        par_elevation.setdefault(round(b.elevation, 1), {})[b.nature] = b
    for trio in par_elevation.values():
        if not {"Z", "RHO", "ZDR"} <= set(trio):
            continue
        z, rho, zdr = trio["Z"], trio["RHO"], trio["ZDR"]
        if not (z.valeurs.shape == rho.valeurs.shape == zdr.valeurs.shape):
            continue
        az, portes = _zone_polaire(z, zone)
        lignes = numpy.array([i % z.valeurs.shape[0] for i in az])
        # Échos du sol autour du radar : ce produit n'est pas filtré (fiche Météo-France).
        colonnes = numpy.array([j for j in portes if (j + 0.5) * z.porte_m >= PORTEE_MIN_KM * 1000])
        if not len(lignes) or not len(colonnes):
            continue
        Z = z.valeurs[numpy.ix_(lignes, colonnes)]
        R = rho.valeurs[numpy.ix_(lignes, colonnes)]
        D = zdr.valeurs[numpy.ix_(lignes, colonnes)]
        with numpy.errstate(invalid="ignore"):
            grele_ici = (Z >= 50) & (numpy.abs(D) <= 1.0) & (R >= 0.70) & (R <= 0.96)
            portes_grele += int(numpy.count_nonzero(grele_ici))
            if rotation_centre is not None:
                debris_ici = (Z >= 35) & (R <= 0.80) & (numpy.abs(D) <= 1.5)
                for a, j in zip(*numpy.nonzero(debris_ici)):
                    azimut = z.azimut0 + lignes[a] * z.pas_azimut
                    lon, lat = position(z, azimut, (colonnes[j] + 0.5) * z.porte_m)
                    if _distance_km(lon, lat, *rotation_centre) <= 3.0:
                        portes_debris += 1
    return {"grele": portes_grele >= 5, "portes_grele": portes_grele, "debris": portes_debris >= 3}


def telecharger_pam(station, tour):
    import gzip
    cle = meteo_france.lire_cle()
    r = requests.get(f"{URL}/{station}/observations/PAM/produit", params={"tour_antenne": tour},
                     headers={"apikey": cle}, timeout=DELAI_REPONSE_S)
    if r.status_code != 200:
        return None
    try:
        return gzip.decompress(r.content)
    except OSError:
        return r.content


def _distance_km(lon1, lat1, lon2, lat2):
    dy = (lat2 - lat1) * 111.32
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def _zone_polaire(balayage, zone):
    """Azimuts (indices) et portes couvrant l'emprise d'un polygone, vus d'un radar."""
    o, s, e, n = zone.extent
    coins = [polaire(balayage, lon, lat) for lon, lat in ((o, s), (o, n), (e, s), (e, n))]
    distances = [d for _, d in coins]
    j0 = max(0, int(min(distances) / balayage.porte_m) - 2)
    j1 = min(balayage.valeurs.shape[1], int(max(distances) / balayage.porte_m) + 3)
    angles = sorted(a for a, _ in coins)
    ecart = angles[-1] - angles[0]
    if ecart > 180:                       # la zone chevauche le nord
        debut, fin = angles[[a > 180 for a in angles].index(True)] - 360, max(a for a in angles if a <= 180)
    else:
        debut, fin = angles[0], angles[-1]
    i0 = int(math.floor((debut - balayage.azimut0) / balayage.pas_azimut)) - 2
    i1 = int(math.ceil((fin - balayage.azimut0) / balayage.pas_azimut)) + 2
    return range(i0, i1 + 1), range(j0, j1)


# ── Relevé ───────────────────────────────────────────────────────────────────

def telecharger_balayage(station, tour):
    import gzip
    cle = meteo_france.lire_cle()
    r = requests.get(f"{URL}/{station}/observations/PAG/produit", params={"tour_antenne": tour},
                     headers={"apikey": cle}, timeout=DELAI_REPONSE_S)
    if r.status_code != 200:
        return None
    try:
        return gzip.decompress(r.content)
    except OSError:
        return r.content


#: Radars d'outre-mer exclus : leurs cellules ne sont pas encore analysées (lame d'eau métropole).
STATIONS_METROPOLE_MAX = 89
POSITIONS_VALABLES = datetime.timedelta(days=7)
CELLULES_MAX = 8
INTENSITE_MIN_MMH = 40
RADARS_PAR_CELLULE = 2


def mettre_a_jour_radars(maintenant=None):
    """Registre des radars : identifiant, nom, balayages, et position lue dans l'en-tête de leurs
    propres fichiers (la liste publiée ne la donne pas). Rafraîchi chaque semaine."""
    import csv
    import io
    from .models import RadarMeteo

    maintenant = maintenant or timezone.now()
    if RadarMeteo.objects.filter(maj__gte=maintenant - POSITIONS_VALABLES).count() >= 20:
        return 0
    cle = meteo_france.lire_cle()
    r = requests.get(f"{URL.rsplit('/', 1)[0]}/liste-stations", headers={"apikey": cle}, timeout=DELAI_REPONSE_S)
    r.raise_for_status()
    nombre = 0
    for ligne in csv.DictReader(io.StringIO(r.text), delimiter=";"):
        try:
            station = int(ligne["Id station"])
        except (KeyError, ValueError):
            continue
        if station > STATIONS_METROPOLE_MAX:
            continue
        tours = [t.strip() for t in (ligne.get("Tours antenne PAG (x)") or "").split(",") if t.strip()]
        if not tours:
            continue
        octets = telecharger_balayage(station, tours[-1])
        balayages = decoder(octets) if octets else []
        tete = next((b for b in balayages if b.latitude is not None), None)
        if tete is None:
            continue
        RadarMeteo.objects.update_or_create(station=station, defaults={
            "nom": (ligne.get("Nom station") or "").replace("RADAR ", "").title(), "tours": tours,
            "latitude": tete.latitude, "longitude": tete.longitude, "altitude": tete.altitude, "maj": maintenant})
        nombre += 1
    return nombre


def relever(maintenant=None):
    """Signatures Doppler des cellules de pluie intense en cours (au plus CELLULES_MAX), lues sur
    les balayages bas des radars les plus proches. Rend le nombre de cellules examinées."""
    from .models import CelluleOrage, RadarMeteo

    maintenant = maintenant or timezone.now()
    mettre_a_jour_radars(maintenant)
    radars = list(RadarMeteo.objects.all())
    # Radars de métropole seulement (STATIONS_METROPOLE_MAX) : les cellules d'outre-mer n'ont
    # rien à attendre d'eux et prendraient la place des autres.
    cellules = list(CelluleOrage.objects.filter(zone="METROPOLE", max_mmh__gte=INTENSITE_MIN_MMH)
                    .order_by("-max_mmh")[:CELLULES_MAX])
    if not cellules or not radars:
        return 0
    besoins = {}
    for cellule in cellules:
        proches = sorted(radars, key=lambda r: _distance_km(cellule.centre.x, cellule.centre.y, r.longitude, r.latitude))
        retenus = [r for r in proches if _distance_km(cellule.centre.x, cellule.centre.y, r.longitude, r.latitude)
                   <= PORTEE_MAX_KM][:RADARS_PAR_CELLULE]
        besoins[cellule.pk] = retenus
    balayages = {}
    for radar in {r.station: r for liste in besoins.values() for r in liste}.values():
        lus = []
        for tour in radar.tours[-BALAYAGES_BAS:]:
            octets = telecharger_balayage(radar.station, tour)
            if octets:
                lus += decoder(octets)
        balayages[radar.station] = lus
    for cellule in cellules:
        zone = cellule.contour.buffer(0.05)
        rotation_retenue, grele_retenue, divergence_retenue, noms = None, None, None, []
        for radar in besoins[cellule.pk]:
            lus = balayages.get(radar.station) or []
            vitesses = [b for b in lus if b.nature == "V"]
            reflectivites = [b for b in lus if b.nature == "Z"]
            if not lus:
                continue
            noms.append(radar.nom)
            rot = rotation(vitesses, zone)
            if rot and (rotation_retenue is None or rot["vrot_ms"] > rotation_retenue["vrot_ms"]):
                rotation_retenue = {**rot, "radar": radar.nom}
            gr = grele(reflectivites, zone)
            if grele_retenue is None or (gr["sommet_45_m"] or 0) > (grele_retenue["sommet_45_m"] or 0):
                grele_retenue = {**gr, "radar": radar.nom}
            div = divergence(vitesses, zone)
            if div is not None and (divergence_retenue is None or div > divergence_retenue["ms"]):
                divergence_retenue = {"ms": div, "radar": radar.nom}
        # Double polarisation, seulement là où elle peut trancher : écho fort ou rotation, au
        # radar le plus proche, deux balayages les plus bas (fichiers lourds : ~4 Mo chacun).
        polar = None
        fort = grele_retenue and (grele_retenue.get("z_max_dbz") or 0) >= 50
        if (fort or rotation_retenue) and besoins[cellule.pk]:
            radar = besoins[cellule.pk][0]
            lus = []
            for tour in radar.tours[-2:]:
                octets = telecharger_pam(radar.station, tour)
                if octets:
                    lus += decoder_pam(octets)
            if lus:
                centre = (rotation_retenue["lon"], rotation_retenue["lat"]) if rotation_retenue else None
                polar = {**polarimetrie(lus, zone, centre), "radar": radar.nom}
        CelluleOrage.objects.filter(pk=cellule.pk).update(
            doppler_rotation=rotation_retenue, doppler_grele=grele_retenue, doppler_divergence=divergence_retenue,
            doppler_polarimetrie=polar,
            doppler_radars=noms, doppler_heure=maintenant)
    return len(cellules)
