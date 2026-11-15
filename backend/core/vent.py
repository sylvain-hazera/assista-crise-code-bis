"""Champ de vent à dix mètres, pour l'animation de la carte : relevé du modèle ARPEGE de
Météo-France, copie en base sous une forme compacte.

SOURCE
Modèle ARPEGE, grille Europe à un dixième de degré, service de valeurs (WCS) du portail public de
Météo-France, même clé que la vigilance, Licence Ouverte 2.0. Quatre calculs par jour (0 h, 6 h,
12 h, 18 h TU), une échéance par heure. Deux champs par échéance : la composante du vent vers
l'est (u) et vers le nord (v), en m/s.

POURQUOI CE MODÈLE ET PAS LA PRÉVISION IMMÉDIATE
Les rafales viennent de la prévision immédiate (1,3 km, 13 Mo par grille). Pour dessiner un
ÉCOULEMENT -- des particules portées par le vent -- cette finesse ne sert à rien et coûterait
340 Mo par heure. ARPEGE à 10 km pèse 300 Ko par échéance et montre ce qu'il faut : d'où vient
le vent, où il tourne, où il force.

CE QUE C'EST, ET CE QUE CE N'EST PAS
Le vent MOYEN prévu, lissé à dix kilomètres : ni les rafales (calque « Rafales prévues »), ni
les effets de relief, ni une mesure (calque « Stations météo »). Une image d'ensemble.

FORME GARDÉE
Un octet par composante et par point : -40 à +40 m/s sur 255 pas, soit 0,3 m/s de finesse --
bien assez pour une animation. 26 000 points, 53 Ko par échéance.

Même règle que le reste de la veille : seul le serveur appelle, pour toute l'emprise, depuis la
tâche planifiée.
"""
import datetime
import logging
import time

import requests
from django.db import transaction
from django.utils import timezone

from . import meteo_france, pluie, rafales

logger = logging.getLogger(__name__)

URL_WCS = ("https://public-api.meteofrance.fr/public/arpege/1.0/wcs/"
           "MF-NWP-GLOBAL-ARPEGE-01-EUROPE-WCS/GetCoverage")
COMPOSANTES = ("U_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND",
               "V_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND")
HAUTEUR_M = 10
DELAI_REPONSE_S = 45
PAUSE_ENTRE_GRILLES_S = 0.5

# Métropole et Corse avec une large marge : l'écoulement se lit mieux quand on voit d'où il vient.
# (ouest, sud, est, nord) en degrés.
EMPRISE = (-10.0, 39.0, 13.0, 53.0)
PAS_DEGRES = 0.1

# De l'heure en cours à + 6 heures.
NOMBRE_D_ECHEANCES = 7
# Un calcul paraît trois à quatre heures après son heure : on essaie les quatre derniers.
ECART_ENTRE_CALCULS = datetime.timedelta(hours=6)
CALCULS_ESSAYES = 4
GARDER_APRES = datetime.timedelta(minutes=70)

VITESSE_MAX_MS = 40.0


def echeances_voulues(maintenant):
    heure = maintenant.replace(minute=0, second=0, microsecond=0)
    return [heure + datetime.timedelta(hours=rang) for rang in range(NOMBRE_D_ECHEANCES)]


def calculs_candidats(maintenant):
    """Heures des derniers calculs possibles, du plus récent au plus ancien."""
    heure = maintenant.astimezone(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    dernier = heure.replace(hour=heure.hour - heure.hour % 6)
    return [dernier - ECART_ENTRE_CALCULS * rang for rang in range(CALCULS_ESSAYES)]


def telecharger_composante(couverture, calcul, echeance):
    """Fichier TIFF d'une composante du vent, ou None si ce calcul ne la propose pas."""
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
            ("subset", f"height({HAUTEUR_M})"), ("format", "image/tiff"),
        ]))
    if reponse.status_code in (400, 404):
        return None
    reponse.raise_for_status()
    if reponse.content[:4] not in (b"II*\x00", b"MM\x00*"):
        return None
    return reponse.content


def coder(u, v):
    """Deux grilles en m/s -> octets : toute la composante u (ligne par ligne, du nord au sud),
    puis toute la composante v. Un octet par valeur ; 0 vaut -40 m/s, 255 vaut +40, et une
    valeur absente vaut le calme (voir `decoder`)."""
    import numpy

    def octets(grille):
        propre = numpy.where(numpy.isfinite(grille), grille, 0.0)
        borne = numpy.clip(propre, -VITESSE_MAX_MS, VITESSE_MAX_MS)
        return numpy.round((borne + VITESSE_MAX_MS) / (2 * VITESSE_MAX_MS) * 255).astype(numpy.uint8).tobytes()

    return octets(u) + octets(v)


def decoder(donnees, largeur, hauteur):
    """L'inverse de `coder` : (u, v) en m/s. Sert aux tests et à la lecture en un point."""
    import numpy

    valeurs = numpy.frombuffer(donnees, dtype=numpy.uint8).astype(float) / 255 * 2 * VITESSE_MAX_MS - VITESSE_MAX_MS
    taille = largeur * hauteur
    return valeurs[:taille].reshape(hauteur, largeur), valeurs[taille:].reshape(hauteur, largeur)


def _relever_une_echeance(calcul, echeance):
    """(largeur, hauteur, ouest, nord, octets) du champ d'une échéance, ou None si ce calcul ne
    la propose pas."""
    grilles = []
    for couverture in COMPOSANTES:
        time.sleep(PAUSE_ENTRE_GRILLES_S)
        contenu = telecharger_composante(couverture, calcul, echeance)
        if contenu is None:
            return None
        grille, ouest, nord, pas = rafales.lire_grille_tiff(contenu)
        if abs(pas - PAS_DEGRES) > 1e-6:
            raise ValueError(f"grille au pas de {pas}°, {PAS_DEGRES}° attendu")
        grilles.append((grille, ouest, nord))
    (u, ouest, nord), (v, ouest_v, nord_v) = grilles
    if u.shape != v.shape or abs(ouest - ouest_v) > 1e-6 or abs(nord - nord_v) > 1e-6:
        raise ValueError("les deux composantes du vent ne sont pas sur la même grille")
    hauteur, largeur = u.shape
    return largeur, hauteur, ouest, nord, coder(u, v)


def relever(maintenant=None):
    """Complète la copie : les échéances qui manquent pour le calcul le plus récent, moins
    celles qui sont passées. Rend le nombre d'échéances en base."""
    from .models import ChampVent

    maintenant = maintenant or timezone.now()
    voulues = echeances_voulues(maintenant)
    connues = {champ.echeance: champ.calcul for champ in ChampVent.objects.only("echeance", "calcul")}

    # Le calcul le plus récent qui sait rendre la première échéance voulue.
    calcul, premier = None, None
    for candidat in calculs_candidats(maintenant):
        if connues.get(voulues[0]) == candidat:
            calcul = candidat
            break
        premier = _relever_une_echeance(candidat, voulues[0])
        if premier is not None:
            calcul = candidat
            break
    if calcul is None:
        raise ValueError("aucun calcul du modèle ARPEGE ne répond pour l'heure en cours")

    manquantes = [echeance for echeance in voulues if connues.get(echeance) != calcul]
    copiees = 0
    for echeance in manquantes:
        if echeance == voulues[0] and premier is not None:
            champ = premier
        else:
            try:
                champ = _relever_une_echeance(calcul, echeance)
            except requests.RequestException as exc:
                logger.warning("Vent : échéance de %s non relevée (%s).", pluie._instant_api(echeance), type(exc).__name__)
                continue
        if champ is None:
            continue
        largeur, hauteur, ouest, nord, donnees = champ
        ChampVent.objects.update_or_create(echeance=echeance, defaults={
            "calcul": calcul, "largeur": largeur, "hauteur": hauteur, "ouest": ouest, "nord": nord,
            "donnees": donnees, "releve_le": maintenant})
        copiees += 1

    with transaction.atomic():
        ChampVent.objects.filter(echeance__lt=maintenant - GARDER_APRES).delete()
    if manquantes and not copiees:
        raise ValueError(f"aucune des {len(manquantes)} échéances manquantes n'a pu être relevée")
    return ChampVent.objects.count()
