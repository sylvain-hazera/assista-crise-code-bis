"""Permissions DRF réutilisables liées au type de compte (User.type)."""
from django.db.models import Q
from rest_framework.permissions import BasePermission

from .models import UserRole

INSTITUTIONAL_TYPES = {
    UserRole.LOCAL_AUTHORITY,
    UserRole.ORGANIZED_RESCUE,
    UserRole.ADMINISTRATOR,
    UserRole.REGULATEUR,
}


class IsInstitutionalActor(BasePermission):
    """Autorise les comptes institutionnels (autorité locale, secours organisés, admin)."""

    message = "Cette action est réservée aux acteurs institutionnels."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.type in INSTITUTIONAL_TYPES
        )


class IsAdministrator(BasePermission):
    """Autorise uniquement les comptes administrateur."""

    message = "Cette action est réservée aux administrateurs."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.type == UserRole.ADMINISTRATOR
        )


def user_can_view_photo(user, obj, *, author_field='author', teams_field=None, dossiers_field=None):
    """Détermine si `user` peut voir la photo d'un objet (Crisis/Offer/Request/
    Information/RecherchePersonne) : l'auteur, un acteur institutionnel, un membre
    d'une équipe affectée à l'objet, ou un participant d'un dossier lié à l'objet."""
    if not user or not user.is_authenticated:
        return False

    if user.type in INSTITUTIONAL_TYPES:
        return True

    author = getattr(obj, author_field, None)
    if author and author == user:
        return True

    if teams_field and getattr(obj, teams_field).filter(
        Q(members=user) | Q(leader=user)
    ).exists():
        return True

    if dossiers_field and getattr(obj, dossiers_field).filter(
        participants__utilisateur=user
    ).exists():
        return True

    return False
