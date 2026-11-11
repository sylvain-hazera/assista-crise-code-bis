"""Qui voit quelles offres d'aide.

Pendant de `core/visibilite_membres.py`, pour `Offer`.

**Pourquoi ce module existe.** `Offer` était entièrement public : `OfferViewSet` est en
`AllowAny`, sa liste alimente la carte publique et la recherche, et le modèle ne portait ni
institution ni visibilité. C'était cohérent tant qu'une offre était le geste d'un citoyen qui
propose son aide à tous.

Ça cesse de l'être dès qu'un membre d'association devient une ressource (décision du
11/11/2026) : une offre « bénévole de la Réserve Résilience » publiée sur la carte publique
serait l'inverse exact de la consigne — « seule la réserve résilience a le droit de les voir
comme ressource ».

**Le défaut est permissif, et c'est délibéré** : `PUBLIQUE` est la valeur par défaut du champ et
celle de toutes les lignes existantes. Ce module ne peut donc pas *réduire* par accident ce qui
était déjà visible ; il ne fait que fermer ce qui est explicitement marqué `INTERNE`.

**À appliquer partout où des offres sont servies à un client**, et nulle part ailleurs : les
commandes d'administration et les traitements internes travaillent sur toute la table, c'est
leur rôle. La liste des points d'application est dans le test
`core/tests/moyens/test_visibilite_offres.py`, qui vérifie chacun d'eux — une nouvelle vue qui
sert des offres sans passer par ici est un oubli que seul ce test attrapera.
"""
from django.db.models import Q


def filtre_offres_visibles(utilisateur, est_administrateur=False):
    """Un `Q` à appliquer sur un queryset d'`Offer`, ou None quand tout est visible.

    None (et non un `Q` toujours vrai) pour l'administrateur : laisser l'appelant sauter le
    filtrage entièrement évite une jointure inutile sur la table la plus volumineuse du projet.

    `est_administrateur` est passé par l'appelant et non déduit de `utilisateur.type`, comme
    pour `filtre_utilisateurs_visibles` : le rôle qui compte est le rôle EFFECTIF de la requête
    (un administrateur basculé en zone de démonstration ne doit pas y voir plus que le rôle
    qu'il y joue).
    """
    from .models import ContactInstitution, VisibiliteOffre

    publiques = Q(visibilite=VisibiliteOffre.PUBLIQUE)

    if utilisateur is None or not getattr(utilisateur, "is_authenticated", False):
        # Un visiteur anonyme ne voit QUE le public. C'est le cas le plus important du module :
        # la carte d'accueil est servie sans authentification.
        return publiques

    if est_administrateur:
        return None

    # Les institutions dont la personne est membre ACTIF. Le rattachement principal
    # (`User.institution`) ne suffit pas : un agent de mairie peut être adhérent de
    # l'association locale, et c'est à ce titre qu'il doit voir ses co-équipiers comme
    # ressources.
    institutions = set(
        ContactInstitution.objects.filter(
            utilisateur=utilisateur, actif=True,
        ).values_list("institution_id", flat=True)
    )
    if getattr(utilisateur, "institution_id", None):
        institutions.add(utilisateur.institution_id)

    visible = publiques | Q(author=utilisateur)
    if institutions:
        visible |= Q(institution_id__in=institutions)
    return visible


def offres_visibles(request, queryset):
    """Filtre un queryset d'offres pour l'appelant de `request`.

    Tolère une requête sans utilisateur (appel interne, objet factice de test) : on retombe
    alors sur le public, qui est le choix sûr."""
    from .permissions import get_effective_role
    from .models import UserRole

    utilisateur = getattr(request, "user", None) if request is not None else None
    est_admin = False
    if utilisateur is not None and getattr(utilisateur, "is_authenticated", False):
        try:
            est_admin = get_effective_role(request) == UserRole.ADMINISTRATOR
        except Exception:
            # Objet de requête factice (test, appel interne) : on retombe sur le rôle réel.
            est_admin = getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR
    filtre = filtre_offres_visibles(utilisateur, est_administrateur=est_admin)
    if filtre is None:
        return queryset
    return queryset.filter(filtre)
