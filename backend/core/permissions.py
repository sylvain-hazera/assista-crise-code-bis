"""Permissions DRF réutilisables liées au type de compte (User.type)."""
from rest_framework.permissions import BasePermission

from .models import UserRole

INSTITUTIONAL_TYPES = {
    UserRole.LOCAL_AUTHORITY,
    UserRole.ORGANIZED_RESCUE,
    UserRole.ADMINISTRATOR,
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
