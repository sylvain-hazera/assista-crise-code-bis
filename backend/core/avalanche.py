"""Risque d'avalanche par massif : relevé des bulletins de Météo-France, copie en base.

SOURCE
API « DonneesPubliquesBRA » du portail public de Météo-France (même clé que la vigilance, voir
core/meteo_france.py), Licence Ouverte 2.0. Un bulletin d'estimation du risque d'avalanche par
massif -- 35 massifs des Alpes, des Pyrénées et de Corse --, publié chaque jour vers 16 h pour
le lendemain, **pendant la saison d'enneigement** (de l'automne au printemps).

CE QU'ON EN GARDE
L'indice de risque du jour et du lendemain sur l'échelle européenne (1 faible, 2 limité,
3 marqué, 4 fort, 5 très fort), le résumé rédigé par le prévisionniste, et le contour du
massif. Le bulletin complet (enneigement, stabilité du manteau, météo) reste chez
Météo-France : l'écran y renvoie.

POUR QUI
Les communes de montagne et celles qui y envoient des secours. Ailleurs, ce bloc n'apparaît
tout simplement pas : il n'est affiché que s'il y a un massif dans le rayon regardé.

Un bulletin par massif, donc 35 appels par relevé, espacés pour rester très en dessous du débit
autorisé (50 par minute). Hors saison l'API répond 404 pour chaque massif : le relevé réussit
alors « à vide », comme la météo des forêts. Même règle que le reste de la veille : seul le
serveur appelle, pour tous les massifs.
"""
import datetime
import json
import logging
import time
import xml.etree.ElementTree as ET

import requests
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.db import transaction
from django.utils import timezone

from . import meteo_france

logger = logging.getLogger(__name__)

URL_BASE = "https://public-api.meteofrance.fr/public/DPBRA/v1"
# Le service est lent et parfois muet : un délai court, et une lecture ratée garde l'indice
# précédent (voir `relever`).
DELAI_REPONSE_S = 15
PAUSE_ENTRE_MASSIFS_S = 1.3
NIVEAUX = {1: "faible", 2: "limité", 3: "marqué", 4: "fort", 5: "très fort"}
MINIMUM_MASSIFS = 20
FUSEAU = meteo_france.FUSEAU


def _appeler(chemin, parametres=None):
    cle = meteo_france.lire_cle()
    if cle is None:
        raise meteo_france.CleAbsente()
    return requests.get(f"{URL_BASE}/{chemin}", params=parametres,
                        headers={"apikey": cle, "accept": "*/*"}, timeout=DELAI_REPONSE_S)


def telecharger_massifs():
    reponse = _appeler("liste-massifs")
    reponse.raise_for_status()
    return reponse.json()


def telecharger_bulletin(code):
    """Bulletin XML d'un massif, ou None s'il n'y en a pas (hors saison : 404)."""
    reponse = _appeler("massif/BRA", {"id-massif": code, "format": "xml"})
    if reponse.status_code == 404:
        return None
    reponse.raise_for_status()
    return reponse.content


def analyser_massifs(donnees):
    """Liste des massifs -> {code: {"nom", "chaine", "departement_nom", "geometrie"}}."""
    massifs = {}
    for element in (donnees or {}).get("features") or []:
        proprietes = element.get("properties") or {}
        try:
            code = int(proprietes["code"])
            geometrie = GEOSGeometry(json.dumps(element.get("geometry")), srid=4326)
        except Exception:      # noqa: BLE001 -- clé absente, code illisible, ou erreur GEOS
            continue
        if geometrie.geom_type == "Polygon":
            geometrie = MultiPolygon(geometrie, srid=4326)
        if geometrie.geom_type != "MultiPolygon" or geometrie.empty:
            continue
        departements = [d for d in (proprietes.get("Departement"), proprietes.get("Dep2")) if d]
        massifs[code] = {
            "nom": str(proprietes.get("title") or "").strip()[:120],
            "chaine": str(proprietes.get("mountain") or "").strip()[:60],
            "departement_nom": ", ".join(departements)[:160],
            "geometrie": geometrie,
        }
    return massifs


def _niveau(texte):
    try:
        niveau = int(texte)
    except (TypeError, ValueError):
        return None
    return niveau if niveau in NIVEAUX else None


def _instant(texte):
    """Les bulletins datent en heure légale, sans fuseau."""
    try:
        return datetime.datetime.fromisoformat(texte).replace(tzinfo=FUSEAU)
    except (TypeError, ValueError):
        return None


def analyser_bulletin(xml):
    """Bulletin XML -> {"risque", "risque_demain", "commentaire", "resume", "publie_le",
    "valide_jusqu_a"}, ou None s'il ne porte aucun indice de risque lisible."""
    try:
        racine = ET.fromstring(xml)
    except ET.ParseError:
        return None
    risque = racine.find("CARTOUCHERISQUE/RISQUE")
    if risque is None or _niveau(risque.get("RISQUEMAXI")) is None:
        return None
    resume = racine.findtext("CARTOUCHERISQUE/RESUME") or ""
    return {
        "risque": _niveau(risque.get("RISQUEMAXI")),
        "risque_demain": _niveau(risque.get("RISQUEMAXIJ2")),
        "commentaire": (risque.get("COMMENTAIRE") or "").strip()[:300],
        "resume": "\n".join(ligne.strip() for ligne in resume.splitlines() if ligne.strip())[:1500],
        "publie_le": _instant(racine.get("DATEBULLETIN")),
        "valide_jusqu_a": _instant(racine.get("DATEVALIDITE")),
    }


def relever(maintenant=None):
    """Relève les massifs puis leurs bulletins. Rend le nombre de massifs ayant un bulletin ;
    zéro hors saison (succès), une erreur si la liste des massifs elle-même est illisible.

    Trois issues possibles pour un massif, et elles ne se valent pas :
    - bulletin lu : son indice remplace le précédent ;
    - pas de bulletin (404, hors saison) : l'indice est effacé, l'écran dit « pas de bulletin » ;
    - lecture en panne (délai, erreur) : l'indice PRÉCÉDENT est gardé -- le service est lent et
      parfois muet, et un massif à risque fort ne doit pas redevenir « sans indice » parce
      qu'une requête a expiré. `valide_jusqu_a` dit de toute façon jusqu'à quand il vaut."""
    from .models import RisqueAvalanche

    maintenant = maintenant or timezone.now()
    massifs = analyser_massifs(telecharger_massifs())
    if len(massifs) < MINIMUM_MASSIFS:
        raise ValueError(f"{len(massifs)} massifs seulement, copie précédente conservée")

    champs_bulletin = ("risque", "risque_demain", "commentaire", "resume", "publie_le", "valide_jusqu_a")
    connus = {m.massif_code: m for m in RisqueAvalanche.objects.all()}
    lignes, avec_bulletin = [], 0
    for rang, (code, massif) in enumerate(sorted(massifs.items())):
        if rang:
            time.sleep(PAUSE_ENTRE_MASSIFS_S)
        try:
            xml = telecharger_bulletin(code)
            bulletin = (analyser_bulletin(xml) if xml else None) or {}
        except requests.RequestException as exc:
            logger.warning("Avalanche : bulletin du massif %s non relevé (%s), le précédent est gardé.",
                           code, type(exc).__name__)
            precedent = connus.get(code)
            bulletin = {c: getattr(precedent, c) for c in champs_bulletin} if precedent else {}
        avec_bulletin += bulletin.get("risque") is not None
        lignes.append(RisqueAvalanche(massif_code=code, releve_le=maintenant, **massif, **bulletin))

    champs = ["nom", "chaine", "departement_nom", "geometrie", "risque", "risque_demain",
              "commentaire", "resume", "publie_le", "valide_jusqu_a", "releve_le"]
    with transaction.atomic():
        RisqueAvalanche.objects.bulk_create(
            lignes, update_conflicts=True, unique_fields=["massif_code"], update_fields=champs)
        RisqueAvalanche.objects.exclude(massif_code__in=list(massifs)).delete()
    return avec_bulletin
