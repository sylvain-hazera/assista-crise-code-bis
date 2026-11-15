"""Radioactivité ambiante : relevé des balises du réseau Téléray, copie en base.

SOURCE
Téléray, le réseau national de télémesure de la radioactivité de l'air ambiant, exploité par
l'ASNR (Autorité de sûreté nucléaire et de radioprotection) : https://teleray.asnr.fr. Environ
480 balises, dont les deux tiers autour des installations nucléaires, une mesure toutes les dix
minutes. Chaque mesure donne le débit de dose gamma ambiant en nanosieverts par heure, et le
« bruit de fond » habituel de la balise -- ce qui permet de voir un écart sans connaître la
géologie du lieu.

⚠ CE SERVICE N'EST PAS UNE API PUBLIÉE (15/11/2026)
C'est le service que le site teleray.asnr.fr interroge lui-même, lisible sans
authentification. Il n'a ni documentation ni conditions d'utilisation, et l'ASNR peut le
modifier sans prévenir. Décision de Sylvain du 15/11/2026 : l'intégrer, ces données étant
celles d'une autorité publique déjà affichées à tous. Conséquences pour ce module :
- un appel national toutes les dix minutes, pas davantage : c'est le rythme des mesures ;
- aucune hypothèse au-delà des champs constatés ; une réponse à la forme inattendue fait
  échouer le relevé proprement (la supervision le signale) au lieu d'écrire n'importe quoi ;
- aucun jeton n'est utilisé : le site en distribue un pour d'autres services, il ne nous est
  pas destiné et ce module n'y touche pas.

PAS D'ALERTE SUR CES VALEURS
Une forte pluie fait monter la mesure pendant une heure ou deux (elle rabat au sol des
descendants naturels du radon) sans qu'il y ait le moindre incident ; une balise en panne ou en
étalonnage aussi. La plateforme européenne EURDEP le dit elle-même : une valeur élevée, même
sur plusieurs balises voisines, ne prouve rien à elle seule. Ce module AFFICHE ; il n'annonce
rien. L'alerte radiologique est l'affaire de l'ASNR et du préfet.

Même règle que le reste de la veille : seul le serveur appelle, pour la France entière.
"""
import datetime
import logging

import requests
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL = "https://teleray.asnr.fr/api/measures"
DELAI_REPONSE_S = 45
# Les balises mesurent toutes les dix minutes, mais le service ne reçoit leurs mesures que par
# paquets, avec jusqu'à trois quarts d'heure de retard : sur les vingt-cinq dernières minutes
# il ne rend que quelques balises, sur la dernière heure presque toutes (constaté le
# 15/11/2026). On demande donc soixante-quinze minutes, triées de la plus récente à la plus
# ancienne -- sans ce tri, le plafond couperait justement les plus récentes --, et on garde la
# dernière mesure de chaque balise.
FENETRE = datetime.timedelta(minutes=75)
MAXIMUM = 4000
# Les balises posées dans des ambassades n'apprennent rien à une commune française.
STRATEGIES_IGNOREES = {"AMBASSADE", "INTERNATIONAL"}
MINIMUM_PLAUSIBLE = 100
# Une balise muette depuis une semaine est retirée de la copie.
OUBLI_APRES = datetime.timedelta(days=7)


def telecharger(maintenant=None):
    depuis = ((maintenant or timezone.now()) - FENETRE).astimezone(datetime.timezone.utc)
    reponse = requests.get(URL, timeout=DELAI_REPONSE_S, params={
        "$limit": MAXIMUM, "$sort[time]": -1,
        "time[$gte]": depuis.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    })
    reponse.raise_for_status()
    donnees = reponse.json()
    if not isinstance(donnees, dict) or not isinstance(donnees.get("features"), list):
        raise ValueError("réponse Téléray sans liste de mesures")
    return donnees


def _nombre(valeur):
    return float(valeur) if isinstance(valeur, (int, float)) and not isinstance(valeur, bool) else None


def analyser(donnees):
    """Réponse du service -> {identifiant de balise: dictionnaire prêt pour
    MesureRadioactivite}, la mesure la plus récente de chaque balise."""
    mesures = {}
    for element in donnees.get("features") or []:
        proprietes = element.get("properties") or {}
        if proprietes.get("strategie") in STRATEGIES_IGNOREES:
            continue
        instant = parse_datetime(str(element.get("time") or proprietes.get("measurementDate") or ""))
        debit = _nombre(proprietes.get("doseRateRaw"))
        try:
            identifiant = int(proprietes["irsnId"])
            longitude, latitude = (element.get("geometry") or {})["coordinates"][:2]
            position = Point(float(longitude), float(latitude), srid=4326)
        except (KeyError, TypeError, ValueError):
            continue
        if instant is None or debit is None:
            continue
        connue = mesures.get(identifiant)
        if connue is not None and connue["mesure_le"] >= instant:
            continue
        mesures[identifiant] = {
            "station": identifiant,
            "nom": str(proprietes.get("publicName") or proprietes.get("name") or "").strip()[:120],
            "location": position,
            "proche_installation": proprietes.get("strategie") == "INB",
            "debit_nsv_h": round(debit, 1),
            "bruit_de_fond_nsv_h": (lambda b: None if b is None else round(b, 1))(_nombre(proprietes.get("bruitdefond"))),
            "valide": proprietes.get("validation") == "valide",
            "mesure_le": instant,
        }
    return mesures


def enregistrer(mesures, maintenant=None):
    from .models import MesureRadioactivite

    if len(mesures) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(mesures)} balises seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    lignes = [MesureRadioactivite(releve_le=maintenant, **mesure) for mesure in mesures.values()]
    with transaction.atomic():
        MesureRadioactivite.objects.bulk_create(
            lignes, update_conflicts=True, unique_fields=["station"],
            update_fields=["nom", "location", "proche_installation", "debit_nsv_h",
                           "bruit_de_fond_nsv_h", "valide", "mesure_le", "releve_le"])
        MesureRadioactivite.objects.filter(mesure_le__lt=maintenant - OUBLI_APRES).delete()
    return len(lignes)


def relever(maintenant=None):
    return enregistrer(analyser(telecharger(maintenant)), maintenant)
