"""Chercher et trier sur des colonnes chiffrées.

Fernet n'étant pas déterministe, la base ne peut ni comparer ni trier une colonne chiffrée (voir
crypto_fields.RequeteSurChampChiffre). Décision du 06/10/2026, étendue le 18/11/2026 quand tout ce
qui est saisi est passé chiffré : on filtre et on trie en Python, après déchiffrement. Acceptable
aux volumes d'une plateforme de crise (quelques milliers de lignes par liste) ; le résultat reste
un QuerySet (`pk__in`), chaînable par la pagination et le reste du pipeline.
"""
from functools import reduce

from django.db.models import Q


def _valeur(objet, chemin):
    for morceau in chemin.split("__"):
        if objet is None:
            return ""
        objet = getattr(objet, morceau, None)
    return "" if objet is None else str(objet)


def _relations(chemins):
    return sorted({c.rsplit("__", 1)[0] for c in chemins if "__" in c})


def filtrer(queryset, terme, chemins_chiffres, chemins_sql=()):
    """Les lignes dont un des champs contient `terme` (sans casse). `chemins_sql` : champs en
    clair, cherchés par la base ; `chemins_chiffres` : cherchés en Python."""
    terme = (terme or "").strip().lower()
    if not terme:
        return queryset
    par_la_base = set()
    if chemins_sql:
        condition = reduce(lambda a, b: a | b, (Q(**{f"{c}__icontains": terme}) for c in chemins_sql))
        par_la_base = set(queryset.filter(condition).values_list("pk", flat=True))
    relations = _relations(chemins_chiffres)
    lignes = queryset.select_related(*relations) if relations else queryset
    en_python = {o.pk for o in lignes.order_by() if any(terme in _valeur(o, c).lower() for c in chemins_chiffres)}
    return queryset.filter(pk__in=par_la_base | en_python)


def trier(objets, *chemins):
    """Une liste triée sur des champs (éventuellement chiffrés), sans casse ; « -champ » inverse."""
    objets = list(objets)
    for chemin in reversed(chemins):
        inverse = chemin.startswith("-")
        chemin = chemin.lstrip("-")
        objets.sort(key=lambda o: _valeur(o, chemin).lower(), reverse=inverse)
    return objets
