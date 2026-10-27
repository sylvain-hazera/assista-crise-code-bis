"""Annuaire des entreprises (SIRENE / INSEE) — API « Recherche d'entreprises » de la DINUM.

Ouverte, sans clé, filtrable par code commune, géolocalisée, Licence Ouverte.
https://recherche-entreprises.api.gouv.fr/search

Ce que cette source apporte et qu'aucune autre ne donne : les MOYENS D'ACTION. Les quatre
premières sources disent où sont les enjeux ; SIRENE dit qui possède un car, une bétaillère, une
pelle, un stock de bâches, une cuisine collective ou une cuve de carburant. Elle complète aussi
les élevages par le bas : sur Châteauneuf-du-Faou, 68 exploitations contre 17 en ICPE — les
quatre cinquièmes sont sous les seuils du classement, donc invisibles jusqu'ici.

Trois précautions, qui sont la raison de la forme de ce module :

1. **L'échelle s'inverse avec la taille de la commune.** 105 établissements à Châteauneuf pour
   les thèmes ci-dessous, 3 409 à Bordeaux. Un import « tout SIRENE » serait inexploitable en
   ville : la collecte est donc THÉMATIQUE, la commune choisit ce qu'elle veut recenser.
2. **SIRENE enregistre une existence juridique, pas une activité physique.** Les 152 « élevages »
   de Bordeaux sont à 85 % des personnes physiques domiciliées en centre-ville, code NAF agricole
   et zéro animal. D'où, encore, le passage obligé par PROPOSE.
3. **Les personnes physiques sont enregistrées chez elles.** `nature_juridique == "1000"` désigne
   un entrepreneur individuel : son adresse est un domicile. On ne peut pas les exclure (61 % des
   élevages de Châteauneuf, et ce sont de vrais agriculteurs) ; elles sont donc marquées, leur
   adresse est chiffrée comme le reste et ne sort de l'API qu'après un dévoilement tracé.
   `statut_diffusion` est respecté : une personne opposée à la diffusion de ses données n'entre
   pas, même si l'API la renvoie."""
from collections import namedtuple

from ..models import CategorieSiteSensible, SourceSiteSensible
from .base import SitePropose, fetch_json

URL = "https://recherche-entreprises.api.gouv.fr/search"

# L'API plafonne `per_page` à 25.
TAILLE_PAGE = 25

# Par thème, et non global : un thème qui déborde ne doit pas priver les autres. Au-delà, la
# commune est trop grande pour un recensement exhaustif et devra affiner.
MAX_PAR_THEME = 200

# Nature juridique 1000 = entrepreneur individuel, c'est-à-dire une personne physique.
NATURE_JURIDIQUE_PERSONNE_PHYSIQUE = "1000"

Theme = namedtuple("Theme", "naf enjeu ressource defaut")

# Ce que la commune peut demander à recenser. Chaque thème est une catégorie de SiteSensible,
# une liste de codes NAF, et un rôle par défaut (à protéger / mobilisable / les deux).
THEMES = {
    CategorieSiteSensible.ELEVAGE: Theme(
        naf=("01.41Z", "01.42Z", "01.43Z", "01.45Z", "01.46Z", "01.47Z", "01.49Z", "01.50Z",
             "01.62Z"),
        # Un cheptel à sauver, mais aussi un tracteur, une cuve, une bétaillère et des bras.
        enjeu=True, ressource=True, defaut=True),
    CategorieSiteSensible.VETERINAIRE: Theme(
        naf=("75.00Z",), enjeu=False, ressource=True, defaut=True),
    CategorieSiteSensible.HEBERGEMENT: Theme(
        naf=("55.10Z", "55.20Z", "55.30Z", "55.90Z"),
        # Un camping, c'est une population saisonnière à évacuer ET des lits disponibles.
        enjeu=True, ressource=True, defaut=True),
    CategorieSiteSensible.MOYENS: Theme(
        naf=("49.31Z", "49.39A", "49.39B", "49.41A", "49.41B", "49.42Z",
             "42.11Z", "43.11Z", "43.12A", "43.12B", "43.91A", "43.91B", "43.32A"),
        enjeu=False, ressource=True, defaut=True),
    CategorieSiteSensible.APPROVISIONNEMENT: Theme(
        naf=("47.11B", "47.11C", "47.11D", "47.11E", "47.11F", "10.71C", "47.30Z",
             "56.29A", "56.29B"),
        enjeu=False, ressource=True, defaut=True),
    CategorieSiteSensible.FUNERAIRE: Theme(
        naf=("96.03Z",), enjeu=False, ressource=True, defaut=True),
    # Décoché par défaut, et c'est délibéré : en commune rurale, « accueil de jeunes enfants »
    # ramène surtout des assistantes maternelles, donc des noms de personnes à leur domicile.
    # À activer en connaissance de cause, pas par défaut.
    CategorieSiteSensible.PETITE_ENFANCE: Theme(
        naf=("88.91A",), enjeu=True, ressource=False, defaut=False),
}

THEMES_PAR_DEFAUT = [code for code, theme in THEMES.items() if theme.defaut]

# Libellés officiels des codes retenus : l'agent doit lire « Élevage de vaches laitières », pas
# « 01.41Z ». Seuls les codes utilisés ici figurent, l'API ne rendant que le code.
LIBELLES_NAF = {
    "01.41Z": "Élevage de vaches laitières",
    "01.42Z": "Élevage d'autres bovins et de buffles",
    "01.43Z": "Élevage de chevaux et d'autres équidés",
    "01.45Z": "Élevage d'ovins et de caprins",
    "01.46Z": "Élevage de porcins",
    "01.47Z": "Élevage de volailles",
    "01.49Z": "Élevage d'autres animaux",
    "01.50Z": "Culture et élevage associés",
    "01.62Z": "Activités de soutien à la production animale",
    "75.00Z": "Activités vétérinaires",
    "55.10Z": "Hôtels et hébergement similaire",
    "55.20Z": "Hébergement touristique de courte durée",
    "55.30Z": "Terrains de camping et parcs pour caravanes",
    "55.90Z": "Autres hébergements",
    "49.31Z": "Transports urbains et suburbains de voyageurs",
    "49.39A": "Transports routiers réguliers de voyageurs",
    "49.39B": "Autres transports routiers de voyageurs",
    "49.41A": "Transports routiers de fret interurbains",
    "49.41B": "Transports routiers de fret de proximité",
    "49.42Z": "Services de déménagement",
    "42.11Z": "Construction de routes et autoroutes",
    "43.11Z": "Travaux de démolition",
    "43.12A": "Travaux de terrassement courants",
    "43.12B": "Travaux de terrassement de grande masse",
    "43.91A": "Travaux de charpente",
    "43.91B": "Travaux de couverture par éléments",
    "43.32A": "Travaux de menuiserie bois et PVC",
    "47.11B": "Commerce d'alimentation générale",
    "47.11C": "Supérettes",
    "47.11D": "Supermarchés",
    "47.11E": "Magasins multi-commerces",
    "47.11F": "Hypermarchés",
    "10.71C": "Boulangerie et boulangerie-pâtisserie",
    "47.30Z": "Commerce de détail de carburants",
    "56.29A": "Restauration collective sous contrat",
    "56.29B": "Autres services de restauration",
    "88.91A": "Accueil de jeunes enfants",
    "96.03Z": "Services funéraires",
}


def _flottant(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _diffusable(entreprise, etablissement):
    """Droit d'opposition INSEE : une unité non diffusible ne doit pas entrer, même si l'API la
    renvoie sous une forme partiellement masquée."""
    return (str(entreprise.get("statut_diffusion") or "O") == "O"
            and str(etablissement.get("statut_diffusion_etablissement") or "O") == "O")


def _ouvert(etablissement):
    return (not etablissement.get("date_fermeture")
            and str(etablissement.get("etat_administratif") or "A") == "A")


def _nom(entreprise, etablissement):
    """Le nom commercial quand il existe (« LA POSTE »), la raison sociale sinon. Pour une
    personne physique, la raison sociale EST son nom."""
    enseignes = etablissement.get("liste_enseignes") or []
    return (etablissement.get("nom_commercial") or (enseignes[0] if enseignes else None)
            or entreprise.get("nom_complet") or entreprise.get("nom_raison_sociale") or "")


def _vers_site(entreprise, etablissement, categorie, theme):
    if not _diffusable(entreprise, etablissement) or not _ouvert(etablissement):
        return None
    siret = etablissement.get("siret")
    if not siret:
        return None
    naf = etablissement.get("activite_principale") or entreprise.get("activite_principale")
    personne_physique = (
        str(entreprise.get("nature_juridique") or "") == NATURE_JURIDIQUE_PERSONNE_PHYSIQUE
    )
    return SitePropose(
        source=SourceSiteSensible.SIRENE,
        source_id=siret,
        categorie=categorie,
        nom=_nom(entreprise, etablissement),
        adresse=etablissement.get("adresse") or "",
        latitude=_flottant(etablissement.get("latitude")),
        longitude=_flottant(etablissement.get("longitude")),
        personne_physique=personne_physique,
        est_enjeu=theme.enjeu,
        est_ressource=theme.ressource,
        attributs={
            "siret": siret,
            "siren": entreprise.get("siren"),
            "naf": naf,
            "naf_libelle": LIBELLES_NAF.get(naf),
            "nature_juridique": entreprise.get("nature_juridique"),
            # Tranche INSEE, renseignée pour les seuls employeurs (12 des 68 élevages de
            # Châteauneuf) : un ordre de grandeur quand il existe, jamais une certitude.
            "tranche_effectif": etablissement.get("tranche_effectif_salarie"),
            # Clés de rapprochement avec les sources déjà branchées, pour reconnaître un
            # établissement déjà connu sous un autre identifiant.
            "uai": (etablissement.get("liste_uai") or [None])[0],
            "finess": (etablissement.get("liste_finess") or [None])[0],
            "date_maj_source": etablissement.get("date_mise_a_jour"),
        },
    )


def _collecter_theme(commune_code, categorie, theme):
    sites, page = [], 1
    while len(sites) < MAX_PAR_THEME:
        data = fetch_json(URL, {
            "code_commune": commune_code,
            "activite_principale": ",".join(theme.naf),
            "etat_administratif": "A",
            "per_page": TAILLE_PAGE,
            "page": page,
        })
        if not data or not data.get("results"):
            break
        for entreprise in data["results"]:
            for etablissement in (entreprise.get("matching_etablissements") or []):
                site = _vers_site(entreprise, etablissement, categorie, theme)
                if site is not None:
                    sites.append(site)
        if page >= (data.get("total_pages") or 1):
            break
        page += 1
    return sites


def collecter(commune_code, categories=None):
    """Collecte les thèmes demandés (tous ceux marqués par défaut si rien n'est précisé).

    Un thème inconnu est ignoré sans bruit : l'appelant valide déjà la liste, et une faute de
    frappe ne doit pas faire échouer les autres thèmes."""
    demandes = categories if categories else THEMES_PAR_DEFAUT
    sites = []
    for categorie in demandes:
        theme = THEMES.get(categorie)
        if theme is None:
            continue
        sites += _collecter_theme(commune_code, categorie, theme)
    return sites
