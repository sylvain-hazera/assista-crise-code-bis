"""Connecteurs open data alimentant SiteSensible (enjeux du territoire pour le plan de
sauvegarde communal). Voir base.py pour la règle commune : proposer, jamais décider."""
from ..models import SourceSiteSensible
from . import dae, ecoles, equipements, finess, icpe, sirene

CONNECTEURS = {
    SourceSiteSensible.ANNUAIRE_EDUCATION: ecoles,
    SourceSiteSensible.FINESS: finess,
    SourceSiteSensible.ICPE: icpe,
    SourceSiteSensible.EQUIPEMENTS_SPORTIFS: equipements,
    SourceSiteSensible.SIRENE: sirene,
    SourceSiteSensible.GEODAE: dae,
}

# Trois sources ne tiennent pas dans une requête HTTP. Géo'DAE : un fichier national de ~80 Mo
# à lire en entier, comme FINESS (voir dae.py). FINESS : son flux national fait ~50 Mo
# compressés, à lire en entier pour en extraire une commune (voir finess.py). SIRENE : jusqu'à
# onze thèmes paginés 25 par 25, soit une cinquantaine d'appels sur une grande ville. Les trois
# autres sont des API filtrables par code INSEE qui répondent en quelques centaines de
# millisecondes.
SOURCES_ASYNCHRONES = {SourceSiteSensible.FINESS, SourceSiteSensible.SIRENE,
                       SourceSiteSensible.GEODAE}
SOURCES_SYNCHRONES = [code for code in CONNECTEURS if code not in SOURCES_ASYNCHRONES]

# Le découpage d'un périmètre large en tranches départementales (voir sites_sensibles.tranches)
# sert les sources interrogées par requête : il leur évite le plafond de résultats de leur API.
# FINESS n'y gagne rien et y perdrait tout : son flux national est lu EN ENTIER quel que soit le
# périmètre, donc le découper en douze ferait télécharger douze fois les mêmes 50 Mo et relire
# douze fois les mêmes 750 Mo de JSON.
# Géo'DAE est dans le même cas : un fichier national, lu en entier.
SOURCES_SANS_DECOUPAGE = {SourceSiteSensible.FINESS, SourceSiteSensible.GEODAE}
