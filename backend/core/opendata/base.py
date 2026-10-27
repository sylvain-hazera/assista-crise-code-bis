"""Socle commun aux connecteurs open data des sites sensibles (voir SiteSensible).

Règle d'or de ce paquet, héritée de RisqueCommunalViewSet.suggestions_georisques : une source
ouverte ne produit JAMAIS une vérité, seulement des PROPOSITIONS qu'un agent accepte, corrige ou
écarte une à une. Aucun connecteur n'écrit en base : chacun rend une liste de SitePropose, et
c'est core/sites_sensibles.py qui décide quoi en faire.

Toutes les sources branchées ici sont nationales, interrogeables par code INSEE et sous Licence
Ouverte (Etalab) -- attribution obligatoire, redistribution libre. Volontairement PAS
d'OpenStreetMap, pourtant plus riche sur les salles des fêtes : sa licence ODbL impose le partage
à l'identique des bases dérivées, ce qui contaminerait la base Assista-Crise entière."""
import logging

import requests

logger = logging.getLogger(__name__)

# Les connecteurs tournent soit dans une requête HTTP (sources API, quelques centaines de ms),
# soit dans une tâche Celery (FINESS). 10s est large pour une API qui répond normalement et
# assez court pour qu'une source en panne ne bloque pas l'import des autres.
TIMEOUT = 10

# Garde-fou : une commune réaliste tient très en dessous. Au-delà, c'est que le filtre commune
# n'a pas été pris en compte par la source -- on s'arrête plutôt que d'inonder la base.
MAX_RESULTATS = 500


class SitePropose:
    """Un site proposé par une source ouverte, avant toute décision humaine.

    `source_id` doit être STABLE dans la source (UAI, n° FINESS, code AIOT, n° d'installation
    RES) : c'est lui qui permet de ré-importer sans dupliquer, et de conserver la décision déjà
    prise par la mairie sur une ligne vue lors d'un import précédent."""

    __slots__ = ("source", "source_id", "categorie", "nom", "adresse",
                 "latitude", "longitude", "telephone", "attributs",
                 "personne_physique", "est_enjeu", "est_ressource")

    def __init__(self, source, source_id, categorie, nom, adresse="",
                 latitude=None, longitude=None, telephone="", attributs=None,
                 personne_physique=False, est_enjeu=True, est_ressource=False):
        self.source = source
        self.source_id = str(source_id)
        self.categorie = categorie
        self.nom = (nom or "").strip()
        self.adresse = (adresse or "").strip()
        self.latitude = latitude
        self.longitude = longitude
        self.telephone = (telephone or "").strip()
        self.attributs = attributs or {}
        # Une personne physique recensée chez elle : son adresse et ses coordonnées ne sortiront
        # de l'API qu'après un dévoilement tracé (voir SiteSensible.personne_physique).
        self.personne_physique = personne_physique
        # À protéger, mobilisable, ou les deux : voir SiteSensible.est_enjeu / est_ressource.
        self.est_enjeu = est_enjeu
        self.est_ressource = est_ressource


def fetch_json(url, params=None):
    """Appel d'une API ouverte : rend le JSON, ou None sur n'importe quel échec.

    Jamais d'exception vers l'appelant : une source indisponible ne doit pas faire échouer
    l'import des autres (mesuré en vrai sur Géorisques, qui rend des 500 sur certains
    endpoints)."""
    try:
        reponse = requests.get(url, params=params, timeout=TIMEOUT)
        reponse.raise_for_status()
        return reponse.json()
    except Exception as exc:
        logger.warning("Source open data injoignable (%s) : %s", url, exc)
        return None


def collecter_ods(portail, dataset, where, mapper, select=None):
    """Collecte paginée sur un portail Opendatasoft (Explore API v2.1) -- patron partagé par
    l'annuaire de l'éducation et le recensement des équipements sportifs, qui exposent tous deux
    cette API avec la même pagination (`limit` plafonné à 100 par l'éditeur, `offset`)."""
    sites, offset = [], 0
    while offset < MAX_RESULTATS:
        params = {"where": where, "limit": 100, "offset": offset}
        if select:
            params["select"] = select
        data = fetch_json(f"https://{portail}/api/explore/v2.1/catalog/datasets/{dataset}/records", params)
        if not data or not data.get("results"):
            break
        for enregistrement in data["results"]:
            site = mapper(enregistrement)
            if site is not None:
                sites.append(site)
        if len(data["results"]) < 100:
            break
        offset += 100
    return sites
