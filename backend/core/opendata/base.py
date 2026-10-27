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
import time
from collections import namedtuple

import requests

logger = logging.getLogger(__name__)

# Les connecteurs tournent soit dans une requête HTTP (sources API, quelques centaines de ms),
# soit dans une tâche Celery (FINESS). 10s est large pour une API qui répond normalement et
# assez court pour qu'une source en panne ne bloque pas l'import des autres.
TIMEOUT = 10

# Pause entre deux appels au même producteur. Aucune des API branchées ici ne publie de limite
# de débit (vérifié le 27/10/2026 : ni les portails Opendatasoft, ni Géorisques, ni l'annuaire
# des entreprises n'en documentent). En l'absence de limite annoncée, on s'en impose une plutôt
# que d'enchaîner au rythme que le réseau permet : un recensement départemental fait des
# centaines d'appels, et un service public gratuit n'a pas à encaisser une rafale au motif que
# nous n'avons pas pris la peine d'espacer.
PAUSE_ENTRE_APPELS = 0.12

# Pause entre deux tranches d'un même périmètre (voir sites_sensibles.tranches) : plus longue,
# c'est le moment où l'on change de territoire et où rien ne presse.
PAUSE_ENTRE_TRANCHES = 1.0

# Budget de temps d'un import entier, toutes tranches confondues. La tâche Celery qui le porte
# a une limite dure (voir tasks.py) : la dépasser ferait tuer la tâche au milieu d'une tranche,
# sans compte rendu et en laissant « recherche en cours » affiché pour toujours. On s'arrête
# nous-mêmes, et surtout on le DIT (voir importer_source).
BUDGET_SECONDES = 900

# Refus temporaires sur lesquels réessayer. Volontairement sans 500 : Géorisques en rend des
# persistants sur certains endpoints, et réessayer trois fois ne ferait que gaspiller le budget.
CODES_REESSAYABLES = {429, 502, 503, 504}
TENTATIVES = 3
ATTENTE_APRES_REFUS = 2.0

# Garde-fou : une commune réaliste tient très en dessous. Au-delà, c'est que le filtre commune
# n'a pas été pris en compte par la source -- on s'arrête plutôt que d'inonder la base.
MAX_RESULTATS = 500

# Un territoire à interroger. `communes` est la liste des codes INSEE qu'il couvre : certaines
# sources ne savent filtrer que commune par commune (FINESS lit un flux national, les portails
# Opendatasoft acceptent un `IN`), d'autres ont un filtre départemental natif, bien plus
# économique (Géorisques `departement`, SIRENE `departement`, annuaire de l'éducation
# `code_departement`).
Perimetre = namedtuple("Perimetre", "niveau code communes")

# Plafonds par niveau, mesurés sur le Finistère (277 communes) : 852 établissements scolaires,
# ~4 000 installations classées, 6 202 élevages. Un département déborde donc largement le
# plafond communal, et un plafond unique rendrait l'un ou l'autre inutilisable.
PLAFONDS = {"commune": 500, "epci": 3000, "departement": 12000, "region": 12000}


def perimetre_commune(commune_code):
    """Le périmètre d'une seule commune — ce que faisait implicitement tout ce paquet avant
    l'arrivée des collectivités de niveau supérieur."""
    return Perimetre("commune", commune_code, [commune_code])


def plafond(perimetre):
    return PLAFONDS.get(getattr(perimetre, "niveau", "commune"), MAX_RESULTATS)


def where_territoire(champ_commune, perimetre, champs_secteur=None, codes_secteur=None):
    """Clause `where` Opendatasoft pour un périmètre.

    `champs_secteur` donne, par niveau, le champ du jeu de données qui le porte
    (`{"departement": "code_departement"}`) : une requête au lieu de 277. `codes_secteur` sert
    aux jeux qui écrivent le code autrement — l'annuaire de l'éducation zéro-complète le
    département (« 029 ») là où le recensement des équipements sportifs ne le fait pas (« 29 »).

    Sans champ pour ce niveau, repli sur un `IN` des codes commune : c'est le cas de l'EPCI,
    qu'aucun des jeux branchés ici ne porte."""
    champ = (champs_secteur or {}).get(perimetre.niveau)
    if champ:
        code = (codes_secteur or {}).get(perimetre.niveau, perimetre.code)
        return f'{champ}="{code}"'
    communes = ", ".join(f'"{code}"' for code in perimetre.communes)
    return f"{champ_commune} IN ({communes})"


class SitePropose:
    """Un site proposé par une source ouverte, avant toute décision humaine.

    `source_id` doit être STABLE dans la source (UAI, n° FINESS, code AIOT, n° d'installation
    RES) : c'est lui qui permet de ré-importer sans dupliquer, et de conserver la décision déjà
    prise par la mairie sur une ligne vue lors d'un import précédent."""

    __slots__ = ("source", "source_id", "categorie", "nom", "adresse",
                 "latitude", "longitude", "telephone", "attributs",
                 "personne_physique", "est_enjeu", "est_ressource",
                 "commune_code", "commune_nom", "echelon_competence")

    def __init__(self, source, source_id, categorie, nom, adresse="",
                 latitude=None, longitude=None, telephone="", attributs=None,
                 personne_physique=False, est_enjeu=True, est_ressource=False,
                 commune_code=None, commune_nom=None, echelon_competence=None):
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
        # La commune du site, et non celle de l'institution qui importe : indispensable dès
        # qu'un département interroge ses 277 communes d'un coup.
        self.commune_code = (str(commune_code).strip() or None) if commune_code else None
        self.commune_nom = (commune_nom or "").strip() or None
        # Qui en a la charge (voir EchelonCompetence) : un collège public est au département,
        # l'école d'à côté à la commune, le lycée à la région.
        self.echelon_competence = echelon_competence


def pause(secondes=PAUSE_ENTRE_APPELS):
    """Souffle entre deux appels à un même producteur (voir PAUSE_ENTRE_APPELS)."""
    time.sleep(secondes)


def _attente_demandee(reponse):
    """L'en-tête `Retry-After` quand le producteur dit lui-même combien attendre."""
    try:
        return max(0.0, min(30.0, float(reponse.headers.get("Retry-After"))))
    except (TypeError, ValueError, AttributeError):
        return None


def fetch_json(url, params=None, tentatives=TENTATIVES):
    """Appel d'une API ouverte : rend le JSON, ou None sur n'importe quel échec.

    Jamais d'exception vers l'appelant : une source indisponible ne doit pas faire échouer
    l'import des autres (mesuré en vrai sur Géorisques, qui rend des 500 sur certains
    endpoints).

    Réessaie sur un refus TEMPORAIRE (voir CODES_REESSAYABLES), en respectant `Retry-After`
    quand le producteur le fournit. Un 429 n'est pas une panne, c'est une demande de ralentir :
    y répondre en abandonnant la source priverait la collectivité de ses données, y répondre en
    insistant immédiatement serait impoli."""
    for tentative in range(1, tentatives + 1):
        reponse = None
        try:
            reponse = requests.get(url, params=params, timeout=TIMEOUT)
            if reponse.status_code not in CODES_REESSAYABLES:
                reponse.raise_for_status()
                return reponse.json()
        except Exception as exc:
            logger.warning("Source open data injoignable (%s) : %s", url, exc)
            return None
        if tentative == tentatives:
            logger.warning(
                "Source open data refuse encore après %s tentatives (%s) : HTTP %s",
                tentatives, url, reponse.status_code,
            )
            return None
        pause(_attente_demandee(reponse) or ATTENTE_APRES_REFUS * tentative)
    return None


class Collecte(list):
    """La liste des sites proposés par une source, qui sait dire si elle est TRONQUÉE.

    Une liste, et pas un objet à part, pour que tout ce qui l'itère ou la compte n'ait rien à
    savoir de plus. `tronque` porte, en français lisible par un agent, la raison pour laquelle
    le recensement est incomplet — et ce champ est la moitié importante : un recensement qui se
    croit complet alors qu'il a perdu des lignes est plus dangereux que pas de recensement du
    tout, parce qu'on bâtit un plan de sauvegarde dessus. Un connecteur qui n'a rien à signaler
    peut rendre une liste nue : l'appelant lit `getattr(proposes, "tronque", None)`."""

    def __init__(self, sites=(), tronque=None):
        super().__init__(sites)
        self.tronque = tronque


# Opendatasoft refuse `offset + limit > 10000` sur l'endpoint `records`, avec un 400 explicite
# (« Invalid value for sum of offset + limit API parameter »). Mesuré en production le
# 27/10/2026 sur le recensement des équipements sportifs à l'échelle d'une région.
#
# Ce plafond n'est PAS une limite de débit : il ne s'écoule pas avec le temps, et étaler les
# appels n'y change rien — l'offset 10 100 est refusé aussi patiemment qu'on le demande. La
# Nouvelle-Aquitaine compte 17 344 équipements sportifs : 7 344 étaient hors d'atteinte.
#
# L'endpoint `exports`, lui, n'a pas ce plafond : il rend le jeu filtré en UN appel. Vérifié en
# direct, 17 344 enregistrements en 10 s et 5 Mo. C'est donc moins d'appels, pas plus, et un
# recensement complet au lieu d'un recensement tronqué.
OFFSET_MAX_ODS = 10000

# Taille d'une page `records`. Sert au comptage et au cas des petits périmètres.
PAGE_ODS = 100

# Au-delà, on ne charge pas : un export de cette taille signifie que le filtre territorial n'a
# pas été pris en compte par le portail, et tenir le jeu national en mémoire dans un worker
# n'aiderait personne.
MAX_EXPORT_ODS = 60000


def _compter_ods(portail, dataset, where):
    """Nombre d'enregistrements que le filtre rend, en un appel à un enregistrement.

    Payé volontairement : c'est lui qui permet de choisir entre `records` et `exports`, de
    refuser un périmètre aberrant avant de le télécharger, et de dire à l'agent ce qui a été
    tronqué plutôt que de le lui laisser découvrir."""
    data = fetch_json(
        f"https://{portail}/api/explore/v2.1/catalog/datasets/{dataset}/records",
        {"where": where, "limit": 1},
    )
    return None if data is None else data.get("total_count")


def collecter_ods(portail, dataset, where, mapper, select=None, maximum=MAX_RESULTATS):
    """Collecte sur un portail Opendatasoft (Explore API v2.1) — patron partagé par l'annuaire
    de l'éducation et le recensement des équipements sportifs.

    Un comptage, puis UN seul appel : `records` quand une page suffit, `exports` au-delà. On ne
    pagine plus `records`, parce que sa pagination a un plafond que le périmètre d'un
    département dépasse (voir OFFSET_MAX_ODS) — et parce qu'un export unique est plus économe
    pour le producteur qu'une centaine de pages.

    `select` restreint les champs au strict nécessaire du mapper : l'export de l'annuaire de
    l'éducation sur une région passe de 14 Mo à 1 Mo, celui des équipements sportifs de 22 Mo
    à 5 Mo. Ce n'est pas un détail quand ça traverse un worker Celery."""
    total = _compter_ods(portail, dataset, where)
    if total is None:
        return Collecte([], "le portail n'a pas répondu")
    if total == 0:
        return Collecte()
    if total > MAX_EXPORT_ODS:
        logger.warning("Collecte %s refusée : %s enregistrements annoncés", dataset, total)
        return Collecte([], f"{total} enregistrements annoncés par le portail, c'est "
                            f"au-delà de ce qu'un import peut charger : le filtre territorial "
                            f"n'a probablement pas été pris en compte")

    params = {"where": where}
    if select:
        params["select"] = select
    if total <= PAGE_ODS:
        chemin, params["limit"] = "records", PAGE_ODS
    else:
        chemin = "exports/json"
    pause()
    data = fetch_json(
        f"https://{portail}/api/explore/v2.1/catalog/datasets/{dataset}/{chemin}", params)
    if data is None:
        return Collecte([], "le portail n'a pas répondu")
    enregistrements = data.get("results", []) if isinstance(data, dict) else data

    sites = [site for site in (mapper(e) for e in enregistrements) if site is not None]
    tronque = None
    if len(enregistrements) > maximum:
        # Le plafond par niveau reste un garde-fou (voir PLAFONDS) : s'il mord, c'est l'agent
        # qu'il faut prévenir, pas le journal.
        sites = sites[:maximum]
        tronque = (f"{total} enregistrements trouvés, {maximum} retenus : resserrez le "
                   f"périmètre pour recenser le reste")
    return Collecte(sites, tronque)
