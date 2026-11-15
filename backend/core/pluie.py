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


def lignes_mercator(hauteur, largeur, sud=EMPRISE[1], nord=EMPRISE[3], ouest=EMPRISE[0], est=EMPRISE[2]):
    """Pour une grille en latitude/longitude de `hauteur` lignes sur `largeur` colonnes, rend
    pour chaque ligne de l'image Mercator de sortie le rang de la ligne source à prendre.

    Les lignes de sortie sont espacées régulièrement en ordonnée Mercator ; pour chacune on
    prend la ligne source qui se trouve à la même latitude. La hauteur de sortie est choisie
    pour que les pixels restent carrés à l'écran. Sert à la pluie comme aux rafales
    (core/rafales.py)."""
    import numpy

    haut, bas = _mercator(nord), _mercator(sud)
    hauteur_sortie = max(1, round((haut - bas) * largeur / math.radians(est - ouest)))
    ordonnees = haut - (numpy.arange(hauteur_sortie) + 0.5) * (haut - bas) / hauteur_sortie
    latitudes = numpy.degrees(2 * numpy.arctan(numpy.exp(ordonnees)) - math.pi / 2)
    return numpy.clip(((nord - latitudes) / (nord - sud) * hauteur).astype(int), 0, hauteur - 1)


def vers_mercator(png, sud=EMPRISE[1], nord=EMPRISE[3], ouest=EMPRISE[0], est=EMPRISE[2]):
    """Redistribue les lignes d'une image en latitude/longitude pour qu'elle se pose juste sur
    une carte Mercator entre les mêmes quatre coins (voir `lignes_mercator`). Rend un PNG."""
    import numpy
    from PIL import Image

    source = numpy.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
    hauteur, largeur = source.shape[:2]
    lignes = lignes_mercator(hauteur, largeur, sud, nord, ouest, est)

    # Palette réduite : l'image ne porte qu'une quinzaine de teintes, la décrire en couleurs
    # indexées la rend six fois plus légère -- treize images réécrites chaque heure, cela compte
    # pour la base et pour ses sauvegardes.
    image = Image.fromarray(source[lignes]).quantize(colors=COULEURS, method=Image.Quantize.FASTOCTREE)
    sortie = io.BytesIO()
    image.save(sortie, format="PNG", optimize=True)
    return sortie.getvalue()


def completer_serie(modele, telecharger, preparer, maintenant, nom):
    """Complète une série d'images par échéance (pluie ou rafales) : télécharge les échéances
    qui manquent pour le calcul le plus récent, retire celles qui sont passées. Rend le nombre
    d'images en base.

    `telecharger(calcul, echeance)` rend le contenu brut ou None si ce calcul ne propose pas
    cette échéance ; `preparer(brut)` en fait le PNG à poser sur la carte.

    Une échéance déjà copiée pour ce calcul n'est pas redemandée : le gros des appels n'a lieu
    qu'une fois par heure, quand un nouveau calcul paraît. Entre-temps un passage ne demande que
    le quart d'heure nouveau -- et rien du tout s'il n'y en a pas, hormis la question « le calcul
    de cette heure est-il paru ? ». Cela compte pour les rafales, dont chaque réponse pèse 13 Mo.

    Lève ValueError si aucun calcul ne répond, ou si des échéances manquaient et qu'AUCUNE n'a
    pu être copiée : le relevé est alors compté en échec, et la source finit signalée périmée.
    Une panne isolée parmi d'autres images réussies n'est qu'un avertissement."""
    voulues = echeances_voulues(maintenant)
    heure = maintenant.replace(minute=0, second=0, microsecond=0)
    connues = {image.echeance: image.calcul for image in modele.objects.only("echeance", "calcul")}

    # Le calcul le plus récent qui sait rendre la première échéance voulue.
    calcul, premiere = None, None
    for recul in range(CALCULS_ESSAYES):
        candidat = heure - datetime.timedelta(hours=recul)
        if connues.get(voulues[0]) == candidat:
            # Déjà copiée depuis ce calcul, et aucun plus récent n'a répondu : c'est toujours
            # lui, inutile de la redemander pour s'en assurer.
            calcul = candidat
            break
        premiere = telecharger(candidat, voulues[0])
        if premiere is not None:
            calcul = candidat
            break
    if calcul is None:
        raise ValueError("aucun calcul de prévision immédiate ne répond pour l'heure en cours")

    manquantes = [echeance for echeance in voulues if connues.get(echeance) != calcul]
    copiees = 0
    for echeance in manquantes:
        if echeance == voulues[0] and premiere is not None:
            brute = premiere
        else:
            time.sleep(PAUSE_ENTRE_IMAGES_S)
            try:
                brute = telecharger(calcul, echeance)
            except requests.RequestException as exc:
                # Une image en panne ne fait pas perdre les autres : celles déjà copiées
                # restent, et celle-ci sera redemandée au passage suivant (elle n'est pas
                # « connue » pour ce calcul). Constaté en service le 15/11/2026 : un refus de
                # connexion sur la quatrième image faisait échouer le relevé entier.
                logger.warning("%s : image de %s non relevée (%s).", nom, _instant_api(echeance), type(exc).__name__)
                continue
        if brute is None:
            continue        # échéance au-delà de la portée de ce calcul : la précédente reste
        modele.objects.update_or_create(echeance=echeance, defaults={
            "calcul": calcul, "image": preparer(brute), "releve_le": maintenant})
        copiees += 1

    with transaction.atomic():
        modele.objects.filter(echeance__lt=maintenant - GARDER_APRES).delete()
    if manquantes and not copiees:
        raise ValueError(f"aucune des {len(manquantes)} échéances manquantes n'a pu être relevée")
    return modele.objects.count()


def relever(maintenant=None):
    """Complète la copie des images de pluie prévue (voir `completer_serie`)."""
    from .models import ImagePluie

    return completer_serie(ImagePluie, telecharger_image, vers_mercator, maintenant or timezone.now(), "Pluie")
