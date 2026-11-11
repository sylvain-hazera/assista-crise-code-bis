"""Déduire un département d'un code postal — et dire quand on ne peut pas.

Besoin : l'import de bénévoles place chacun dans l'équipe départementale de son territoire, et
le fichier source ne porte qu'un code postal (jamais un code commune INSEE).

**Un code postal n'est PAS un code département**, et c'est la source d'erreur de toute
intégration de ce genre. Trois cas où la règle « les deux premiers chiffres » est fausse :

- **la Corse** : `20xxx` ne distingue pas la Corse-du-Sud (2A) de la Haute-Corse (2B). Les deux
  partagent le préfixe, et seule la commune tranche ;
- **l'outre-mer** : `971xx` à `976xx` demandent **trois** chiffres — `97` seul ne désigne aucun
  département ;
- **Monaco et quelques enclaves** : `98000` n'est pas un département français.

On rend donc `None` dans ces cas plutôt qu'un département plausible. Une ligne non résolue est
signalée à l'importateur, qui tranche ; deviner placerait un bénévole dans la mauvaise équipe,
et personne ne le verrait — ni lui, ni son coordinateur.
"""

#: Codes postaux d'outre-mer : le département tient sur les TROIS premiers chiffres.
PREFIXES_OUTRE_MER = {
    "971": "971",  # Guadeloupe
    "972": "972",  # Martinique
    "973": "973",  # Guyane
    "974": "974",  # La Réunion
    "976": "976",  # Mayotte
}

#: Préfixes qui ne désignent aucun département métropolitain exploitable sans la commune.
#: 20 : Corse, ambiguë entre 2A et 2B. 98 : Monaco et collectivités du Pacifique.
PREFIXES_AMBIGUS = {
    "20": "La Corse partage le préfixe 20 entre 2A et 2B : le code postal ne suffit pas, il "
          "faut la commune.",
    "98": "Le préfixe 98 ne correspond à aucun département français exploitable ici (Monaco, "
          "collectivités du Pacifique).",
}


def departement_depuis_code_postal(code_postal):
    """Renvoie `(code_departement, motif_d_echec)`.

    Exactement l'un des deux est renseigné. Le motif est destiné au rapport d'import : il doit
    dire à un humain ce qu'il doit corriger, pas « valeur invalide ».
    """
    code = (code_postal or "").strip().replace(" ", "")
    if not code:
        return None, "Code postal absent."

    # EXCEL SUPPRIME LE ZÉRO INITIAL. Un fichier passé par un tableur rend « 1000 » pour
    # « 01000 » (Ain), « 9100 » pour « 09100 » (Ariège) : quatre chiffres n'est jamais un code
    # postal français valide, c'est toujours un cinq-chiffres amputé. On le rétablit plutôt que
    # de rejeter la ligne — refuser ici ferait échouer tout un département pour une
    # particularité de tableur, et c'est le cas le plus fréquent du terrain.
    if code.isdigit() and len(code) == 4:
        code = "0" + code

    if not code.isdigit() or len(code) != 5:
        return None, f"« {code_postal} » n'est pas un code postal à 5 chiffres."

    if code[:3] in PREFIXES_OUTRE_MER:
        return PREFIXES_OUTRE_MER[code[:3]], None

    prefixe = code[:2]
    if prefixe in PREFIXES_AMBIGUS:
        return None, PREFIXES_AMBIGUS[prefixe]
    if prefixe == "00":
        return None, f"« {code} » ne correspond à aucun département."

    # 97 et 98 déjà traités ci-dessus ; 96 et au-delà n'existent pas en métropole.
    if prefixe >= "96":
        return None, f"« {code} » ne correspond à aucun département français."

    return prefixe, None
