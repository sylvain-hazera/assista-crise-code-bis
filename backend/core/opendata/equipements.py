"""Équipements sportifs et socioculturels — Recensement des équipements sportifs (ministère des
Sports), portail Opendatasoft, filtrable par code INSEE. Licence Ouverte.

Deux usages dans un plan de sauvegarde, d'où sa présence ici : ce sont des sites accueillant du
public (donc des enjeux à protéger), et ce sont les CANDIDATS NATURELS aux centres d'accueil —
un gymnase a des sanitaires, du chauffage et un parking. D'où l'action « en faire un point
opérationnel » côté vue : le nom, l'adresse et les coordonnées sont déjà là.

Attention à la qualité : le recensement est large. Sur Châteauneuf-du-Faou, 9 des 15
« installations » sont des écluses du canal de Nantes à Brest. C'est précisément pourquoi tout
sort en PROPOSE."""
from ..models import CategorieSiteSensible, SourceSiteSensible
from .base import SitePropose, collecter_ods

PORTAIL = "equipements.sports.gouv.fr"
DATASET = "data-es-installation"


def _vers_site(enregistrement):
    numero = enregistrement.get("numero")
    if not numero:
        return None
    coordonnees = enregistrement.get("coordonnees") or {}
    adresse = ", ".join(
        part for part in (
            (enregistrement.get("adresse") or "").strip(),
            " ".join(p for p in (enregistrement.get("cp"), enregistrement.get("commune")) if p),
        ) if part
    )
    return SitePropose(
        source=SourceSiteSensible.EQUIPEMENTS_SPORTIFS,
        source_id=numero,
        categorie=CategorieSiteSensible.RASSEMBLEMENT,
        nom=enregistrement.get("nom") or numero,
        adresse=adresse,
        latitude=coordonnees.get("lat"),
        longitude=coordonnees.get("lon"),
        attributs={
            "numero_installation": numero,
            # Une salle accessible aux personnes à mobilité réduite n'est pas un centre d'accueil
            # comme un autre : c'est le premier critère de choix quand il faut héberger.
            "acces_handicap": enregistrement.get("acces_handi"),
            "acces_transport_commun": enregistrement.get("acces_transp_commun"),
            "nombre_equipements": enregistrement.get("install_nb"),
            "date_maj_source": enregistrement.get("maj_date"),
        },
    )


def collecter(commune_code):
    return collecter_ods(PORTAIL, DATASET, f'insee="{commune_code}"', _vers_site)
