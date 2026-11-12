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


def equipe_de_rattachement(institution):
    """L'équipe sous laquelle accrocher celle d'une institution fille.

    On prend l'équipe de tête de la mère : celle qui n'a pas elle-même de parente, et la plus
    ancienne s'il y en a plusieurs. Une mairie peut avoir dix équipes (logistique, accueil,
    astreinte) ; accrocher la médiathèque à l'une d'elles au hasard donnerait un arbre faux,
    tandis que la racine est toujours le bon niveau — le chef d'équipe la déplacera s'il le
    souhaite, et c'est un geste qui lui appartient."""
    from .models import Team

    if institution is None:
        return None
    return (Team.objects
            .filter(institution=institution, actif=True, equipe_parente__isnull=True)
            .order_by("created_at")
            .first())


def creer_equipe_fille(institution_fille, institution_mere, utilisateur, environnement):
    """Crée l'équipe de l'institution fille, rattachée à celle de la mère.

    Demande de Sylvain du 12/11/2026 : « la création de la médiathèque entraîne la création de
    l'équipe médiathèque, avec leurs coordonnées, et la possibilité de les contacter en
    campagne pour savoir si l'équipe médiathèque peut apporter son soutien pour les
    divertissements sur un centre d'accueil ».

    **Pourquoi l'équipe et pas seulement l'institution.** Une institution est une entité
    administrative : elle ne reçoit pas de campagne de disponibilité, ne porte pas de mission
    et n'apparaît pas dans la constitution d'équipe. C'est l'ÉQUIPE qui est l'unité
    opérationnelle. Créer l'une sans l'autre obligeait à y penser ensuite — et personne n'y
    pense le jour où l'on en a besoin.

    Elle hérite des coordonnées de son institution : c'est le même standard, le même
    téléphone, et les resaisir serait les faire diverger au premier changement.

    **Celui qui crée n'en devient PAS membre** (correction de Sylvain, le soir même) : un DSI
    crée l'équipe de la médiathèque sans en faire partie pour autant. L'écran lui propose
    ensuite, au choix, d'y entrer lui-même ou d'inviter ses vrais membres par leur adresse
    email — voir `TeamViewSet.rejoindre` et `ContactInstitutionViewSet.inviter`.

    La création échoue en silence — jamais au prix de l'institution elle-même. L'équipe se
    recrée à la main depuis la page Équipes ; l'institution, non.
    """
    from .models import Team

    try:
        parente = equipe_de_rattachement(institution_mere)
        equipe = Team.objects.create(
            name=institution_fille.nom_affichage or institution_fille.nom,
            description=f"Équipe de {institution_fille.nom}.",
            institution=institution_fille,
            equipe_parente=parente,
            environment=environnement,
        )
        return equipe
    except Exception:  # noqa: BLE001 - voir la docstring : jamais au prix de l'institution
        return None


def gere_institution(utilisateur, institution, est_admin=False):
    """Ce compte peut-il agir pour cette institution — elle-même, ou sa mère ?

    Une mère répond de ses filles : la mairie qui a créé la médiathèque doit pouvoir y
    inviter du monde, sinon l'équipe naîtrait vide et le resterait. La réciproque est fausse,
    et volontairement : un membre de la médiathèque n'agit pas pour la mairie."""
    from .models import ContactInstitution

    if est_admin:
        return True
    if institution is None or not getattr(utilisateur, "is_authenticated", False):
        return False
    cibles = [institution.id]
    if institution.institution_parente_id:
        cibles.append(institution.institution_parente_id)
    return ContactInstitution.objects.filter(
        institution_id__in=cibles, utilisateur=utilisateur, actif=True).exists()
