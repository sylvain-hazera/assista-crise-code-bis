"""Événements routiers du réseau national : relevé du flux Bison Futé, copie en base.

SOURCE
« Bison Futé ouvert » (https://tipi.bison-fute.gouv.fr/bison-fute-ouvert/), publication
événementielle des directions interdépartementales des routes, Licence Ouverte 2.0. Aucune clé.
Le flux couvre le réseau routier NATIONAL non concédé (routes nationales, autoroutes de
l'État), plus quelques routes départementales que les directions des routes signalent quand
elles touchent leur réseau (cols fermés, déviations). Il ne couvre ni les autoroutes concédées,
ni l'essentiel des routes départementales, ni la voirie communale. L'écran doit le dire, sinon
une carte vide passerait pour « rien à signaler ».

FORMAT
DATEX II version 2, la norme européenne d'échange routier : un instantané XML d'environ 2,5 Mo
republié toutes les quelques minutes. Chaque `situation` regroupe des `situationRecord`
(travaux + voie neutralisée + limitation + déviation) ; on écrit UNE ligne par situation, avec
la catégorie la plus contraignante de ses fragments.

Même règle que le reste de la veille : seul le serveur appelle, pour la France entière, depuis
la tâche planifiée. Rien de ce qui part ne désigne un utilisateur ni un territoire.
"""
import logging
import re
import xml.etree.ElementTree as ET

import requests
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL_FLUX = ("https://tipi.bison-fute.gouv.fr/bison-fute-ouvert/publicationsDIR/"
            "Evenementiel-DIR/grt/RRN/content.xml")
DELAI_REPONSE_S = 60
# Le flux pèse 2,5 Mo. Dix fois plus n'est pas un flux routier : on refuse de l'analyser.
TAILLE_MAX = 30 * 1024 * 1024

_NS = "{http://datex2.eu/schema/2/2_0}"
_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# Du plus contraignant au moins contraignant : c'est l'ordre qui désigne la catégorie d'une
# situation à plusieurs fragments, et l'ordre d'affichage.
ORDRE_CATEGORIES = ("FERMETURE", "ACCIDENT", "OBSTACLE", "CONDITIONS", "DEVIATION", "TRAVAUX",
                    "RESTRICTION", "AUTRE")

_CATEGORIE_PAR_TYPE = {
    "Accident": "ACCIDENT",
    "GeneralObstruction": "OBSTACLE",
    "VehicleObstruction": "OBSTACLE",
    "EnvironmentalObstruction": "OBSTACLE",
    "InfrastructureDamageObstruction": "OBSTACLE",
    "AnimalPresenceObstruction": "OBSTACLE",
    "EquipmentOrSystemFault": "OBSTACLE",
    "WeatherRelatedRoadConditions": "CONDITIONS",
    "NonWeatherRelatedRoadConditions": "CONDITIONS",
    "PoorEnvironmentConditions": "CONDITIONS",
    "AbnormalTraffic": "CONDITIONS",
    "ReroutingManagement": "DEVIATION",
    "MaintenanceWorks": "TRAVAUX",
    "ConstructionWorks": "TRAVAUX",
    "RoadOrCarriagewayOrLaneManagement": "RESTRICTION",
    "SpeedManagement": "RESTRICTION",
    "GeneralNetworkManagement": "RESTRICTION",
    "GeneralInstructionOrMessageToRoadUsers": "RESTRICTION",
    "WinterDrivingManagement": "RESTRICTION",
}

# Valeurs qui signifient que la route ne passe plus, quel que soit le fragment qui les porte.
_VALEURS_FERMETURE = {
    "roadClosed", "closedPermanentlyForTheWinter", "roadBlocked", "carriagewayBlocked",
    "carriagewayClosures",
}

# Champs DATEX qui précisent la nature d'un fragment.
_CHAMPS_NATURE = (
    "accidentType", "obstructionType", "vehicleObstructionType", "environmentalObstructionType",
    "infrastructureDamageType", "animalPresenceType", "weatherRelatedRoadConditionType",
    "roadOrCarriagewayOrLaneManagementType", "reroutingManagementType", "roadMaintenanceType",
    "constructionWorkType", "speedManagementType", "generalInstructionToRoadUsersType",
    "trafficConstrictionType",
)

# Libellés des valeurs effectivement rencontrées dans le flux (relevé du 15/11/2026). Une valeur
# inconnue retombe sur le libellé de sa catégorie : jamais de terme anglais à l'écran.
_LIBELLES = {
    "accident": "Accident",
    "roadClosed": "Route fermée",
    "closedPermanentlyForTheWinter": "Fermeture hivernale",
    "roadBlocked": "Route coupée",
    "carriagewayBlocked": "Chaussée coupée",
    "carriagewayClosures": "Chaussée fermée",
    "laneClosures": "Voie neutralisée",
    "lanesBlocked": "Voie neutralisée",
    "singleAlternateLineTraffic": "Circulation alternée",
    "contraflow": "Circulation à double sens sur une chaussée",
    "narrowLanes": "Voies réduites",
    "weightRestrictionInOperation": "Tonnage limité",
    "heightRestrictionInOperation": "Hauteur limitée",
    "speedRestrictionInOperation": "Vitesse limitée",
    "noOvertaking": "Dépassement interdit",
    "doNotUseEntry": "Entrée fermée",
    "doNotUseExit": "Sortie fermée",
    "followLocalDiversion": "Déviation locale",
    "followDiversionSigns": "Déviation",
    "useExit": "Sortie conseillée",
    "roadworks": "Travaux",
    "maintenanceWork": "Entretien",
    "repairWork": "Réparation",
    "resurfacingWork": "Réfection de chaussée",
    "roadMarkingWork": "Marquage au sol",
    "roadsideWork": "Travaux en bord de route",
    "grassCuttingWork": "Fauchage",
    "constructionWork": "Chantier",
    "brokenDownVehicle": "Véhicule en panne",
    "obstructionOnTheRoad": "Obstacle sur la chaussée",
    "objectOnTheRoad": "Objet sur la chaussée",
    "incident": "Incident",
    "animalsOnTheRoad": "Animaux sur la chaussée",
    "damagedRoadSurface": "Chaussée dégradée",
    "subsidence": "Affaissement",
    "rockfalls": "Chute de pierres",
    "flooding": "Inondation",
    "landslips": "Glissement de terrain",
    "fallenTrees": "Arbres sur la chaussée",
    "snowOnTheRoad": "Neige sur la chaussée",
    "ice": "Verglas",
    "blackIce": "Verglas",
    "snowDrifts": "Congères",
}
_LIBELLE_CATEGORIE = {
    "FERMETURE": "Route fermée", "ACCIDENT": "Accident", "OBSTACLE": "Obstacle",
    "CONDITIONS": "Conditions difficiles", "DEVIATION": "Déviation", "TRAVAUX": "Travaux",
    "RESTRICTION": "Restriction", "AUTRE": "Événement",
}

_REPERE = re.compile(r"^(\d{2}|2[AB])PR", re.IGNORECASE)


def telecharger():
    """Le flux XML brut. Lève une exception réseau ou ValueError s'il est démesuré."""
    reponse = requests.get(URL_FLUX, timeout=DELAI_REPONSE_S)
    reponse.raise_for_status()
    if len(reponse.content) > TAILLE_MAX:
        raise ValueError(f"flux de {len(reponse.content)} octets, refusé")
    return reponse.content


def _texte(element, chemin):
    """Texte du premier descendant direct désigné par `chemin` (« a/b/c »), ou chaîne vide."""
    trouve = element.find("/".join(f"{_NS}{partie}" for partie in chemin.split("/")))
    return (trouve.text or "").strip() if trouve is not None else ""


def _tous(element, nom):
    return element.iter(f"{_NS}{nom}")


def _points(fragment):
    """Coordonnées (lon, lat) portées par un fragment, dans l'ordre du document."""
    points = []
    for coordonnees in _tous(fragment, "pointCoordinates"):
        try:
            points.append((float(_texte(coordonnees, "longitude")), float(_texte(coordonnees, "latitude"))))
        except ValueError:
            continue
    return points


def _descripteur(fragment, genre):
    """Premier nom de lieu d'un genre donné (`townName`, `linkName`)."""
    for nom in _tous(fragment, "name"):
        if _texte(nom, "tpegOtherPointDescriptorType") == genre:
            valeur = _texte(nom, "descriptor/values/value")
            if valeur:
                return valeur
    return ""


def _commentaires(fragment, genre):
    textes = []
    for commentaire in fragment.findall(f"{_NS}generalPublicComment"):
        if _texte(commentaire, "commentType") == genre:
            valeur = _texte(commentaire, "comment/values/value")
            if valeur:
                textes.append(" ".join(valeur.split()))
    return textes


def _ajouter(liste, valeur):
    if valeur and valeur not in liste:
        liste.append(valeur)


# Analyse avec la bibliothèque standard : elle ne résout aucune entité externe, et l'expat de
# l'image (2.8) borne lui-même l'expansion d'entités en cascade. Avec le plafond de taille de
# `telecharger`, un flux malveillant ne peut ni lire un fichier ni épuiser la mémoire.
def analyser(xml):
    """Flux brut -> (heure de publication, [dictionnaires prêts pour EvenementRoutier]).

    Une situation sans coordonnées lisibles est ignorée : sans position, ni la carte ni le tri
    par territoire ne peuvent rien en faire."""
    racine = ET.fromstring(xml)
    publication = next(_tous(racine, "publicationTime"), None)
    publie_le = parse_datetime(publication.text.strip()) if publication is not None and publication.text else None

    evenements = []
    for situation in _tous(racine, "situation"):
        reference = situation.get("id")
        fragments = situation.findall(f"{_NS}situationRecord")
        if not reference or not fragments:
            continue

        categories, natures, descriptions, localisations = set(), [], [], []
        points, debuts, fins = [], [], []
        route = commune = gestionnaire = departement = ""
        for fragment in fragments:
            genre = (fragment.get(_TYPE) or "").split(":")[-1]
            categorie = _CATEGORIE_PAR_TYPE.get(genre, "AUTRE")
            for champ in _CHAMPS_NATURE:
                for element in _tous(fragment, champ):
                    valeur = (element.text or "").strip()
                    if valeur in _VALEURS_FERMETURE:
                        categorie = "FERMETURE"
                    if valeur and valeur != "other":
                        _ajouter(natures, _LIBELLES.get(valeur))
            categories.add(categorie)

            for texte in _commentaires(fragment, "description"):
                _ajouter(descriptions, texte)
            for texte in _commentaires(fragment, "locationDescriptor"):
                _ajouter(localisations, texte)
            if not points:
                points = _points(fragment)
            route = route or _descripteur(fragment, "linkName")
            commune = commune or _descripteur(fragment, "townName")
            gestionnaire = gestionnaire or _texte(fragment, "source/sourceIdentification")
            if not departement:
                for repere in _tous(fragment, "referentIdentifier"):
                    trouve = _REPERE.match((repere.text or "").strip())
                    if trouve:
                        departement = trouve.group(1).upper()
                        break
            debut = parse_datetime(_texte(fragment, "validity/validityTimeSpecification/overallStartTime") or "")
            fin = parse_datetime(_texte(fragment, "validity/validityTimeSpecification/overallEndTime") or "")
            if debut:
                debuts.append(debut)
            if fin:
                fins.append(fin)

        if not points:
            continue
        categorie = next(c for c in ORDRE_CATEGORIES if c in categories)
        version = situation.find(f"{_NS}situationVersionTime")
        evenements.append({
            "reference": reference[:80],
            "categorie": categorie,
            "natures": natures or [_LIBELLE_CATEGORIE[categorie]],
            "gravite": _texte(situation, "overallSeverity")[:10],
            "route": route[:20],
            "commune_nom": commune[:120],
            "description": "\n".join(descriptions),
            "localisation": "\n".join(localisations),
            "gestionnaire": gestionnaire.split("/")[-1][:160],
            "departement_code": departement or None,
            "location": Point(points[0][0], points[0][1], srid=4326),
            "location_fin": Point(points[-1][0], points[-1][1], srid=4326) if len(points) > 1 else None,
            "debut": min(debuts) if debuts else None,
            # Une situation dure tant que l'un de ses fragments dure ; un fragment sans fin
            # annoncée rend la fin inconnue.
            "fin": max(fins) if fins and len(fins) == len(fragments) else None,
            "mis_a_jour_le": parse_datetime(version.text.strip()) if version is not None and version.text else None,
        })
    return publie_le, evenements


def enregistrer(evenements, maintenant=None):
    """Remplace l'instantané : écrit ce que le flux contient, supprime ce qu'il ne contient plus.

    Un flux VIDE n'efface rien : le réseau national a toujours des chantiers en cours, zéro
    événement est une anomalie du producteur, pas une bonne nouvelle."""
    from .models import EvenementRoutier

    if not evenements:
        raise ValueError("flux sans aucun événement, instantané précédent conservé")
    maintenant = maintenant or timezone.now()
    lignes = [EvenementRoutier(releve_le=maintenant, **evenement) for evenement in evenements]
    champs = [champ for champ in evenements[0] if champ != "reference"] + ["releve_le"]
    with transaction.atomic():
        EvenementRoutier.objects.bulk_create(
            lignes, update_conflicts=True, unique_fields=["reference"], update_fields=champs,
        )
        EvenementRoutier.objects.exclude(reference__in=[l.reference for l in lignes]).delete()
    return len(lignes)


def relever():
    _publie_le, evenements = analyser(telecharger())
    return enregistrer(evenements)
