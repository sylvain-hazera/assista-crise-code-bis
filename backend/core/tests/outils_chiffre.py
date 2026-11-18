"""Filtrer, dans un essai, sur une colonne chiffrée : la base ne le peut pas (voir
core.crypto_fields.RequeteSurChampChiffre), on compare donc en Python après déchiffrement. Rend
un QuerySet : .exists(), .count(), .get(), .first() s'enchaînent comme avant."""

OPERATEURS = {
    "exact": lambda v, a: v == a,
    "iexact": lambda v, a: str(v).lower() == str(a).lower(),
    "contains": lambda v, a: str(a) in str(v),
    "icontains": lambda v, a: str(a).lower() in str(v).lower(),
    "startswith": lambda v, a: str(v).startswith(str(a)),
    "istartswith": lambda v, a: str(v).lower().startswith(str(a).lower()),
}


def _valeur(objet, morceaux):
    for m in morceaux:
        if objet is None:
            return None
        objet = getattr(objet, m)
    return objet


def filtrer_chiffre(qs, **criteres):
    def convient(objet):
        for cle, attendu in criteres.items():
            morceaux = cle.split("__")
            op = morceaux.pop() if morceaux[-1] in OPERATEURS else "exact"
            valeur = _valeur(objet, morceaux)
            if valeur is None or not OPERATEURS[op](valeur, attendu):
                return False
        return True
    return qs.filter(pk__in=[o.pk for o in qs.all() if convient(o)])
