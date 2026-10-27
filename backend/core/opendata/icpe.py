"""Sites industriels et installations classées — API Géorisques (ministère de la Transition
écologique).

Filtrable par code INSEE, sans clé. Le champ `statutSeveso` distingue les sites soumis à la
directive Seveso ; `ied` signale les installations relevant de la directive sur les émissions
industrielles. Licence Ouverte."""
from ..models import CategorieSiteSensible, SourceSiteSensible
from .base import MAX_RESULTATS, SitePropose, fetch_json

URL = "https://georisques.gouv.fr/api/v1/installations_classees"

# « Non ICPE » désigne des établissements sortis du régime (fermés, ou passés sous les seuils) :
# Géorisques les garde en base, ils n'ont rien à faire dans un plan de sauvegarde.
REGIMES_IGNORES = {"Non ICPE"}


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


def _vers_site(enregistrement):
    if (enregistrement.get("regime") or "") in REGIMES_IGNORES:
        return None
    code_aiot = enregistrement.get("codeAIOT")
    if not code_aiot:
        return None
    seveso = enregistrement.get("statutSeveso")
    return SitePropose(
        source=SourceSiteSensible.ICPE,
        source_id=code_aiot,
        categorie=CategorieSiteSensible.INDUSTRIE,
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
