"""Permissions DRF réutilisables liées au type de compte (User.type)."""
import hashlib

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission

from .models import Environment, UserRole

INSTITUTIONAL_TYPES = {
    UserRole.LOCAL_AUTHORITY,
    UserRole.ORGANIZED_RESCUE,
    UserRole.ADMINISTRATOR,
    UserRole.REGULATEUR,
}


def get_active_environment(request):
    """Zone active de la requête (PROD par défaut), choisie par le frontend via l'en-tête
    X-Environment (bascule "kill switch"). Cette valeur ne fait que sélectionner laquelle de
    deux configurations déjà décidées par un admin (type/demo_role) s'applique — elle ne peut
    jamais accorder plus de droits que ce que l'admin a explicitement réglé pour cet
    utilisateur, et sert aussi de filtre sur les données (voir EnvironmentScopedViewSetMixin
    dans views.py), donc pas de scénario où on "prétend" un environnement pour lire les
    données d'un autre."""
    value = request.META.get("HTTP_X_ENVIRONMENT", Environment.PROD)
    if value not in (Environment.PROD, Environment.DEMO):
        raise ValidationError({"environment": "Environnement invalide (PROD ou DEMO attendu)."})
    return value


def get_effective_role(request):
    """Rôle appliqué pour CETTE requête : `user.type` en PROD, `user.demo_role` en DEMO.
    À utiliser à la place de tout accès direct à `request.user.type` dans les contrôles de
    permission, pour que la bascule démo/prod soit respectée uniformément partout."""
    if get_active_environment(request) == Environment.DEMO:
        if not request.user.demo_role:
            raise PermissionDenied("Vous n'avez pas accès à la zone de démonstration.")
        return request.user.demo_role
    return request.user.type


def effective_role_or_none(request):
    """Variante non-bloquante de get_effective_role, pour les vérifications de visibilité
    "douces" (ex: masquer un champ de localisation) qui ne doivent jamais faire échouer toute
    une réponse à cause d'un client qui prétend être en DEMO sans y avoir droit — contrairement
    à un vrai contrôle de permission, où l'échec explicite (403) est voulu."""
    try:
        return get_effective_role(request)
    except PermissionDenied:
        return None


class IsInstitutionalActor(BasePermission):
    """Autorise les comptes institutionnels (autorité locale, secours organisés, admin) —
    au sens du rôle EFFECTIF de la requête (prod ou démo selon la bascule active)."""

    message = "Cette action est réservée aux acteurs institutionnels."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and get_effective_role(request) in INSTITUTIONAL_TYPES
        )


class IsAdministrator(BasePermission):
    """Autorise uniquement les comptes administrateur, au sens du rôle effectif de la requête."""

    message = "Cette action est réservée aux administrateurs."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and get_effective_role(request) == UserRole.ADMINISTRATOR
        )


def mask_email(value):
    """Email factice mais stable (la même vraie adresse donne toujours le même masque), pour
    ne jamais exposer une vraie adresse pendant une démonstration en zone DEMO."""
    if not value:
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()[:10]
    return f"{digest}@zone.demo"


def mask_phone(value):
    """Numéro factice mais stable, au format +33 x xx xx xx xx — même principe que mask_email."""
    if not value:
        return value
    digest = "".join(c for c in hashlib.sha256(value.encode()).hexdigest() if c.isdigit())
    digits = (digest + "0123456789")[:9]
    return f"+33 {digits[0]} {digits[1:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]}"


def user_can_view_photo(request, obj, *, author_field='author', teams_field=None, dossiers_field=None):
    """Détermine si l'utilisateur de `request` peut voir la photo d'un objet (Crisis/Offer/
    Request/Information/RecherchePersonne) : l'auteur, un acteur institutionnel (au sens du
    rôle effectif prod/démo), un membre d'une équipe affectée à l'objet, ou un participant
    d'un dossier lié à l'objet."""
    user = request.user
    if not user or not user.is_authenticated:
        return False

    if effective_role_or_none(request) in INSTITUTIONAL_TYPES:
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
