"""Séismes récents en France : relevé du catalogue national, copie en base ; et, pour les
volcans français, la sismicité qui les entoure.

SOURCE
Le catalogue du BCSF-Rénass (EOST, Strasbourg), https://api.franceseisme.fr, au format FDSN,
Licence Ouverte. Il rassemble l'hexagone et l'outre-mer : les séismes des Antilles, de La
Réunion et de Mayotte y viennent des observatoires volcanologiques de l'IPGP. Aucune clé.

C'est la même source que l'ALERTE sismique existante (verifier_alertes_sismiques, qui la
recoupe avec le catalogue européen EMSC et prévient par radio) : ce module-ci ne prévient
personne, il donne à VOIR les trente derniers jours sur la carte et dans la veille.

CE QUE LE CATALOGUE CONTIENT AUSSI
Des tirs de carrière (un événement sur cinq), des explosions, des glissements de terrain : le
réseau enregistre tout ce qui secoue. Ils sont gardés avec leur nature, et l'écran les
distingue -- les masquer ferait croire à une carte plus calme qu'elle ne l'est, les mêler aux
séismes ferait croire à une sismicité qu'il n'y a pas. Les grands séismes lointains (« Monde »)
ne sont pas copiés.

LES VOLCANS
Il n'existe pas de donnée ouverte sur l'état des volcans français : les observatoires publient
des bulletins en PDF, et le niveau d'alerte est fixé par le préfet. Ce qui est ouvert, et
mesuré, c'est la sismicité sous l'édifice -- le premier signe d'une reprise d'activité.
`activite_volcans` la compte, sans rien en conclure : l'écran renvoie vers l'observatoire.
"""
import datetime
import logging
import math
import re

import requests
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL = "https://api.franceseisme.fr/fdsnws/event/1/query"
DELAI_REPONSE_S = 60
PROFONDEUR = datetime.timedelta(days=30)
MAXIMUM = 8000
MINIMUM_PLAUSIBLE = 50

NATURES = {
    "earthquake": "Séisme",
    "quarry blast": "Tir de carrière",
    "explosion": "Explosion",
    "landslide": "Glissement de terrain",
    "induced or triggered event": "Séisme induit",
}
_ZONE = re.compile(r"\(([^)]*)\)\s*$")
_LIEU = re.compile(r"near (.+?)\s*\(")

# Volcans français actifs ou surveillés, avec l'observatoire de l'IPGP qui en a la charge.
VOLCANS = (
    {"code": "FOURNAISE", "nom": "Piton de la Fournaise", "territoire": "La Réunion",
     "latitude": -21.244, "longitude": 55.708,
     "observatoire": "Observatoire volcanologique du Piton de la Fournaise (OVPF-IPGP)",
     "url": "https://www.ipgp.fr/observation/ovs/ovpf/"},
    {"code": "SOUFRIERE", "nom": "La Soufrière", "territoire": "Guadeloupe",
     "latitude": 16.044, "longitude": -61.664,
     "observatoire": "Observatoire volcanologique et sismologique de Guadeloupe (OVSG-IPGP)",
     "url": "https://www.ipgp.fr/observation/ovs/ovsg/"},
    {"code": "PELEE", "nom": "Montagne Pelée", "territoire": "Martinique",
     "latitude": 14.809, "longitude": -61.165,
     "observatoire": "Observatoire volcanologique et sismologique de Martinique (OVSM-IPGP)",
     "url": "https://www.ipgp.fr/observation/ovs/ovsm/"},
    {"code": "FANI_MAORE", "nom": "Fani Maoré (volcan sous-marin)", "territoire": "Mayotte",
     "latitude": -12.92, "longitude": 45.71,
     "observatoire": "Réseau de surveillance volcanologique et sismologique de Mayotte (REVOSIMA)",
     "url": "https://www.ipgp.fr/actualites-du-revosima/"},
)
RAYON_VOLCAN_KM = 15
# Au-delà, un volcan ne concerne plus le territoire regardé : le bloc ne s'affiche pas.
PORTEE_VOLCAN_KM = 250


def telecharger(maintenant=None):
    depuis = ((maintenant or timezone.now()) - PROFONDEUR).astimezone(datetime.timezone.utc)
    reponse = requests.get(URL, timeout=DELAI_REPONSE_S, params={
        "format": "text", "limit": MAXIMUM, "orderby": "time",
        "starttime": depuis.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    reponse.raise_for_status()
    return reponse.text


def analyser(texte):
    """Catalogue au format texte FDSN -> dictionnaires prêts pour Seisme. Une ligne mal formée
    est ignorée ; les événements lointains (« Monde ») ne sont pas gardés."""
    evenements = []
    for ligne in texte.splitlines():
        if not ligne.strip() or ligne.startswith("#"):
            continue
        champs = ligne.split("|")
        if len(champs) < 13:
            continue
        description = champs[12].strip()
        zone = (_ZONE.search(description) or [None, ""])[1]
        if zone == "Monde":
            continue
        try:
            instant = parse_datetime(champs[1])
            position = Point(float(champs[3]), float(champs[2]), srid=4326)
            magnitude = float(champs[10])
        except (ValueError, TypeError):
            continue
        if instant is None:
            continue
        try:
            profondeur = round(float(champs[4]), 1)
        except ValueError:
            profondeur = None
        nature = champs[13].strip() if len(champs) > 13 else ""
        lieu = (_LIEU.search(description) or [None, ""])[1]
        evenements.append({
            "reference": champs[0].strip()[:40],
            "date": instant,
            "location": position,
            "magnitude": round(magnitude, 1),
            "profondeur_km": profondeur,
            "lieu": lieu[:160],
            "zone": zone[:60],
            "nature": (nature or "earthquake")[:40],
        })
    return evenements


def enregistrer(evenements, maintenant=None):
    """Remplace la copie des trente derniers jours."""
    from .models import Seisme

    if len(evenements) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(evenements)} événements seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    lignes = [Seisme(releve_le=maintenant, **evenement) for evenement in evenements]
    champs = [champ for champ in evenements[0] if champ != "reference"] + ["releve_le"]
    with transaction.atomic():
        Seisme.objects.bulk_create(lignes, batch_size=1000, update_conflicts=True,
                                   unique_fields=["reference"], update_fields=champs)
        Seisme.objects.exclude(reference__in=[l.reference for l in lignes]).delete()
    return len(lignes)


def relever(maintenant=None):
    return enregistrer(analyser(telecharger(maintenant)), maintenant)


def distance_km(latitude1, longitude1, latitude2, longitude2):
    phi1, phi2 = math.radians(latitude1), math.radians(latitude2)
    a = (math.sin((phi2 - phi1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(longitude2 - longitude1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def activite_volcans(maintenant=None):
    """Pour chaque volcan : le nombre de séismes à moins de RAYON_VOLCAN_KM sur les sept
    derniers jours et sur les sept précédents, et la plus forte magnitude de la semaine."""
    from django.contrib.gis.geos import Polygon

    from .models import Seisme

    maintenant = maintenant or timezone.now()
    semaine = maintenant - datetime.timedelta(days=7)
    quinzaine = maintenant - datetime.timedelta(days=14)
    resultats = []
    for volcan in VOLCANS:
        ecart_lat = RAYON_VOLCAN_KM / 111.0
        ecart_lon = RAYON_VOLCAN_KM / (111.0 * math.cos(math.radians(volcan["latitude"])))
        emprise = Polygon.from_bbox((volcan["longitude"] - ecart_lon, volcan["latitude"] - ecart_lat,
                                     volcan["longitude"] + ecart_lon, volcan["latitude"] + ecart_lat))
        proches = [s for s in Seisme.objects.filter(location__within=emprise, date__gte=quinzaine,
                                                    nature="earthquake")
                   if distance_km(volcan["latitude"], volcan["longitude"], s.location.y, s.location.x) <= RAYON_VOLCAN_KM]
        recents = [s for s in proches if s.date >= semaine]
        resultats.append({
            **volcan,
            "seismes_7_jours": len(recents),
            "seismes_7_jours_precedents": len(proches) - len(recents),
            "magnitude_max": max((s.magnitude for s in recents), default=None),
            "dernier_seisme": max((s.date for s in recents), default=None),
        })
    return resultats
