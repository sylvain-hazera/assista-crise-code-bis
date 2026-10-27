"""Sites industriels, élevages et installations classées — API Géorisques (ministère de la
Transition écologique).

Filtrable par code INSEE, sans clé. Le champ `statutSeveso` distingue les sites soumis à la
directive Seveso ; `ied` signale les installations relevant de la directive sur les émissions
industrielles. Licence Ouverte.

Les élevages sortent de cette même API et sont rangés à part (catégorie ELEVAGE) : la protection
des animaux est une mission possible du plan de sauvegarde, et un élevage ne se planifie pas
comme une usine. Évacuer un cheptel demande des bétaillères et des heures ; une coupure
électrique longue arrête la traite, la ventilation des bâtiments et l'abreuvement ; une
inondation ou un feu qui approche impose de savoir, avant, combien d'animaux sont où. Les
rubriques ICPE donnent l'effectif autorisé (« 56 000 volailles », « 1 232 animaux-équivalents
porcs ») : c'est l'ordre de grandeur dont la commune a besoin, on le remonte tel quel.

Le classement élevage/industrie est une proposition comme le reste : il s'appuie sur les
rubriques, le code NAF et les indicateurs d'espèce de Géorisques, et l'agent voit la rubrique en
clair sur la ligne pour le corriger d'un clic.
"""
import re

from ..models import CategorieSiteSensible, SourceSiteSensible
from .base import MAX_RESULTATS, SitePropose, fetch_json

URL = "https://georisques.gouv.fr/api/v1/installations_classees"

# « Non ICPE » désigne des établissements sortis du régime (fermés, ou passés sous les seuils) :
# Géorisques les garde en base. On les écarte — sauf quand l'établissement a l'air d'une
# exploitation : une ferme repassée sous le seuil ICPE garde ses animaux, et c'est justement ce
# qu'il faut savoir avant une évacuation.
REGIMES_IGNORES = {"Non ICPE"}

# Rubriques de la nomenclature ICPE qui signalent une présence animale : 2101 bovins,
# 2102 porcs, 2110 lapins, 2111 volailles, 2120 chiens, 2130 piscicultures, 2140 animaux
# d'espèces non domestiques (parcs animaliers), 2180 établissements de monte, 3660 élevage
# intensif relevant de la directive IED.
RUBRIQUES_ANIMAUX = {"2101", "2102", "2110", "2111", "2120", "2130", "2140", "2180", "3660"}

# Filet de sécurité sur le libellé de la rubrique : la nomenclature est renumérotée de temps en
# temps, le libellé reste explicite. Volontairement sans « animaux » seul, qui attraperait les
# usines d'aliments du bétail.
MOTS_ANIMAUX = (
    "élevage", "elevage", "volaille", "porc", "bovin", "veau", "lapin", "pisciculture",
    "chien", "équidé", "equidé", "ovin", "caprin", "espèces non domestiques",
)

# Section 01 de la NAF : « culture et production animale ». Rattrape les exploitations déclarées
# sans rubrique détaillée, qui existent (« Autres régimes ») et comptent autant.
PREFIXE_NAF_AGRICOLE = "01"

# Formes juridiques que la loi réserve à l'agriculture : un GAEC (groupement agricole
# d'exploitation en commun), une EARL (exploitation agricole à responsabilité limitée) ou une
# SCEA (société civile d'exploitation agricole) ne peut rien être d'autre. Dernier repli, et il
# compte : Géorisques laisse souvent le code NAF vide et ne détaille pas les rubriques des
# établissements simplement déclarés, si bien que sans lui la moitié des élevages d'une commune
# bretonne arrivait en « site industriel ».
MOTIF_FORME_AGRICOLE = re.compile(r"\b(GAEC|EARL|SCEA)\b")

# Libellé affichable par mot-clé trouvé dans la rubrique, pour que la commune lise « porcs » et
# pas « 2102 ».
ESPECES = (
    ("volaille", "volailles"),
    ("porc", "porcs"),
    ("bovin", "bovins"),
    ("veau", "veaux"),
    ("lapin", "lapins"),
    ("équidé", "équidés"),
    ("equidé", "équidés"),
    ("ovin", "ovins"),
    ("caprin", "caprins"),
    ("chien", "chiens"),
    ("pisciculture", "poissons"),
    ("espèces non domestiques", "animaux d'espèces non domestiques"),
)


def _adresse(enregistrement):
    rue = " ".join(
        (enregistrement.get(f"adresse{i}") or "").strip() for i in (1, 2, 3)
    ).strip()
    ville = " ".join(
        part for part in (enregistrement.get("codePostal"), enregistrement.get("commune")) if part
    )
    return ", ".join(part for part in (rue, ville) if part)


def _date_maj(valeur):
    """`date_maj` arrive au format « 2024-09-04/14-48-00 » : on ne garde que la date."""
    return (valeur or "").split("/")[0] or None


def _rubriques(enregistrement):
    valeur = enregistrement.get("rubriques")
    return valeur if isinstance(valeur, list) else []


def _est_rubrique_animale(rubrique):
    if (rubrique.get("numeroRubrique") or "").strip() in RUBRIQUES_ANIMAUX:
        return True
    nature = (rubrique.get("nature") or "").lower()
    return any(mot in nature for mot in MOTS_ANIMAUX)


def _quantite(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _espece_de(nature):
    """L'espèce que désigne le libellé de la rubrique, nommée comme la mairie la nommerait."""
    texte = (nature or "").lower()
    for mot, libelle in ESPECES:
        if mot in texte:
            return libelle
    return None


def _cheptel(rubriques):
    """L'effectif animal autorisé, rubrique par rubrique : ce qu'il faudrait déplacer."""
    return [
        {
            "rubrique": (rubrique.get("numeroRubrique") or "").strip() or None,
            "nature": rubrique.get("nature"),
            "espece": _espece_de(rubrique.get("nature")),
            "quantite": _quantite(rubrique.get("quantiteTotale")),
            "unite": rubrique.get("unite"),
        }
        for rubrique in rubriques
        if _est_rubrique_animale(rubrique)
    ]


def _especes(enregistrement, rubriques_animales):
    """Les espèces présentes, en français. Géorisques a trois indicateurs (`bovins`, `porcs`,
    `volailles`) mais les laisse souvent à faux sur des élevages que la rubrique désigne
    clairement : on prend l'union des deux."""
    trouvees = []
    for champ, libelle in (("bovins", "bovins"), ("porcs", "porcs"), ("volailles", "volailles")):
        if enregistrement.get(champ) and libelle not in trouvees:
            trouvees.append(libelle)
    for rubrique in rubriques_animales:
        libelle = _espece_de(rubrique.get("nature"))
        if libelle and libelle not in trouvees:
            trouvees.append(libelle)
    return trouvees


def _est_elevage(enregistrement, rubriques_animales):
    if rubriques_animales:
        return True
    if any(enregistrement.get(champ) for champ in ("bovins", "porcs", "volailles")):
        return True
    if (enregistrement.get("codeNaf") or "").startswith(PREFIXE_NAF_AGRICOLE):
        return True
    return bool(MOTIF_FORME_AGRICOLE.search((enregistrement.get("raisonSociale") or "").upper()))


def _vers_site(enregistrement):
    code_aiot = enregistrement.get("codeAIOT")
    if not code_aiot:
        return None
    rubriques_animales = [r for r in _rubriques(enregistrement) if _est_rubrique_animale(r)]
    elevage = _est_elevage(enregistrement, rubriques_animales)
    if (enregistrement.get("regime") or "") in REGIMES_IGNORES and not elevage:
        return None
    seveso = enregistrement.get("statutSeveso")
    return SitePropose(
        source=SourceSiteSensible.ICPE,
        source_id=code_aiot,
        categorie=(
            CategorieSiteSensible.ELEVAGE if elevage else CategorieSiteSensible.INDUSTRIE
        ),
        nom=enregistrement.get("raisonSociale") or code_aiot,
        adresse=_adresse(enregistrement),
        latitude=enregistrement.get("latitude"),
        longitude=enregistrement.get("longitude"),
        attributs={
            "code_aiot": code_aiot,
            "regime": enregistrement.get("regime"),
            "statut_seveso": seveso,
            "ied": enregistrement.get("ied"),
            "industrie": enregistrement.get("industrie"),
            "siret": enregistrement.get("siret"),
            # Géorisques distingue « En exploitation avec titre » et « En fin d'exploitation » ;
            # on ne filtre pas sur ce champ (un site en cessation garde du stock et des animaux
            # le temps de la remise en état), on le montre à l'agent.
            "etat_activite": enregistrement.get("etatActivite"),
            "especes": _especes(enregistrement, rubriques_animales),
            "cheptel": _cheptel(rubriques_animales),
            "date_maj_source": _date_maj(enregistrement.get("date_maj")),
        },
    )


def collecter(commune_code):
    sites, page = [], 1
    while len(sites) < MAX_RESULTATS:
        data = fetch_json(URL, {"code_insee": commune_code, "page": page, "page_size": 100})
        if not data or not data.get("data"):
            break
        for enregistrement in data["data"]:
            site = _vers_site(enregistrement)
            if site is not None:
                sites.append(site)
        if page >= (data.get("total_pages") or 1):
            break
        page += 1
    return sites
