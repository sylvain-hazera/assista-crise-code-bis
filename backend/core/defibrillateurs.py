"""Carte nationale des défibrillateurs : relevé du fichier Géo'DAE, copie en base.

SOURCE
Géo'DAE, la base nationale des défibrillateurs automatisés externes (ministère de la Santé,
Atlasanté), Licence Ouverte 2.0 : le même fichier national que core/opendata/dae.py, d'où
viennent sa lecture et ses règles de tri.

DEUX USAGES, DEUX COPIES, ET CE N'EST PAS UN DOUBLON
- core/opendata/dae.py PROPOSE à une collectivité les appareils de son territoire, pour qu'elle
  les vérifie un à un et les inscrive à son plan de sauvegarde (Sites sensibles) ;
- ce module-ci tient la carte de TOUS les appareils du pays, tels que la base les déclare, pour
  répondre à « où est le défibrillateur le plus proche » sans attendre qu'une mairie ait fait
  son recensement.

La carte montre donc ce que les exploitants ont déclaré, pas ce qu'une collectivité a vérifié :
un appareil volé ou en panne peut y figurer. L'écran le dit, et rappelle qu'en cas d'arrêt
cardiaque on appelle d'abord le 15.

Seuls les appareils actifs, validés et déclarés en fonctionnement sont copiés (voir
`dae._vers_site`). Un relevé par jour : 80 Mo à lire en flot.
"""
import csv
import logging

from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

from .opendata import dae

logger = logging.getLogger(__name__)

MINIMUM_PLAUSIBLE = 20000


def lire(flux):
    """Appareils à garder parmi les lignes du fichier : dictionnaires prêts pour
    Defibrillateur. Un appareil sans position est ignoré -- il ne se place pas sur une carte."""
    appareils = {}
    for ligne in csv.DictReader(flux, delimiter=";"):
        site = dae._vers_site(ligne)
        if site is None or site.latitude is None or site.longitude is None:
            continue
        if not (-90 <= site.latitude <= 90 and -180 <= site.longitude <= 180):
            continue
        appareils[site.source_id[:20]] = {
            "reference": site.source_id[:20],
            "nom": site.nom[:255],
            "adresse": site.adresse[:255],
            "commune_code": (site.commune_code or "")[:10],
            "acces": str(site.attributs.get("acces") or "")[:40],
            "acces_libre": bool(site.attributs.get("acces_libre")),
            "emplacement": str(site.attributs.get("emplacement") or "")[:255],
            "disponibilite": str(site.attributs.get("disponibilite") or "")[:120],
            "location": Point(site.longitude, site.latitude, srid=4326),
        }
    return list(appareils.values())


def enregistrer(appareils, maintenant=None):
    from .models import Defibrillateur

    if len(appareils) < MINIMUM_PLAUSIBLE:
        raise ValueError(f"{len(appareils)} appareils seulement, copie précédente conservée")
    maintenant = maintenant or timezone.now()
    champs = [champ for champ in appareils[0] if champ != "reference"] + ["releve_le"]
    references = set()
    with transaction.atomic():
        for debut in range(0, len(appareils), 2000):
            lot = appareils[debut:debut + 2000]
            references.update(a["reference"] for a in lot)
            Defibrillateur.objects.bulk_create(
                [Defibrillateur(releve_le=maintenant, **a) for a in lot],
                update_conflicts=True, unique_fields=["reference"], update_fields=champs)
        # Ce qui n'a pas été réécrit à l'instant n'est plus dans le fichier.
        Defibrillateur.objects.filter(releve_le__lt=maintenant).delete()
    return len(references)


def relever():
    chemin = dae._telecharger()
    with open(chemin, "r", encoding="utf-8", newline="") as flux:
        return enregistrer(lire(flux))
