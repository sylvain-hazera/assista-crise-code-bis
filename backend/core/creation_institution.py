"""Qui a le droit de créer une institution, et sous quelle mère.

Règle posée par Sylvain le 12/11/2026, après avoir constaté des « Mairie debug test » dans le
référentiel national : **n'importe quel compte institutionnel pouvait créer n'importe quelle
institution**, à l'unité comme par import de fichier, et elle se retrouvait au même rang qu'une
mairie réelle.

Le besoin légitime existe pourtant, et il a deux visages :

- une **collectivité** crée ses satellites administratifs — CCAS, CIAS, médiathèque municipale,
  régie. Des entités réelles, distinctes d'elle, mais qui en dépendent ;
- une **association** crée ses échelons — un comité départemental sous l'association nationale
  (le cas Réserve Résilience).

Dans les deux cas la fille n'existe que **sous** sa mère, et c'est tout ce qui change par
rapport à avant : on ne retire pas le droit de créer, on retire le droit de créer **à côté**.

**Pourquoi l'institution mère n'est pas demandée à l'utilisateur** : il n'a pas le choix de la
mettre ailleurs. La poser d'office depuis son rattachement évite un champ de formulaire qui
n'aurait qu'une seule valeur possible — et évite surtout qu'on puisse en poser une autre.

**Ce que la règle n'interdit pas** : un administrateur de la plateforme crée ce qu'il veut, où
il veut, y compris une institution de plein exercice sans mère. C'est lui qui tient le
référentiel national des mairies ; le lui interdire fermerait la porte à celui-là même qui doit
pouvoir la franchir.
"""

#: Codes de type qu'une collectivité peut créer sous elle. Volontairement une liste OUVERTE :
#: une commune crée des entités que le référentiel national ne connaît pas (une régie des eaux,
#: un syndicat). Ce qui est contraint, c'est le RATTACHEMENT, pas la nature de la fille.
#: La seule exclusion est le type de la mère elle-même : une mairie ne crée pas une mairie.
TYPES_RESERVES_AU_REFERENTIEL = {"MAIRIE", "EPCI", "PREFECTURE", "SOUS_PREF", "SDIS",
                                 "GENDARMERIE", "CG", "CR"}


class CreationRefusee(Exception):
    """Refus explicite, avec un message destiné à l'utilisateur."""


def institution_mere(utilisateur):
    """L'institution sous laquelle ce compte peut créer, ou None s'il n'en a aucune."""
    return getattr(utilisateur, "institution", None)


def verifier_creation(utilisateur, est_admin, type_cible, mere):
    """Lève `CreationRefusee` si ce compte ne peut pas créer cette institution.

    `type_cible` est l'`InstitutionType` demandé (ou None), `mere` l'institution du créateur.
    """
    if est_admin:
        return

    if mere is None:
        raise CreationRefusee(
            "Votre compte n'est rattaché à aucune institution : vous ne pouvez pas en créer. "
            "Une institution créée ici dépend forcément de la vôtre."
        )

    code = (getattr(type_cible, "code", "") or "").upper()
    if code in TYPES_RESERVES_AU_REFERENTIEL:
        raise CreationRefusee(
            "Ce type d'institution fait partie du référentiel national et ne peut pas être "
            "créé ici. Vous pouvez créer une entité qui dépend de la vôtre — un CCAS, une "
            "régie, un comité départemental — mais pas une mairie, une préfecture ou un "
            "service de l'État. Signalez-nous l'institution manquante et nous l'ajouterons."
        )
