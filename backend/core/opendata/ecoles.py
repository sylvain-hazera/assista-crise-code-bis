"""Établissements d'enseignement — Annuaire de l'éducation (ministère de l'Éducation nationale).

API Opendatasoft publique, filtrable par code commune ou par département, sans clé ni quota.
Licence Ouverte. Couvre public et privé, de la maternelle au lycée, plus les établissements
médico-sociaux rattachés à l'éducation nationale (IME, ITEP…).

C'est la source qui porte la hiérarchie des compétences scolaires, et elle la porte en clair :
`type_etablissement` et `statut_public_prive` suffisent à dire qui a la charge du bâtiment —
école publique à la commune, collège public au département, lycée public à la région. Mesuré sur
le Finistère : 852 établissements, dont 374 écoles publiques, 75 collèges publics et 40 lycées
publics. Sans cette distinction, un conseil départemental reçoit 852 lignes à relire au lieu
de 75."""
from ..models import CategorieSiteSensible, EchelonCompetence, SourceSiteSensible
from .base import SitePropose, collecter_ods, plafond, where_territoire

PORTAIL = "data.education.gouv.fr"
DATASET = "fr-en-annuaire-education"

# Les établissements fermés restent dans l'annuaire avec cet état : les proposer ferait
# travailler la mairie sur des écoles qui n'existent plus.
ETAT_OUVERT = "OUVERT"

# Qui a la charge du bâtiment, par type d'établissement public. Le privé sous contrat est à
# part : son bâtiment n'appartient à aucune collectivité, alors qu'il reste un enjeu en crise
# (302 des 852 établissements du Finistère).
ECHELON_PAR_TYPE = {
    "ECOLE": EchelonCompetence.COMMUNE,
    "COLLEGE": EchelonCompetence.DEPARTEMENT,
    "LYCEE": EchelonCompetence.REGION,
    "EREA": EchelonCompetence.REGION,
}

STATUT_PRIVE = "PRIVÉ"


def _sans_accent_majuscule(valeur):
    """« Collège » et « Lycée » arrivent accentués : on compare sur une forme stable."""
    table = str.maketrans("ÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸàâäçéèêëîïôöùûüÿ", "AAACEEEEIIOOUUUYaaaceeeeiioouuuy")
    return (valeur or "").translate(table).upper().strip()


def _echelon(enregistrement):
    statut = _sans_accent_majuscule(enregistrement.get("statut_public_prive"))
    type_etablissement = _sans_accent_majuscule(enregistrement.get("type_etablissement"))
    if statut.startswith("PRIVE"):
        return EchelonCompetence.PRIVE
    if type_etablissement.startswith("SERVICE"):
        return EchelonCompetence.ETAT
    for prefixe, echelon in ECHELON_PAR_TYPE.items():
        if type_etablissement.startswith(prefixe):
            return echelon
    # Médico-social public, « Information et orientation », types nouveaux : on ne devine pas.
    return EchelonCompetence.INDETERMINE


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
        commune_code=enregistrement.get("code_commune"),
        commune_nom=enregistrement.get("nom_commune"),
        echelon_competence=_echelon(enregistrement),
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


def collecter(perimetre):
    where = where_territoire(
        "code_commune", perimetre,
        champs_secteur={"departement": "code_departement", "region": "code_region"},
        # L'annuaire zéro-complète le code département sur trois caractères (« 029 »).
        codes_secteur={"departement": str(perimetre.code).zfill(3)},
    )
    return collecter_ods(PORTAIL, DATASET, where, _vers_site, maximum=plafond(perimetre))
