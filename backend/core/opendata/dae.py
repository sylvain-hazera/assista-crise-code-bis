"""Défibrillateurs automatisés externes — Géo'DAE, base nationale tenue par le ministère de la
Santé (Atlasanté), Licence Ouverte 2.0.

Trois choses à savoir :

1. L'API de Géo'DAE est réservée aux exploitants de défibrillateurs. Ce qui est ouvert, c'est
   le FICHIER national publié sur data.gouv.fr, régénéré plusieurs fois par jour : ~80 Mo de
   CSV, sans filtre par commune. On le lit en flot, comme FINESS, d'où la tâche de fond.

2. La base garde les appareils retirés, en doublon ou en attente de validation. On ne propose
   que ceux qui sont actifs, validés et déclarés en fonctionnement — sinon la mairie compte sur
   un appareil qui n'existe plus.

3. Un défibrillateur n'est pas un lieu à protéger mais un moyen à connaître : il est proposé
   comme RESSOURCE, jamais comme enjeu. Et comme partout dans ce paquet, c'est une proposition :
   l'agent qui sait que l'appareil du gymnase a été volé l'écarte.

L'adresse du fichier change à chaque régénération (elle porte un horodatage) ; on passe donc
par le lien stable de data.gouv.fr, qui redirige vers la version courante."""
import csv
import datetime
import logging
import os
import tempfile

import requests

from ..models import CategorieSiteSensible, EchelonCompetence, SourceSiteSensible
from .base import Collecte, SitePropose

logger = logging.getLogger(__name__)

# Lien stable de la ressource « geodae.csv » du jeu « Géo'DAE - Base Nationale des
# Défibrillateurs » (identifiant de ressource data.gouv.fr).
URL_FICHIER = "https://www.data.gouv.fr/api/1/datasets/r/edb6a9e1-2f16-4bbf-99e7-c3eb6b90794c"
TIMEOUT_TELECHARGEMENT = 300
TAILLE_LECTURE = 1024 * 1024

# Certaines descriptions d'accès sont longues : la limite par défaut du module csv (128 Kio par
# champ) est largement suffisante, on ne la relève pas.


def _telecharger():
    """Télécharge le fichier du jour dans le répertoire temporaire, et le réutilise s'il y est.

    Une copie par jour : recenser une deuxième commune le même jour ne retélécharge pas 80 Mo,
    et un défibrillateur déclaré ce matin attendra demain — sans conséquence pour un plan de
    sauvegarde."""
    chemin = os.path.join(tempfile.gettempdir(), f"geodae-{datetime.date.today():%Y%m%d}.csv")
    if os.path.exists(chemin) and os.path.getsize(chemin) > 0:
        return chemin
    temporaire = f"{chemin}.part"
    with requests.get(URL_FICHIER, stream=True, timeout=TIMEOUT_TELECHARGEMENT) as reponse:
        reponse.raise_for_status()
        with open(temporaire, "wb") as sortie:
            for bloc in reponse.iter_content(chunk_size=TAILLE_LECTURE):
                sortie.write(bloc)
    # Renommage atomique : une lecture concurrente ne tombe jamais sur un fichier à moitié écrit.
    os.replace(temporaire, chemin)
    return chemin


def _coordonnee(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _vrai(valeur):
    return (valeur or "").strip().lower() in ("t", "true", "oui")


def _vers_site(ligne):
    """Une ligne du fichier -> SitePropose, ou None si l'appareil n'est pas à proposer."""
    if (ligne.get("c_etat") or "").strip() != "Actif":
        return None
    if (ligne.get("c_etat_valid") or "").strip() != "validées":
        return None
    if (ligne.get("c_etat_fonct") or "").strip() != "En fonctionnement":
        return None
    if _vrai(ligne.get("c_doublon")):
        return None
    identifiant = (ligne.get("c_gid") or ligne.get("gid") or "").strip()
    if not identifiant:
        return None

    voie = " ".join(part.strip() for part in (ligne.get("c_adr_num"), ligne.get("c_adr_voie")) if part and part.strip())
    commune = " ".join(part.strip() for part in (ligne.get("c_com_cp"), ligne.get("c_com_nom")) if part and part.strip())
    exploitant = (ligne.get("c_expt_rais") or "").strip()
    return SitePropose(
        source=SourceSiteSensible.GEODAE,
        source_id=identifiant,
        categorie=CategorieSiteSensible.DEFIBRILLATEUR,
        # Le nom saisi par l'exploitant va du modèle de l'appareil (« DAE G5 ») au nom du lieu.
        # L'exploitant situe mieux l'appareil quand il est connu.
        nom=(f"Défibrillateur — {exploitant}" if exploitant
             else (ligne.get("c_nom") or "").strip() or "Défibrillateur"),
        adresse=", ".join(part for part in (voie, commune) if part),
        latitude=_coordonnee(ligne.get("c_lat_coor1")),
        longitude=_coordonnee(ligne.get("c_long_coor1")),
        est_enjeu=False,
        est_ressource=True,
        commune_code=(ligne.get("c_com_insee") or "").strip() or None,
        commune_nom=(ligne.get("c_com_nom") or "").strip() or None,
        echelon_competence=EchelonCompetence.INDETERMINE,
        attributs={
            "designation": (ligne.get("c_nom") or "").strip(),
            "acces": (ligne.get("c_acc") or "").strip(),            # Intérieur / Extérieur
            "acces_libre": _vrai(ligne.get("c_acc_lib")),
            "etage": (ligne.get("c_acc_etg") or "").strip(),
            "emplacement": (ligne.get("c_acc_complt") or "").strip(),
            "disponibilite": (ligne.get("c_dispo_horaires") or "").strip(),
            "precision_disponibilite": (ligne.get("c_disp_complt") or "").strip(),
            "derniere_maintenance": (ligne.get("c_dermnt") or "").strip() or None,
            "date_maj_source": (ligne.get("c_maj_don") or "").strip() or None,
        },
    )


def lire(flux, communes):
    """Défibrillateurs à proposer parmi les lignes d'un fichier Géo'DAE ouvert en texte.
    `communes` est un ensemble de codes INSEE : le fichier est national, c'est ici que le
    périmètre s'applique."""
    sites = []
    for ligne in csv.DictReader(flux, delimiter=";"):
        if (ligne.get("c_com_insee") or "").strip() not in communes:
            continue
        site = _vers_site(ligne)
        if site is not None:
            sites.append(site)
    return sites


def collecter(perimetre):
    """Défibrillateurs en service sur le périmètre. Liste vide si le fichier est injoignable —
    jamais d'exception : une source en panne ne doit pas faire échouer l'import des autres.

    Le périmètre ne change rien au coût : le fichier national est lu en entier de toute façon."""
    try:
        chemin = _telecharger()
    except Exception as exc:
        logger.warning("Téléchargement du fichier Géo'DAE impossible : %s", exc)
        return Collecte([], "le fichier national des défibrillateurs n'a pas pu être téléchargé")
    with open(chemin, "r", encoding="utf-8", newline="") as flux:
        return Collecte(lire(flux, set(perimetre.communes)))
