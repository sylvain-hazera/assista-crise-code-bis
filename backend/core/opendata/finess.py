"""Structures de soins et médico-sociales — FINESS, flux « nouvelle génération » de l'Agence du
numérique en santé. Licence Ouverte.

Trois particularités qui expliquent la forme de ce module :

1. L'ANCIENNE extraction CSV de FINESS est MORTE. Sa génération s'est arrêtée à l'été 2026 : le
   fichier se télécharge encore mais n'est plus mis à jour depuis le 12/05/2026. Le flux vivant
   est le JSON quotidien publié sous le jeu `finess-structures-1`, et c'est lui qu'on lit.

2. Il n'existe aucune API par commune : le flux est un fichier unique de ~50 Mo compressés,
   ~750 Mo décompressés. On le lit en flot (`_objets_du_tableau`), jamais en mémoire, et on en
   extrait la seule commune demandée — d'où l'exécution en tâche Celery et pas dans une requête.

3. FINESS conserve l'historique : sur une commune réelle, la moitié des entités sont fermées
   (pharmacies radiées en 2009…). On filtre sur `dateFermeture` et `etatObjet`, sinon la mairie
   travaille sur des établissements qui n'existent plus.

L'URL du fichier n'est jamais écrite en dur : elle est résolue à chaque fois via l'API data.gouv,
le nom du fichier portant la date du jour."""
import datetime
import gzip
import json
import logging
import os
import tempfile

import requests

from ..models import CategorieSiteSensible, SourceSiteSensible
from .base import SitePropose, fetch_json

logger = logging.getLogger(__name__)

DATASET = "finess-structures-1"
PREFIXE_JOURNALIER = "finess-structures-journalier"
PREFIXE_MENSUEL = "finess-structures-mensuel"

# Lecture par blocs d'1 Mio : assez grand pour que `raw_decode` aboutisse presque toujours du
# premier coup, assez petit pour que l'empreinte mémoire reste négligeable.
TAILLE_LECTURE = 1024 * 1024

# Téléchargement : le fichier fait une cinquantaine de Mo, servi par un CDN. Large, mais borné.
TIMEOUT_TELECHARGEMENT = 300


def _resource_du_jour():
    """URL et date du flux FINESS le plus récent, résolues via l'API data.gouv.

    On préfère le journalier au mensuel ; à défaut, le mensuel fait l'affaire (il reste bien plus
    frais que l'ancienne extraction CSV abandonnée)."""
    data = fetch_json(f"https://www.data.gouv.fr/api/1/datasets/{DATASET}/")
    if not data:
        return None, None
    candidats = []
    for resource in data.get("resources", []):
        titre = resource.get("title") or ""
        if titre.startswith(PREFIXE_JOURNALIER):
            candidats.append((2, titre, resource.get("url")))
        elif titre.startswith(PREFIXE_MENSUEL):
            candidats.append((1, titre, resource.get("url")))
    if not candidats:
        logger.warning("Aucun flux FINESS trouvé dans le jeu %s", DATASET)
        return None, None
    _priorite, titre, url = max(candidats)
    return url, _date_depuis_titre(titre)


def _date_depuis_titre(titre):
    """« finess-structures-journalier-20261027.json.gz » → date(2026, 10, 27). Le mensuel ne porte
    que l'année et le mois : on le date au 1er."""
    chiffres = "".join(c for c in titre if c.isdigit())
    for longueur, format_date in ((8, "%Y%m%d"), (6, "%Y%m")):
        if len(chiffres) >= longueur:
            try:
                return datetime.datetime.strptime(chiffres[:longueur], format_date).date()
            except ValueError:
                continue
    return None


def _telecharger(url):
    """Télécharge le flux dans le répertoire temporaire, et le réutilise s'il y est déjà.

    Importer une deuxième commune le même jour ne retélécharge donc pas 50 Mo. Le cache est
    volontairement local au conteneur et sans expiration explicite : le nom du fichier portant sa
    date, un flux plus récent crée simplement un nouveau fichier."""
    chemin = os.path.join(tempfile.gettempdir(), os.path.basename(url))
    if os.path.exists(chemin) and os.path.getsize(chemin) > 0:
        return chemin
    temporaire = f"{chemin}.part"
    with requests.get(url, stream=True, timeout=TIMEOUT_TELECHARGEMENT) as reponse:
        reponse.raise_for_status()
        with open(temporaire, "wb") as sortie:
            for bloc in reponse.iter_content(chunk_size=TAILLE_LECTURE):
                sortie.write(bloc)
    # Renommage atomique : une lecture concurrente ne tombe jamais sur un fichier à moitié écrit.
    os.replace(temporaire, chemin)
    return chemin


def _objets_du_tableau(flux, cle):
    """Itère les objets du tableau JSON `cle` d'un document trop gros pour tenir en mémoire.

    Volontairement indépendant de la mise en forme du fichier (indentation, sauts de ligne) :
    on avance avec `raw_decode`, en rechargeant du texte tant qu'un objet est tronqué."""
    decodeur = json.JSONDecoder()
    marqueur = f'"{cle}"'
    tampon = ""

    while marqueur not in tampon:
        morceau = flux.read(TAILLE_LECTURE)
        if not morceau:
            return
        # Ne garder qu'un chevauchement du début : le marqueur peut être à cheval sur deux blocs.
        tampon = tampon[-len(marqueur):] + morceau
    tampon = tampon[tampon.index(marqueur) + len(marqueur):]

    while "[" not in tampon:
        morceau = flux.read(TAILLE_LECTURE)
        if not morceau:
            return
        tampon += morceau
    tampon = tampon[tampon.index("[") + 1:]

    while True:
        tampon = tampon.lstrip()
        if tampon[:1] == ",":
            tampon = tampon[1:]
            continue
        if tampon[:1] == "]":
            return
        if tampon:
            try:
                objet, fin = decodeur.raw_decode(tampon)
            except ValueError:
                objet = None
            if objet is not None:
                yield objet
                tampon = tampon[fin:]
                continue
        morceau = flux.read(TAILLE_LECTURE)
        if not morceau:
            return
        tampon += morceau


def _adresse_de_la_commune(entite, commune_code):
    for adresse in entite.get("adresse") or []:
        if adresse.get("cogCommune") == commune_code:
            return adresse
    return None


def _telephone(entite):
    for contact in entite.get("contact") or []:
        telephone = (contact.get("telecom") or {}).get("telephone")
        if telephone:
            return telephone
    return ""


def _coordonnee(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _vers_site(ege, adresse, denomination_juridique, date_source):
    infos = ege.get("informationsGeneralesEGE") or {}
    if infos.get("dateFermeture") or ege.get("etatObjet") == "I":
        return None
    numero = infos.get("numFinessEge") or infos.get("egeId")
    if not numero:
        return None
    geo = adresse.get("coordonneesGeographique") or {}
    lignes = [adresse.get("ligneQuatre"), " ".join(
        part for part in (adresse.get("codePostal"), adresse.get("ligneAcheminement")) if part
    )]
    return SitePropose(
        source=SourceSiteSensible.FINESS,
        source_id=numero,
        categorie=CategorieSiteSensible.SOINS,
        nom=infos.get("nomEgeLong") or infos.get("nomEgeCourt") or numero,
        adresse=", ".join(ligne.strip() for ligne in lignes if ligne and ligne.strip()),
        # Coordonnées issues du géocodage BAN fait par le producteur : déjà au bon format.
        latitude=_coordonnee(geo.get("directionLatitude")),
        longitude=_coordonnee(geo.get("directionLongitude")),
        telephone=_telephone(ege),
        attributs={
            "numero_finess": numero,
            "date_maj_source": date_source.isoformat() if date_source else None,
            # Code de nomenclature FINESS, conservé brut : sa traduction en clair demande une
            # table de référence que l'ANS ne publie pas dans ce flux. Le nom de l'établissement
            # est explicite (« EHPAD RESIDENCE… », « MAS… »), il suffit à l'agent qui relit.
            "categorie_finess": ege.get("categorieentiteGeographiqueExercice"),
            "siret": infos.get("siret"),
            "date_ouverture": infos.get("dateOuverture"),
            "entite_juridique": denomination_juridique,
        },
    )


def collecter(commune_code):
    """Structures FINESS en activité sur la commune. Liste vide si le flux est injoignable —
    jamais d'exception : une source en panne ne doit pas faire échouer l'import des autres."""
    url, date_source = _resource_du_jour()
    if not url:
        return []
    try:
        chemin = _telecharger(url)
    except Exception as exc:
        logger.warning("Téléchargement du flux FINESS impossible : %s", exc)
        return []

    sites = []
    with gzip.open(chemin, "rt", encoding="utf-8") as flux:
        for pmej in _objets_du_tableau(flux, "pmej"):
            denomination = (pmej.get("informationsGeneralesPMEJ") or {}).get("denominationLonguePmSmsse")
            for ege in pmej.get("ege") or []:
                adresse = _adresse_de_la_commune(ege, commune_code)
                if adresse is None:
                    continue
                site = _vers_site(ege, adresse, denomination, date_source)
                if site is not None:
                    sites.append(site)
    return sites
