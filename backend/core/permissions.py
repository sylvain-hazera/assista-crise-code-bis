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


def send_mail_env_aware(request, subject, message, from_email, recipient_list, **kwargs):
    """Enveloppe django.core.mail.send_mail pour les notifications opérationnelles
    (affectation, confirmation de création...) : en zone DEMO, redirige systématiquement vers
    l'utilisateur connecté à l'origine de l'action plutôt que vers le destinataire enregistré
    (souvent fictif/de repli en démo, ex: contact anonyme du formulaire "Autre information") —
    pour que les comptes de démonstration voient concrètement ce que l'appli aurait envoyé,
    sans jamais spammer une adresse tierce. Sans effet en PROD. Ne concerne pas les emails de
    cycle de vie de compte (inscription, activation, validation) : structurellement propres à
    PROD, la démo ne crée jamais de compte."""
    from .audit import send_mail_logged

    if get_active_environment(request) == Environment.DEMO and getattr(request.user, "is_authenticated", False):
        recipient_list = [request.user.email]
        subject = f"[DEMO] {subject}"
    return send_mail_logged(request, subject, message, from_email, recipient_list, **kwargs)


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


def is_regulateur_aut_locale_de_la_crise(request, crise) -> bool:
    """L'utilisateur courant est-il un compte AUT_LOCALE (rôle effectif, prod/démo) rattaché à
    une institution elle-même impliquée (validée, active) sur `crise` ? — condition
    d'autorisation pour valider/refuser une déclaration ACTEUR en attente d'une institution
    tierce (ImplicationInstitutionViewSet.valider/refuser), et pour piloter l'affichage des
    boutons correspondants côté ImplicationInstitutionSerializer.peut_valider. Défini ici (et
    pas dans serializers.py/views.py) pour être appelable depuis les deux sans import
    circulaire — même raison que _peut_gerer_stock_point."""
    if not request.user or not request.user.is_authenticated:
        return False
    if effective_role_or_none(request) != UserRole.LOCAL_AUTHORITY:
        return False

    # ContactInstitution (rattachement institutionnel), pas User.institution (FK direct
    # distinct, réservé à la "Vue Ma collectivité" — voir UserSerializer.get_ma_zone) : c'est
    # ContactInstitution que ImplicationInstitutionViewSet utilise déjà partout ailleurs
    # (perform_create/_can_manage) pour déterminer "l'institution de l'appelant".
    from .models import ContactInstitution, ImplicationInstitution, StatutImplication

    institution_ids = ContactInstitution.objects.filter(
        utilisateur=request.user, actif=True,
    ).values_list('institution_id', flat=True)
    return ImplicationInstitution.objects.filter(
        crise=crise, institution_id__in=institution_ids, statut=StatutImplication.VALIDEE, actif=True,
    ).exists()


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


class IsOwnerOrInstitutional(BasePermission):
    """Autorise l'auteur (compte lié, `obj.author`) d'un contenu public à le modifier ou le
    supprimer lui-même, en plus des acteurs institutionnels. Offer/Request/Information sont en
    `permission_classes = [AllowAny]` pour permettre la création publique (y compris anonyme) —
    sans `get_permissions()` dédié pour update/partial_update/destroy, cette même permission
    s'appliquait à CES actions aussi : n'importe qui, même anonyme, pouvait modifier ou
    supprimer le contenu de n'importe qui d'autre (vérifié en le reproduisant). La suppression
    anonyme reste possible par ailleurs via le lien à jeton envoyé par email
    (delete-offer/delete-request/delete-information), qui ne passe pas par ce ViewSet."""

    message = "Vous ne pouvez modifier ou supprimer que votre propre contenu."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.author_id == request.user.id


class IsOfferOwnerOrInstitutional(BasePermission):
    """Même principe que IsOwnerOrInstitutional, pour les objets qui n'ont pas d'auteur direct
    mais dépendent d'une Offer (ex: DisponibiliteOffre) — l'auteur de l'offre parente fait
    autorité. DisponibiliteOffreViewSet était en `permission_classes = [AllowAny]` sur toute la
    classe, sans aucune restriction : n'importe qui, même anonyme, pouvait créer/modifier/
    supprimer les créneaux de disponibilité de n'importe quel bénévole sur n'importe quelle
    offre (vérifié en le reproduisant)."""

    message = "Vous ne pouvez modifier ou supprimer que les disponibilités de votre propre offre."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.offer.author_id == request.user.id


class IsInstitutionMemberOrAdministrator(BasePermission):
    """Seul un membre actif de CETTE institution précise (ContactInstitution), ou un
    administrateur plateforme, peut la modifier — contrairement à IsInstitutionalActor
    (n'importe quel acteur institutionnel, de n'importe quelle institution), qui laissait
    n'importe quel compte authentifié institutionnel éditer l'institution de quelqu'un d'autre
    (InstitutionViewSet n'avait aucune restriction de permission sur update/partial_update)."""

    message = "Seul un membre de cette institution peut la modifier."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if get_effective_role(request) == UserRole.ADMINISTRATOR:
            return True
        from .models import ContactInstitution
        return ContactInstitution.objects.filter(
            institution=obj, utilisateur=request.user, actif=True,
            environment=get_active_environment(request),
        ).exists()


class IsSelfOrInstitutional(BasePermission):
    """Pour UserViewSet : un compte ne peut modifier/supprimer que lui-même, en plus des
    acteurs institutionnels — sans permission dédiée, UserViewSet (permission par défaut
    IsAuthenticated, aucun get_permissions()) laissait n'importe quel compte authentifié
    modifier ou supprimer le compte de n'importe qui d'autre par son UUID (vérifié en le
    reproduisant)."""

    message = "Vous ne pouvez modifier ou supprimer que votre propre compte."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.pk == request.user.pk


class IsOwnDeclarationOrInstitutional(BasePermission):
    """Autorise l'auteur d'une déclaration de sécurité ("je suis en sécurité") à modifier sa
    propre situation (arrivée/départ d'un centre d'accueil, relogement...), en plus des
    acteurs institutionnels qui peuvent modifier n'importe quelle déclaration."""

    message = "Vous ne pouvez modifier que vos propres déclarations."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.declare_par_id == request.user.id


class IsAdministrator(BasePermission):
    """Autorise uniquement les comptes administrateur, au sens du rôle effectif de la requête."""

    message = "Cette action est réservée aux administrateurs."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and get_effective_role(request) == UserRole.ADMINISTRATOR
        )


def _peut_gerer_stock_point(request, point) -> bool:
    """Admin, responsable du point (champ `responsable` singulier — pas le M2M `responsables`,
    même limite que le contrôle d'origine), ou chef/membre de son équipe. Utilisé à la fois
    pour l'autorisation réelle (RegistrePresenceViewSet, ContributionMaterielViewSet,
    MaterielPointViewSet dans views.py) et pour le champ calculé `peut_gerer` exposé par
    PointOperationnelSerializer, afin que les boutons Secrétariat/Stock du frontend reflètent
    exactement les mêmes droits que ceux réellement appliqués par l'API."""
    user = request.user
    if get_effective_role(request) == UserRole.ADMINISTRATOR:
        return True
    if point.responsable_id == user.id:
        return True
    if point.equipe:
        if point.equipe.leader_id == user.id:
            return True
        if point.equipe.members.filter(id=user.id).exists():
            return True
    return False


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


def strip_masked_fields_in_demo(request, validated_data, fields):
    """Retire `fields` de `validated_data` en zone DEMO — un formulaire d'édition affiche la
    version masquée (mask_email/mask_phone, voir to_representation des serializers concernés)
    et la renvoie telle quelle au save, même si un tout autre champ a changé : sans ce garde-
    fou, éditer une fiche en DEMO écrase silencieusement une vraie adresse email/téléphone par
    son masque affiché. Reproduit et corrigé en direct (comptes GRUISSAN/NICOLAS sur .114,
    voir UserSerializer.update) puis généralisé à Request/Offer/Information, qui suivent le
    même schéma de masquage."""
    if request is not None and get_active_environment(request) == Environment.DEMO:
        for field in fields:
            validated_data.pop(field, None)
    return validated_data


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
