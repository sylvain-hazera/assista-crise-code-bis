"""Météo des forêts : danger de feu par département, pour demain et après-demain.

SOURCE
API « DonneesPubliquesMeteoForets » du portail public de Météo-France (même clé que la
vigilance, voir core/meteo_france.py), Licence Ouverte 2.0. Le produit paraît chaque jour à
17 h, **de juin à septembre seulement**. Quatre niveaux de danger : faible, modéré, élevé, très
élevé.

⚠ ÉCRIT SANS DONNÉE RÉELLE (15/11/2026)
Hors saison, l'API répond 404 « no matching blob » : il n'y avait rien à lire le jour où ce
module a été écrit, et la forme exacte de la réponse n'a donc pas pu être constatée. Deux
précautions en découlent :

1. `analyser` ne suppose pas une forme précise. Elle parcourt la réponse à la recherche
   d'objets portant un code de département et un niveau de 1 à 4, quels que soient les noms
   des champs et la profondeur où ils se trouvent.
2. Chaque réponse reçue est CONSERVÉE TELLE QUELLE (`ReleveMeteoForets.brut`). Si, à la
   première publication de juin, l'analyse ne trouve rien, le relevé est marqué « non compris »
   -- la supervision le signale -- et l'échantillon est là pour ajuster `analyser` en dix
   minutes, sans attendre une nouvelle publication.

Tant que ce module n'a pas vu une vraie réponse, l'écran dit « hors saison » et rien d'autre.
"""
import json
import logging
import re

import requests
from django.db import transaction
from django.utils import timezone

from . import meteo_france

logger = logging.getLogger(__name__)

URL = "https://public-api.meteofrance.fr/public/DPMeteoForets/v1/carte/encours"
DELAI_REPONSE_S = 30
NIVEAUX = {1: "faible", 2: "modéré", 3: "élevé", 4: "très élevé"}
# La réponse brute est gardée, mais pas sans limite.
TAILLE_BRUT_MAX = 2 * 1024 * 1024

_CODE = re.compile(r"^(?:\d{2,3}|2[AB])$", re.IGNORECASE)
_CHAMP_DEPARTEMENT = re.compile(r"dep|dpt|insee|code|domain", re.IGNORECASE)
_CHAMP_NIVEAU = re.compile(r"niveau|danger|risque|level|color|couleur|valeur", re.IGNORECASE)
_CHAMP_DEMAIN = re.compile(r"j1|j\+1|demain|tomorrow", re.IGNORECASE)
_CHAMP_APRES_DEMAIN = re.compile(r"j2|j\+2|apres|surlendemain", re.IGNORECASE)


class HorsSaison(Exception):
    """Aucune carte publiée : c'est l'état normal d'octobre à mai."""


def telecharger():
    """(type de contenu, octets). Lève `HorsSaison` quand Météo-France ne publie rien."""
    cle = meteo_france.lire_cle()
    if cle is None:
        raise meteo_france.CleAbsente()
    reponse = meteo_france.avec_reprise(lambda: requests.get(
        URL, headers={"apikey": cle, "accept": "*/*"}, timeout=DELAI_REPONSE_S))
    if reponse.status_code == 404:
        raise HorsSaison()
    reponse.raise_for_status()
    return reponse.headers.get("content-type", ""), reponse.content


def _entier(valeur):
    try:
        nombre = int(valeur)
    except (TypeError, ValueError):
        return None
    return nombre if nombre in NIVEAUX else None


def _lire_objet(objet):
    """(code de département, niveau demain, niveau après-demain) si cet objet en porte un,
    sinon None. Tolère n'importe quels noms de champs (voir l'en-tête du module)."""
    code = None
    for cle, valeur in objet.items():
        if _CHAMP_DEPARTEMENT.search(str(cle)) and isinstance(valeur, (str, int)):
            texte = str(valeur).strip().upper()
            if isinstance(valeur, int) and valeur < 10:
                texte = f"{valeur:02d}"
            if _CODE.match(texte):
                code = texte
                break
    if code is None:
        return None
    # Les niveaux sont cherchés dans l'objet lui-même, puis un cran plus bas ({"risque": {"j1": 4}}).
    champs = list(objet.items())
    for valeur in objet.values():
        if isinstance(valeur, dict):
            champs.extend(valeur.items())
    demain = apres = seul = None
    for cle, valeur in champs:
        nom = str(cle)
        if not _CHAMP_NIVEAU.search(nom) and not _CHAMP_DEMAIN.search(nom) and not _CHAMP_APRES_DEMAIN.search(nom):
            continue
        niveau = _entier(valeur)
        if niveau is None:
            continue
        if _CHAMP_APRES_DEMAIN.search(nom):
            apres = niveau
        elif _CHAMP_DEMAIN.search(nom):
            demain = niveau
        elif seul is None:
            seul = niveau
    if demain is None:
        demain = seul
    return (code, demain, apres) if demain is not None or apres is not None else None


def analyser(type_contenu, contenu):
    """{code de département: (niveau demain, niveau après-demain)}. Vide si la réponse n'est pas
    du JSON ou ne contient rien de reconnaissable -- l'appelant le consigne."""
    try:
        donnees = json.loads(contenu.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    trouves = {}

    def parcourir(noeud):
        if isinstance(noeud, dict):
            lu = _lire_objet(noeud)
            if lu is not None:
                code, demain, apres = lu
                connu = trouves.get(code, (None, None))
                trouves[code] = (demain if demain is not None else connu[0],
                                 apres if apres is not None else connu[1])
            for valeur in noeud.values():
                parcourir(valeur)
        elif isinstance(noeud, list):
            for valeur in noeud:
                parcourir(valeur)

    parcourir(donnees)
    return trouves


def relever(maintenant=None):
    """Relève la carte du jour. Hors saison : vide la copie et rend 0 (c'est un succès, pas une
    panne). En saison : garde la réponse brute, et lève une erreur si rien n'y est reconnu."""
    from .models import DangerFeuForet, ReleveMeteoForets

    maintenant = maintenant or timezone.now()
    try:
        type_contenu, contenu = telecharger()
    except HorsSaison:
        with transaction.atomic():
            DangerFeuForet.objects.all().delete()
            ReleveMeteoForets.objects.update_or_create(pk=1, defaults={
                "en_saison": False, "compris": True, "releve_le": maintenant})
        return 0

    niveaux = analyser(type_contenu, contenu)
    with transaction.atomic():
        ReleveMeteoForets.objects.update_or_create(pk=1, defaults={
            "en_saison": True, "compris": bool(niveaux), "type_contenu": type_contenu[:120],
            "brut": contenu[:TAILLE_BRUT_MAX], "releve_le": maintenant})
        if niveaux:
            DangerFeuForet.objects.all().delete()
            DangerFeuForet.objects.bulk_create([
                DangerFeuForet(departement_code=code, niveau_demain=demain,
                               niveau_apres_demain=apres, releve_le=maintenant)
                for code, (demain, apres) in niveaux.items()
            ])
    if not niveaux:
        raise ValueError(
            "carte publiée mais non comprise : la réponse brute est gardée dans "
            "ReleveMeteoForets, ajuster core/meteo_forets.analyser")
    return len(niveaux)
