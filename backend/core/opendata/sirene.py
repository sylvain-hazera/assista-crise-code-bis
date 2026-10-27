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
import logging
from collections import namedtuple

from ..models import CategorieSiteSensible, EchelonCompetence, SourceSiteSensible
from .base import Collecte, SitePropose, fetch_json, pause

logger = logging.getLogger(__name__)

URL = "https://recherche-entreprises.api.gouv.fr/search"

# L'API plafonne `per_page` à 25.
TAILLE_PAGE = 25

# Par thème, et non global : un thème qui déborde ne doit pas priver les autres. Le plafond
# dépend du périmètre — mesuré sur le Finistère, « transport de marchandises » rend 483
# établissements et « travaux publics » 412, qu'un plafond de 200 tronquerait en silence.
MAX_PAR_THEME = {"commune": 200, "epci": 800, "departement": 1500}
MAX_PAR_THEME_DEFAUT = 1500

# L'API refuse `page * per_page > 10 000`, et le dit elle-même sans ambiguïté : « Le nombre
# total de résultats est restreint à 10 000. » Pire, elle PLAFONNE son propre `total_results` à
# ce chiffre, si bien qu'une requête tronquée ressemble exactement à une requête complète.
#
# Mesuré le 27/10/2026 : le thème « élevages » sur la région Nouvelle-Aquitaine annonce 10 000
# établissements. La somme de ses douze départements, interrogés un par un, en donne 48 499.
# Quatre cinquièmes du territoire disparaissaient sans un mot. C'est la raison d'être du
# découpage par tranches (voir sites_sensibles.tranches) : non pas étaler la charge, mais poser
# des questions auxquelles l'API sait répondre entièrement. Et quand il reste tronqué malgré
# tout, on le dit à l'agent (voir base.Collecte).
PLAFOND_RESULTATS = 10000

# Nature juridique 1000 = entrepreneur individuel, c'est-à-dire une personne physique.
NATURE_JURIDIQUE_PERSONNE_PHYSIQUE = "1000"

Theme = namedtuple("Theme", "libelle categorie naf enjeu ressource defaut")

# Ce qu'une collectivité peut demander à recenser. Un thème porte une catégorie de SiteSensible,
# une liste de codes NAF et un rôle par défaut (à protéger / mobilisable / les deux).
#
# Le thème est volontairement PLUS FIN que la catégorie : à l'échelle d'un département, un
# « moyens et travaux » unique rendrait 3 270 établissements dans le Finistère, inexploitable,
# alors que « transport de voyageurs » en rend 57 — et ce sont précisément les 57 autocaristes
# qui constituent le levier d'évacuation d'un conseil départemental. La catégorie reste large
# pour que les filtres de la page restent lisibles.
THEMES = {
    "ELEVAGE": Theme(
        libelle="Élevages", categorie=CategorieSiteSensible.ELEVAGE,
        naf=("01.41Z", "01.42Z", "01.43Z", "01.45Z", "01.46Z", "01.47Z", "01.49Z", "01.50Z",
             "01.62Z"),
        # Un cheptel à sauver, mais aussi un tracteur, une cuve, une bétaillère et des bras.
        enjeu=True, ressource=True, defaut=True),
    "VETERINAIRE": Theme(
        libelle="Vétérinaires", categorie=CategorieSiteSensible.VETERINAIRE,
        naf=("75.00Z",), enjeu=False, ressource=True, defaut=True),
    "HEBERGEMENT": Theme(
        libelle="Hôtels, campings, villages vacances",
        categorie=CategorieSiteSensible.HEBERGEMENT,
        naf=("55.10Z", "55.20Z", "55.30Z", "55.90Z"),
        # Un camping, c'est une population saisonnière à évacuer ET des lits disponibles.
        enjeu=True, ressource=True, defaut=True),
    "TRANSPORT_VOYAGEURS": Theme(
        libelle="Transport de voyageurs (autocars)", categorie=CategorieSiteSensible.MOYENS,
        naf=("49.31Z", "49.39A", "49.39B"), enjeu=False, ressource=True, defaut=True),
    "TRANSPORT_MARCHANDISES": Theme(
        libelle="Transport de marchandises (dont bétaillères)",
        categorie=CategorieSiteSensible.MOYENS,
        naf=("49.41A", "49.41B", "49.42Z"), enjeu=False, ressource=True, defaut=True),
    "TRAVAUX_PUBLICS": Theme(
        libelle="Travaux publics, terrassement, routes", categorie=CategorieSiteSensible.MOYENS,
        naf=("42.11Z", "43.11Z", "43.12A", "43.12B"), enjeu=False, ressource=True, defaut=True),
    "BATIMENT_URGENCE": Theme(
        libelle="Couverture et menuiserie (bâchage)", categorie=CategorieSiteSensible.MOYENS,
        naf=("43.91A", "43.91B", "43.32A"), enjeu=False, ressource=True, defaut=True),
    "APPROVISIONNEMENT": Theme(
        libelle="Commerces, boulangeries, carburants, repas",
        categorie=CategorieSiteSensible.APPROVISIONNEMENT,
        naf=("47.11B", "47.11C", "47.11D", "47.11E", "47.11F", "10.71C", "47.30Z",
             "56.29A", "56.29B"),
        enjeu=False, ressource=True, defaut=True),
    # Les parcs animaliers n'arrivaient que par Géorisques, et seulement les CLASSÉS : la
    # rubrique ICPE 2140 (« présentation au public d'animaux d'espèces non domestiques ») rend
    # 8 établissements pour le Loir-et-Cher et la Dordogne réunis — Beauval, l'aquarium du
    # Périgord noir, la réserve zoologique de Calviac, le parc animalier du Thot. Tout ce qui
    # est sous les seuils du classement — fermes pédagogiques, petits aquariums, refuges,
    # volières — n'apparaissait nulle part, alors que ce sont des animaux captifs, donc
    # entièrement dépendants de leurs soigneurs en cas d'évacuation ou de coupure longue.
    #
    # Le code NAF 91.04Z mélange trois choses (1 040 en France, 32 en Dordogne, 17 dans le
    # Finistère) : des zoos, des parcs botaniques et des associations de protection de la
    # nature. On le range quand même en ELEVAGE, et c'est un choix : un parc botanique mal
    # classé se corrige d'un clic, alors qu'un zoo absent de la liste des animaux est un trou
    # dans le plan. Le libellé NAF est affiché sur la ligne pour que l'arbitrage soit évident.
    "PARCS_ANIMALIERS": Theme(
        libelle="Parcs animaliers, zoos, aquariums",
        categorie=CategorieSiteSensible.ELEVAGE,
        naf=("91.04Z",),
        # Ressource autant qu'enjeu : un parc animalier est souvent le seul endroit d'un
        # département où des gens savent contenir, soigner et transporter un animal de deux
        # tonnes — exactement la compétence qui manque quand il faut évacuer un cheptel.
        enjeu=True, ressource=True, defaut=True),
    "FUNERAIRE": Theme(
        libelle="Opérateurs funéraires", categorie=CategorieSiteSensible.FUNERAIRE,
        naf=("96.03Z",), enjeu=False, ressource=True, defaut=True),
    # Décoché par défaut, et c'est délibéré : en commune rurale, « accueil de jeunes enfants »
    # ramène surtout des assistantes maternelles, donc des noms de personnes à leur domicile.
    # À activer en connaissance de cause, pas par défaut.
    "PETITE_ENFANCE": Theme(
        libelle="Accueil du jeune enfant", categorie=CategorieSiteSensible.PETITE_ENFANCE,
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
    "91.04Z": "Gestion des jardins botaniques et zoologiques et des réserves naturelles",
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


def _echelon(entreprise):
    """Les catégories juridiques 4xxx et 7xxx désignent des personnes morales de droit public.
    Elles disent « public » sans dire quel échelon (État, région, département, commune) : on ne
    tranche pas à leur place, l'agent le fera. Tout le reste est privé ou associatif."""
    nature = str(entreprise.get("nature_juridique") or "")
    if nature.startswith(("4", "7")):
        return EchelonCompetence.INDETERMINE
    return EchelonCompetence.PRIVE


def _vers_site(entreprise, etablissement, theme):
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
        categorie=theme.categorie,
        nom=_nom(entreprise, etablissement),
        adresse=etablissement.get("adresse") or "",
        latitude=_flottant(etablissement.get("latitude")),
        longitude=_flottant(etablissement.get("longitude")),
        personne_physique=personne_physique,
        est_enjeu=theme.enjeu,
        est_ressource=theme.ressource,
        commune_code=etablissement.get("commune"),
        commune_nom=etablissement.get("libelle_commune"),
        echelon_competence=_echelon(entreprise),
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


def _filtres_territoire(perimetre):
    """L'API a un filtre `departement` et un filtre `region` natifs — une requête au lieu de
    277. Sans eux (EPCI, commune), un filtre par commune."""
    if perimetre.niveau == "departement":
        return [{"departement": perimetre.code}]
    if perimetre.niveau == "region":
        return [{"region": perimetre.code}]
    return [{"code_commune": code} for code in perimetre.communes]


def _params_theme(theme):
    return {"activite_principale": ",".join(theme.naf), "etat_administratif": "A"}


def _total_annonce(filtre, theme):
    """Ce que l'API dit du nombre d'établissements, en un appel à un résultat.

    Payé volontairement : c'est le seul moyen de distinguer « 10 000 établissements » de
    « au moins 10 000, et nous n'en saurons pas plus » (voir PLAFOND_RESULTATS)."""
    data = fetch_json(URL, {**filtre, **_params_theme(theme), "per_page": 1})
    return None if data is None else data.get("total_results")


def _collecter_filtre(filtre, theme, maximum):
    """Pagine un filtre. Rend (sites, complet) — `complet` dit si la source était au bout."""
    sites, page = [], 1
    pages_max = PLAFOND_RESULTATS // TAILLE_PAGE
    while len(sites) < maximum and page <= pages_max:
        if page > 1:
            pause()
        data = fetch_json(URL, {**filtre, **_params_theme(theme),
                                "per_page": TAILLE_PAGE, "page": page})
        if not data or not data.get("results"):
            return sites[:maximum], True
        for entreprise in data["results"]:
            for etablissement in (entreprise.get("matching_etablissements") or []):
                site = _vers_site(entreprise, etablissement, theme)
                if site is not None:
                    sites.append(site)
        if page >= (data.get("total_pages") or 1):
            return sites[:maximum], True
        page += 1
    return sites[:maximum], False


def _collecter_theme(perimetre, theme, maximum):
    """Collecte un thème sur le périmètre. Rend (sites, raison d'incomplétude ou None)."""
    filtres = _filtres_territoire(perimetre)
    sites, raisons = [], []

    # Le plafond de l'API ne se constate que sur un filtre de secteur : une commune seule n'en
    # approche jamais. Un appel à un résultat suffit à le savoir avant de paginer pour rien.
    if len(filtres) == 1 and "code_commune" not in filtres[0]:
        total = _total_annonce(filtres[0], theme)
        if total is not None and total >= PLAFOND_RESULTATS:
            raisons.append(
                f"l'annuaire des entreprises ne sert jamais plus de {PLAFOND_RESULTATS} "
                f"résultats et plafonne son propre compte à ce chiffre — le nombre réel "
                f"d'établissements est inconnu et supérieur")
        pause()

    for rang, filtre in enumerate(filtres):
        if len(sites) >= maximum:
            break
        if rang:
            pause()
        trouves, complet = _collecter_filtre(filtre, theme, maximum - len(sites))
        sites += trouves
        if not complet:
            break

    if len(sites) >= maximum:
        raisons.append(f"{maximum} établissements retenus au plus pour ce thème")
    return sites, " ; ".join(raisons) or None


def collecter(perimetre, themes=None):
    """Collecte les thèmes demandés (tous ceux marqués par défaut si rien n'est précisé).

    Un thème inconnu est ignoré sans bruit : l'appelant valide déjà la liste, et une faute de
    frappe ne doit pas faire échouer les autres thèmes.

    Ce qui est incomplet remonte dans la Collecte, thème par thème, en français : à l'échelle
    d'un département un recensement thématique est un ÉCHANTILLON, et l'agent doit le savoir
    avant d'en faire un plan de sauvegarde."""
    demandes = themes if themes else THEMES_PAR_DEFAUT
    maximum = MAX_PAR_THEME.get(perimetre.niveau, MAX_PAR_THEME_DEFAUT)
    sites, raisons = [], []
    for rang, code in enumerate(demandes):
        theme = THEMES.get(code)
        if theme is None:
            continue
        if rang:
            pause()
        trouves, raison = _collecter_theme(perimetre, theme, maximum)
        sites += trouves
        if raison:
            logger.warning("SIRENE : thème %s incomplet sur le périmètre %s %s — %s",
                           code, perimetre.niveau, perimetre.code, raison)
            raisons.append(f"{theme.libelle} : {raison}")
    return Collecte(sites, " ; ".join(raisons) or None)
