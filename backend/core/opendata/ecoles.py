"""Établissements d'enseignement — Annuaire de l'éducation (ministère de l'Éducation nationale).

API Opendatasoft publique, filtrable par code commune, sans clé ni quota. Licence Ouverte.
Couvre public et privé, de la maternelle au lycée, plus les établissements médico-sociaux
rattachés à l'éducation nationale (IME, ITEP…)."""
from ..models import CategorieSiteSensible, SourceSiteSensible
from .base import SitePropose, collecter_ods

PORTAIL = "data.education.gouv.fr"
DATASET = "fr-en-annuaire-education"

# Les établissements fermés restent dans l'annuaire avec cet état : les proposer ferait
# travailler la mairie sur des écoles qui n'existent plus.
ETAT_OUVERT = "OUVERT"


def _adresse(enregistrement):
    lignes = [enregistrement.get(f"adresse_{i}") for i in (1, 2, 3)]
    rue = " ".join(ligne.strip() for ligne in lignes if ligne and ligne.strip())
    ville = " ".join(
        part for part in (enregistrement.get("code_postal"), enregistrement.get("nom_commune")) if part
    )
    return ", ".join(part for part in (rue, ville) if part)


def _vers_site(enregistrement):
    if (enregistrement.get("etat") or "").upper() != ETAT_OUVERT:
        return None
    uai = enregistrement.get("identifiant_de_l_etablissement")
    if not uai:
        return None
    return SitePropose(
        source=SourceSiteSensible.ANNUAIRE_EDUCATION,
        source_id=uai,
        categorie=CategorieSiteSensible.ENSEIGNEMENT,
        nom=enregistrement.get("nom_etablissement") or uai,
        adresse=_adresse(enregistrement),
        latitude=enregistrement.get("latitude"),
        longitude=enregistrement.get("longitude"),
        telephone=enregistrement.get("telephone") or "",
        attributs={
            "uai": uai,
            "type_etablissement": enregistrement.get("type_etablissement"),
            "statut": enregistrement.get("statut_public_prive"),
            # Déterminants pour un plan de sauvegarde : un internat, ce sont des enfants présents
            # la nuit ; une cantine, c'est une cuisine mobilisable pour un centre d'accueil.
            "hebergement": enregistrement.get("hebergement"),
            "restauration": enregistrement.get("restauration"),
            "date_maj_source": enregistrement.get("date_maj_ligne"),
        },
    )


def collecter(commune_code):
    return collecter_ods(PORTAIL, DATASET, f'code_commune="{commune_code}"', _vers_site)
