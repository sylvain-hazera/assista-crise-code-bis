"""Rafales de vent prévues dans les heures qui viennent : valeurs de la « prévision immédiate »
de Météo-France, peintes par ce serveur et copiées en base pour être posées sur la carte.

SOURCE
Modèle AROME-PI du portail public de Météo-France, même clé et même calcul horaire que la pluie
prévue (core/pluie.py), Licence Ouverte 2.0. Le champ demandé est la rafale la plus forte des
quinze minutes qui précèdent chaque échéance, à dix mètres du sol.

POURQUOI LES VALEURS ET NON L'IMAGE
Le service d'images (WMS) sait dessiner les rafales, mais dans une seule teinte, par paliers de
dix NŒUDS et sans légende accessible -- illisible pour qui raisonne en km/h. On demande donc au
service de valeurs (WCS) la grille brute en m/s, et c'est ce serveur qui la peint, en km/h, aux
seuils qui parlent à une cellule de crise (voir SEUILS_KMH). La comparaison des deux a été
faite le 15/11/2026 : la zone colorée de l'image WMS coïncide avec « 30 nœuds et plus » dans la
grille, ce qui a confirmé à la fois l'unité et le sens de lecture.

CE QUE C'EST, ET CE QUE CE N'EST PAS
Une PRÉVISION à trois heures, pas une mesure : les rafales mesurées sont celles des stations
(core/observations_meteo.py). Et pas une alerte : la vigilance « vent violent » reste celle de
Météo-France (core/meteo_france.py), qui tient compte de ce qu'un modèle seul ne voit pas.

Métropole seulement, comme la pluie prévue.

MÊME RÈGLE QUE LE RESTE DE LA VEILLE
Seul le serveur appelle Météo-France, depuis la tâche planifiée, pour la France entière.

POIDS
La grille arrive en nombres de 64 bits sans compression : 13 Mo par échéance, treize échéances
à chaque nouveau calcul, soit 170 Mo par heure. C'est le format que le service propose (l'autre
est le GRIB, que ce serveur ne lit pas). Rien de cela n'est gardé : seule l'image peinte l'est,
une trentaine de kilo-octets.
"""
import datetime
import io
import logging
import struct

import requests
from django.utils import timezone

from . import meteo_france, pluie

logger = logging.getLogger(__name__)

URL_WCS = ("https://public-api.meteofrance.fr/public/aromepi/1.0/wcs/"
           "MF-NWP-HIGHRES-AROMEPI-001-FRANCE-WCS/GetCoverage")
COUVERTURE = "WIND_SPEED_GUST_15MIN__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND"
# Le service range les échéances d'un même calcul en plusieurs séries ; celle-ci les porte
# toutes, de + 15 minutes à + 6 heures par quart d'heure.
SERIE = "PT15M"
HAUTEUR_M = 10
DELAI_REPONSE_S = 90

# Même emprise que la pluie. La grille porte un point tous les centièmes de degré, bornes
# comprises : un point de plus que la pluie dans chaque sens.
OUEST, SUD, EST, NORD = pluie.EMPRISE
PAS_DEGRES = 0.01
LARGEUR, HAUTEUR = 1551, 1051
# Chaque valeur vaut pour le carré centré sur son point : l'image déborde donc l'emprise d'un
# demi-pas de chaque côté.
EMPRISE_IMAGE = (OUEST - PAS_DEGRES / 2, SUD - PAS_DEGRES / 2, EST + PAS_DEGRES / 2, NORD + PAS_DEGRES / 2)

# Paliers peints, en km/h, et leur teinte (rouge, vert, bleu). En dessous du premier, rien n'est
# dessiné : le vent ordinaire ne doit pas couvrir la carte. 100 km/h est le seuil habituel de la
# vigilance orange dans l'intérieur des terres, 130 celui des tempêtes majeures -- les paliers
# de 20 l'encadrent sans prétendre le remplacer. Teintes du lilas au violet presque noir, pour
# ne pas se confondre avec la palette de la pluie (bleu, vert, jaune, rouge) quand les deux
# calques sont affichés ensemble.
SEUILS_KMH = (40, 60, 80, 100, 120, 140)
TEINTES = ((214, 198, 242), (171, 136, 228), (124, 70, 204), (196, 44, 158), (122, 14, 92), (38, 4, 40))
# Opacité de chaque palier (0 à 255). Le premier est laissé à demi transparent : par temps
# venteux il couvre la moitié du pays, et ne doit pas voiler la carte qu'il y a dessous.
OPACITES = (120, 235, 255, 255, 255, 255)
# Au-delà, la valeur n'est pas une rafale mais une case vide ou un défaut de lecture.
VITESSE_MAX_PLAUSIBLE_MS = 110

MS_EN_KMH = 3.6


def telecharger_couverture(couverture, calcul, echeance, serie="", hauteur_m=None):
    """Fichier TIFF d'un champ de la prévision immédiate (service de valeurs, WCS) pour le
    `calcul` et l'`echeance` donnés, sur l'emprise nationale, ou None si ce calcul ne le propose
    pas (pas encore paru, ou échéance hors de sa portée). Sert aux rafales et aux types de
    précipitation (core/precipitations_hiver.py).

    Le service annonce un type de contenu sans rapport avec ce qu'il envoie (« wmo-grib » pour
    un TIFF) : ce sont les premiers octets qui disent si l'on tient la grille."""
    cle = meteo_france.lire_cle()
    if cle is None:
        raise meteo_france.CleAbsente()
    identifiant = f"{couverture}___{calcul.astimezone(datetime.timezone.utc):%Y-%m-%dT%H.%M.%SZ}"
    if serie:
        identifiant += f"_{serie}"
    params = [
        ("service", "WCS"), ("version", "2.0.1"), ("coverageid", identifiant),
        ("subset", f"time({pluie._instant_api(echeance)})"),
        ("subset", f"lat({SUD},{NORD})"), ("subset", f"long({OUEST},{EST})"),
    ]
    if hauteur_m is not None:
        params.append(("subset", f"height({hauteur_m})"))
    params.append(("format", "image/tiff"))
    reponse = meteo_france.avec_reprise(lambda: requests.get(
        URL_WCS, headers={"apikey": cle}, timeout=DELAI_REPONSE_S, params=params))
    if reponse.status_code in (400, 404):
        return None
    reponse.raise_for_status()
    if reponse.content[:4] not in (b"II*\x00", b"MM\x00*"):
        return None
    return reponse.content


def telecharger_grille(calcul, echeance):
    """Fichier TIFF des rafales prévues par `calcul` pour `echeance` (voir `telecharger_couverture`)."""
    return telecharger_couverture(COUVERTURE, calcul, echeance, serie=SERIE, hauteur_m=HAUTEUR_M)


# Étiquettes TIFF lues, et rien d'autre : largeur, hauteur, bits par valeur, compression,
# position et taille des bandes, nature des valeurs, pas et point d'ancrage géographiques.
_LARGEUR, _HAUTEUR, _BITS, _COMPRESSION, _POSITIONS, _TAILLES, _NATURE = 256, 257, 258, 259, 273, 279, 339
_PAS, _ANCRAGE = 33550, 33922
_FORMATS = {1: "B", 3: "H", 4: "I", 12: "d"}
_NOMBRE_A_VIRGULE = 3


def lire_tiff(octets):
    """Grille de vitesses (m/s) d'un fichier TIFF tel que le service le rend : des nombres à
    virgule de 32 ou 64 bits, sans compression, rangés ligne par ligne du nord au sud.

    Lecteur volontairement étroit : la bibliothèque d'images du serveur ne lit pas les TIFF de
    nombres à virgule de 64 bits, et en installer une autre pour un seul format ne se justifie
    pas. Tout ce qui sort de ce cas -- compression, grille d'une autre taille ou posée ailleurs
    -- lève ValueError plutôt que de peindre une carte fausse."""
    import numpy

    if octets[:4] == b"II*\x00":
        ordre = "<"
    elif octets[:4] == b"MM\x00*":
        ordre = ">"
    else:
        raise ValueError("ce n'est pas un fichier TIFF")
    try:
        debut, = struct.unpack(ordre + "I", octets[4:8])
        nombre, = struct.unpack(ordre + "H", octets[debut:debut + 2])
        etiquettes = {}
        for rang in range(nombre):
            entree = octets[debut + 2 + 12 * rang:debut + 14 + 12 * rang]
            numero, genre, combien = struct.unpack(ordre + "HHI", entree[:8])
            code = _FORMATS.get(genre)
            if code is None:
                continue
            taille = struct.calcsize(ordre + code) * combien
            brut = entree[8:12]
            if taille > 4:
                position, = struct.unpack(ordre + "I", brut)
                brut = octets[position:position + taille]
            etiquettes[numero] = struct.unpack(ordre + code * combien, brut[:taille])

        largeur, hauteur = etiquettes[_LARGEUR][0], etiquettes[_HAUTEUR][0]
        bits, positions, tailles = etiquettes[_BITS][0], etiquettes[_POSITIONS], etiquettes[_TAILLES]
        if etiquettes.get(_COMPRESSION, (1,))[0] != 1:
            raise ValueError("TIFF compressé : format non prévu")
        if etiquettes.get(_NATURE, (0,))[0] != _NOMBRE_A_VIRGULE or bits not in (32, 64):
            raise ValueError("TIFF sans nombres à virgule : format non prévu")
        if (largeur, hauteur) != (LARGEUR, HAUTEUR):
            raise ValueError(f"grille de {largeur} x {hauteur} points, {LARGEUR} x {HAUTEUR} attendus")
        pas, ancrage = etiquettes[_PAS], etiquettes[_ANCRAGE]
        if (abs(pas[0] - PAS_DEGRES) > 1e-6 or abs(pas[1] - PAS_DEGRES) > 1e-6
                or abs(ancrage[3] - OUEST) > 1e-6 or abs(ancrage[4] - NORD) > 1e-6):
            raise ValueError("grille posée ailleurs que sur l'emprise demandée")
        # Les bandes doivent se suivre sans trou pour être lues d'un seul tenant.
        if any(positions[i] + tailles[i] != positions[i + 1] for i in range(len(positions) - 1)):
            raise ValueError("TIFF en bandes dispersées : format non prévu")
        valeurs = numpy.frombuffer(octets, dtype=f"{ordre}f{bits // 8}", count=largeur * hauteur,
                                   offset=positions[0])
    except (KeyError, IndexError, struct.error) as exc:
        raise ValueError(f"TIFF illisible ({type(exc).__name__})") from exc
    return valeurs.reshape(hauteur, largeur)


def peindre_rangs(rangs, teintes, opacites):
    """Image PNG, en projection Mercator, d'une grille de rangs de palette (0 : rien à
    dessiner ; n : la n-ième teinte). Commun aux rafales et aux types de précipitation."""
    from PIL import Image

    hauteur, largeur = rangs.shape
    ouest, sud, est, nord = EMPRISE_IMAGE
    rangs = rangs[pluie.lignes_mercator(hauteur, largeur, sud, nord, ouest, est)]
    image = Image.fromarray(rangs)        # niveaux de gris, que la palette change en couleurs
    image.putpalette([0, 0, 0] + [composante for teinte in teintes for composante in teinte])
    sortie = io.BytesIO()
    # Rang 0 de la palette : entièrement transparent.
    image.save(sortie, format="PNG", optimize=True, transparency=bytes((0,) + tuple(opacites)))
    return sortie.getvalue()


def rang_au_point(png, latitude, longitude):
    """Rang de palette peint à un endroit d'une image rendue par `peindre_rangs`, ou None hors
    de l'image."""
    from PIL import Image

    ouest, sud, est, nord = EMPRISE_IMAGE
    if not (ouest <= longitude <= est and sud <= latitude <= nord):
        return None
    image = Image.open(io.BytesIO(png))
    haut, bas = pluie._mercator(nord), pluie._mercator(sud)
    colonne = min(image.width - 1, int((longitude - ouest) / (est - ouest) * image.width))
    ligne = min(image.height - 1, int((haut - pluie._mercator(latitude)) / (haut - bas) * image.height))
    return image.getpixel((colonne, ligne))


def peindre(grille):
    """Image PNG, en projection Mercator, d'une grille de rafales en m/s : une teinte par
    palier de SEUILS_KMH, transparent en dessous du premier et là où la valeur manque."""
    import numpy

    plausible = numpy.isfinite(grille) & (grille >= 0) & (grille <= VITESSE_MAX_PLAUSIBLE_MS)
    kmh = numpy.where(plausible, grille, 0) * MS_EN_KMH
    # 0 : rien à dessiner ; 1 à 6 : le palier atteint.
    return peindre_rangs(numpy.digitize(kmh, SEUILS_KMH).astype(numpy.uint8), TEINTES, OPACITES)


def preparer(octets):
    return peindre(lire_tiff(octets))


def palier_au_point(png, latitude, longitude):
    """Palier de rafale peint à un endroit d'une image rendue par `peindre` : le seuil bas en
    km/h (40, 60…), 0 en dessous du premier palier, None hors de l'image."""
    rang = rang_au_point(png, latitude, longitude)
    if rang is None:
        return None
    return SEUILS_KMH[rang - 1] if rang else 0


def legende():
    """Les paliers et leur teinte, pour que l'écran dessine la même légende que l'image."""
    return [{"a_partir_de_kmh": seuil, "couleur": "#%02x%02x%02x" % teinte}
            for seuil, teinte in zip(SEUILS_KMH, TEINTES)]


def relever(maintenant=None):
    """Complète la copie des images de rafales prévues (voir `pluie.completer_serie`)."""
    from .models import ImageRafales

    return pluie.completer_serie(ImageRafales, telecharger_grille, preparer,
                                 maintenant or timezone.now(), "Rafales")
