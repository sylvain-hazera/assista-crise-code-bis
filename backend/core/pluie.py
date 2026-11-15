"""Pluie prévue dans les heures qui viennent : images de la « prévision immédiate » de
Météo-France, copiées en base pour être posées sur la carte.

SOURCE
Modèle AROME-PI (prévision immédiate) du portail public de Météo-France, service WMS, même clé
que la vigilance (core/meteo_france.py), Licence Ouverte 2.0. Un calcul par heure, une échéance
toutes les 15 minutes jusqu'à 6 heures. La couche demandée est l'intensité des précipitations,
dans la palette des images radar.

CE QUE C'EST, ET CE QUE CE N'EST PAS
C'est une PRÉVISION à très courte échéance, recalée chaque heure sur les radars -- pas l'image
radar observée elle-même. Le radar brut n'est publié que dans des formats scientifiques (BUFR,
HDF5) que ce serveur ne lit pas. L'écran doit le dire : « pluie prévue », avec l'heure du
calcul, jamais « radar ».

Métropole seulement : la prévision immédiate ne couvre pas l'outre-mer.

MÊME RÈGLE QUE LE RESTE DE LA VEILLE
Seul le serveur appelle Météo-France, depuis la tâche planifiée, et toujours pour la France
entière : une image nationale par échéance, jamais une tuile à la demande. Déplacer la carte
ne déclenche donc aucun appel sortant, et rien ne dit à l'extérieur ce que quelqu'un regarde.

PROJECTION
Le service ne rend ses images qu'en latitude/longitude (EPSG:4326), où les lignes sont espacées
régulièrement en latitude. La carte, elle, est en Mercator : posée telle quelle, l'image serait
décalée d'une quarantaine de kilomètres au centre de la France. `vers_mercator` redistribue les
lignes ; c'est tout ce qu'il y a à faire, les colonnes sont déjà justes.
"""
import datetime
import io
import logging
import math
import time

import requests
from django.db import transaction
from django.utils import timezone

from . import meteo_france

logger = logging.getLogger(__name__)

URL_WMS = ("https://public-api.meteofrance.fr/public/aromepi/1.0/wms/"
           "MF-NWP-HIGHRES-AROMEPI-001-FRANCE-WMS/GetMap")
COUCHE = "TOTAL_PRECIPITATION_RATE__GROUND_OR_WATER_SURFACE"
STYLE = "RFLCTVT_MAX__GROUND__SHADING"
DELAI_REPONSE_S = 45

# Métropole et Corse, avec une marge sur la mer. (ouest, sud, est, nord) en degrés.
EMPRISE = (-5.5, 41.0, 10.0, 51.5)
# Un pixel par centième de degré : la maille du modèle (1,3 km).
LARGEUR, HAUTEUR = 1550, 1050

PAS = datetime.timedelta(minutes=15)
# De maintenant à + 3 heures : au-delà, la prévision immédiate ne vaut plus mieux qu'un bulletin.
NOMBRE_D_ECHEANCES = 13
# Un calcul paraît dans l'heure qui suit son heure de référence : on essaie le plus récent
# possible, puis on recule.
CALCULS_ESSAYES = 4
GARDER_APRES = datetime.timedelta(minutes=20)
# Souffle entre deux images : treize demandes d'affilée à chaque nouveau calcul, sur un service
# limité à 50 par minute et partagé avec nos autres relevés.
PAUSE_ENTRE_IMAGES_S = 1.5
# Nombre de teintes gardées à l'écriture (voir vers_mercator).
COULEURS = 64


def _instant_api(instant):
    return instant.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def echeances_voulues(maintenant):
    """Les quarts d'heure à afficher : celui en cours, puis les suivants sur trois heures."""
    depart = maintenant.replace(minute=maintenant.minute - maintenant.minute % 15, second=0, microsecond=0)
    return [depart + PAS * i for i in range(NOMBRE_D_ECHEANCES)]


def telecharger_image(calcul, echeance):
    """Image PNG de l'intensité de pluie prévue par `calcul` pour `echeance`, ou None si ce
    calcul ne la propose pas (pas encore paru, ou échéance hors de sa portée).

    Le service répond 200 avec un document XML d'erreur dans ces cas-là : c'est le type du
    contenu qui dit si l'on tient une image."""
    cle = meteo_france.lire_cle()
    if cle is None:
        raise meteo_france.CleAbsente()
    ouest, sud, est, nord = EMPRISE
    reponse = meteo_france.avec_reprise(lambda: requests.get(URL_WMS, headers={"apikey": cle}, timeout=DELAI_REPONSE_S, params={
        "service": "WMS", "version": "1.3.0", "layers": COUCHE, "styles": STYLE,
        "crs": "EPSG:4326",
        # WMS 1.3.0 en EPSG:4326 : la latitude d'abord.
        "bbox": f"{sud},{ouest},{nord},{est}",
        "width": LARGEUR, "height": HAUTEUR, "format": "image/png", "transparent": "true",
        "reference_time": _instant_api(calcul), "time": _instant_api(echeance),
    }))
    if reponse.status_code in (400, 404):
        return None
    reponse.raise_for_status()
    if not reponse.headers.get("content-type", "").startswith("image/png"):
        return None
    return reponse.content


def _mercator(latitude):
    return math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2))


def vers_mercator(png, sud=EMPRISE[1], nord=EMPRISE[3], ouest=EMPRISE[0], est=EMPRISE[2]):
    """Redistribue les lignes d'une image en latitude/longitude pour qu'elle se pose juste sur
    une carte Mercator entre les mêmes quatre coins. Rend un PNG.

    Pour chaque ligne de l'image de sortie (espacées régulièrement en ordonnée Mercator), on
    prend la ligne de l'image source qui se trouve à la même latitude. La hauteur de sortie est
    choisie pour que les pixels restent carrés à l'écran."""
    import numpy
    from PIL import Image

    source = numpy.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
    hauteur, largeur = source.shape[:2]
    haut, bas = _mercator(nord), _mercator(sud)
    hauteur_sortie = max(1, round((haut - bas) * largeur / math.radians(est - ouest)))

    ordonnees = haut - (numpy.arange(hauteur_sortie) + 0.5) * (haut - bas) / hauteur_sortie
    latitudes = numpy.degrees(2 * numpy.arctan(numpy.exp(ordonnees)) - math.pi / 2)
    lignes = numpy.clip(((nord - latitudes) / (nord - sud) * hauteur).astype(int), 0, hauteur - 1)

    # Palette réduite : l'image ne porte qu'une quinzaine de teintes, la décrire en couleurs
    # indexées la rend six fois plus légère -- treize images réécrites chaque heure, cela compte
    # pour la base et pour ses sauvegardes.
    image = Image.fromarray(source[lignes]).quantize(colors=COULEURS, method=Image.Quantize.FASTOCTREE)
    sortie = io.BytesIO()
    image.save(sortie, format="PNG", optimize=True)
    return sortie.getvalue()


def relever(maintenant=None):
    """Complète la copie : télécharge les échéances qui manquent pour le calcul le plus récent,
    retire celles qui sont passées. Rend le nombre d'images en base.

    Une échéance déjà copiée pour ce calcul n'est pas redemandée : le gros des appels n'a lieu
    qu'une fois par heure, quand un nouveau calcul paraît."""
    from .models import ImagePluie

    maintenant = maintenant or timezone.now()
    voulues = echeances_voulues(maintenant)
    heure = maintenant.replace(minute=0, second=0, microsecond=0)

    # Le calcul le plus récent qui sait rendre la première échéance voulue.
    calcul, premiere = None, None
    for recul in range(CALCULS_ESSAYES):
        candidat = heure - datetime.timedelta(hours=recul)
        premiere = telecharger_image(candidat, voulues[0])
        if premiere is not None:
            calcul = candidat
            break
    if calcul is None:
        raise ValueError("aucun calcul de prévision immédiate ne répond pour l'heure en cours")

    connues = {image.echeance: image.calcul for image in ImagePluie.objects.only("echeance", "calcul")}
    for echeance in voulues:
        if connues.get(echeance) == calcul:
            continue
        if echeance == voulues[0]:
            brute = premiere
        else:
            time.sleep(PAUSE_ENTRE_IMAGES_S)
            brute = telecharger_image(calcul, echeance)
        if brute is None:
            continue        # échéance au-delà de la portée de ce calcul : la précédente reste
        ImagePluie.objects.update_or_create(echeance=echeance, defaults={
            "calcul": calcul, "image": vers_mercator(brute), "releve_le": maintenant})

    with transaction.atomic():
        ImagePluie.objects.filter(echeance__lt=maintenant - GARDER_APRES).delete()
    return ImagePluie.objects.count()
