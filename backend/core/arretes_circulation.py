"""Arrêtés de circulation des collectivités : relevé de DiaLog, copie en base.

SOURCE
DiaLog (https://dialog.beta.gouv.fr), service de l'État où les communes, intercommunalités et
départements publient leurs arrêtés de circulation, Licence Ouverte 2.0. Aucune clé. Un fichier
national au format DATEX II version 3, d'environ 80 Mo, qui rassemble tous les arrêtés publiés.

POURQUOI EN PLUS DE BISON FUTÉ
Bison Futé ne connaît que le réseau national. Les routes fermées par un maire ou un
département -- celles qui comptent pour une commune -- ne sont que dans DiaLog.

CE QU'ON EN GARDE
Sur les ~7 000 arrêtés, seulement ceux qui changent un itinéraire : circulation interdite à
tous, interdite aux poids lourds (avec le tonnage), ou alternée. Les limitations de vitesse et
le stationnement, qui font la moitié du fichier, n'apprennent rien à une cellule de crise et ne
sont pas copiés. Les arrêtés déjà terminés non plus.

CE QUE LA CARTE NE DIT PAS
Seules les collectivités qui publient dans DiaLog y figurent, et elles sont encore peu
nombreuses : une commune sans aucun arrêté ici n'est pas une commune sans route fermée.
L'écran doit le dire.

Le fichier est lourd : il est téléchargé sur disque puis lu en flot, une fois par jour. Même
règle que le reste de la veille : seul le serveur appelle, pour la France entière.
"""
import json
import logging
import os
import tempfile
import xml.etree.ElementTree as ET

import requests
from django.contrib.gis.geos import GEOSGeometry, GeometryCollection
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

URL_FLUX = "https://dialog.beta.gouv.fr/api/regulations/datex"
DELAI_REPONSE_S = 300
TAILLE_LECTURE = 1024 * 1024
# Le fichier pèse 80 Mo ; dix fois plus n'est pas ce fichier.
TAILLE_MAX = 800 * 1024 * 1024
MINIMUM_PLAUSIBLE = 500

_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

FERMETURE, POIDS_LOURDS, ALTERNAT = "FERMETURE", "POIDS_LOURDS", "ALTERNAT"
# Du plus contraignant au moins contraignant : désigne la catégorie d'un arrêté à plusieurs
# mesures.
ORDRE_CATEGORIES = (FERMETURE, POIDS_LOURDS, ALTERNAT)


def _nom(balise):
    return balise.rsplit("}", 1)[-1]


def _texte(element, *chemin):
    """Texte du premier descendant qui suit `chemin` (noms de balises sans espace de noms)."""
    courant = element
    for nom in chemin:
        courant = next((enfant for enfant in courant if _nom(enfant.tag) == nom), None)
        if courant is None:
            return ""
    return (courant.text or "").strip()


def _descendants(element, nom):
    return (e for e in element.iter() if _nom(e.tag) == nom)


def telecharger(dossier=None):
    """Télécharge le fichier sur disque et rend son chemin. À supprimer par l'appelant."""
    chemin = os.path.join(dossier or tempfile.gettempdir(), "dialog-arretes.xml.part")
    taille = 0
    with requests.get(URL_FLUX, stream=True, timeout=DELAI_REPONSE_S) as reponse:
        reponse.raise_for_status()
        with open(chemin, "wb") as sortie:
            for bloc in reponse.iter_content(chunk_size=TAILLE_LECTURE):
                taille += len(bloc)
                if taille > TAILLE_MAX:
                    raise ValueError("fichier DiaLog démesuré, lecture abandonnée")
                sortie.write(bloc)
    return chemin


def _lire_mesure(mesure):
    """Une mesure d'un arrêté -> (catégorie, tonnage, géométries, voies), ou None si elle ne
    change pas un itinéraire (vitesse, stationnement, dépassement) ou n'est pas en vigueur."""
    if _texte(mesure, "status") not in ("", "active"):
        return None
    nature = next((e for e in mesure if _nom(e.tag) == "typeOfRegulation"), None)
    genre = (nature.get(_TYPE) or "").split(":")[-1] if nature is not None else ""
    if genre == "AccessRestriction":
        # Interdite aux seuls poids lourds si une condition (non inversée) désigne ce type de
        # véhicule ; interdite à tous sinon -- les conditions inversées sont des exceptions
        # (livraisons, secours, bus), pas une restriction du champ.
        tonnages, poids_lourds = [], False
        for condition in mesure.iter():
            if (condition.get(_TYPE) or "").split(":")[-1] != "VehicleCondition":
                continue
            if _texte(condition, "negate") == "true":
                continue
            if any(e.text == "heavyGoodsVehicle" for e in _descendants(condition, "vehicleType")):
                poids_lourds = True
            for poids in _descendants(condition, "grossVehicleWeight"):
                try:
                    tonnages.append(float(poids.text))
                    poids_lourds = True
                except (TypeError, ValueError):
                    pass
        categorie = POIDS_LOURDS if poids_lourds else FERMETURE
        tonnage = min(tonnages) if tonnages else None
    elif genre == "RoadOrCarriagewayOrLaneManagement":
        categorie, tonnage = ALTERNAT, None
    else:
        return None

    geometries, voies = [], []
    for emplacement in _descendants(mesure, "locationByOrder"):
        for champ in ("roadName", "roadNumber"):
            for voie in _descendants(emplacement, champ):
                nom = (voie.text or "").strip()
                if nom and nom not in voies:
                    voies.append(nom)
        for brut in _descendants(emplacement, "geoJsonGeometry"):
            try:
                geometrie = GEOSGeometry(json.dumps(json.loads(brut.text)), srid=4326)
            except Exception:      # noqa: BLE001 -- JSON abîmé ou géométrie refusée par GEOS
                continue
            # Certains tracés sont eux-mêmes des assemblages : on les met à plat, un assemblage
            # ne pouvant pas en contenir un autre.
            geometries.extend(geometrie if geometrie.geom_type == "GeometryCollection" else [geometrie])
    return categorie, tonnage, geometries, voies


def lire(chemin, maintenant=None):
    """Arrêtés à garder parmi ceux du fichier : dictionnaires prêts pour ArreteCirculation.
    Lecture en flot : le fichier n'est jamais en mémoire en entier."""
    maintenant = maintenant or timezone.now()
    arretes = []
    for _evenement, element in ET.iterparse(chemin, events=("end",)):
        if _nom(element.tag) != "trafficRegulationOrder":
            continue
        arrete = _lire_arrete(element, maintenant)
        if arrete is not None:
            arretes.append(arrete)
        element.clear()
    return arretes


def _lire_arrete(element, maintenant):
    reference = (element.get("id") or "").strip()
    if not reference or _texte(element, "status") not in ("", "madeAndImplemented"):
        return None
    fin = parse_datetime(_texte(element, "validityByOrder", "validityTimeSpecification", "overallEndTime"))
    if fin is not None and fin < maintenant:
        return None

    categories, tonnages, geometries, voies = set(), [], [], []
    for mesure in element:
        if _nom(mesure.tag) != "trafficRegulation":
            continue
        lue = _lire_mesure(mesure)
        if lue is None:
            continue
        categorie, tonnage, tracees, noms = lue
        categories.add(categorie)
        if tonnage is not None:
            tonnages.append(tonnage)
        geometries.extend(tracees)
        voies.extend(nom for nom in noms if nom not in voies)
    if not categories or not geometries:
        return None

    ensemble = GeometryCollection(*geometries, srid=4326)
    return {
        "reference": reference[:80],
        "categorie": next(c for c in ORDRE_CATEGORIES if c in categories),
        "description": _texte(element, "description", "values", "value")[:500],
        "autorite": _texte(element, "issuingAuthority", "values", "value")[:200],
        "voies": ", ".join(voies)[:300],
        "tonnage_max": min(tonnages) if tonnages else None,
        "debut": parse_datetime(_texte(element, "validityByOrder", "validityTimeSpecification", "overallStartTime")),
        "fin": fin,
        "url": next((e.text.strip() for e in _descendants(element, "publicUrl") if e.text), "")[:300],
        "geometrie": ensemble,
        "location": ensemble.centroid if not ensemble.centroid.empty else geometries[0].centroid,
    }


def enregistrer(arretes, maintenant=None):
    """Remplace la copie : écrit les arrêtés du fichier, retire ceux qui n'y sont plus."""
    from .models import ArreteCirculation

    if len(arretes) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(arretes)} arrêtés seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    lignes = [ArreteCirculation(releve_le=maintenant, **arrete) for arrete in arretes]
    champs = [champ for champ in arretes[0] if champ != "reference"] + ["releve_le"]
    with transaction.atomic():
        ArreteCirculation.objects.bulk_create(
            lignes, batch_size=500, update_conflicts=True, unique_fields=["reference"],
            update_fields=champs)
        ArreteCirculation.objects.exclude(reference__in=[l.reference for l in lignes]).delete()
    return len(lignes)


def relever():
    chemin = telecharger()
    try:
        return enregistrer(lire(chemin))
    finally:
        try:
            os.remove(chemin)
        except OSError:
            pass
