"""Contrôle d'accès au registre communal des personnes vulnérables (recensement PCS).

**Régime : l'art. R. 121-7 du CASF**, qui réserve le traitement de ces données au maire et aux
agents des services municipaux, du CCAS et le cas échéant du CIAS *nommément désignés et
habilités*, tenus au secret professionnel. Deux conséquences qui gouvernent tout ce module :

1. **La désignation est nominative.** Appartenir à la RCSC ou porter un rôle RESPONSABLE n'est
   pas une désignation : c'est une fonction, pas un acte du maire visant une personne. Jusqu'au
   28/10/2026 la branche mairie reposait sur ce critère d'équipe ; elle repose désormais sur
   HabilitationRegistreVulnerables, qui le REMPLACE (`utilisateur_a_acces_rcsc` subsiste
   seulement pour proposer des candidats à la désignation, voir son docstring).
2. **Le secret professionnel est un engagement personnel.** Toute personne qui touche au
   registre -- mairie, association délégataire, administrateur de la plateforme -- doit l'avoir
   signé (User.engagement_secret_registre_le). Une désignation non contresignée ouvre l'écran
   qui fait signer, et rien d'autre.

**Lecture et écriture ne sont pas gardées par la même fonction**, et c'est voulu :

- `filter_personnes_vulnerables_queryset` / `communes_accessibles` gardent la **lecture**.
  ADMINISTRATOR y conserve une vue complète, pour l'exploitation et le support, entièrement
  journalisée.
- `institution_accede_commune` garde l'**écriture** (création, modification, radiation) et
  **exclut ADMINISTRATOR**. Inscrire quelqu'un au registre est un acte de la collectivité : un
  administrateur de plateforme qui inscrit est une personne non désignée par le maire dans la
  chaîne de traitement, ce que R. 121-7 interdit, et cela déplacerait le responsable de
  traitement de la commune vers l'éditeur. Voir BASE-LEGALE-REGISTRE-VULNERABLES.md § 5.

Une institution tierce (association, AASC) garde l'accès standard dès lors qu'elle détient une
DelegationCompetence active sur la commune -- la délégation est elle-même un acte de la mairie,
elle n'a donc pas à être redoublée d'une désignation individuelle ; seul l'engagement au secret
s'y ajoute.
"""
from django.db.models import Q
from django.utils import timezone

from .habitations import _delegation_couvre_commune
from .models import (
    AffectationRoleOperationnel,
    DelegationCompetence,
    HabilitationRegistreVulnerables,
    Team,
    UserRole,
    VERSION_ENGAGEMENT_SECRET_REGISTRE,
)

NOM_COMPETENCE_VULNERABILITES = "Recensement personnes vulnérables"
CODE_ROLE_RESPONSABLE = "RESPONSABLE"

#: Texte de l'engagement présenté à la première connexion après la désignation, puis résumé en
#: bandeau permanent. Servi par l'API et non écrit en dur dans le front : le texte est l'objet
#: même de la signature, il doit avoir une source unique et une version (voir
#: VERSION_ENGAGEMENT_SECRET_REGISTRE) pour qu'on sache ce qui a été signé.
TEXTE_ENGAGEMENT_SECRET = """Vous avez été nommément désigné pour tenir le registre communal des \
personnes vulnérables de votre commune, en application de l'article R. 121-7 du code de l'action \
sociale et des familles.

Ce registre contient des données personnelles de personnes âgées ou en situation de handicap. \
Son usage est strictement encadré :

1. Vous êtes tenu au secret professionnel sur l'ensemble de son contenu. Sa violation est punie \
d'un an d'emprisonnement et de 15 000 euros d'amende (article 226-13 du code pénal).
2. Vous ne consultez une fiche que si l'exercice de vos fonctions l'exige -- besoin d'en \
connaître, article R. 121-8 du même code.
3. Vous ne communiquez ces données qu'aux services sanitaires, sociaux et médico-sociaux \
destinataires, dans la limite de leurs attributions.
4. Toute réutilisation à des fins électorales ou commerciales est interdite.
5. Vous n'inscrivez aucune donnée de santé ni aucun diagnostic : le registre ne décrit que des \
besoins fonctionnels.
6. Chacune de vos consultations et de vos saisies est journalisée au nom de votre compte.

En poursuivant, vous attestez avoir pris connaissance de ces obligations et vous engagez à les \
respecter."""

#: Rappel court, affiché en permanence sur chaque écran du registre.
RAPPEL_SECRET_BANDEAU = (
    "Registre communal des personnes vulnérables — données couvertes par le secret "
    "professionnel (art. R. 121-7 du CASF). Consultation limitée au besoin d'en connaître ; "
    "toute violation est punie d'un an d'emprisonnement et de 15 000 € d'amende (art. 226-13 "
    "du code pénal). Vos accès sont journalisés."
)


def equipes_rcsc(institution) -> set:
    """IDs des Team formant la RCSC de `institution` : les équipes marquées
    `est_equipe_rcsc=True`, PLUS récursivement tout leur sous-arbre via `equipe_parente` (une
    RCSC scindée en sous-équipes reste UNE RCSC, voir Team.est_equipe_rcsc)."""
    racines = set(
        Team.objects.filter(institution=institution, est_equipe_rcsc=True)
        .values_list("id", flat=True)
    )
    ids, frontiere = set(racines), list(racines)
    while frontiere:
        enfants = set(
            Team.objects.filter(equipe_parente_id__in=frontiere)
            .exclude(id__in=ids)
            .values_list("id", flat=True)
        )
        if not enfants:
            break
        ids |= enfants
        frontiere = list(enfants)
    return ids


def utilisateur_a_acces_rcsc(user, institution) -> bool:
    """RESPONSABLE actif de `institution` OU membre d'une Team de sa RCSC (ou sous-équipe).

    **N'ouvre plus aucun accès au registre** depuis le passage à l'habilitation nominative : ne
    sert qu'à mettre en tête de liste, dans l'écran de désignation, les agents qu'il est
    plausible de désigner. Conservé sous ce nom parce que c'est la définition de la RCSC, utile
    en elle-même."""
    if institution is None:
        return False
    if AffectationRoleOperationnel.objects.filter(
        utilisateur=user, institution=institution, role__code=CODE_ROLE_RESPONSABLE, actif=True,
    ).exists():
        return True
    ids_rcsc = equipes_rcsc(institution)
    if not ids_rcsc:
        return False
    return (
        Team.objects.filter(id__in=ids_rcsc, actif=True)
        .filter(Q(leader=user) | Q(members=user))
        .exists()
    )


def engagement_secret_signe(user) -> bool:
    """True si `user` a signé la version COURANTE de l'engagement au secret professionnel.

    La comparaison porte sur la version et pas seulement sur la présence d'une date : si le
    texte de l'engagement change, une signature donnée sur l'ancien texte n'engage à rien et
    doit être redemandée."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(
        user.engagement_secret_registre_le
        and user.engagement_secret_registre_version == VERSION_ENGAGEMENT_SECRET_REGISTRE
    )


def habilitation_active(user, institution):
    """L'habilitation nominative vivante de `user` sur `institution`, ou None.

    Renvoie l'objet et non un booléen : les appelants ont besoin de la ligne elle-même pour
    journaliser au titre de quelle désignation l'accès a eu lieu, et pour dire à l'écran qui a
    désigné."""
    if user is None or institution is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        HabilitationRegistreVulnerables.objects.filter(
            utilisateur=user, institution=institution, actif=True,
        )
        .filter(Q(date_fin__isnull=True) | Q(date_fin__gt=timezone.now()))
        .first()
    )


def _delegations_actives(institution):
    return (
        DelegationCompetence.objects.filter(
            institution_cible=institution,
            competence__nom=NOM_COMPETENCE_VULNERABILITES,
            active=True,
        )
        .filter(Q(date_fin__isnull=True) | Q(date_fin__gt=timezone.now()))
    )


def designation_en_place(request, commune_code: str) -> bool:
    """La désignation existe-t-elle, indépendamment de l'engagement au secret ?

    Sépare les deux refus possibles, pour que l'écran puisse dire lequel s'applique : « vous
    n'êtes pas désigné, demandez-le au maire » n'a rien à voir avec « il vous reste à signer
    votre engagement », et les confondre dans un seul 403 rendrait la page inexplicable."""
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return False
    if not commune_code:
        return False

    institution = getattr(user, "institution", None)
    if institution is None:
        return False

    role = get_effective_role(request)
    if role == UserRole.LOCAL_AUTHORITY and institution.commune_code == commune_code:
        return habilitation_active(user, institution) is not None

    return any(
        _delegation_couvre_commune(d, commune_code)
        for d in _delegations_actives(institution)
    )


def institution_accede_commune(request, commune_code: str) -> bool:
    """**Garde d'ÉCRITURE** sur le registre de `commune_code` : inscrire, modifier, radier.

    ADMINISTRATOR est délibérément exclu (voir le docstring du module) : écrire au registre est
    un acte de la collectivité responsable de traitement. Pour la mairie, il faut une
    habilitation nominative vivante ; pour une institution tierce, une délégation de compétence
    active couvrant la commune. Dans les deux cas, l'engagement au secret doit être signé."""
    if not designation_en_place(request, commune_code):
        return False
    return engagement_secret_signe(getattr(request, "user", None))


def communes_accessibles(request) -> list | None:
    """Codes commune LISIBLES par l'appelant -- `None` signifie « toutes » (ADMINISTRATOR),
    liste vide « aucune ». Sert à filtrer un queryset PersonneVulnerable."""
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return []
    if not engagement_secret_signe(user):
        # Pas d'exception pour l'administrateur : le secret professionnel de R. 121-7 vise
        # quiconque traite ces données, éditeur compris.
        return []

    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return None

    institution = getattr(user, "institution", None)
    if institution is None:
        return []

    communes = set()
    if (
        role == UserRole.LOCAL_AUTHORITY
        and institution.commune_code
        and habilitation_active(user, institution) is not None
    ):
        communes.add(institution.commune_code)

    for d in _delegations_actives(institution):
        communes.update(d.communes or [])
        # Un département délégué ne peut pas être listé exhaustivement en codes commune ici sans
        # requêter le référentiel Commune ; filter_personnes_vulnerables_queryset gère ce cas à
        # part via une condition OR sur le préfixe département, voir plus bas.

    return list(communes)


def filter_personnes_vulnerables_queryset(request, queryset):
    """**Garde de LECTURE** : réduit `queryset` (PersonneVulnerable) aux communes lisibles.

    Même logique de délégation que habitations.filter_habitations_queryset (niveau département
    traité par préfixe de commune_code), avec l'habilitation nominative sur la branche mairie et
    l'engagement au secret exigé de tout le monde."""
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return queryset.none()
    if not engagement_secret_signe(user):
        return queryset.none()

    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return queryset

    institution = getattr(user, "institution", None)
    if institution is None:
        return queryset.none()

    filtre = Q(pk__in=[])  # base vide, complétée ci-dessous

    if (
        role == UserRole.LOCAL_AUTHORITY
        and institution.commune_code
        and habilitation_active(user, institution) is not None
    ):
        filtre |= Q(commune_code=institution.commune_code)

    for d in _delegations_actives(institution):
        if not d.communes and not d.departements and d.zone_precise is None:
            return queryset  # délégation sans restriction = accès à tout (rare)
        if d.communes:
            filtre |= Q(commune_code__in=d.communes)
        for dep in d.departements or []:
            filtre |= Q(commune_code__startswith=dep)

    return queryset.filter(filtre)
