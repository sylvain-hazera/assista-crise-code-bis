"""Connecteurs open data alimentant SiteSensible (enjeux du territoire pour le plan de
sauvegarde communal). Voir base.py pour la règle commune : proposer, jamais décider."""
from ..models import SourceSiteSensible
from . import ecoles, equipements, finess, icpe

CONNECTEURS = {
    SourceSiteSensible.ANNUAIRE_EDUCATION: ecoles,
    SourceSiteSensible.FINESS: finess,
    SourceSiteSensible.ICPE: icpe,
    SourceSiteSensible.EQUIPEMENTS_SPORTIFS: equipements,
}

# FINESS ne tient pas dans une requête HTTP : son flux national fait ~50 Mo compressés, à lire en
# entier pour en extraire une commune (voir finess.py). Les trois autres sont des API filtrables
# par code INSEE qui répondent en quelques centaines de millisecondes.
SOURCES_ASYNCHRONES = {SourceSiteSensible.FINESS}
SOURCES_SYNCHRONES = [code for code in CONNECTEURS if code not in SOURCES_ASYNCHRONES]
