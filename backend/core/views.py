from django.shortcuts import render
from django.http import FileResponse
from rest_framework.decorators import action
from rest_framework import viewsets, status, generics, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import MyTokenObtainPairSerializer  # if you've defined it in serializers
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from urllib.parse import quote
from django_filters import rest_framework as filters
from django.db import IntegrityError, transaction
from django.db.models import Q, F
from django.contrib.gis.db.models.functions import Distance
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .auth_validation import InstitutionEmailValidator
import datetime
import os
import secrets
import uuid
import hashlib
from django.core.files.base import ContentFile
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

from .audit import audit_log, get_client_ip
from .export import build_crisis_export_zip
from .institution_attachment import attach_user_to_institution, resolve_or_invite_responsable
from .permissions import (
    IsInstitutionalActor, IsAdministrator, IsOwnDeclarationOrInstitutional, IsOwnerOrInstitutional,
    IsSelfOrInstitutional,
    INSTITUTIONAL_TYPES, user_can_view_photo,
    get_active_environment, get_effective_role, mask_email, mask_phone, send_mail_env_aware,
)
from .geo_lookup import commune_code_from_point
from django.contrib.gis.geos import Point


GPS_IFD_TAG = 0x8825  # PIL.ExifTags.IFD.GPSInfo


def extract_exif_metadata(filepath):
    """Retourne (metadata_publiques, metadata_privees) : les données de localisation GPS
    embarquées dans la photo (sous-IFD GPSInfo) vont exclusivement dans le second dict,
    jamais dans le premier — cohérent avec le reste de l'app qui traite la localisation
    précise comme une donnée sensible (voir _location_visible() sur les serializers)."""

    metadata_publiques = {}
    metadata_privees = {}

    try:

        image = Image.open(filepath)

        exif = image.getexif()

        if not exif:
            return metadata_publiques, metadata_privees

        gps_ifd = exif.get_ifd(GPS_IFD_TAG)

        if gps_ifd:
            for tag_id, value in gps_ifd.items():
                tag = GPSTAGS.get(tag_id, tag_id)
                metadata_privees[tag] = str(value)

        for tag_id, value in exif.items():

            if tag_id == GPS_IFD_TAG:
                continue

            tag = TAGS.get(tag_id, tag_id)

            metadata_publiques[tag] = str(value)

    except Exception:
        pass

    return metadata_publiques, metadata_privees


from .models import (
    Environment,
    UserRole,
    InstitutionType,
    Institution,
    RoleOperationnel,
    InstitutionCompetence,
    AffectationRoleOperationnel,
    DelegationCompetence,
    DisponibiliteOperationnelle,
    ContactInstitution,
    InstitutionDomaine,
    PointType,
    PointOperationnel,
    ImplicationInstitution,
    TypeImplication,
    User, Crisis, Request, Offer, Information, DisponibiliteOffre, DisponibilitePointEquipe, MaterielPoint,
    MaterielCatalogue, NiveauStock, RegistrePresence, TypePersonneAccueillie, DeclarationSecurite, SituationDeclarant,
    AffectationPointBenevole, StatutAffectation,
    RecherchePersonne, RecherchePersonneCommentaire, Besoin, Notification, DossierParticipant,
    RecherchePersonneCommentairePhoto, RecherchePersonneLecture, RecherchePersonneLectureHistorique,
    Document, DossierCommentaire, DossierHistorique, BesoinCompetence, Competence, Dossier, Mission,
    AuditLog, AuditAction,
    RecherchePersonneHistorique, RecherchePersonnePhoto,
    AffectationCompetence, RequestType, RequestTypeBesoin, OfferType, InformationType, Team,
    Status,
    DernierePositionUtilisateur,
)


MAGIC_LINK_SALT = "assista-crise-magic-link"
MAGIC_LINK_SIGNER = TimestampSigner(salt=MAGIC_LINK_SALT)


FRONTEND_MAGIC_LINK_PATHS = {
    "activate-account": "activate-account",
    "magic-login": "connexion-magique",
    "reset-password": "reinitialiser-mot-de-passe",
}


def build_magic_link(request, user, action: str, next_url: str = None) -> str:
    uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = MAGIC_LINK_SIGNER.sign(uidb64)

    frontend_path = FRONTEND_MAGIC_LINK_PATHS.get(action)
    if frontend_path:
        # Doit pointer vers une page du frontend (qui appelle ensuite l'API elle-même côté
        # client), jamais directement sur l'API : sinon le clic affiche du JSON brut.
        frontend_url = settings.SERVER_URL.rstrip('/')
        url = f"{frontend_url}/{frontend_path}/{uidb64}/{token}"
        if next_url:
            url += f"?next={quote(next_url, safe='')}"
        return url

    base_url = settings.SERVER_URL.rstrip('/')
    return f"{base_url}/api/{action}/{uidb64}/{token}/"


def get_user_from_magic_link(uidb64: str, token: str):
    try:
        unsigned = MAGIC_LINK_SIGNER.unsign(token, max_age=60 * 60 * 24 * 7)
        if unsigned != uidb64:
            return None
        user_id = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=user_id)
    except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist):
        return None


def send_institution_account_email(request, user):
    activation_link = build_magic_link(request, user, "activate-account")
    login_link = build_magic_link(request, user, "magic-login")

    message = (
        "Bonjour,\n\n"
        "Votre compte institutionnel sur Assista-Crise a été créé.\n\n"
        "Il est encore inactif : cliquez sur le lien ci-dessous pour confirmer que vous êtes bien "
        "le propriétaire de cette adresse email et activer votre compte.\n\n"
        f"- Activation du compte : {activation_link}\n\n"
        f"Vous pourrez ensuite vous reconnecter à tout moment via : {login_link}\n\n"
        "Ces liens sont valables pendant 7 jours.\n\n"
        "Cordialement,\n"
        "L'équipe Assista-Crise"
    )

    send_mail(
        subject="Votre accès institutionnel Assista-Crise",
        message=message,
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_crisis_regulateur_invite_email(request, user, crisis, institution):
    activation_link = build_magic_link(request, user, "activate-account")
    login_link = build_magic_link(request, user, "magic-login")

    message = (
        "Bonjour,\n\n"
        f"Vous avez été désigné(e) responsable/régulateur par {institution.nom} "
        f"pour la crise « {crisis.name} » sur Assista-Crise.\n\n"
        "Votre compte est encore inactif : cliquez sur le lien ci-dessous pour confirmer que "
        "vous êtes bien le propriétaire de cette adresse email et l'activer.\n\n"
        f"- Activation du compte : {activation_link}\n\n"
        f"Vous pourrez ensuite vous reconnecter à tout moment via : {login_link}\n\n"
        "Ces liens sont valables pendant 7 jours.\n\n"
        "Cordialement,\n"
        "L'équipe Assista-Crise"
    )

    send_mail(
        subject="Vous avez été désigné responsable d'une crise sur Assista-Crise",
        message=message,
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )

from .serializers import (
    validate_crisis_open,
    InstitutionTypeSerializer,
    InstitutionSerializer,
    RoleOperationnelSerializer,
    InstitutionCompetenceSerializer,
    AffectationRoleOperationnelSerializer,
    DelegationCompetenceSerializer,
    DisponibiliteOperationnelleSerializer,
    PointTypeSerializer,
    ContactInstitutionSerializer,
    InstitutionDomaineSerializer,
    PointOperationnelSerializer,
    PointOperationnelPublicSerializer,
    ImplicationInstitutionSerializer,
    RecherchePersonnePhotoSerializer,
    DocumentSerializer,
    RecherchePersonneSerializer,
    RecherchePersonneCommentaireSerializer,
    RecherchePersonneCommentairePhotoSerializer,
    DossierCommentaireSerializer,
    DossierHistoriqueSerializer,
    NotificationSerializer,
    UserSerializer,
    RecherchePersonneLectureSerializer,
    RecherchePersonneLectureHistoriqueSerializer,
    CrisisSerializer,
    RequestTypeBesoinSerializer,
    RequestSerializer,
    OfferSerializer,
    DisponibiliteOffreSerializer,
    DisponibilitePointEquipeSerializer,
    MaterielPointSerializer,
    MaterielCatalogueSerializer,
    RegistrePresenceSerializer,
    DeclarationSecuriteSerializer,
    AffectationPointBenevoleSerializer,
    InformationSerializer,
    RequestTypeSerializer,
    OfferTypeSerializer,
    InformationTypeSerializer,
    TeamSerializer,
    CompetenceSerializer,
    DossierSerializer,
    MissionSerializer,
    AffectationCompetenceSerializer,
    BesoinSerializer,
    RecherchePersonneHistoriqueSerializer,
    BesoinCompetenceSerializer,
    DernierePositionUtilisateurSerializer,
)

class BesoinViewSet(viewsets.ModelViewSet):
    queryset = Besoin.objects.all()
    serializer_class = BesoinSerializer

    def perform_create(self, serializer):
        besoin = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Besoin",
            objet_id=besoin.id,
            commentaire=f"Création besoin : {besoin}",
        )

class BesoinCompetenceViewSet(viewsets.ModelViewSet):
    queryset = BesoinCompetence.objects.all()
    serializer_class = BesoinCompetenceSerializer

class RequestTypeBesoinViewSet(viewsets.ModelViewSet):
    queryset = RequestTypeBesoin.objects.all()
    serializer_class = RequestTypeBesoinSerializer

class TagLikeViewSetMixin:
    """Pour les modèles qui fonctionnent comme des hashtags réutilisables (Competence.nom,
    InformationType.type) : recherche par mots-clés indépendante de l'ordre (`?q=transport
    animaux` remonte la même chose que `?q=animaux transport`) et création qui réutilise
    silencieusement une entrée existante proche (comparaison insensible à la casse) au lieu
    de dupliquer un thème déjà là sous une casse différente — cohérent avec l'usage attendu
    d'un tag : n'importe qui doit pouvoir en "créer" un sans jamais fragmenter le vocabulaire
    partagé par erreur de frappe sur la casse."""

    tag_field = "nom"

    def get_search_queryset(self, queryset, query):
        tokens = [t for t in query.strip().split() if t]
        for token in tokens:
            queryset = queryset.filter(**{f"{self.tag_field}__icontains": token})
        return queryset

    def list(self, request, *args, **kwargs):
        query = request.query_params.get("q", "").strip()
        if not query:
            return super().list(request, *args, **kwargs)

        queryset = self.get_search_queryset(self.filter_queryset(self.get_queryset()), query)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        return (
            self.get_paginated_response(serializer.data)
            if page is not None
            else Response(serializer.data)
        )


    def create(self, request, *args, **kwargs):
        raw_value = " ".join(str(request.data.get(self.tag_field) or "").split())
        if raw_value:
            existing = self.get_queryset().filter(**{f"{self.tag_field}__iexact": raw_value}).first()
            if existing:
                return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

            data = request.data.copy()
            data[self.tag_field] = raw_value
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

        return super().create(request, *args, **kwargs)


class EnvironmentScopedViewSetMixin:
    """Point de passage unique pour isoler PROD et DEMO sur tout modèle "de contenu"
    (EnvironmentScopedModel) : filtre automatiquement le queryset sur l'environnement actif de
    la requête, et tamponne toute création avec ce même environnement. Volontairement un mixin
    appliqué à chaque ViewSet concerné plutôt qu'un filtrage global implicite, pour rester
    explicite sur quels modèles sont isolés (voir la répartition contenu/vocabulaire du plan) —
    même choix de conception que TagLikeViewSetMixin ci-dessus."""

    def get_queryset(self):
        return super().get_queryset().filter(environment=get_active_environment(self.request))

    def perform_create(self, serializer):
        serializer.save(environment=get_active_environment(self.request))


class CompetenceViewSet(TagLikeViewSetMixin, viewsets.ModelViewSet):
    queryset = Competence.objects.all()
    serializer_class = CompetenceSerializer

    def get_search_queryset(self, queryset, query):
        # Élargit la recherche par mots-clés aux compétences reliées à un Besoin dont le nom
        # matche (ex: chercher "animaux" doit aussi remonter une compétence rattachée à un
        # besoin "Sauvetage animalier", même si "animaux" n'apparaît pas dans son propre nom).
        base = super().get_search_queryset(queryset, query)
        tokens = [t for t in query.strip().split() if t]
        via_besoin = Competence.objects.all()
        for token in tokens:
            via_besoin = via_besoin.filter(besoins__besoin__nom__icontains=token)
        return (base | via_besoin).distinct()

    def perform_create(self, serializer):
        competence = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Competence",
            objet_id=competence.id,
            commentaire=f"Création thème/compétence : {competence.nom}",
        )

class AffectationCompetenceViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = AffectationCompetence.objects.all()
    serializer_class = AffectationCompetenceSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        affectation = serializer.save(environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="AFFECTATION",
            objet_type="AffectationCompetence",
            objet_id=affectation.id,
            commentaire=(
                f"Équipe {affectation.equipe.name} affectée à la compétence "
                f"{affectation.competence.nom} sur la crise {affectation.crise.name}"
            ),
        )

    def perform_update(self, serializer):
        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="AffectationCompetence",
            objet_id=affectation.id,
            commentaire=f"Modification affectation compétence : {affectation}",
        )

def _notify_dossier_closure(dossier, request):
    """Prévient la personne à l'origine du dossier (demandeur ou signalant) que son dossier
    vient d'être résolu ou clôturé — jusqu'ici la seule notification qu'elle recevait était la
    prise en charge initiale (_assign_request_to_team/_assign_information_to_team), plus rien
    ensuite : elle n'apprenait jamais que sa situation avait été traitée. Silencieux si le
    dossier n'a pas d'origine identifiable (créé manuellement, sans demande/signalement) ou pas
    d'email exploitable."""
    if dossier.demande is not None:
        destinataire = dossier.demande.email_request
        prenom = dossier.demande.first_name_request
        nature = "demande"
        titre = dossier.demande.title
    elif dossier.information is not None:
        destinataire = dossier.information.email_information
        prenom = dossier.information.first_name_information
        nature = "signalement"
        titre = dossier.information.title
    else:
        return

    if not destinataire:
        return

    verbe = "résolue" if dossier.statut == Dossier.Statut.RESOLU else "clôturée"
    try:
        send_mail_env_aware(
            request,
            subject=f"Votre {nature} « {titre} » a été {verbe}",
            message=(
                f"Bonjour {prenom},\n\n"
                f"Nous vous informons que votre {nature} « {titre} » (dossier {dossier.numero}) "
                f"a été {verbe} par l'équipe {dossier.equipe.name if dossier.equipe else 'en charge'}.\n\n"
                "Merci pour votre confiance,\n"
                "L'équipe Assista-Crise"
            ),
            from_email=None,
            recipient_list=[destinataire],
            fail_silently=True,
        )
    except Exception as e:
        print(f"Erreur envoi email clôture dossier : {e}")


class DossierViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Dossier.objects.all()
    serializer_class = DossierSerializer

    def get_permissions(self):
        # La lecture reste ouverte à tout utilisateur authentifié concerné (filtrée par
        # get_queryset : participant du dossier, ou compte institutionnel). Modifier ou
        # supprimer un dossier restait jusqu'ici possible à n'importe quel participant
        # (ex: un simple demandeur) faute de restriction dédiée — désormais réservé aux
        # comptes institutionnels, comme pour les autres écritures sensibles de l'app.
        if self.action in ("update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        environment = get_active_environment(self.request)
        if not user.is_authenticated:
            return Dossier.objects.none()
        if get_effective_role(self.request) in INSTITUTIONAL_TYPES:
            return Dossier.objects.filter(environment=environment)
        # Un chef d'équipe de terrain (leader/régulateur d'une équipe) doit voir TOUS les
        # dossiers de cette équipe, pas seulement ceux où il est lui-même participant — sinon
        # aucune vue d'ensemble possible pour coordonner plusieurs équipes à la fois.
        return Dossier.objects.filter(
            Q(participants__utilisateur=user) | Q(equipe__leader=user) | Q(equipe__regulateur=user),
            environment=environment,
        ).distinct()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def perform_create(self, serializer):
        dossier = serializer.save(environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Dossier",
            objet_id=dossier.id,
            commentaire=f"Création dossier : {dossier}",
        )

    @action(
        detail=True,
        methods=["post"]
    )
    def mark_viewed(self, request, pk=None):

        dossier = self.get_object()

        participant = dossier.participants.filter(
            utilisateur=request.user
        ).first()

        if participant:

            participant.date_derniere_vue = (
                timezone.now()
            )

            participant.save()

        return Response(
            {"status": "ok"}
        )

    @action(detail=True, methods=["post"], url_path="definir-priorite")
    def definir_priorite(self, request, pk=None):
        """Réservé au chef d'équipe de terrain (leader/régulateur de l'équipe affectée) ou à un
        acteur institutionnel : contrairement à update/partial_update (réservés institutionnel),
        cette action ne touche jamais qu'à `priorite`/`ordre`, pour permettre à un chef qui
        pilote plusieurs équipes de trier/prioriser sa tournée sans lui ouvrir toute l'édition
        du dossier."""
        dossier = self.get_object()
        user = request.user
        equipe = dossier.equipe

        est_chef_equipe = equipe is not None and user.id in (equipe.leader_id, equipe.regulateur_id)
        if not est_chef_equipe and get_effective_role(request) not in INSTITUTIONAL_TYPES:
            return Response(
                {"error": "Seul le chef ou le régulateur de l'équipe affectée peut modifier la priorité/l'ordre."},
                status=status.HTTP_403_FORBIDDEN,
            )

        priorite = request.data.get("priorite")
        if priorite is not None:
            if priorite not in Dossier.Priorite.values:
                return Response({"error": "Priorité invalide."}, status=status.HTTP_400_BAD_REQUEST)
            dossier.priorite = priorite

        ordre = request.data.get("ordre")
        if ordre is not None:
            try:
                dossier.ordre = int(ordre)
            except (TypeError, ValueError):
                return Response({"error": "L'ordre doit être un nombre entier."}, status=status.HTTP_400_BAD_REQUEST)

        dossier.save(update_fields=["priorite", "ordre"])
        return Response(DossierSerializer(dossier, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"])
    def ma_file(self, request):
        """Dossiers en attente d'affectation sur les compétences (thèmes) du régulateur
        connecté — contrairement à la liste générale (tous les dossiers pour un compte
        institutionnel), ici filtrée à ce qui concerne réellement l'utilisateur."""
        user = request.user
        if not user.is_authenticated:
            return Response([])

        competence_ids = AffectationRoleOperationnel.objects.filter(
            utilisateur=user, role__code="REGULATEUR", actif=True, competence__isnull=False,
        ).values_list('competence_id', flat=True)

        queryset = Dossier.objects.filter(
            statut__in=[Dossier.Statut.EN_ATTENTE_DISTRIBUTION, Dossier.Statut.EN_ATTENTE_AFFECTATION],
            competence_id__in=competence_ids,
        ).distinct()

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def cloturer(self, request, pk=None):
        """Clôture un dossier (ou le marque résolu, via {"statut": "RESOLU"} dans le corps
        de la requête). Réservé au régulateur affecté à ce dossier précis (DossierParticipant
        role=REGULATION), au responsable désigné de l'institution impliquée sur la crise
        (ImplicationInstitution.responsable), ou à un administrateur — pas open-bar à tout
        compte institutionnel comme le PATCH générique."""
        dossier = self.get_object()
        user = request.user

        est_regulateur_du_dossier = dossier.participants.filter(
            utilisateur=user, role=DossierParticipant.Role.REGULATION,
        ).exists()
        est_responsable_crise = dossier.crise.implications.filter(
            responsable=user, actif=True,
        ).exists()

        if not (est_regulateur_du_dossier or est_responsable_crise or get_effective_role(request) == UserRole.ADMINISTRATOR):
            return Response(
                {"error": "Seul le régulateur affecté à ce dossier ou le responsable de la crise peut le clôturer."},
                status=status.HTTP_403_FORBIDDEN,
            )

        nouveau_statut = request.data.get("statut", Dossier.Statut.CLOTURE)
        if nouveau_statut not in (Dossier.Statut.CLOTURE, Dossier.Statut.RESOLU):
            return Response({"error": "Statut de clôture invalide."}, status=status.HTTP_400_BAD_REQUEST)

        ancien_statut = dossier.statut
        dossier.statut = nouveau_statut
        if nouveau_statut == Dossier.Statut.CLOTURE:
            dossier.date_cloture = timezone.now()
        else:
            dossier.date_resolution = timezone.now()
        dossier.save()

        DossierHistorique.objects.create(
            dossier=dossier, auteur=user,
            evenement=f"Dossier {dossier.get_statut_display().lower()}",
            commentaire=request.data.get("commentaire"),
            environment=dossier.environment,
        )

        audit_log(
            request=request,
            action_code="CLOTURE",
            objet_type="Dossier",
            objet_id=dossier.id,
            crise=dossier.crise,
            ancien_etat=ancien_statut,
            nouvel_etat=nouveau_statut,
            commentaire=f"Dossier {dossier.numero} {dossier.get_statut_display().lower()} par {user.email}",
        )

        _notify_dossier_closure(dossier, request)

        return Response({"status": "ok", "statut": dossier.statut})


class AuthorEmailFilter(filters.FilterSet):
    author_email = filters.CharFilter(field_name='author__email', lookup_expr='iexact')


class OfferSearchFilter(AuthorEmailFilter):
    """Recherche texte libre (nom, email, titre) sur toutes les offres du système — utilisée
    pour recruter un bénévole individuel sur un point (PointOperationnelViewSet.
    inviter_benevole) : on cherche parmi TOUTES les offres, pas seulement celles de la crise en
    cours, décision actée avec l'utilisateur."""
    search = filters.CharFilter(method='filter_search')

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(first_name_offer__icontains=value)
            | Q(last_name_offer__icontains=value)
            | Q(email_offer__icontains=value)
            | Q(title__icontains=value)
            | Q(author__first_name__icontains=value)
            | Q(author__last_name__icontains=value)
            | Q(author__email__icontains=value)
        )

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_queryset(self):
        # ?institution=<uuid> restreint la liste aux membres actifs de cette institution (via
        # ContactInstitution, la relation faisant autorité pour "qui appartient à cette
        # institution" — User.institution n'est pas posé de façon fiable par tous les chemins
        # d'inscription/rattachement) — utilisé par le sélecteur de membres d'une équipe pour ne
        # proposer que les gens de la mairie qui la constitue, jamais tous les comptes de la
        # plateforme.
        queryset = super().get_queryset()
        if self.action == 'list':
            institution_id = self.request.query_params.get('institution')
            if institution_id:
                queryset = queryset.filter(
                    institutions__institution_id=institution_id,
                    institutions__actif=True,
                ).distinct()
        return queryset

    def get_permissions(self):
        # get_permissions() étant surchargé, chaque @action avec son propre permission_classes
        # doit être explicitement listée ici, sinon elle retombe sur le cas général ci-dessous
        # (gotcha connue de ce fichier). AVANT ce correctif, list/retrieve n'avaient AUCUNE
        # restriction (n'importe quel compte authentifié pouvait lister tous les utilisateurs,
        # emails/téléphones compris) et update/partial_update/destroy non plus (n'importe quel
        # compte pouvait modifier ou supprimer le compte de n'importe qui d'autre — vérifié en
        # le reproduisant, y compris une élévation de privilège via `type`/`demo_role`/
        # `enabled`, voir UserSerializer.update()).
        if self.action in ('register', 'login'):
            return [AllowAny()]
        if self.action in ('list', 'retrieve'):
            return [IsInstitutionalActor()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsSelfOrInstitutional()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def register(self, request):
        """Inscription d'un nouvel utilisateur"""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="User",
                objet_id=user.id,
                commentaire=f"Inscription compte : {user.email}",
            )

            if getattr(user, 'type', None) == UserRole.LOCAL_AUTHORITY:
                # Compte créé mais désactivé (enabled=False, posé par UserSerializer.create) tant
                # que l'email n'est pas confirmé : pas de token ici. Le rattachement à une
                # institution n'a lieu qu'après le clic sur le lien d'activation
                # (AccountActivationView) — jamais sur la seule foi d'un email non vérifié.
                try:
                    send_institution_account_email(request, user)
                except Exception as e:
                    print(f"Erreur envoi email institution : {e}")

                return Response({
                    'user': UserSerializer(user).data,
                    'message': "Votre compte a été créé. Vérifiez votre boîte mail et cliquez sur le lien d'activation pour finaliser votre inscription.",
                    'requires_validation': False,
                    'requires_email_confirmation': True,
                }, status=status.HTTP_201_CREATED)

            # Si le compte nécessite validation (Secours, Admin)
            if not user.enabled:
                # Envoyer email à l'utilisateur
                try:
                    send_mail(
                        subject="Compte créé - En attente de validation",
                        message=(
                            f"Bonjour {user.first_name} {user.last_name},\n\n"
                            f"Votre compte ({user.get_type_display()}) a bien été créé.\n"
                            "Cependant, il est en attente de validation par un administrateur.\n"
                            "Vous recevrez un email dès que votre compte sera validé.\n\n"
                            "Cordialement,\n"
                            "L'équipe Assista-Crise"
                        ),
                        from_email=None,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(f"Erreur envoi email utilisateur : {e}")
                
                # Notifier les administrateurs
                admin_emails = User.objects.filter(
                    type='ADMIN', 
                    is_active=True
                ).values_list('email', flat=True)
                
                if admin_emails:
                    try:
                        send_mail(
                            subject=f"Nouvelle demande de validation - {user.get_type_display()}",
                            message=(
                                f"Un nouveau compte nécessite votre validation :\n\n"
                                f"- Nom : {user.first_name} {user.last_name}\n"
                                f"- Email : {user.email}\n"
                                f"- Type : {user.get_type_display()}\n"
                                f"- Code postal : {user.postal_code or 'Non renseigné'}\n\n"
                                f"Connectez-vous au dashboard pour valider ou rejeter ce compte.\n\n"
                                "Cordialement,\n"
                                "Système Assista-Crise"
                            ),
                            from_email=None,
                            recipient_list=list(admin_emails),
                            fail_silently=False,
                        )
                    except Exception as e:
                        print(f"Erreur envoi email admins : {e}")

                if getattr(user, 'type', None) in {'AUT_LOCALE', 'SECOURS', 'ADMIN'}:
                    try:
                        send_mail(
                            subject="Nouvelle création de compte institutionnel",
                            message=(
                                f"Bonjour,\n\n"
                                f"Un nouveau compte institutionnel a été créé sur Assista-Crise.\n\n"
                                f"- Nom : {user.first_name} {user.last_name}\n"
                                f"- Email : {user.email}\n"
                                f"- Type : {user.get_type_display()}\n"
                                f"- Code postal : {user.postal_code or 'Non renseigné'}\n\n"
                                "Une validation est nécessaire avant activation."
                            ),
                            from_email=None,
                            recipient_list=['contact@assista-crise.fr'],
                            fail_silently=False,
                        )
                    except Exception as e:
                        print(f"Erreur envoi email contact institutionnel : {e}")
                
                # NE PAS retourner de token si le compte nécessite validation
                return Response({
                    'user': UserSerializer(user).data,
                    'message': 'Votre demande a été soumise et transmise à l’équipe. Un administrateur la validra prochainement.',
                    'requires_validation': True
                }, status=status.HTTP_201_CREATED)
            
            # Le compte est validé, retourner le token
            refresh = RefreshToken.for_user(user)
            return Response({
                'user': UserSerializer(user).data,
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'message': 'Utilisateur créé avec succès'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def login(self, request):
        """Connexion utilisateur"""
        email = request.data.get('email')
        password = request.data.get('password')
        
        if not email or not password:
            return Response(
                {'error': 'Email et mot de passe requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Authentifier par email
        try:
            user = User.objects.get(email=email)
            
            # Vérifier que le compte est actif ET validé
            if not user.is_active:
                return Response(
                    {'error': 'Ce compte a été désactivé'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            if not user.enabled:
                return Response(
                    {'error': 'Votre compte est en attente de validation par un administrateur'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if user.check_password(password):
                refresh = RefreshToken.for_user(user)
                audit_log(
                    request=request,
                    action_code="CONNEXION",
                    objet_type="User",
                    objet_id=user.id,
                    commentaire=(
                        f"Connexion de "
                        f"{user.email}"
                    )
                )
                return Response({
                    'user': UserSerializer(user).data,
                    'token': str(refresh.access_token),
                    'refresh': str(refresh),
                    'message': 'Connexion réussie'
                })
            else:
                return Response(
                    {'error': 'Identifiants invalides'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
        except User.DoesNotExist:
            return Response(
                {'error': 'Identifiants invalides'},
                status=status.HTTP_401_UNAUTHORIZED
            )
    
    @action(detail=False, methods=['post'])
    def logout(self, request):
        """Déconnexion (côté client, le token sera supprimé)"""
        return Response({'message': 'Déconnexion réussie'}, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def pending_validations(self, request):
        """Liste des comptes en attente de validation"""
        user = request.user
        role = get_effective_role(request)

        # Seuls les admins et institutions peuvent voir les validations
        if role not in [UserRole.ADMINISTRATOR, UserRole.LOCAL_AUTHORITY]:
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Les admins voient tout, les institutions voient leur code postal
        if role == UserRole.ADMINISTRATOR:
            pending_users = User.objects.filter(enabled=False, is_active=True)
        else:
            pending_users = User.objects.filter(
                enabled=False, 
                is_active=True,
                postal_code=user.postal_code
            )
        
        serializer = self.get_serializer(pending_users, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def approve_account(self, request, pk=None):
        """Approuver un compte en attente"""
        user_to_approve = self.get_object()
        validator = request.user
        validator_role = get_effective_role(request)

        # Vérifier les permissions
        if validator_role not in [UserRole.ADMINISTRATOR, UserRole.LOCAL_AUTHORITY]:
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Les institutions ne peuvent valider que leur code postal
        if validator_role == UserRole.LOCAL_AUTHORITY and validator.postal_code != user_to_approve.postal_code:
            return Response(
                {'error': 'Vous ne pouvez valider que les comptes de votre territoire'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Activer le compte (is_active est le champ réellement vérifié par /api/token/ ;
        # enabled seul ne suffit pas à bloquer la connexion)
        user_to_approve.enabled = True
        user_to_approve.is_active = True
        user_to_approve.save()
        
        # Envoyer email de confirmation
        try:
            send_mail(
                subject="Votre compte a été validé !",
                message=(
                    f"Bonjour {user_to_approve.first_name} {user_to_approve.last_name},\n\n"
                    f"Bonne nouvelle ! Votre compte ({user_to_approve.get_type_display()}) a été validé.\n"
                    "Vous pouvez maintenant vous connecter et accéder à toutes les fonctionnalités.\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[user_to_approve.email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Erreur envoi email validation : {e}")
        
        return Response({
            'message': 'Compte validé avec succès',
            'user': UserSerializer(user_to_approve).data
        })
    
    @action(detail=True, methods=['post'])
    def reject_account(self, request, pk=None):
        """Rejeter un compte en attente"""
        user_to_reject = self.get_object()
        validator = request.user
        validator_role = get_effective_role(request)
        reason = request.data.get('reason', 'Non spécifiée')

        # Vérifier les permissions
        if validator_role not in [UserRole.ADMINISTRATOR, UserRole.LOCAL_AUTHORITY]:
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Les institutions ne peuvent rejeter que leur code postal
        if validator_role == UserRole.LOCAL_AUTHORITY and validator.postal_code != user_to_reject.postal_code:
            return Response(
                {'error': 'Vous ne pouvez rejeter que les comptes de votre territoire'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Envoyer email de rejet
        try:
            send_mail(
                subject="Votre demande de compte a été refusée",
                message=(
                    f"Bonjour {user_to_reject.first_name} {user_to_reject.last_name},\n\n"
                    f"Nous sommes désolés de vous informer que votre demande de compte "
                    f"({user_to_reject.get_type_display()}) n'a pas été acceptée.\n\n"
                    f"Raison : {reason}\n\n"
                    "Pour plus d'informations, vous pouvez nous contacter.\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[user_to_reject.email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Erreur envoi email rejet : {e}")
        
        # Désactiver le compte (ou le supprimer)
        user_to_reject.is_active = False
        user_to_reject.save()

        return Response({
            'message': 'Compte rejeté',
            'user': UserSerializer(user_to_reject).data
        })

    @action(detail=True, methods=['post'])
    def send_password_reset(self, request, pk=None):
        """Envoie à l'utilisateur ciblé un lien lui permettant de définir un nouveau mot de
        passe sans connaître l'ancien (contrairement à ChangePasswordView) — déclenché depuis
        la page d'administration des utilisateurs, jamais en libre-service : réservé aux
        administrateurs, même garde-fou que le reste de la page (sysAdminGuard côté front)."""
        if get_effective_role(request) != UserRole.ADMINISTRATOR:
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )

        target_user = self.get_object()
        reset_link = build_magic_link(request, target_user, "reset-password")

        message = (
            f"Bonjour {target_user.first_name} {target_user.last_name},\n\n"
            "Un administrateur d'Assista-Crise a demandé la réinitialisation du mot de passe "
            "de votre compte.\n\n"
            f"Pour choisir un nouveau mot de passe, cliquez sur le lien suivant :\n{reset_link}\n\n"
            "Ce lien est valable 7 jours et ne peut être utilisé qu'une seule fois. Si vous "
            "n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet email : votre mot "
            "de passe actuel reste valable.\n\n"
            "Cordialement,\n"
            "L'équipe Assista-Crise"
        )

        send_mail_env_aware(
            request,
            subject="Réinitialisation de votre mot de passe Assista-Crise",
            message=message,
            from_email=None,
            recipient_list=[target_user.email],
            fail_silently=False,
        )

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="User",
            objet_id=target_user.id,
            commentaire=f"Envoi d'un lien de réinitialisation de mot de passe à {target_user.email}",
        )

        return Response({'message': f"Email de réinitialisation envoyé à {target_user.email}"})

class CrisisViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Crisis.objects.all()
    serializer_class = CrisisSerializer
    filterset_class = AuthorEmailFilter

    def get_permissions(self):
        # Consultation (liste/détail) : ouverte à tous, transparence publique inchangée.
        # Création/modification : réservées aux acteurs institutionnels.
        # Suppression : réservée aux administrateurs.
        # Ce get_permissions() étant surchargé au niveau de la classe, les permission_classes
        # posées sur un @action ne s'appliquent jamais d'elles-mêmes — chaque action custom
        # doit être explicitement listée ici, sinon elle retombe sur AllowAny (cf. cloturer/
        # reouvrir, découvert en corrigeant ce bug).
        if self.action in ("create", "update", "partial_update"):
            return [IsInstitutionalActor()]
        if self.action == "destroy":
            return [IsAdministrator()]
        if self.action == "cloturer":
            return [IsInstitutionalActor()]
        if self.action == "reouvrir":
            return [IsAdministrator()]
        if self.action == "export":
            return [permissions.IsAuthenticated()]
        if self.action == "stocks_comparaison":
            return [permissions.IsAuthenticated()]
        return [AllowAny()]

    def perform_create(self, serializer):
        crise = serializer.save(author=self.request.user, environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            commentaire=f"Création crise : {crise.name}",
        )

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        crise = self.get_object()
        if not crise.photo or not user_can_view_photo(
            request, crise, teams_field='assigned_teams', dossiers_field='dossiers'
        ):
            return Response(status=403)
        return FileResponse(open(crise.photo.path, "rb"))

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def cloturer(self, request, pk=None):
        """Clôture une crise : bloque toute nouvelle implication/point/délégation dessus
        (cf. validate_crisis_open) sans toucher aux dossiers déjà en cours. Réservé au
        responsable actif d'une institution impliquée sur cette crise, ou à un administrateur."""
        crise = self.get_object()
        user = request.user

        est_responsable_crise = crise.implications.filter(responsable=user, actif=True).exists()
        if not (est_responsable_crise or get_effective_role(request) == UserRole.ADMINISTRATOR):
            return Response(
                {"error": "Seul le responsable d'une institution impliquée sur cette crise peut la clôturer."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if crise.end_date is not None:
            return Response({"error": "Cette crise est déjà clôturée."}, status=status.HTTP_400_BAD_REQUEST)

        crise.end_date = timezone.now()
        crise.save()

        audit_log(
            request=request,
            action_code="CLOTURE",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            ancien_etat="OUVERTE",
            nouvel_etat="CLOTUREE",
            commentaire=f"Crise {crise.name} clôturée par {user.email}",
        )

        return Response({"status": "ok", "end_date": crise.end_date})

    @action(detail=True, methods=["post"], permission_classes=[IsAdministrator])
    def reouvrir(self, request, pk=None):
        """Réouvre une crise clôturée par erreur — réservé aux administrateurs."""
        crise = self.get_object()

        if crise.end_date is None:
            return Response({"error": "Cette crise est déjà ouverte."}, status=status.HTTP_400_BAD_REQUEST)

        crise.end_date = None
        crise.save()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            ancien_etat="CLOTUREE",
            nouvel_etat="OUVERTE",
            commentaire=f"Crise {crise.name} réouverte par {request.user.email}",
        )

        return Response({"status": "ok"})

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """Export de la main courante complète de la crise (zip multi-CSV). Réservé au
        responsable actif d'une institution impliquée ou à un administrateur — plus strict
        que IsInstitutionalActor : un acteur institutionnel quelconque n'a pas forcément
        vocation à voir les données de TOUTES les institutions de la crise."""
        crise = self.get_object()
        user = request.user

        est_responsable_crise = crise.implications.filter(responsable=user, actif=True).exists()
        if not (est_responsable_crise or get_effective_role(request) == UserRole.ADMINISTRATOR):
            return Response(
                {"error": "Seul le responsable d'une institution impliquée sur cette crise peut exporter sa main courante."},
                status=status.HTTP_403_FORBIDDEN,
            )

        zip_buffer = build_crisis_export_zip(crise)

        audit_log(
            request=request,
            action_code="EXPORT",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            commentaire=f"Export de la main courante de la crise {crise.name} par {user.email}",
        )

        response = FileResponse(zip_buffer, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="crise-{crise.id}-main-courante.zip"'
        return response

    @action(detail=True, methods=["get"], url_path="stocks-comparaison")
    def stocks_comparaison(self, request, pk=None):
        """Niveau de stock de chaque item du catalogue matériel, pour chaque point de la crise
        — de quoi construire directement un tableau comparatif côté frontend (lignes = items,
        colonnes = points) pour organiser une navette entre deux centres."""
        crise = self.get_object()
        points = list(crise.points_operationnels.select_related("type").order_by("nom"))
        materiels = MaterielPoint.objects.filter(point__in=points).select_related("item", "point")

        niveaux = {}
        for m in materiels:
            niveaux.setdefault(str(m.item_id), {})[str(m.point_id)] = {
                "niveau_stock": m.niveau_stock,
                "niveau_stock_libelle": m.get_niveau_stock_display(),
            }

        items = []
        for item in MaterielCatalogue.objects.all().order_by("nom"):
            par_point = niveaux.get(str(item.id), {})
            items.append({
                "item": str(item.id),
                "item_nom": item.nom,
                "niveaux": {
                    str(p.id): par_point.get(str(p.id), {
                        "niveau_stock": NiveauStock.NUL,
                        "niveau_stock_libelle": NiveauStock.NUL.label,
                    })
                    for p in points
                },
            })

        return Response({
            "points": [{"id": str(p.id), "nom": p.nom, "type_libelle": p.type.libelle if p.type else None} for p in points],
            "items": items,
        })

def resolve_or_invite_demandeur(demande, request=None):
    """Résout le compte utilisateur du demandeur d'une aide pour lui permettre de suivre son
    dossier par lien magique : l'auteur de la demande s'il est authentifié, sinon un compte
    existant partageant le même email, sinon un nouveau compte créé à la volée à partir des
    coordonnées saisies dans le formulaire (`email_request`/`first_name_request`/`last_name_request`).
    Contrairement à `resolve_or_invite_responsable`, ce compte n'a besoin d'aucune étape de
    définition de mot de passe : il n'est destiné qu'à recevoir des liens de connexion magique,
    donc `enabled`/`is_active` sont activés directement.

    Retourne (user, created)."""
    if demande.author:
        return demande.author, False

    email = (demande.email_request or '').strip().lower()
    if not email:
        return None, False

    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        return existing, False

    user = User.objects.create_user(
        username=email,
        email=email,
        password=None,
        type=UserRole.SIMPLE_USER,
        first_name=demande.first_name_request,
        last_name=demande.last_name_request,
        enabled=True,
        is_active=True,
    )
    if request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="User",
            objet_id=user.id,
            commentaire=f"Compte créé pour {email} afin de suivre sa demande d'aide",
        )
    return user, True


def resolve_or_invite_benevole(offer, request=None):
    """Même principe que resolve_or_invite_demandeur, pour recruter un bénévole individuel sur
    un point depuis une offre d'aide (Offer.author si authentifié, sinon coordonnées libres
    first_name_offer/last_name_offer/email_offer). Compte activé directement (pas d'étape de
    mot de passe) : la confirmation se fait par le jeton opaque de l'affectation, pas par un
    lien magique lié au compte.

    Retourne (user, created)."""
    if offer.author:
        return offer.author, False

    email = (offer.email_offer or '').strip().lower()
    if not email:
        return None, False

    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        return existing, False

    user = User.objects.create_user(
        username=email,
        email=email,
        password=None,
        type=UserRole.SIMPLE_USER,
        first_name=offer.first_name_offer,
        last_name=offer.last_name_offer,
        enabled=True,
        is_active=True,
    )
    if request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="User",
            objet_id=user.id,
            commentaire=f"Compte créé pour {email} afin de le recruter comme bénévole sur un point",
        )
    return user, True


def send_point_volunteer_confirmation_email(request, affectation):
    """Email envoyé à un bénévole recruté individuellement sur un point (voir
    PointOperationnelViewSet.inviter_benevole) — jeton opaque, même idiome que
    Offer.deletion_token, pas besoin de compte/mot de passe pour répondre."""
    base_url = settings.SERVER_URL.rstrip('/')
    lien_oui = f"{base_url}/api/confirmer-affectation-benevole/{affectation.token_confirmation}/oui/"
    lien_non = f"{base_url}/api/confirmer-affectation-benevole/{affectation.token_confirmation}/non/"

    point = affectation.point
    responsable = point.responsable

    lignes = [
        "Bonjour,",
        "",
        f"L'équipe du point « {point.nom} » vous sollicite pour la crise « {point.crise.name} ».",
        f"Merci de confirmer votre disponibilité :",
        "",
        f"- Oui, je confirme : {lien_oui}",
        f"- Non, je ne suis pas disponible : {lien_non}",
        "",
        f"Vous êtes attendu(e) le {affectation.date_attendue.strftime('%d/%m/%Y à %H:%M')}.",
    ]

    if point.adresse:
        lignes.append(f"Adresse : {point.adresse}")

    if affectation.point_transit:
        lignes.append(
            f"Point de transit obligatoire avant de rejoindre le point (route fermée / "
            f"contrôle d'accès) : {affectation.point_transit.nom}"
            + (f" ({affectation.point_transit.adresse})" if affectation.point_transit.adresse else "")
        )

    if responsable:
        contact = responsable.email
        if responsable.phone_number:
            contact += f" / {responsable.phone_number}"
        lignes.append(f"Responsable du point : {responsable.first_name} {responsable.last_name} ({contact})".strip())

    lignes += ["", "Cordialement,", "L'équipe Assista-Crise"]

    send_mail_env_aware(
        request,
        subject=f"Confirmation de disponibilité — {point.nom}",
        message="\n".join(lignes),
        from_email=None,
        recipient_list=[affectation.benevole.email],
        fail_silently=False,
    )


def department_code_from_commune_code(commune_code):
    """Extrait le code département d'un code commune INSEE : 3 chiffres pour l'outre-mer
    (971-976/98x), 2 caractères sinon (dont '2A'/'2B' pour la Corse, déjà sous cette forme
    dans le code commune)."""
    if not commune_code:
        return None
    code = commune_code.strip().upper()
    if code[:2] in ('2A', '2B'):
        return code[:2]
    if code[:2] in ('97', '98'):
        return code[:3]
    return code[:2]


def team_zone_specificity(team, demande):
    """Score de spécificité de la couverture géographique d'une équipe pour une demande :
    plus le nombre est élevé, plus la correspondance est précise. `None` si l'équipe a
    déclaré une zone mais qu'elle ne couvre pas la demande — dans ce cas l'équipe est
    exclue du matching. Une équipe n'ayant déclaré aucune zone (cas de toutes les équipes
    existantes avant cette fonctionnalité) est considérée disponible partout, pour ne pas
    régresser le comportement précédent."""
    if not (team.departements or team.communes or team.zone_precise):
        return 0

    if team.zone_precise and demande.location and team.zone_precise.contains(demande.location):
        return 3

    commune_code = (demande.commune_code or '').strip()

    if team.communes and commune_code in team.communes:
        return 2

    if team.departements:
        departement = department_code_from_commune_code(commune_code)
        if departement and departement in team.departements:
            return 1

    return None


def annotate_distance_from_crisis(queryset):
    """Distance (annotée en mètres par GeoDjango) entre `location` de chaque ligne et la
    `location` de sa propre crise liée — même fonction Distance que
    PointOperationnelViewSet.candidats_benevoles, mais la référence varie par ligne (F() sur
    la jointure crisis__location) au lieu d'être un point fixe. NULL naturellement (donc
    distance_from_crisis=None) si location ou crisis absent, la jointure crisis étant déjà
    nullable côté FK — pas de traitement particulier requis ici."""
    return queryset.annotate(distance_from_crisis=Distance('location', F('crisis__location')))


def _institution_commune_or_400(request):
    """Code commune de l'institution de l'utilisateur appelant, pour les actions "vue mairie"
    partagées par RequestViewSet/InformationViewSet. Retourne soit le code (str), soit une
    Response 400 prête à renvoyer si l'utilisateur n'a pas d'institution ou que celle-ci n'a
    pas de commune renseignée (ex: institution non-AUT_LOCALE, ou AUT_LOCALE non encore
    rattachée via l'annuaire) — jamais une liste vide silencieuse qui masquerait la vraie
    cause."""
    institution = getattr(request.user, 'institution', None)
    if institution is None or not institution.commune_code:
        return Response(
            {"error": "Aucune commune associée à votre institution : contactez un administrateur."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return institution.commune_code


def resolve_competence_for_request(demande):
    """Compétence déduite du type de demande (RequestType -> Besoin -> Competence),
    utilisée aussi bien pour le matching automatique (perform_create) que pour fiabiliser
    le rattachement d'un dossier créé manuellement (assign_team)."""
    mapping_besoin = RequestTypeBesoin.objects.filter(request_type=demande.request_type).first()
    if not mapping_besoin:
        return None
    mapping_competence = BesoinCompetence.objects.filter(besoin=mapping_besoin.besoin).first()
    return mapping_competence.competence if mapping_competence else None


def _assign_request_to_team(demande, team, request, mission=None):
    """Corps partagé par RequestViewSet.assign_team (une demande) et .bulk_assign_mission
    (plusieurs) : crée le dossier de suivi, notifie le·s régulateur·s, informe le demandeur
    par email, journalise. Retourne (outcome, dossier, regulateurs) où outcome vaut
    "already_assigned" (no-op, dossier=None), "no_crisis" (dossier=None) ou "created"."""
    if team.assigned_requests.filter(pk=demande.pk).exists():
        return "already_assigned", None, None

    if not demande.crisis:
        return "no_crisis", None, None

    team.assigned_requests.add(demande)

    dossier = Dossier.objects.create(
        numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
        crise=demande.crisis,
        competence=resolve_competence_for_request(demande),
        equipe=team,
        mission=mission,
        demande=demande,
        titre=demande.title,
        description=f"Demande affectée à l'équipe {team.name} : {demande.title}",
        statut=Dossier.Statut.AFFECTE,
        environment=demande.environment,
    )

    demandeur, _ = resolve_or_invite_demandeur(demande, request=request)

    # Régulateur·s à notifier : ceux affectés à la compétence du dossier si elle a pu
    # être déduite, sinon (à défaut) les membres de l'équipe ayant un rôle opérationnel
    # REGULATEUR actif pour l'une des compétences de l'équipe — pour ne pas notifier
    # personne juste parce que le mapping RequestType->Besoin est absent.
    regulateurs = populate_dossier_participants_and_notify(
        dossier, demandeur=demandeur, equipe=team,
        notification_titre="Nouvelle demande affectée à votre équipe",
        notification_message=f"La demande « {demande.title} » a été affectée à l'équipe {team.name} (dossier {dossier.numero}).",
    )

    try:
        suivi_paragraph = ""
        if demandeur:
            suivi_link = build_magic_link(
                request, demandeur, "magic-login", next_url=f"/dossier-suivi/{dossier.id}"
            )
            suivi_paragraph = (
                f"\nVous pouvez suivre l'avancement de votre dossier, ajouter des "
                f"commentaires et des photos ici :\n{suivi_link}\n"
            )
        send_mail_env_aware(
            request,
            subject=f"Votre demande « {demande.title} » a été prise en charge",
            message=(
                f"Bonjour {demande.first_name_request},\n\n"
                f"Votre demande d'aide « {demande.title} » a été affectée à l'équipe {team.name}, "
                f"qui va la traiter (dossier {dossier.numero}).\n"
                f"{suivi_paragraph}\n"
                "Cordialement,\n"
                "L'équipe Assista-Crise"
            ),
            from_email=None,
            recipient_list=[demande.email_request],
            fail_silently=True,
        )
    except Exception as e:
        print(f"Erreur envoi email affectation demande : {e}")

    audit_log(
        request=request,
        action_code="CREATION",
        objet_type="Dossier",
        objet_id=dossier.id,
        crise=demande.crisis,
        commentaire=f"Dossier {dossier.numero} créé suite à l'affectation de la demande à {team.name}",
    )

    return "created", dossier, regulateurs


def _assign_information_to_team(signalement, team, request):
    """Corps de InformationViewSet.bulk_assign_team : crée le dossier de suivi, notifie les
    régulateurs de l'équipe et le signalant lui-même — symétrique à _assign_request_to_team.
    Pas de participant DEMANDEUR (rôle qui ne correspond pas à un simple signalement). Le mail
    au signalant peut échouer silencieusement (souvent une adresse de repli/anonyme, voir
    other-declaration-form) : ce n'est jamais bloquant. Retourne (outcome, dossier) où outcome
    vaut "already_assigned" (no-op), "no_crisis" ou "created"."""
    if team.assigned_informations.filter(pk=signalement.pk).exists():
        return "already_assigned", None

    if not signalement.crisis:
        return "no_crisis", None

    team.assigned_informations.add(signalement)
    nouveau_membre = False
    if signalement.author_id and not team.members.filter(pk=signalement.author_id).exists():
        team.members.add(signalement.author)
        nouveau_membre = True

    dossier = Dossier.objects.create(
        numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
        crise=signalement.crisis,
        equipe=team,
        information=signalement,
        titre=signalement.title,
        description=f"Signalement affecté à l'équipe {team.name} : {signalement.title}",
        statut=Dossier.Statut.AFFECTE,
        environment=signalement.environment,
    )

    populate_dossier_participants_and_notify(
        dossier, equipe=team,
        notification_titre="Nouveau signalement affecté à votre équipe",
        notification_message=f"Le signalement « {signalement.title} » a été affecté à l'équipe {team.name} (dossier {dossier.numero}).",
    )

    audit_log(
        request=request,
        action_code="CREATION",
        objet_type="Dossier",
        objet_id=dossier.id,
        crise=signalement.crisis,
        commentaire=f"Dossier {dossier.numero} créé suite à l'affectation du signalement à {team.name}",
    )

    if signalement.email_information:
        equipe_paragraph = ""
        if nouveau_membre:
            equipe_paragraph = (
                "\nVous avez été associé(e) à l'équipe : vous pouvez consulter à tout moment "
                "sa zone, ses membres, ses missions et ses dossiers ici :\n"
                f"{_vue_equipe_link(request, team, signalement.author)}\n"
            )
        try:
            send_mail_env_aware(
                request,
                subject=f"Votre signalement « {signalement.title} » a été pris en charge",
                message=(
                    f"Bonjour {signalement.first_name_information},\n\n"
                    f"Votre signalement « {signalement.title} » a été affecté à l'équipe "
                    f"{team.name}, qui va s'en charger (dossier {dossier.numero}).\n{equipe_paragraph}\n"
                    "Merci pour votre vigilance,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[signalement.email_information],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Erreur envoi email prise en charge signalement : {e}")

    return "created", dossier


def populate_dossier_participants_and_notify(
    dossier, demandeur=None, equipe=None,
    notification_titre="Nouveau dossier à affecter",
    notification_message=None,
):
    """Peuple les DossierParticipant (demandeur, équipe, régulation) et notifie les
    régulateurs concernés d'un dossier fraîchement créé. Logique partagée entre le chemin
    automatique (perform_create) et le chemin manuel (assign_team), qui divergeaient
    jusqu'ici : l'un ajoutait l'équipe comme participants mais ne notifiait jamais de
    régulateur sur simple base de compétence, l'autre notifiait sans jamais peupler le rôle
    REGULATION ni ajouter l'équipe comme participants."""
    if demandeur:
        DossierParticipant.objects.get_or_create(
            dossier=dossier, utilisateur=demandeur, role=DossierParticipant.Role.DEMANDEUR,
            defaults={"environment": dossier.environment},
        )
        DossierHistorique.objects.create(
            dossier=dossier, auteur=demandeur, evenement="Demandeur ajouté au dossier",
            environment=dossier.environment,
        )

    if equipe:
        DossierHistorique.objects.create(
            dossier=dossier, evenement=f"Équipe affectée : {equipe.name}",
            environment=dossier.environment,
        )
        for membre in equipe.members.all():
            DossierParticipant.objects.get_or_create(
                dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE,
                defaults={"environment": dossier.environment},
            )
            DossierHistorique.objects.create(
                dossier=dossier, auteur=membre, evenement="Intervenant ajouté au dossier",
                environment=dossier.environment,
            )

    if dossier.competence:
        # Régulateur·s affecté·s à cette compétence, indépendamment de leur équipe.
        regulateurs = User.objects.filter(
            affectations_roles__competence=dossier.competence,
            affectations_roles__role__code="REGULATEUR",
            affectations_roles__actif=True,
        ).distinct()
    elif equipe:
        # Pas de compétence rattachée au dossier (ex: mapping RequestType->Besoin absent) :
        # à défaut, régulateur·s parmi les membres de l'équipe affectée, sur l'une de ses
        # compétences déclarées (ou n'importe laquelle des leurs si l'équipe n'en a aucune).
        member_ids = equipe.members.values_list('id', flat=True)
        regulateur_affectations = AffectationRoleOperationnel.objects.filter(
            utilisateur_id__in=member_ids, role__code="REGULATEUR", actif=True,
        )
        competence_ids = list(equipe.competences.values_list('id', flat=True))
        if competence_ids:
            regulateur_affectations = regulateur_affectations.filter(competence_id__in=competence_ids)
        regulateurs = User.objects.filter(
            id__in=regulateur_affectations.values_list('utilisateur_id', flat=True)
        ).distinct()
    else:
        regulateurs = User.objects.none()

    for regulateur in regulateurs:
        DossierParticipant.objects.get_or_create(
            dossier=dossier, utilisateur=regulateur, role=DossierParticipant.Role.REGULATION,
            defaults={"environment": dossier.environment},
        )
        Notification.objects.create(
            utilisateur=regulateur,
            dossier=dossier,
            titre=notification_titre,
            message=notification_message or f"Le dossier {dossier.numero} ({dossier.titre}) nécessite une affectation.",
            environment=dossier.environment,
        )
        DossierHistorique.objects.create(
            dossier=dossier, auteur=regulateur,
            evenement=f"{regulateur.email} notifié en tant que régulateur",
            environment=dossier.environment,
        )

    return regulateurs


# Un régulateur en tri initial se trompe parfois de formulaire (ex: une offre de matériel
# déposée comme demande d'aide) : _transformer_soumission recrée l'objet sous le bon type en
# copiant les champs communs (contact, localisation, description si le type cible en a un,
# crise, auteur, photo), plutôt que d'obliger la personne à ressaisir. Volontairement réservé
# aux soumissions PAS ENCORE affectées (aucune équipe, aucun dossier) : au-delà, la conversion
# devrait migrer des relations (participants, historique...) que ce helper ne gère pas.
_TRANSFORM_SUFFIX = {"REQUEST": "request", "OFFER": "offer", "INFORMATION": "information"}
_TRANSFORM_TYPE_FIELD = {"REQUEST": "request_type", "OFFER": "offer_type", "INFORMATION": "information_type"}


def _transform_deja_affecte(source_kind, obj) -> bool:
    if obj.assigned_teams.exists():
        return True
    if source_kind in ("REQUEST", "INFORMATION") and obj.dossiers.exists():
        return True
    return False


def _transformer_soumission(source_obj, source_kind, target_kind, request):
    from .models import Request as RequestModel, Offer as OfferModel, Information as InformationModel
    from .models import RequestType as RequestTypeModel, OfferType as OfferTypeModel, InformationType as InformationTypeModel

    target_model = {"REQUEST": RequestModel, "OFFER": OfferModel, "INFORMATION": InformationModel}[target_kind]
    target_type_model = {"REQUEST": RequestTypeModel, "OFFER": OfferTypeModel, "INFORMATION": InformationTypeModel}[target_kind]

    source_suffix = _TRANSFORM_SUFFIX[source_kind]
    target_suffix = _TRANSFORM_SUFFIX[target_kind]

    # Type cible déduit par correspondance de libellé (ex: "Matériel" existe dans les 3
    # catalogues) — à défaut, "Autre" ; jamais bloquant si aucun des deux n'existe.
    source_type_obj = getattr(source_obj, _TRANSFORM_TYPE_FIELD[source_kind], None)
    target_type_obj = None
    if source_type_obj and source_type_obj.type:
        target_type_obj = target_type_model.objects.filter(type=source_type_obj.type).first()
    if not target_type_obj:
        target_type_obj = target_type_model.objects.filter(type="Autre").first()

    fields = {
        "title": source_obj.title,
        f"first_name_{target_suffix}": getattr(source_obj, f"first_name_{source_suffix}"),
        f"last_name_{target_suffix}": getattr(source_obj, f"last_name_{source_suffix}"),
        f"email_{target_suffix}": getattr(source_obj, f"email_{source_suffix}"),
        f"phone_{target_suffix}": getattr(source_obj, f"phone_{source_suffix}"),
        "location": source_obj.location,
        "crisis": source_obj.crisis,
        "author": source_obj.author,
        # Pas de report du statut source : NON_TRAITEE/EN_COURS/TRAITEE (demande/signalement)
        # et DISPONIBLE/INDISPONIBLE (offre) sont deux sémantiques différentes du même enum
        # partagé — le nouvel objet part sur le statut par défaut de son propre type.
        "environment": source_obj.environment,
        "deletion_token": secrets.token_urlsafe(32),
        _TRANSFORM_TYPE_FIELD[target_kind]: target_type_obj,
    }
    if hasattr(target_model, "commune_code") and hasattr(source_obj, "commune_code"):
        fields["commune_code"] = source_obj.commune_code
    if hasattr(target_model, "description"):
        fields["description"] = getattr(source_obj, "description", None)

    new_obj = target_model.objects.create(**fields)

    if source_obj.photo:
        source_obj.photo.open("rb")
        new_obj.photo.save(os.path.basename(source_obj.photo.name), ContentFile(source_obj.photo.read()), save=True)
        source_obj.photo.close()

    audit_log(
        request=request,
        action_code="CREATION",
        objet_type=target_kind.capitalize(),
        objet_id=new_obj.id,
        crise=new_obj.crisis,
        commentaire=f"{target_kind.capitalize()} créé(e) par transformation de {source_kind.capitalize()} {source_obj.id} ({source_obj.title})",
    )
    audit_log(
        request=request,
        action_code="SUPPRESSION",
        objet_type=source_kind.capitalize(),
        objet_id=source_obj.id,
        crise=source_obj.crisis,
        commentaire=f"Supprimé(e) suite à transformation en {target_kind.capitalize()} {new_obj.id}",
    )
    source_obj.delete()
    return new_obj


class RequestViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Request.objects.all()
    serializer_class = RequestSerializer
    permission_classes = [AllowAny]
    filterset_class = AuthorEmailFilter

    def get_permissions(self):
        # get_permissions() étant surchargé, chaque @action avec son propre permission_classes
        # doit être explicitement listée ici, sinon elle retombe sur AllowAny (gotcha connue de
        # ce fichier). update/partial_update/destroy n'avaient justement AUCUNE restriction
        # avant ce correctif : n'importe qui, même anonyme, pouvait modifier/supprimer la
        # demande de n'importe qui d'autre — voir IsOwnerOrInstitutional.
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwnerOrInstitutional()]
        if self.action in ('assign_team', 'bulk_assign_mission', 'vue_mairie', 'transformer'):
            return [IsInstitutionalActor()]
        return [AllowAny()]

    def get_queryset(self):
        return annotate_distance_from_crisis(
            super().get_queryset().select_related('crisis', 'author')
        )

    @action(detail=True, methods=['post'])
    def transformer(self, request, pk=None):
        """Recrée cette demande sous forme d'offre ou de signalement (voir
        _transformer_soumission) — réservé aux demandes pas encore affectées."""
        demande = self.get_object()
        cible = request.data.get('cible')
        if cible not in ('OFFER', 'INFORMATION'):
            return Response({'error': "cible doit être 'OFFER' ou 'INFORMATION'."}, status=status.HTTP_400_BAD_REQUEST)
        if _transform_deja_affecte('REQUEST', demande):
            return Response(
                {'error': "Cette demande est déjà affectée à une équipe ou un dossier : impossible de la transformer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        nouvel_objet = _transformer_soumission(demande, 'REQUEST', cible, request)
        serializer_class = OfferSerializer if cible == 'OFFER' else InformationSerializer
        return Response(serializer_class(nouvel_objet, context={'request': request}).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        # Générer un token de suppression unique
        deletion_token = secrets.token_urlsafe(32)

        # Définir l'auteur si authentifié, sinon None
        author = self.request.user if self.request.user.is_authenticated else None
        demande = serializer.save(author=author, deletion_token=deletion_token, environment=get_active_environment(self.request))
        
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Request",
            objet_id=demande.id,
            crise=demande.crisis,
            commentaire=(
                f"Création demande : "
                f"{demande.title}"
            )
        )

        try:

            statut = Dossier.Statut.EN_ATTENTE_AFFECTATION

            equipe = None
            competence = resolve_competence_for_request(demande)

            if competence:

                regulateurs_disponibles = (
                    AffectationRoleOperationnel.objects
                    .filter(
                        competence=competence,
                        role__code="REGULATEUR",
                        actif=True,
                        disponibilites__disponible=True,
                        disponibilites__date_fin__isnull=True
                    )
                    .distinct()
                )

                if regulateurs_disponibles.exists():

                    statut = Dossier.Statut.AFFECTE

                else:

                    statut = (
                        Dossier.Statut
                        .EN_ATTENTE_DISTRIBUTION
                    )

                if demande.crisis:

                    # Parmi les équipes affectées à cette compétence sur cette crise, on
                    # retient celle dont la zone d'intervention déclarée couvre le mieux
                    # la localisation de la demande (zone précise > commune > département
                    # > aucune zone déclarée = disponible partout).
                    affectations = (
                        AffectationCompetence.objects
                        .filter(
                            crise=demande.crisis,
                            competence=competence,
                            active=True
                        )
                        .select_related('equipe')
                    )

                    meilleur_score = None

                    for affectation in affectations:

                        score = team_zone_specificity(affectation.equipe, demande)

                        if score is not None and (meilleur_score is None or score > meilleur_score):
                            meilleur_score = score
                            equipe = affectation.equipe

            if competence:

                dossier = Dossier.objects.create(
                    numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
                    crise=demande.crisis,
                    competence=competence,
                    equipe=equipe,
                    demande=demande,
                    titre=demande.title,
                    description=f"Demande créée automatiquement : {demande.title}",
                    statut=statut,
                    environment=demande.environment,
                )

                demandeur, _ = resolve_or_invite_demandeur(demande, request=self.request)
                # Notifie aussi les régulateurs actifs sur cette compétence : sans ça, un
                # dossier créé automatiquement n'était visible qu'en parcourant la liste
                # complète des dossiers — contrairement au chemin manuel (assign_team) qui
                # notifie déjà. Ils le retrouvent aussi via /dossiers/ma_file/.
                populate_dossier_participants_and_notify(dossier, demandeur=demandeur, equipe=equipe)

                audit_log(
                    request=self.request,
                    action_code="CREATION",
                    objet_type="Dossier",
                    objet_id=dossier.id,
                    crise=dossier.crise,
                    commentaire=f"Dossier {dossier.numero} créé automatiquement pour la demande : {demande.title}",
                )

            else:

                # Dossier.crise est obligatoire (NOT NULL) : sans crise associée à la
                # demande, il n'y a de toute façon aucun contexte auquel rattacher un
                # dossier de suivi automatique — le créer plantait silencieusement
                # (IntegrityError avalée par le except englobant) pour toute demande
                # anonyme sans crise dont le type n'a pas de compétence mappée.
                if demande.crisis:

                    dossier = Dossier.objects.create(
                        numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
                        crise=demande.crisis,
                        competence=None,
                        equipe=None,
                        demande=demande,
                        titre=demande.title,
                        description=(
                            f"Demande créée automatiquement : "
                            f"{demande.title}"
                        ),
                        statut=Dossier.Statut.EN_ATTENTE_AFFECTATION,
                        environment=demande.environment,
                    )

                    demandeur, _ = resolve_or_invite_demandeur(demande, request=self.request)
                    # Sans compétence ni équipe identifiée, seul le demandeur peut être
                    # rattaché ici (aucun régulateur à notifier) — mais c'est déjà mieux que
                    # zéro participant : sans ça ce dossier restait invisible au demandeur
                    # (le suivi passe par DossierParticipant, pas seulement par institution).
                    populate_dossier_participants_and_notify(dossier, demandeur=demandeur)

                    DossierHistorique.objects.create(
                        dossier=dossier,
                        evenement="Aucune compétence trouvée automatiquement",
                        commentaire=(
                            "Le dossier nécessite "
                            "une affectation manuelle."
                        ),
                        environment=dossier.environment,
                    )

                    audit_log(
                        request=self.request,
                        action_code="CREATION",
                        objet_type="Dossier",
                        objet_id=dossier.id,
                        crise=dossier.crise,
                        commentaire=f"Dossier {dossier.numero} créé automatiquement (sans compétence) pour la demande : {demande.title}",
                    )

                print(
                    f"Aucune compétence trouvée pour "
                    f"{demande.request_type}"
                )

        except Exception as e:
            print(f"Erreur création dossier automatique : {e}")

        # Construire l'URL de suppression (automatique selon l'environnement)
        deletion_url = f"{settings.SERVER_URL.rstrip('/')}/api/delete-request/{deletion_token}/"
        
        try:
            print(f"Tentative d'envoi de mail à {demande.email_request}...")
            
            send_mail_env_aware(
                self.request,
                subject="Confirmation de votre demande",
                message=(
                    f"Bonjour {demande.first_name_request},\n\n"
                    f"Nous accusons réception de votre demande d'aide : {demande.title}.\n"
                    "Elle est actuellement en attente de traitement par nos services.\n\n"
                    f"Si vous souhaitez annuler cette demande, cliquez sur le lien suivant :\n"
                    f"{deletion_url}\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,  # Utilise DEFAULT_FROM_EMAIL défini dans settings.py
                recipient_list=[demande.email_request],
                fail_silently=False,
            )
            print("Succès : Email de confirmation envoyé.")
            
        except Exception as e:
            print(f"Erreur critique : L'envoi de l'email a échoué. Détails : {e}")

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def assign_team(self, request, pk=None):
        """Affecte la demande à une équipe : crée un dossier de suivi, notifie le·s
        régulateur·s de l'équipe (AffectationRoleOperationnel role=REGULATEUR) et informe le
        demandeur par email. Ré-affecter à la même équipe est un no-op (pas de doublon)."""
        demande = self.get_object()
        team = get_object_or_404(Team, pk=request.data.get("team"))

        outcome, dossier, regulateurs = _assign_request_to_team(demande, team, request)

        if outcome == "already_assigned":
            return Response({"already_assigned": True})
        if outcome == "no_crisis":
            return Response(
                {"error": "Cette demande n'est liée à aucune crise : impossible de créer un dossier de suivi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"dossier": str(dossier.id), "numero": dossier.numero, "regulateurs_notifies": regulateurs.count()})

    @action(detail=False, methods=["post"], permission_classes=[IsInstitutionalActor])
    def bulk_assign_mission(self, request):
        """Affecte plusieurs demandes en une fois à une mission (existante ou créée à la
        volée) et à une équipe — même mécanique que assign_team (un Dossier par demande,
        notifications/email/audit inchangés), appliquée en boucle. Toutes les demandes
        sélectionnées doivent partager la même crise (une mission est rattachée à une seule
        crise) : sélection multi-crise refusée explicitement plutôt que scindée en silence."""
        request_ids = request.data.get("request_ids") or []
        if not request_ids:
            return Response({"error": "Aucune demande sélectionnée."}, status=status.HTTP_400_BAD_REQUEST)

        demandes = list(Request.objects.filter(pk__in=request_ids))
        if len(demandes) != len(set(request_ids)):
            return Response({"error": "Une ou plusieurs demandes sont introuvables."}, status=status.HTTP_400_BAD_REQUEST)

        crisis_ids = {d.crisis_id for d in demandes}
        if len(crisis_ids) != 1 or None in crisis_ids:
            return Response(
                {"error": "Toutes les demandes sélectionnées doivent être liées à la même crise pour être affectées à une mission commune."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        crisis_id = crisis_ids.pop()

        team = get_object_or_404(Team, pk=request.data.get("team"))

        mission_id = request.data.get("mission")
        new_mission = request.data.get("new_mission")
        if mission_id:
            mission = get_object_or_404(Mission, pk=mission_id)
            if str(mission.crise_id) != str(crisis_id):
                return Response(
                    {"error": "La mission choisie n'est pas rattachée à la même crise que les demandes sélectionnées."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif new_mission:
            mission = Mission.objects.create(
                titre=new_mission.get("titre", "").strip() or "Mission sans titre",
                crise_id=crisis_id,
                environment=get_active_environment(request),
            )
            mission.equipes.add(team)
        else:
            return Response({"error": "Choisissez une mission existante ou renseignez-en une nouvelle."}, status=status.HTTP_400_BAD_REQUEST)

        dossiers_created = []
        already_assigned = []
        for demande in demandes:
            outcome, dossier, _regulateurs = _assign_request_to_team(demande, team, request, mission=mission)
            if outcome == "already_assigned":
                already_assigned.append(str(demande.id))
            elif outcome == "created":
                dossiers_created.append(str(dossier.id))

        return Response({
            "mission": str(mission.id),
            "dossiers_created": dossiers_created,
            "already_assigned": already_assigned,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor])
    def vue_mairie(self, request):
        """Demandes de la commune de l'institution de l'utilisateur appelant (typiquement une
        mairie AUT_LOCALE) — 400 explicite si aucune institution ou aucune commune n'est
        associée au compte, plutôt qu'une liste vide silencieuse."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code
        queryset = self.get_queryset().filter(commune_code=commune_code)
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        demande = self.get_object()
        if not demande.photo or not user_can_view_photo(
            request, demande, teams_field='assigned_teams', dossiers_field='dossiers'
        ):
            return Response(status=403)
        return FileResponse(open(demande.photo.path, "rb"))

def _notify_institution_referent_of_team(team, institution, request):
    """Prévient le référent de l'institution qu'une équipe vient d'être créée sous son
    rattachement — le référent est le contact principal (ContactInstitution.contact_principal)
    s'il y en a un, sinon n'importe quel contact actif. Silencieux si l'institution n'a encore
    aucun contact enregistré : ne bloque pas la création de l'équipe pour autant."""
    referent_contact = (
        ContactInstitution.objects.filter(institution=institution, actif=True, contact_principal=True).first()
        or ContactInstitution.objects.filter(institution=institution, actif=True).first()
    )
    if referent_contact is None:
        return

    referent = referent_contact.utilisateur
    message = (
        f"L'équipe « {team.name} » vient d'être créée sous le rattachement de votre "
        f"institution ({institution.nom})."
    )
    Notification.objects.create(
        utilisateur=referent, titre="Nouvelle équipe créée sous votre institution",
        message=message, environment=team.environment,
    )
    try:
        send_mail_env_aware(
            request,
            subject=f"Nouvelle équipe créée sous {institution.nom}",
            message=(
                f"Bonjour {referent.first_name},\n\n{message}\n\n"
                "Cordialement,\nL'équipe Assista-Crise"
            ),
            from_email=None,
            recipient_list=[referent.email],
            fail_silently=True,
        )
    except Exception as e:
        print(f"Erreur envoi email référent institution (équipe) : {e}")


def _vue_equipe_link(request, team, membre):
    """Lien magique vers la "vue équipe" du bénévole (zone, membres, missions, dossiers) —
    utilisé par toutes les notifications d'association à une équipe, quel que soit le chemin
    d'affectation (voir TeamViewSet.perform_update, OfferViewSet.bulk_create_team,
    _assign_information_to_team)."""
    return build_magic_link(request, membre, "magic-login", next_url=f"/mon-equipe/{team.id}")


def _notify_new_team_member(team, membre, request):
    """Email envoyé à un bénévole qui vient d'être ajouté aux membres d'une équipe (cas
    générique, ex: édition de l'équipe côté admin) : l'informe de l'association et lui
    transmet le lien vers sa "vue équipe". Silencieux si l'envoi échoue (jamais bloquant)."""
    if not membre.email:
        return
    try:
        send_mail_env_aware(
            request,
            subject=f"Vous avez été associé(e) à l'équipe {team.name}",
            message=(
                f"Bonjour {membre.first_name},\n\n"
                f"Vous avez été associé(e) à l'équipe « {team.name} ».\n\n"
                "Vous pouvez consulter à tout moment la zone, les membres, les missions et les "
                f"dossiers de votre équipe ici :\n{_vue_equipe_link(request, team, membre)}\n\n"
                "Cordialement,\nL'équipe Assista-Crise"
            ),
            from_email=None,
            recipient_list=[membre.email],
            fail_silently=True,
        )
    except Exception as e:
        print(f"Erreur envoi email association équipe : {e}")


def _appartient_a_institution(request, institution) -> bool:
    """Un admin plateforme n'est jamais limité par cette vérification ; sinon, l'appelant doit
    être un contact actif de l'institution donnée — même garde-fou territorial que
    approve_account/reject_account, appliqué ici aux actions qui agissent sur une équipe."""
    if get_effective_role(request) == UserRole.ADMINISTRATOR:
        return True
    return ContactInstitution.objects.filter(
        institution=institution, utilisateur=request.user, actif=True,
    ).exists()


class TeamViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset           = Team.objects.prefetch_related(
        'members', 'assigned_crises', 'assigned_offers', 'assigned_requests'
    ).select_related('leader').all()
    serializer_class   = TeamSerializer

    def get_permissions(self):
        # AVANT ce correctif, list/create/update/destroy n'avaient aucune restriction propre :
        # n'importe quel compte authentifié pouvait lister toutes les équipes (zones, membres),
        # en créer, ou modifier n'importe laquelle — y compris se nommer soi-même leader/
        # régulateur d'une équipe à laquelle il n'appartient pas (vérifié en le reproduisant).
        # retrieve reste ouvert à tout authentifié : un bénévole doit pouvoir consulter SA
        # propre équipe (voir "vue équipe"), déjà distribuée par ID via mes-equipes/l'email
        # d'association, jamais par une liste publique.
        if self.action in (
            'list', 'create', 'update', 'partial_update', 'destroy',
            'inviter_membre', 'definir_mission', 'assigner_ressource', 'retirer_ressource',
        ):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        # Une équipe ne doit pas rester livrée à elle-même : rattachée par défaut à
        # l'institution du créateur si aucune n'est explicitement fournie — pas d'erreur si le
        # créateur lui-même n'en a pas (compte encore non rattaché), l'équipe reste alors sans
        # institution comme avant ce changement, plutôt que de bloquer sa création.
        institution = serializer.validated_data.get('institution') or getattr(self.request.user, 'institution', None)
        team = serializer.save(environment=get_active_environment(self.request), institution=institution)

        if institution is not None:
            _notify_institution_referent_of_team(team, institution, self.request)

        for membre in team.members.all():
            _notify_new_team_member(team, membre, self.request)

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Création équipe : {team.name}",
        )

    def perform_update(self, serializer):
        # Ne notifier que les membres réellement NOUVEAUX (jamais ceux déjà présents avant
        # cette modification, pour ne pas ré-envoyer le mail à chaque édition de l'équipe qui
        # ne touche pas member_ids, ex: changement de couleur ou de zone).
        previous_member_ids = set(serializer.instance.members.values_list('id', flat=True))
        team = serializer.save()
        new_members = team.members.exclude(id__in=previous_member_ids)
        for membre in new_members:
            _notify_new_team_member(team, membre, self.request)

    @action(detail=False, methods=['get'], url_path='mes-equipes')
    def mes_equipes(self, request):
        """Équipes dont l'utilisateur connecté est membre, chef ou régulateur — point d'entrée
        de sa "vue équipe" (voir aussi le lien direct envoyé par email lors de son
        association). Inclut le rôle de chef/régulateur pour qu'un chef d'équipe de terrain
        pilotant plusieurs équipes les retrouve toutes, même sur celles où il n'est pas compté
        comme simple membre."""
        equipes = self.get_queryset().filter(
            Q(members=request.user) | Q(leader=request.user) | Q(regulateur=request.user)
        ).distinct()
        return Response(self.get_serializer(equipes, many=True).data)

    @action(detail=True, methods=['post'], url_path='inviter-membre')
    def inviter_membre(self, request, pk=None):
        """Invite un nouveau membre dans l'institution de l'équipe (nom/prénom/email/tél/rôle),
        l'ajoute directement à l'équipe, et lui donne les droits collectivité locale sur la
        plateforme — quel que soit le rôle FONCTIONNEL choisi (RoleOperationnel), qui ne décrit
        que sa place dans l'équipe, pas ses permissions applicatives. Si un compte existe déjà
        pour cet email, son `type` n'est jamais rétrogradé ni changé : seul le rattachement à
        l'institution/l'équipe est ajouté."""
        team = self.get_object()
        if team.institution is None:
            return Response(
                {"error": "Cette équipe n'est rattachée à aucune institution."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Une mairie ne doit pouvoir inviter que dans SES propres équipes, pas dans celles
        # d'une autre institution — un admin plateforme n'est pas concerné par cette limite.
        if not _appartient_a_institution(request, team.institution):
            return Response(
                {"error": "Vous ne pouvez inviter des membres que pour les équipes de votre propre institution."},
                status=status.HTTP_403_FORBIDDEN,
            )

        email = (request.data.get('email') or '').strip().lower()
        first_name = (request.data.get('first_name') or '').strip()
        last_name = (request.data.get('last_name') or '').strip()
        phone_number = (request.data.get('phone_number') or '').strip()
        role_code = request.data.get('role_code')

        if not email or not first_name or not last_name or not role_code:
            return Response(
                {"error": "Prénom, nom, email et rôle sont obligatoires."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = RoleOperationnel.objects.filter(code=role_code).first()
        if not role:
            return Response({"error": "Rôle inconnu."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email__iexact=email).first()
        invited = False
        if user is None:
            user = User.objects.create_user(
                username=email, email=email,
                first_name=first_name, last_name=last_name, phone_number=phone_number,
                password=None, type=UserRole.LOCAL_AUTHORITY, institution=team.institution,
                enabled=False, is_active=False,
            )
            invited = True

        ContactInstitution.objects.get_or_create(
            institution=team.institution, utilisateur=user,
            defaults={'fonction': role.libelle, 'actif': True},
        )
        AffectationRoleOperationnel.objects.get_or_create(
            utilisateur=user, institution=team.institution, role=role, competence=None,
            defaults={'actif': True},
        )
        team.members.add(user)

        if invited:
            # Le lien "vue équipe" de _notify_new_team_member est un lien de connexion magique :
            # inutilisable tant que le compte n'est pas activé (voir MagicLoginView). Un compte
            # tout juste invité ne reçoit donc que l'email d'activation (qui contient déjà un
            # lien de connexion pour APRÈS activation) — jamais les deux à la fois.
            send_institution_account_email(request, user)
        else:
            _notify_new_team_member(team, user, request)

        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Invitation de {user.email} comme membre ({role.libelle})",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='definir-mission')
    def definir_mission(self, request, pk=None):
        """Définit (ou remplace) la mission courante de l'équipe, en texte libre — une équipe
        n'a qu'une seule mission active à la fois ; la redéfinir n'efface pas l'historique
        (voir AuditLog), elle change simplement ce sur quoi portent les prochaines ressources
        affectées."""
        team = self.get_object()
        if not _appartient_a_institution(request, team.institution):
            return Response(
                {"error": "Vous ne pouvez définir la mission que pour les équipes de votre propre institution."},
                status=status.HTTP_403_FORBIDDEN,
            )

        titre = (request.data.get('titre') or '').strip()
        if not titre:
            return Response({"error": "Le titre de la mission est obligatoire."}, status=status.HTTP_400_BAD_REQUEST)

        mission = Mission.objects.create(titre=titre, environment=get_active_environment(request))
        mission.equipes.add(team)
        team.mission_active = mission
        team.save(update_fields=['mission_active'])

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Mission de l'équipe définie : « {mission.titre} »",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='assigner-ressource')
    def assigner_ressource(self, request, pk=None):
        """Ajoute une offre (bénévole seul, bénévole+matériel, ou matériel seul) comme
        ressource de l'équipe, rattachée à sa mission active — voir Team.mission_active. Ajoute
        aussi l'auteur de l'offre comme membre de l'équipe, comme le faisait déjà l'ancien
        mécanisme de "missions" assignées."""
        team = self.get_object()
        if not _appartient_a_institution(request, team.institution):
            return Response(
                {"error": "Vous ne pouvez affecter des ressources qu'aux équipes de votre propre institution."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not team.mission_active_id:
            return Response(
                {"error": "Définissez d'abord la mission de l'équipe avant d'y affecter des ressources."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        offer_id = request.data.get('offer_id')
        try:
            offer = Offer.objects.get(id=offer_id)
        except (Offer.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Offre introuvable."}, status=status.HTTP_400_BAD_REQUEST)

        offer.mission = team.mission_active
        offer.save(update_fields=['mission'])
        team.assigned_offers.add(offer)
        if offer.author_id:
            team.members.add(offer.author_id)

        audit_log(
            request=request,
            action_code="AFFECTATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Ressource ajoutée : « {offer.title} » (mission : {team.mission_active.titre})",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='retirer-ressource')
    def retirer_ressource(self, request, pk=None):
        """Retire une offre des ressources de l'équipe — ne vide le lien Offer.mission que s'il
        pointait bien vers la mission active de CETTE équipe (une offre déjà réaffectée
        ailleurs entre-temps ne doit pas se faire couper son lien par erreur)."""
        team = self.get_object()
        if not _appartient_a_institution(request, team.institution):
            return Response(
                {"error": "Vous ne pouvez retirer des ressources que pour les équipes de votre propre institution."},
                status=status.HTTP_403_FORBIDDEN,
            )

        offer_id = request.data.get('offer_id')
        try:
            offer = Offer.objects.get(id=offer_id)
        except (Offer.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Offre introuvable."}, status=status.HTTP_400_BAD_REQUEST)

        team.assigned_offers.remove(offer)
        if team.mission_active_id and offer.mission_id == team.mission_active_id:
            offer.mission = None
            offer.save(update_fields=['mission'])

        audit_log(
            request=request,
            action_code="SUPPRESSION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Ressource retirée : « {offer.title} »",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

class MissionViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Mission.objects.select_related('crise').prefetch_related('equipes').all()
    serializer_class = MissionSerializer

    def get_permissions(self):
        # Écriture réservée aux institutionnels, comme avant. Lecture ouverte à tout
        # authentifié (voir get_queryset) : un bénévole doit pouvoir consulter les missions
        # de sa propre équipe depuis sa "vue équipe", pas seulement un acteur institutionnel.
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        if get_effective_role(self.request) in INSTITUTIONAL_TYPES:
            return qs
        return qs.filter(equipes__members=self.request.user).distinct()

class OfferViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Offer.objects.all()
    serializer_class = OfferSerializer
    permission_classes = [AllowAny]
    filterset_class = OfferSearchFilter

    def get_permissions(self):
        # Voir le commentaire équivalent sur RequestViewSet.get_permissions : même correctif
        # (update/partial_update/destroy n'avaient aucune restriction avant ce changement).
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwnerOrInstitutional()]
        if self.action in ('assign_dossier', 'bulk_create_team', 'transformer'):
            return [IsInstitutionalActor()]
        return [AllowAny()]

    def get_queryset(self):
        return annotate_distance_from_crisis(
            super().get_queryset().select_related('crisis', 'author')
        )

    @action(detail=True, methods=['post'])
    def transformer(self, request, pk=None):
        """Recrée cette offre sous forme de demande ou de signalement — réservé aux offres pas
        encore affectées à une équipe (voir _transformer_soumission)."""
        offre = self.get_object()
        cible = request.data.get('cible')
        if cible not in ('REQUEST', 'INFORMATION'):
            return Response({'error': "cible doit être 'REQUEST' ou 'INFORMATION'."}, status=status.HTTP_400_BAD_REQUEST)
        if _transform_deja_affecte('OFFER', offre):
            return Response(
                {'error': "Cette offre est déjà affectée à une équipe : impossible de la transformer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not offre.location:
            return Response(
                {'error': "Cette offre n'a pas de localisation : impossible de la transformer en demande/signalement, qui en exigent une."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        nouvel_objet = _transformer_soumission(offre, 'OFFER', cible, request)
        serializer_class = RequestSerializer if cible == 'REQUEST' else InformationSerializer
        return Response(serializer_class(nouvel_objet, context={'request': request}).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        # Générer un token de suppression unique
        deletion_token = secrets.token_urlsafe(32)
        
        # Si user authentifié, il est autheur
        environment = get_active_environment(self.request)
        if self.request.user.is_authenticated:
            offre = serializer.save(author=self.request.user, deletion_token=deletion_token, environment=environment)
        else:
            # Sinon il est none
            offre = serializer.save(author=None, deletion_token=deletion_token, environment=environment)
        
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Offer",
            objet_id=offre.id,
            commentaire=f"Création offre : {offre.title}",
        )

        # Construire l'URL de suppression (automatique selon l'environnement)
        deletion_url = f"{settings.SERVER_URL.rstrip('/')}/api/delete-offer/{deletion_token}/"

        try:
            print(f"Tentative d'envoi de mail à {offre.email_offer}...")
            
            send_mail_env_aware(
                self.request,
                subject=f"Confirmation : Votre offre '{offre.title}' a bien été enregistrée",
                message=(
                    f"Bonjour {offre.first_name_offer},\n\n"
                    f"Nous vous remercions pour votre offre d'aide : {offre.title}.\n"
                    "Elle est maintenant visible et disponible pour les personnes dans le besoin.\n\n"
                    f"Si vous souhaitez retirer cette offre, cliquez sur le lien suivant :\n"
                    f"{deletion_url}\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[offre.email_offer],
                fail_silently=False,
            )
            print("Succès : Email de confirmation envoyé.")
            
        except Exception as e:
            print(f"Erreur critique : L'envoi de l'email a échoué. Détails : {e}")

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def assign_dossier(self, request, pk=None):
        """Affecte l'auteur de l'offre à un dossier (participant OFFRANT). L'offre doit avoir un
        auteur identifié (compte utilisateur) : une offre anonyme ne peut pas être rattachée."""
        offer = self.get_object()
        if not offer.author:
            return Response(
                {"error": "Cette offre n'a pas d'auteur identifié : impossible de l'affecter à un dossier."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dossier = get_object_or_404(Dossier, pk=request.data.get("dossier"), environment=get_active_environment(request))
        participant, created = DossierParticipant.objects.get_or_create(
            dossier=dossier, utilisateur=offer.author, role=DossierParticipant.Role.OFFRANT,
            defaults={"environment": dossier.environment},
        )
        if created:
            DossierHistorique.objects.create(
                dossier=dossier, auteur=offer.author,
                evenement=f"Offrant ajouté au dossier (offre : {offer.title})",
                environment=dossier.environment,
            )
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="DossierParticipant",
                objet_id=participant.id,
                commentaire=f"{offer.author.email} affecté au dossier {dossier.numero} en tant qu'offrant",
            )
            try:
                send_mail_env_aware(
                    request,
                    subject=f"Votre offre « {offer.title} » a été affectée à un dossier",
                    message=(
                        f"Bonjour {offer.first_name_offer},\n\n"
                        f"Votre offre d'aide « {offer.title} » a été rattachée au dossier "
                        f"{dossier.numero}, dont l'équipe {dossier.equipe.name if dossier.equipe else 'en charge'} "
                        "s'occupe activement.\n\n"
                        "Merci pour votre aide,\n"
                        "L'équipe Assista-Crise"
                    ),
                    from_email=None,
                    recipient_list=[offer.email_offer],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Erreur envoi email affectation offre à un dossier : {e}")

        return Response({"id": str(participant.id), "dossier": str(dossier.id), "created": created})

    @action(detail=False, methods=["post"], permission_classes=[IsInstitutionalActor])
    def bulk_create_team(self, request):
        """Crée une équipe à partir d'une sélection d'offres : les membres sont les auteurs
        distincts des offres sélectionnées (offres anonymes ignorées, même logique que
        l'affectation d'équipe individuelle existante côté frontend), l'équipe est reliée aux
        offres sélectionnées et un régulateur optionnel lui est assigné directement."""
        offer_ids = request.data.get("offer_ids") or []
        if not offer_ids:
            return Response({"error": "Aucune offre sélectionnée."}, status=status.HTTP_400_BAD_REQUEST)

        offres = list(Offer.objects.filter(pk__in=offer_ids))
        if len(offres) != len(set(offer_ids)):
            return Response({"error": "Une ou plusieurs offres sont introuvables."}, status=status.HTTP_400_BAD_REQUEST)

        team_name = (request.data.get("team_name") or "").strip()
        if not team_name:
            return Response({"error": "Le nom de l'équipe est obligatoire."}, status=status.HTTP_400_BAD_REQUEST)

        regulateur_id = request.data.get("regulateur")
        regulateur = get_object_or_404(User, pk=regulateur_id) if regulateur_id else None

        team = Team.objects.create(
            name=team_name, regulateur=regulateur,
            environment=get_active_environment(request),
        )
        team.assigned_offers.set(offres)
        members = {o.author for o in offres if o.author_id}
        if members:
            team.members.set(members)

        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Équipe {team.name} créée depuis {len(offres)} offre(s) sélectionnée(s)",
        )

        for offre in offres:
            equipe_paragraph = ""
            if offre.author_id:
                equipe_paragraph = (
                    "\nVous pouvez consulter à tout moment la zone, les membres, les missions "
                    f"et les dossiers de votre équipe ici :\n{_vue_equipe_link(request, team, offre.author)}\n"
                )
            try:
                send_mail_env_aware(
                    request,
                    subject=f"Votre offre « {offre.title} » a été affectée à l'équipe {team.name}",
                    message=(
                        f"Bonjour {offre.first_name_offer},\n\n"
                        f"Votre offre d'aide « {offre.title} » a été affectée à l'équipe {team.name}, "
                        f"qui va s'en charger.\n{equipe_paragraph}\n"
                        "Merci pour votre aide,\n"
                        "L'équipe Assista-Crise"
                    ),
                    from_email=None,
                    recipient_list=[offre.email_offer],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Erreur envoi email affectation offre à l'équipe : {e}")

        return Response(TeamSerializer(team).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        offer = self.get_object()
        if not offer.photo or not user_can_view_photo(
            request, offer, teams_field='assigned_teams'
        ):
            return Response(status=403)
        return FileResponse(open(offer.photo.path, "rb"))

class DisponibiliteOffreViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Créneaux de disponibilité (matin/midi/soir/nuit, 8 jours) déclarés avec une offre d'aide."""
    queryset = DisponibiliteOffre.objects.all()
    serializer_class = DisponibiliteOffreSerializer
    permission_classes = [AllowAny]
    filterset_fields = ["offer"]

class InformationViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Information.objects.all()
    serializer_class = InformationSerializer
    permission_classes = [AllowAny]
    filterset_class = AuthorEmailFilter

    def get_permissions(self):
        # Voir le commentaire équivalent sur RequestViewSet.get_permissions : même correctif
        # (update/partial_update/destroy n'avaient aucune restriction avant ce changement —
        # reproduit en direct : une requête DELETE anonyme supprimait n'importe quel
        # signalement).
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwnerOrInstitutional()]
        if self.action in ('vue_mairie', 'bulk_assign_team', 'transformer'):
            return [IsInstitutionalActor()]
        return [AllowAny()]

    def get_queryset(self):
        return annotate_distance_from_crisis(
            super().get_queryset().select_related('crisis', 'author')
        )

    @action(detail=True, methods=['post'])
    def transformer(self, request, pk=None):
        """Recrée ce signalement sous forme de demande ou d'offre — réservé aux signalements
        pas encore affectés à une équipe/dossier (voir _transformer_soumission). La
        description, si le régulateur en saisit une ensuite côté demande/offre, n'existe pas
        sur Information : seul le titre est repris."""
        signalement = self.get_object()
        cible = request.data.get('cible')
        if cible not in ('REQUEST', 'OFFER'):
            return Response({'error': "cible doit être 'REQUEST' ou 'OFFER'."}, status=status.HTTP_400_BAD_REQUEST)
        if _transform_deja_affecte('INFORMATION', signalement):
            return Response(
                {'error': "Ce signalement est déjà affecté à une équipe ou un dossier : impossible de le transformer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        nouvel_objet = _transformer_soumission(signalement, 'INFORMATION', cible, request)
        serializer_class = RequestSerializer if cible == 'REQUEST' else OfferSerializer
        return Response(serializer_class(nouvel_objet, context={'request': request}).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        # Générer un token de suppression unique
        deletion_token = secrets.token_urlsafe(32)
        
        # Si l'utilisateur est authentifié, on l'assigne comme auteur
        environment = get_active_environment(self.request)
        if self.request.user.is_authenticated:
            info = serializer.save(author=self.request.user, deletion_token=deletion_token, environment=environment)
        else:
            # Sinon on sauvegarde sans auteur (None)
            info = serializer.save(author=None, deletion_token=deletion_token, environment=environment)
        
        # Construire l'URL de suppression (automatique selon l'environnement)
        deletion_url = f"{settings.SERVER_URL.rstrip('/')}/api/delete-information/{deletion_token}/"
        
        try:
            print(f"Tentative d'envoi de mail à {info.email_information}...")
            
            send_mail_env_aware(
                self.request,
                subject=f"Confirmation : Votre information '{info.title}' a bien été partagée",
                message=(
                    f"Bonjour {info.first_name_information},\n\n"
                    f"Nous vous remercions pour le partage de cette information : {info.title}.\n"
                    "Elle est maintenant visible par la communauté.\n\n"
                    f"Si vous souhaitez retirer cette information, cliquez sur le lien suivant :\n"
                    f"{deletion_url}\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[info.email_information],
                fail_silently=False,
            )
            print("Succès : Email de confirmation envoyé.")
            
        except Exception as e:
            print(f"Erreur critique : L'envoi de l'email a échoué. Détails : {e}")

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor])
    def vue_mairie(self, request):
        """Signalements de la commune de l'institution de l'utilisateur appelant — même
        contrat que RequestViewSet.vue_mairie."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code
        queryset = self.get_queryset().filter(commune_code=commune_code)
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["post"], permission_classes=[IsInstitutionalActor])
    def bulk_assign_team(self, request):
        """Affecte une sélection de signalements ("divers" — ex: arbre sur la chaussée) à une
        équipe existante (ex: voirie), en une fois. Crée un Dossier par signalement (statut
        AFFECTE, "en attente de traitement"), comme pour les demandes — un signalement affecté
        doit pouvoir être suivi au même titre qu'une demande, pas seulement rattaché à
        l'équipe."""
        information_ids = request.data.get("information_ids") or []
        if not information_ids:
            return Response({"error": "Aucun signalement sélectionné."}, status=status.HTTP_400_BAD_REQUEST)

        informations = list(Information.objects.filter(pk__in=information_ids))
        if len(informations) != len(set(information_ids)):
            return Response({"error": "Un ou plusieurs signalements sont introuvables."}, status=status.HTTP_400_BAD_REQUEST)

        team = get_object_or_404(Team, pk=request.data.get("team"))

        dossiers_created = []
        already_assigned = []
        no_crisis = []
        for signalement in informations:
            outcome, dossier = _assign_information_to_team(signalement, team, request)
            if outcome == "already_assigned":
                already_assigned.append(str(signalement.id))
            elif outcome == "no_crisis":
                no_crisis.append(str(signalement.id))
            elif outcome == "created":
                dossiers_created.append(str(dossier.id))

        return Response({
            "team": TeamSerializer(team).data,
            "dossiers_created": dossiers_created,
            "already_assigned": already_assigned,
            "no_crisis": no_crisis,
        })

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        info = self.get_object()
        if not info.photo or not user_can_view_photo(request, info):
            return Response(status=403)
        return FileResponse(open(info.photo.path, "rb"))

# --- VIEWSETS SIMPLES POUR LES TYPES ---
class RequestTypeViewSet(viewsets.ModelViewSet):
    # AllowAny : le formulaire public "demander de l'aide" (request-help-form) n'a pas de
    # garde d'authentification — sans ça, un visiteur anonyme recevait un 401 en listant les
    # types, d'où le menu "Choisissez votre besoin" vide (même bug que déjà corrigé sur
    # InformationTypeViewSet pour le signalement, et déjà bon sur OfferTypeViewSet).
    queryset = RequestType.objects.all()
    serializer_class = RequestTypeSerializer
    permission_classes = [AllowAny]

class OfferTypeViewSet(viewsets.ModelViewSet):
    queryset = OfferType.objects.all()
    serializer_class = OfferTypeSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return OfferType.objects.filter(actif=True)

class InformationTypeViewSet(TagLikeViewSetMixin, viewsets.ModelViewSet):
    # AllowAny : la page de signalement (other-declaration-form) est accessible sans compte,
    # au même titre que les autres formulaires publics (demande/offre/crise) — un passant qui
    # signale un arbre sur la chaussée ne doit pas avoir à se connecter, y compris pour lister
    # les types existants ou en proposer un nouveau.
    queryset = InformationType.objects.all()
    serializer_class = InformationTypeSerializer
    permission_classes = [AllowAny]
    tag_field = "type"

    def perform_create(self, serializer):
        information_type = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InformationType",
            objet_id=information_type.id,
            commentaire=f"Création type de signalement : {information_type.type}",
        )

# --- VUES POUR LA SUPPRESSION VIA TOKEN ---
from django.views import View
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

class DeleteRequestView(View):
    """Vue pour supprimer une demande via token"""
    def get(self, request, token):
        demande = get_object_or_404(Request, deletion_token=token)
        titre = demande.title
        demande.delete()
        return HttpResponse(f"<h1>Demande supprimée</h1><p>La demande '{titre}' a bien été supprimée.</p>")

class DeleteOfferView(View):
    """Vue pour supprimer une offre via token"""
    def get(self, request, token):
        offre = get_object_or_404(Offer, deletion_token=token)
        titre = offre.title
        offre.delete()
        return HttpResponse(f"<h1>Offre supprimée</h1><p>L'offre '{titre}' a bien été supprimée.</p>")

class ConfirmerAffectationBenevoleView(View):
    """Confirmation par lien (oui/non) de l'affectation d'un bénévole individuel sur un point
    — pas de compte requis, jeton opaque comme les autres liens de désinscription anonymes."""
    def get(self, request, token, reponse):
        affectation = get_object_or_404(AffectationPointBenevole, token_confirmation=token)

        if reponse not in ("oui", "non"):
            return HttpResponse("<h1>Lien invalide</h1>", status=400)

        if affectation.date_reponse is not None:
            return HttpResponse(
                f"<h1>Réponse déjà enregistrée</h1>"
                f"<p>Vous aviez déjà répondu « {affectation.get_statut_display()} » à cette sollicitation.</p>"
            )

        affectation.statut = StatutAffectation.CONFIRME if reponse == "oui" else StatutAffectation.DECLINE
        affectation.date_reponse = timezone.now()
        affectation.save()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="AffectationPointBenevole",
            objet_id=affectation.id,
            crise=affectation.point.crise,
            commentaire=f"{affectation.benevole.email} a répondu « {affectation.get_statut_display()} » pour le point {affectation.point.nom}",
        )

        if reponse == "non":
            # Les créneaux liés à une affectation déclinée n'ont plus lieu d'être : on les
            # retire du planning plutôt que de laisser un "confirmé" fantôme visible.
            affectation.creneaux.all().delete()
            message = "Votre indisponibilité a bien été enregistrée. Merci de nous avoir prévenus."
        else:
            message = "Merci ! Votre disponibilité est confirmée."

        return HttpResponse(f"<h1>{message}</h1>")


class DeleteInformationView(View):
    """Vue pour supprimer une information via token"""
    def get(self, request, token):
        info = get_object_or_404(Information, deletion_token=token)
        titre = info.title
        info.delete()
        return HttpResponse(f"<h1>Information supprimée</h1><p>L'information '{titre}' a bien été supprimée.</p>")

    #  --------------------------- add by Laura ------------------------------------

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

class MyTokenRefreshView(TokenRefreshView):
    """Rafraîchir un token ne nécessite qu'un refresh token valide, pas une session déjà authentifiée."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer # Ajoute la logique de mot de passe dans le serializer
    permission_classes = [permissions.AllowAny]

class InstitutionValidationView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email", "")
        institution_name = request.data.get("institution_name", "")
        institution_type = request.data.get("institution_type", "")
        commune_name = request.data.get("commune_name", "")
        commune_code = request.data.get("commune_code", "")

        valid, message, details = InstitutionEmailValidator.validate_institution_account(
            email=email,
            institution_name=institution_name,
            institution_type=institution_type,
            commune_name=commune_name,
            commune_code=commune_code,
        )

        return Response({
            "valid": valid,
            "message": message,
            "details": details,
        }, status=status.HTTP_200_OK if valid else status.HTTP_400_BAD_REQUEST)

class AccountActivationView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, uidb64, token, *args, **kwargs):
        user = get_user_from_magic_link(uidb64, token)
        if not user:
            return Response({'error': 'Lien invalide ou expiré'}, status=status.HTTP_400_BAD_REQUEST)

        already_enabled = user.enabled

        user.enabled = True
        user.is_active = True
        user.save(update_fields=['enabled', 'is_active'])

        # Le rattachement à une institution (contact + rôle opérationnel) ne doit se faire qu'ici,
        # une fois la possession de la boîte mail prouvée par ce clic — jamais à la simple
        # inscription. Idempotent (get_or_create) : un second clic ne duplique rien.
        if not already_enabled and getattr(user, 'type', None) == UserRole.LOCAL_AUTHORITY:
            attach_user_to_institution(user, request)
            audit_log(
                request=request,
                action_code="CONNEXION",
                objet_type="User",
                objet_id=user.id,
                commentaire=f"Activation de compte confirmée par email : {user.email}",
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'message': 'Compte activé avec succès',
        }, status=status.HTTP_200_OK)


class MagicLoginView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, uidb64, token, *args, **kwargs):
        user = get_user_from_magic_link(uidb64, token)
        if not user or not user.enabled:
            return Response({'error': 'Lien invalide ou expiré'}, status=status.HTTP_400_BAD_REQUEST)

        user.enabled = True
        user.is_active = True
        user.save(update_fields=['enabled', 'is_active'])

        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'message': 'Connexion réussie sans mot de passe'
        }, status=status.HTTP_200_OK)


class UserMeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

class ChangePasswordView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")
        if not user.check_password(old_password):
            return Response({"error": "Ancien mot de passe incorrect"}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetConfirmView(generics.GenericAPIView):
    """Consomme le lien envoyé par UserViewSet.send_password_reset : contrairement à
    ChangePasswordView, ne requiert pas de connaître l'ancien mot de passe — la preuve de
    possession de la boîte mail (via le token signé) en tient lieu."""

    permission_classes = [permissions.AllowAny]

    def post(self, request, uidb64, token, *args, **kwargs):
        user = get_user_from_magic_link(uidb64, token)
        if not user:
            return Response({'error': 'Lien invalide ou expiré'}, status=status.HTTP_400_BAD_REQUEST)

        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 8:
            return Response(
                {'error': 'Le mot de passe doit contenir au moins 8 caractères'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save(update_fields=['password'])

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="User",
            objet_id=user.id,
            commentaire=f"Mot de passe réinitialisé via lien email : {user.email}",
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class MaPositionView(generics.GenericAPIView):
    """Auto-déclaration de position par l'utilisateur connecté : jamais un traçage forcé en
    tâche de fond — c'est au frontend de décider quand appeler ce endpoint, seulement lorsqu'il
    a déjà obtenu la position pour une autre raison (carte, adresse...). Voir
    DernierePositionUtilisateur pour la sémantique exacte (un seul enregistrement par
    utilisateur et par environnement, écrasé à chaque capture)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            latitude = float(request.data.get('latitude'))
            longitude = float(request.data.get('longitude'))
        except (TypeError, ValueError):
            return Response(
                {'error': 'latitude et longitude sont requis et doivent être numériques'},
                status=status.HTTP_400_BAD_REQUEST
            )

        position, _ = DernierePositionUtilisateur.objects.update_or_create(
            utilisateur=request.user,
            environment=get_active_environment(request),
            defaults={'location': Point(longitude, latitude, srid=4326)},
        )
        return Response(DernierePositionUtilisateurSerializer(position).data, status=status.HTTP_200_OK)


class PositionsEquipesView(generics.ListAPIView):
    """Dernières positions connues des membres d'équipe (intervenants terrain), pour
    affichage sur la carte admin ou sur la "vue équipe" d'un bénévole — un acteur
    institutionnel voit tout le monde, un simple membre d'équipe ne voit que les positions
    des membres de SES propres équipes (jamais celles d'une équipe à laquelle il n'appartient
    pas, même logique que la localisation précise des demandes/offres)."""

    serializer_class = DernierePositionUtilisateurSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = DernierePositionUtilisateur.objects.filter(
            environment=get_active_environment(self.request),
            utilisateur__teams__isnull=False,
        ).distinct().select_related('utilisateur')
        if get_effective_role(self.request) in INSTITUTIONAL_TYPES:
            return qs
        return qs.filter(utilisateur__teams__members=self.request.user)


class DocumentViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):

    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    def get_queryset(self):

        user = self.request.user
        environment = get_active_environment(self.request)

        if not user.is_authenticated:
            return Document.objects.none()

        if get_effective_role(self.request) in [
            UserRole.ADMINISTRATOR,
            UserRole.LOCAL_AUTHORITY,
        ]:
            return Document.objects.filter(environment=environment)

        return Document.objects.filter(
            Q(auteur=user) | Q(dossier__participants__utilisateur=user), environment=environment
        ).distinct()

    def perform_create(self, serializer):

        user = self.request.user
        dossier = serializer.validated_data.get('dossier')
        if dossier and get_effective_role(self.request) not in INSTITUTIONAL_TYPES:
            if not dossier.participants.filter(utilisateur=user).exists():
                raise PermissionDenied("Vous n'êtes pas participant de ce dossier.")

        document = serializer.save(auteur=user, environment=get_active_environment(self.request))

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Document",
            objet_id=document.id,
            crise=(
                document.dossier.crise
                if document.dossier
                else None
            ),
            commentaire="Création document"
        )

        try:

            with open(document.fichier.path, "rb") as f:

                sha256 = hashlib.sha256(
                    f.read()
                ).hexdigest()

            document.sha256 = sha256

            document.metadata_publiques, document.metadata_privees = (
                extract_exif_metadata(
                    document.fichier.path
                )
            )

            document.save()

        except Exception as e:
            print("DOCUMENT ERROR:", e)

        if document.dossier:

            DossierHistorique.objects.create(
                dossier=document.dossier,
                auteur=document.auteur,
                evenement="Document ajouté",
                commentaire=document.commentaire or "",
                environment=document.environment,
            )

        if document.dossier:

            participants = (
                document.dossier
                .participants
                .all()
            )

            for participant in participants:

                if (
                    participant.utilisateur_id ==
                    document.auteur_id
                ):
                    continue

                Notification.objects.create(
                    utilisateur=participant.utilisateur,
                    dossier=document.dossier,
                    titre="Nouvelle photo",
                    message=document.commentaire or "",
                    environment=document.environment,
                )

    def check_document_access(
        self,
        request,
        document
    ):

        user = request.user

        if not user.is_authenticated:
            return False

        if get_effective_role(request) in [
            UserRole.ADMINISTRATOR,
            UserRole.LOCAL_AUTHORITY,
        ]:
            return True

        if document.auteur_id == user.id:
            return True

        dossier = document.dossier

        if not dossier:
            return False

        if dossier.equipe:

            if dossier.equipe.leader_id == user.id:
                return True

            if dossier.equipe.members.filter(
                id=user.id
            ).exists():
                return True

        if dossier.participants.filter(utilisateur=user).exists():
            return True

        return False

    @action(
        detail=True,
        methods=["get"]
    )
    def download(self, request, pk=None):

        document = Document.objects.get(
            pk=pk
        )

        if not self.check_document_access(
            request,
            document
        ):

            audit_log(
                request=request,
                action_code="TELECHARGEMENT",
                objet_type="Document",
                objet_id=document.id,
                commentaire="Accès refusé",
                succes=False
            )

            return Response(
                status=403
            )

        audit_log(
            request=request,
            action_code="TELECHARGEMENT",
            objet_type="Document",
            objet_id=document.id,
            crise=(
                document.dossier.crise
                if document.dossier
                else None
            ),
            commentaire=(
                f"Téléchargement document "
                f"{document.id}"
            )
        )

        return FileResponse(
            open(
                document.fichier.path,
                "rb"
            ),
            as_attachment=True
        )

    @action(
        detail=True,
        methods=["get"]
    )
    def preview(self, request, pk=None):

        document = Document.objects.get(pk=pk)

        if not self.check_document_access(
            request,
            document
        ):
            return Response(
                status=403
            )

        return FileResponse(
            open(document.fichier.path, "rb")
        )

class DossierCommentaireViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):

    queryset = DossierCommentaire.objects.all()
    serializer_class = DossierCommentaireSerializer

    def get_queryset(self):
        user = self.request.user
        environment = get_active_environment(self.request)
        if not user.is_authenticated:
            return DossierCommentaire.objects.none()
        if get_effective_role(self.request) in INSTITUTIONAL_TYPES:
            return DossierCommentaire.objects.filter(environment=environment)
        return DossierCommentaire.objects.filter(
            dossier__participants__utilisateur=user, environment=environment
        ).distinct()

    def perform_create(self, serializer):

        user = self.request.user
        dossier = serializer.validated_data.get('dossier')
        if dossier and get_effective_role(self.request) not in INSTITUTIONAL_TYPES:
            if not dossier.participants.filter(utilisateur=user).exists():
                raise PermissionDenied("Vous n'êtes pas participant de ce dossier.")

        commentaire = serializer.save(auteur=user, environment=get_active_environment(self.request))

        DossierHistorique.objects.create(
            dossier=commentaire.dossier,
            auteur=commentaire.auteur,
            evenement="Commentaire ajouté",
            commentaire=commentaire.commentaire,
            environment=commentaire.environment,
        )

        participants = (
            commentaire.dossier
            .participants
            .all()
        )

        for participant in participants:

            if (
                participant.utilisateur_id ==
                commentaire.auteur_id
            ):
                continue

            Notification.objects.create(
                utilisateur=participant.utilisateur,
                dossier=commentaire.dossier,
                titre="Nouveau commentaire",
                message=commentaire.commentaire[:250],
                environment=commentaire.environment,
            )

class DossierHistoriqueViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = DossierHistorique.objects.all()
    serializer_class = DossierHistoriqueSerializer

class NotificationViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Notifications de l'utilisateur connecté (ex: régulateur d'équipe averti d'une nouvelle
    affectation). Chacun ne voit et ne modifie que les siennes."""
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(
            utilisateur=self.request.user, environment=get_active_environment(self.request)
        ).order_by('-date_creation')

class RecherchePersonneViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonne.objects
        .order_by("-date_creation")
    )

    serializer_class = (
        RecherchePersonneSerializer
    )

    permission_classes = [
        permissions.IsAuthenticated
    ]
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return RecherchePersonne.objects.none()
        if not self.request.user.enabled:
            return RecherchePersonne.objects.none()
        return RecherchePersonne.objects.filter(
            environment=get_active_environment(self.request)
        ).order_by("-date_creation")

    def perform_create(self, serializer):

        if not self.request.user.enabled:
            raise PermissionDenied(
                "Compte non validé"
            )

        recherche = serializer.save(
            createur=self.request.user,
            environment=get_active_environment(self.request),
        )

        RecherchePersonneHistorique.objects.create(
            recherche=recherche,
            auteur=self.request.user,
            evenement="Recherche créée",
            commentaire="Création de la fiche de recherche.",
            environment=recherche.environment,
        )

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            crise=getattr(recherche, "crise", None),
            commentaire="Création de la fiche de recherche.",
        )

    @action(detail=True, methods=["post"])
    def archiver(self, request, pk=None):

        recherche = self.get_object()
        recherche.statut = "ARCHIVEE"
        ancien_statut = recherche.statut
        recherche.save()

        RecherchePersonneHistorique.objects.create(
            recherche=recherche,
            auteur=request.user,
            evenement="Recherche archivée",
            commentaire="Recherche masquée.",
            environment=recherche.environment,
        )
        audit_log(
            request=request,
            action_code="LECTURE",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            commentaire="Consultation recherche personne"
        )
        return Response({"status": "ok"})

    @action(
        detail=True,
        methods=["post"]
    )
    def retrouver(
        self,
        request,
        pk=None
    ):


        recherche = self.get_object()

        ancien_statut = recherche.statut

        recherche.statut = (
            RecherchePersonne
            .Statut
            .RETROUVEE
        )

        recherche.save()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            ancien_etat={
                "statut": ancien_statut
            },
            nouvel_etat={
                "statut": recherche.statut
            },
            commentaire="Personne déclarée retrouvée"
        )

        RecherchePersonneHistorique.objects.create(
            recherche=recherche,
            auteur=request.user,
            evenement="Personne retrouvée",
            commentaire="La personne a été déclarée retrouvée",
            environment=recherche.environment,
        )

        return Response(
            {"status": "ok"}
        )

    @action(
        detail=True,
        methods=["post"]
    )
    def lecture(
        self,
        request,
        pk=None
    ):
    
        recherche = self.get_object()

        lecture, _ = (
            RecherchePersonneLecture.objects
            .get_or_create(
                recherche=recherche,
                utilisateur=request.user,
                defaults={"environment": recherche.environment},
            )
        )

        lecture.date_derniere_lecture = (
            timezone.now()
        )

        lecture.save()

        RecherchePersonneLectureHistorique.objects.create(
            recherche=recherche,
            utilisateur=request.user,
            action=(
                RecherchePersonneLectureHistorique
                .ActionLecture
                .LECTURE
            ),
            environment=recherche.environment,
        )

        audit_log(
            request=request,
            action_code="LECTURE",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            commentaire=(
                f"Consultation recherche "
                f"{recherche.prenom} "
                f"{recherche.nom}"
            )
        )


        return Response(
            {"status": "ok"}
        )


    @action(
        detail=True,
        methods=["post"]
    )
    def acquitter(
        self,
        request,
        pk=None
    ):

        recherche = self.get_object()

        lecture, _ = (
            RecherchePersonneLecture.objects
            .get_or_create(
                recherche=recherche,
                utilisateur=request.user,
                defaults={"environment": recherche.environment},
            )
        )

        lecture.date_dernier_acquittement = (
            timezone.now()
        )

        lecture.save()

        RecherchePersonneLectureHistorique.objects.create(
            recherche=recherche,
            utilisateur=request.user,
            action=(
                RecherchePersonneLectureHistorique
                .ActionLecture
                .ACQUITTEMENT
            ),
            environment=recherche.environment,
        )

        audit_log(
            request=request,
            action_code="ACQUITTEMENT",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            commentaire="Recherche acquittée"
        )


        return Response(
            {"status": "ok"}
        )

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        recherche = self.get_object()
        if not recherche.photo or not user_can_view_photo(
            request, recherche, author_field='createur'
        ):
            return Response(status=403)
        return FileResponse(open(recherche.photo.path, "rb"))



class RecherchePersonneCommentaireViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonneCommentaire
        .objects
        .all()
    )

    serializer_class = (
        RecherchePersonneCommentaireSerializer
    )

    def perform_create(self, serializer):

        commentaire = serializer.save(
            auteur=self.request.user,
            environment=get_active_environment(self.request),
        )

        recherche = commentaire.recherche

        if (
            recherche.createur
            != commentaire.auteur
        ):

            Notification.objects.create(
                utilisateur=
                    recherche.createur,

                dossier=None,

                titre=
                    "Nouveau commentaire",

                message=(
                    f"Un commentaire a été "
                    f"ajouté sur la "
                    f"recherche de "
                    f"{recherche.prenom}"
                ),
                environment=commentaire.environment,
            )

        RecherchePersonneHistorique.objects.create(
            recherche=commentaire.recherche,
            auteur=self.request.user,
            evenement="Commentaire ajouté",
            commentaire=commentaire.commentaire,
            environment=commentaire.environment,
        )

class RecherchePersonneHistoriqueViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonneHistorique
        .objects
        .all()
        .order_by('-date_creation')
    )

    serializer_class = (
        RecherchePersonneHistoriqueSerializer
    )

class RecherchePersonnePhotoViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonnePhoto
        .objects
        .all()
    )

    serializer_class = (
        RecherchePersonnePhotoSerializer
    )

    permission_classes = [
        permissions.IsAuthenticated
    ]

    def perform_create(
        self,
        serializer
    ):

        serializer.save(
            auteur=self.request.user,
            environment=get_active_environment(self.request),
        )

    @action(
        detail=True,
        methods=["get"]
    )
    def preview(
        self,
        request,
        pk=None
    ):

        photo = self.get_object()

        if not request.user.is_authenticated:
            return Response(status=403)

        return FileResponse(
            open(photo.fichier.path, "rb")
        )

class RecherchePersonneCommentairePhotoViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonneCommentairePhoto
        .objects
        .all()
    )

    serializer_class = (
        RecherchePersonneCommentairePhotoSerializer
    )

    permission_classes = [
        permissions.IsAuthenticated
    ]

    @action(
        detail=True,
        methods=["get"]
    )
    def preview(
        self,
        request,
        pk=None
    ):

        photo = self.get_object()

        if not request.user.is_authenticated:
            return Response(status=403)

        return FileResponse(
            open(photo.fichier.path, "rb")
        )



class InstitutionTypeViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        InstitutionType.objects.all()
    )

    serializer_class = (
        InstitutionTypeSerializer
    )

    def perform_create(self, serializer):
        institution_type = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InstitutionType",
            objet_id=institution_type.id,
            commentaire=f"Création type d'institution : {institution_type.libelle}",
        )

class InstitutionViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        Institution.objects.all()
    )

    serializer_class = (
        InstitutionSerializer
    )

    def get_queryset(self):
        """Règle à sens unique (voir plan zone de démo) : les vraies institutions (PROD)
        restent visibles en DEMO pour permettre de s'appuyer sur les vraies mairies/
        associations dans une démonstration, mais une institution créée en DEMO ne doit
        jamais apparaître en PROD."""
        environment = get_active_environment(self.request)
        if environment == Environment.DEMO:
            return Institution.objects.filter(environment__in=[Environment.PROD, Environment.DEMO])
        return Institution.objects.filter(environment=Environment.PROD)

    def perform_create(self, serializer):
        institution = serializer.save(environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Institution",
            objet_id=institution.id,
            commentaire=f"Création institution : {institution.nom}",
        )

        if self.request.user.is_authenticated:
            contact, created = ContactInstitution.objects.get_or_create(
                institution=institution,
                utilisateur=self.request.user,
                defaults={
                    "fonction": "Créateur",
                    "contact_principal": True,
                    "actif": True,
                    "environment": institution.environment,
                },
            )
            if created:
                audit_log(
                    request=self.request,
                    action_code="CREATION",
                    objet_type="ContactInstitution",
                    objet_id=contact.id,
                    commentaire=f"Rattachement automatique du créateur à l'institution {institution.nom}",
                )

class RoleOperationnelViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        RoleOperationnel.objects.all()
    )

    serializer_class = (
        RoleOperationnelSerializer
    )

    def perform_create(self, serializer):
        role = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="RoleOperationnel",
            objet_id=role.id,
            commentaire=f"Création rôle opérationnel : {role.libelle}",
        )
class InstitutionCompetenceViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        InstitutionCompetence.objects.all()
    )

    serializer_class = (
        InstitutionCompetenceSerializer
    )
class AffectationRoleOperationnelViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        AffectationRoleOperationnel.objects.all()
    )

    serializer_class = (
        AffectationRoleOperationnelSerializer
    )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def _check_own_institution(self, institution):
        is_own_institution = ContactInstitution.objects.filter(
            utilisateur=self.request.user, institution=institution, actif=True
        ).exists()
        if not is_own_institution and get_effective_role(self.request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied(
                "Vous ne pouvez gérer les affectations que pour une institution à laquelle vous êtes rattaché."
            )

    def perform_create(self, serializer):
        institution = serializer.validated_data.get("institution")
        self._check_own_institution(institution)

        affectation = serializer.save(environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="AFFECTATION",
            objet_type="AffectationRoleOperationnel",
            objet_id=affectation.id,
            commentaire=(
                f"Affectation de {affectation.utilisateur.email} en tant que "
                f"{affectation.role.libelle} pour {institution.nom}"
                + (f" sur le thème {affectation.competence.nom}" if affectation.competence else "")
            ),
        )

    def perform_update(self, serializer):
        institution = serializer.instance.institution
        self._check_own_institution(institution)

        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="AffectationRoleOperationnel",
            objet_id=affectation.id,
            commentaire=f"Modification affectation rôle opérationnel : {affectation}",
        )

    @action(
        detail=False,
        methods=["get"]
    )
    def par_competence(
        self,
        request
    ):

        competence_id = request.GET.get(
            "competence"
        )

        queryset = (
            AffectationRoleOperationnel.objects
            .filter(
                competence_id=competence_id,
                role__code="REGULATEUR",
                actif=True,
                disponibilites__disponible=True,
                disponibilites__date_fin__isnull=True
            )
            .distinct()
        )

        serializer = self.get_serializer(
            queryset,
            many=True
        )

        return Response(
            serializer.data
        )


    @action(
        detail=False,
        methods=["get"]
    )
    def regulateurs_disponibles(
        self,
        request
    ):

        queryset = (
            AffectationRoleOperationnel.objects
            .filter(
                role__code="REGULATEUR",
                disponibilites__disponible=True,
                disponibilites__date_fin__isnull=True
            )
            .distinct()
        )

        serializer = self.get_serializer(
            queryset,
            many=True
        )

        return Response(
            serializer.data
        )

class DelegationCompetenceViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        DelegationCompetence.objects.all()
    )

    serializer_class = (
        DelegationCompetenceSerializer
    )

    filterset_fields = ["crise"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_update(self, serializer):
        delegation = serializer.save()
        audit_log(
            request=self.request,
            action_code="DELEGATION_COMPETENCE",
            objet_type="DelegationCompetence",
            objet_id=delegation.id,
            crise=delegation.crise,
            commentaire=(
                f"Modification délégation {delegation.institution_source} -> {delegation.institution_cible}"
                f" ({delegation.competence})"
            )
        )

    def perform_create(
        self,
        serializer
    ):

        delegation = serializer.save(environment=get_active_environment(self.request))

        audit_log(
            request=self.request,
            action_code="DELEGATION_COMPETENCE",
            objet_type="DelegationCompetence",
            objet_id=delegation.id,
            crise=delegation.crise,
            commentaire=(
                f"{delegation.institution_source}"
                f" -> "
                f"{delegation.institution_cible}"
            )
        )

class DisponibiliteOperationnelleViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        DisponibiliteOperationnelle.objects.all()
    )

    serializer_class = (
        DisponibiliteOperationnelleSerializer
    )

    @action(
        detail=True,
        methods=["post"]
    )
    def prendre_permanence(
        self,
        request,
        pk=None
    ):

        disponibilite = self.get_object()

        disponibilite.disponible = True

        disponibilite.date_fin = None

        disponibilite.save()

        audit_log(
            request=request,
            action_code="PRISE_PERMANENCE",
            objet_type="DisponibiliteOperationnelle",
            objet_id=disponibilite.id,
            commentaire="Prise de permanence"
        )

        return Response(
            {
                "status": "ok",
                "disponible": True
            }
        )

    @action(
        detail=True,
        methods=["post"]
    )
    def quitter_permanence(
        self,
        request,
        pk=None
    ):

        disponibilite = self.get_object()

        disponibilite.disponible = False

        disponibilite.date_fin = timezone.now()

        disponibilite.save()

        audit_log(
            request=request,
            action_code="FIN_PERMANENCE",
            objet_type="DisponibiliteOperationnelle",
            objet_id=disponibilite.id,
            commentaire="Fin de permanence"
        )

        return Response(
            {
                "status": "ok",
                "disponible": False
            }
        )

    @action(
        detail=False,
        methods=["get"]
    )
    def actives(
        self,
        request
    ):

        queryset = (
            DisponibiliteOperationnelle.objects
            .filter(
                disponible=True,
                date_fin__isnull=True
            )
        )

        serializer = self.get_serializer(
            queryset,
            many=True
        )

        return Response(
            serializer.data
        )

class PointTypeViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        PointType.objects.all()
    )

    serializer_class = (
        PointTypeSerializer
    )
class PointOperationnelViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        PointOperationnel.objects.all()
    )

    serializer_class = (
        PointOperationnelSerializer
    )

    filterset_fields = ["crise"]

    def get_queryset(self):
        """`?mine=true` restreint aux points dont l'utilisateur est responsable, leader ou
        membre de l'équipe — alimente la page "Mes centres" (accès direct, toutes crises
        confondues, sans repasser par la fiche de chaque crise)."""
        qs = super().get_queryset()
        if self.request.query_params.get("mine") == "true":
            user = self.request.user
            qs = qs.filter(
                Q(responsable=user) | Q(equipe__leader=user) | Q(equipe__members=user)
            ).distinct()
        return qs

    def get_permissions(self):
        # Avant ce correctif, seul `create` était restreint : n'importe quel compte connecté
        # pouvait modifier ou supprimer le point opérationnel d'une institution tierce.
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        # `centres_accueil` doit rester accessible aux visiteurs anonymes : c'est ce qui
        # alimente le choix de centre du formulaire public "je suis en sécurité". Le
        # `permission_classes=[AllowAny]` posé sur l'action elle-même (plus bas) ne suffit pas
        # à lui seul : cette méthode le remplace entièrement pour toute cette vue, il faut
        # explicitement la laisser passer ici aussi.
        if self.action == "centres_accueil":
            return [AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def centres_accueil(self, request):
        """Liste publique, à champs restreints, des centres d'accueil actifs (PointType
        HEBERGEMENT) d'une crise — alimente le formulaire public "je suis en sécurité"
        (`?crise=<id>`, requis) : choix d'un centre, ou suggestions de centres disponibles."""
        crisis_id = request.query_params.get("crise")
        if not crisis_id:
            return Response({"error": "Le paramètre crise est requis."}, status=status.HTTP_400_BAD_REQUEST)
        queryset = PointOperationnel.objects.filter(
            crise_id=crisis_id, actif=True, type__code="HEBERGEMENT",
            environment=get_active_environment(request),
        ).select_related("type")
        return Response(PointOperationnelPublicSerializer(queryset, many=True).data)

    def perform_update(self, serializer):
        point = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="PointOperationnel",
            objet_id=point.id,
            crise=point.crise,
            commentaire=f"Modification point opérationnel : {point.nom}",
        )

    def perform_create(self, serializer):
        point = serializer.save(responsable=self.request.user, environment=get_active_environment(self.request))

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="PointOperationnel",
            objet_id=point.id,
            crise=point.crise,
            commentaire=f"Création point opérationnel : {point.nom}",
        )

        # Devenir responsable d'un point sur une crise vaut déclaration "acteur" pour
        # l'institution — pas besoin de le déclarer une seconde fois. `institution` n'est pas un
        # champ de PointOperationnel : c'est un choix fait dans le formulaire de création, lu
        # directement depuis le payload. Si l'utilisateur n'a pas le droit de déclarer pour cette
        # institution (pas contact, pas admin), on retombe sur l'ancienne heuristique (son propre
        # rattachement) plutôt que d'échouer silencieusement.
        if point.crise_id:
            institution = None
            institution_id = self.request.data.get('institution')
            if institution_id:
                candidate = Institution.objects.filter(pk=institution_id).first()
                is_own = candidate and ContactInstitution.objects.filter(
                    utilisateur=self.request.user, institution=candidate, actif=True
                ).exists()
                if candidate and (is_own or get_effective_role(self.request) == UserRole.ADMINISTRATOR):
                    institution = candidate

            if institution is None:
                contact = ContactInstitution.objects.filter(
                    utilisateur=self.request.user, actif=True
                ).select_related("institution").first()
                institution = contact.institution if contact else None

            if institution:
                implication, created = ImplicationInstitution.objects.get_or_create(
                    crise=point.crise,
                    institution=institution,
                    type_implication=TypeImplication.ACTEUR,
                    defaults={"utilisateur": self.request.user, "actif": True, "environment": point.environment},
                )
                if created:
                    audit_log(
                        request=self.request,
                        action_code="CREATION",
                        objet_type="ImplicationInstitution",
                        objet_id=implication.id,
                        crise=point.crise,
                        commentaire=(
                            f"{institution.nom} déclarée acteur sur la crise "
                            f"{point.crise.name} (gestion de {point.nom})"
                        ),
                    )

    HEURES_PAR_CRENEAU = 6  # MATIN/MIDI/SOIR/NUIT ≈ 4 créneaux de 6h sur 24h — approximation
    # affichée telle quelle (voir décision : affichage seul, pas de blocage automatique).

    @action(detail=True, methods=["get"])
    def equipe(self, request, pk=None):
        """Membres de l'équipe responsable de ce point + leurs disponibilités déclarées sur
        ce point précis, en un seul appel (évite un aller-retour Team + Dispo séparé côté
        frontend). Inclut aussi les affectations de bénévoles individuels recrutés depuis une
        offre d'aide (avec leur statut de confirmation) et le temps cumulé par membre sur CE
        point (nombre de créneaux déclarés × durée conventionnelle d'un créneau)."""
        point = self.get_object()
        disponibilites = DisponibilitePointEquipe.objects.filter(point=point).select_related("membre", "affectation")
        affectations = point.affectations_benevoles.select_related("benevole", "offer", "point_transit")

        temps_par_membre = {}
        for d in disponibilites:
            temps_par_membre[str(d.membre_id)] = temps_par_membre.get(str(d.membre_id), 0) + self.HEURES_PAR_CRENEAU

        membres = point.equipe.members.all() if point.equipe else []

        return Response({
            "membres": [
                {
                    "id": str(m.id),
                    "nom": f"{m.first_name} {m.last_name}".strip() or m.email,
                    "email": m.email,
                    "temps_total_heures": temps_par_membre.get(str(m.id), 0),
                }
                for m in membres
            ],
            "disponibilites": DisponibilitePointEquipeSerializer(disponibilites, many=True).data,
            "affectations": AffectationPointBenevoleSerializer(affectations, many=True).data,
        })

    @action(detail=True, methods=["post"], url_path="inviter-benevole")
    def inviter_benevole(self, request, pk=None):
        """Recrute un ou plusieurs bénévoles sur ce point depuis des offres d'aide (affectation
        groupée depuis le tableau de recrutement), et leur envoie à chacun un email de
        confirmation de disponibilité (lien oui/non). Nécessite que le point ait déjà une
        équipe assignée (chaque bénévole y est ajouté, condition déjà posée par
        DisponibilitePointEquipeSerializer.validate pour créer ses créneaux). Les créneaux et
        le point de transit sont communs à tout le lot (décidés par le régulateur), pas propres
        à chaque bénévole. Un échec individuel (ex: offre introuvable) n'annule pas les autres."""
        point = self.get_object()

        if point.responsable_id != request.user.id and not (
            point.equipe and point.equipe.leader_id == request.user.id
        ) and get_effective_role(request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied(
                "Seul le responsable ou le leader de l'équipe du point peut recruter un bénévole."
            )

        validate_crisis_open(point.crise, field_name="crise")

        if not point.equipe:
            return Response(
                {"error": "Ce point doit d'abord avoir une équipe assignée pour pouvoir y recruter un bénévole."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        offer_ids = request.data.get("offer_ids") or []
        if not offer_ids:
            return Response({"error": "offer_ids est requis (au moins un identifiant)."}, status=status.HTTP_400_BAD_REQUEST)

        date_attendue = parse_datetime(request.data.get("date_attendue") or "")
        if not date_attendue:
            return Response({"error": "date_attendue est requis et doit être une date/heure valide (ISO 8601)."}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(date_attendue):
            date_attendue = timezone.make_aware(date_attendue)

        point_transit = None
        point_transit_id = request.data.get("point_transit_id")
        if point_transit_id:
            point_transit = get_object_or_404(PointOperationnel, pk=point_transit_id, crise=point.crise)

        creneaux = request.data.get("creneaux", [])

        offers_by_id = {str(o.id): o for o in Offer.objects.filter(pk__in=offer_ids)}

        created = []
        errors = []

        for offer_id in offer_ids:
            offer = offers_by_id.get(str(offer_id))
            if not offer:
                errors.append({"offer_id": offer_id, "error": "Offre introuvable."})
                continue

            benevole, _created = resolve_or_invite_benevole(offer, request)
            if not benevole:
                errors.append({"offer_id": offer_id, "error": "Impossible de déterminer les coordonnées du bénévole depuis cette offre."})
                continue

            point.equipe.members.add(benevole)

            affectation = AffectationPointBenevole.objects.create(
                point=point,
                benevole=benevole,
                offer=offer,
                date_attendue=date_attendue,
                point_transit=point_transit,
                token_confirmation=secrets.token_urlsafe(32),
                affecte_par=request.user,
                environment=point.environment,
            )

            for creneau in creneaux:
                DisponibilitePointEquipe.objects.get_or_create(
                    point=point, membre=benevole, date=creneau.get("date"), creneau=creneau.get("creneau"),
                    defaults={"affectation": affectation, "environment": point.environment},
                )

            send_point_volunteer_confirmation_email(request, affectation)

            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="AffectationPointBenevole",
                objet_id=affectation.id,
                crise=point.crise,
                commentaire=f"{benevole.email} invité(e) sur le point {point.nom}",
            )

            created.append(affectation)

        if not created:
            return Response({"created": [], "errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"created": AffectationPointBenevoleSerializer(created, many=True).data, "errors": errors},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="candidats-benevoles")
    def candidats_benevoles(self, request, pk=None):
        """Liste paginée/filtrable/triable des offres d'aide candidates au recrutement sur ce
        point — alimente le tableau de recrutement (recherche, disponibilité, compétences, tri
        par distance). Même permission que inviter_benevole (lecture préparatoire à cette
        action). Ne renvoie que les offres encore disponibles (Status.AVAILABLE)."""
        point = self.get_object()

        if point.responsable_id != request.user.id and not (
            point.equipe and point.equipe.leader_id == request.user.id
        ) and get_effective_role(request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied(
                "Seul le responsable ou le leader de l'équipe du point peut consulter les candidats."
            )

        queryset = Offer.objects.filter(
            environment=get_active_environment(request), status=Status.AVAILABLE,
        ).prefetch_related("disponibilites", "competences")

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = OfferSearchFilter(queryset=queryset).filter_search(queryset, "search", search)

        creneaux_param = request.query_params.getlist("creneaux")
        if creneaux_param:
            creneau_filter = Q()
            for item in creneaux_param:
                date_str, _, creneau_str = item.partition(":")
                if date_str and creneau_str:
                    creneau_filter |= Q(disponibilites__date=date_str, disponibilites__creneau=creneau_str)
            if creneau_filter:
                queryset = queryset.filter(creneau_filter).distinct()

        competences_param = request.query_params.getlist("competences")
        if competences_param:
            queryset = queryset.filter(competences__id__in=competences_param).distinct()

        has_location = point.location is not None
        if has_location:
            queryset = queryset.annotate(distance=Distance("location", point.location))

        ordering = request.query_params.get("ordering", "distance" if has_location else "nom")
        if ordering == "distance" and has_location:
            queryset = queryset.order_by("distance")
        else:
            queryset = queryset.order_by("first_name_offer", "last_name_offer")

        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 25))
        page = paginator.paginate_queryset(queryset, request, view=self)

        borne_min = timezone.now().date()
        borne_max = borne_min + datetime.timedelta(days=8)

        results = []
        for offer in page:
            results.append({
                "id": str(offer.id),
                "first_name_offer": offer.first_name_offer,
                "last_name_offer": offer.last_name_offer,
                "email_offer": mask_email(offer.email_offer) if get_active_environment(request) == Environment.DEMO else offer.email_offer,
                "title": offer.title,
                "competences_libelles": [c.nom for c in offer.competences.all()],
                "distance_km": round(offer.distance.km, 1) if has_location and offer.distance is not None else None,
                "disponibilites": [
                    {"date": d.date.isoformat(), "creneau": d.creneau}
                    for d in offer.disponibilites.all()
                    if borne_min <= d.date < borne_max
                ],
            })

        return paginator.get_paginated_response(results)

    @action(detail=True, methods=["get"])
    def stocks(self, request, pk=None):
        """État du stock de CHAQUE item du catalogue matériel pour ce point, y compris ceux
        qu'il n'a encore jamais touchés (complétés à la volée avec niveau_stock=NUL, sans rien
        écrire en base) — c'est ce mécanisme qui fait qu'un item ajouté sur un centre apparaît
        immédiatement, à niveau nul, dans la liste de tous les autres centres."""
        point = self.get_object()
        existants = {m.item_id: m for m in point.materiels.select_related("item", "responsable")}

        resultats = []
        for item in MaterielCatalogue.objects.all().order_by("nom"):
            materiel = existants.get(item.id)
            if materiel:
                resultats.append(MaterielPointSerializer(materiel).data)
            else:
                resultats.append({
                    "id": None,
                    "point": str(point.id),
                    "item": str(item.id),
                    "item_nom": item.nom,
                    "niveau_stock": NiveauStock.NUL,
                    "niveau_stock_libelle": NiveauStock.NUL.label,
                    "nom": "",
                    "quantite": 1,
                    "unite": "unité",
                    "statut": None,
                    "statut_libelle": None,
                    "responsable": None,
                    "responsable_nom": None,
                    "commentaire": None,
                    "date_maj": None,
                })
        return Response(resultats)


class DisponibilitePointEquipeViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Planning de disponibilité des membres de l'équipe responsable d'un point opérationnel."""

    queryset = DisponibilitePointEquipe.objects.select_related("point", "membre").all()
    serializer_class = DisponibilitePointEquipeSerializer
    filterset_fields = ["point", "membre"]

    def _can_manage(self, request, point, membre):
        # Le membre lui-même déclare sa propre disponibilité ; le leader de l'équipe ou le
        # responsable du point peuvent la gérer pour toute l'équipe ; un admin, toujours.
        user = request.user
        if get_effective_role(request) == UserRole.ADMINISTRATOR:
            return True
        if user.id == membre.id:
            return True
        if point.equipe and point.equipe.leader_id == user.id:
            return True
        if point.responsable_id == user.id:
            return True
        return False

    def perform_create(self, serializer):
        point = serializer.validated_data.get('point')
        membre = serializer.validated_data.get('membre')
        if not self._can_manage(self.request, point, membre):
            raise PermissionDenied(
                "Vous ne pouvez déclarer une disponibilité que pour vous-même, ou pour l'équipe "
                "dont vous êtes le·la leader / le·la responsable du point."
            )
        serializer.save(environment=get_active_environment(self.request))

    def perform_destroy(self, instance):
        if not self._can_manage(self.request, instance.point, instance.membre):
            raise PermissionDenied(
                "Vous ne pouvez retirer qu'une disponibilité vous concernant, ou celles de "
                "l'équipe dont vous êtes le·la leader / le·la responsable du point."
            )
        instance.delete()


class MaterielCatalogueViewSet(TagLikeViewSetMixin, viewsets.ModelViewSet):
    """Vocabulaire partagé des besoins matériel — recherche/création façon hashtag, comme
    Competence/InformationType : n'importe quel centre peut ajouter un item, immédiatement
    réutilisable par tous les autres (voir PointOperationnelViewSet.stocks)."""

    queryset = MaterielCatalogue.objects.all()
    serializer_class = MaterielCatalogueSerializer
    permission_classes = [permissions.IsAuthenticated]


class MaterielPointViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """État du stock (niveau qualitatif + suivi quantitatif optionnel) d'un item du catalogue
    matériel sur un point opérationnel."""

    queryset = MaterielPoint.objects.select_related("point", "item", "responsable").all()
    serializer_class = MaterielPointSerializer
    filterset_fields = ["point", "statut", "item"]

    def _can_manage(self, request, point):
        # Même logique que DisponibilitePointEquipeViewSet._can_manage (pas de notion de
        # "membre" ici — n'importe quel membre de l'équipe peut mettre à jour un stock).
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

    def perform_create(self, serializer):
        point = serializer.validated_data.get('point')
        if not self._can_manage(self.request, point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier son stock."
            )
        materiel = serializer.save(responsable=self.request.user, environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="MaterielPoint",
            objet_id=materiel.id,
            crise=materiel.point.crise,
            commentaire=f"Stock « {materiel.item.nom} » ({materiel.get_niveau_stock_display()}) sur le point {materiel.point.nom}",
        )

    def perform_update(self, serializer):
        point = serializer.instance.point
        if not self._can_manage(self.request, point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier son stock."
            )
        materiel = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="MaterielPoint",
            objet_id=materiel.id,
            crise=materiel.point.crise,
            commentaire=f"Stock « {materiel.item.nom} » mis à jour ({materiel.get_niveau_stock_display()})",
        )

    def perform_destroy(self, instance):
        if not self._can_manage(self.request, instance.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier son stock."
            )
        instance.delete()


class RegistrePresenceViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Registre de présence ("secrétariat") d'un point opérationnel."""

    queryset = RegistrePresence.objects.select_related("point", "enregistre_par").all()
    serializer_class = RegistrePresenceSerializer
    filterset_fields = ["point", "type_personne"]

    def _can_manage(self, request, point):
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

    def perform_create(self, serializer):
        point = serializer.validated_data.get('point')
        if not self._can_manage(self.request, point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut enregistrer une arrivée."
            )
        entree = serializer.save(enregistre_par=self.request.user, environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="RegistrePresence",
            objet_id=entree.id,
            crise=entree.point.crise,
            commentaire=f"Arrivée « {entree.get_type_personne_display()} » ({entree.nombre}) sur le point {entree.point.nom}",
        )

    def perform_update(self, serializer):
        if not self._can_manage(self.request, serializer.instance.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier le registre."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if not self._can_manage(self.request, instance.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier le registre."
            )
        instance.delete()

    @action(detail=True, methods=["post"])
    def sortie(self, request, pk=None):
        """Marque une sortie (date_depart=maintenant) — ne retire pas la ligne, garde la trace
        du passage."""
        entree = self.get_object()
        if not self._can_manage(request, entree.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut enregistrer une sortie."
            )
        if entree.date_depart is not None:
            return Response({"error": "Cette sortie est déjà enregistrée."}, status=status.HTTP_400_BAD_REQUEST)

        entree.date_depart = timezone.now()
        entree.save()
        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="RegistrePresence",
            objet_id=entree.id,
            crise=entree.point.crise,
            commentaire=f"Sortie « {entree.get_type_personne_display()} » du point {entree.point.nom}",
        )
        return Response(RegistrePresenceSerializer(entree).data)


class DeclarationSecuriteViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """"Je suis en sécurité" : création publique ouverte à tous, avec ou sans centre d'accueil
    — soit une auto-déclaration générique (ex: "je ne suis pas sur place, ne me cherchez pas"),
    soit une entrée en centre d'accueil (déclarée par la personne elle-même depuis le centre,
    ou recensée par un opérateur du secrétariat) : les deux passent par le même formulaire
    public, sans distinction de permission entre les deux à la création. Lecture/modification/
    suppression réservées aux acteurs institutionnels : ce sont des coordonnées personnelles,
    pas un contenu public à lister librement."""

    queryset = DeclarationSecurite.objects.select_related('crise', 'centre_accueil', 'declare_par').all()
    serializer_class = DeclarationSecuriteSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        if self.action == 'mes_declarations':
            return [permissions.IsAuthenticated()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwnDeclarationOrInstitutional()]
        return [IsInstitutionalActor()]

    def _enregistrer_arrivee_centre(self, declaration, centre, enregistre_par):
        """Crée l'entrée de registre de présence d'un centre et la rattache à la déclaration
        — factorisé car appelé à la fois à la création et lors d'un changement de situation
        vers EN_CENTRE (arrivée dans un centre, éventuellement après en avoir quitté un autre)."""
        commentaire = declaration.commentaire or ''
        if declaration.regime_alimentaire_specifique:
            avertissement = "⚠ Régime alimentaire spécifique déclaré — se rapprocher du déclarant."
            commentaire = f"{commentaire}\n{avertissement}" if commentaire else avertissement
        registre = RegistrePresence.objects.create(
            point=centre,
            type_personne=TypePersonneAccueillie.EVACUE,
            nom=f"{declaration.prenom_referent} {declaration.nom_referent}".strip(),
            nombre=declaration.nombre_adultes + declaration.nombre_enfants,
            commentaire=commentaire or None,
            enregistre_par=enregistre_par,
            environment=declaration.environment,
        )
        declaration.registre_presence = registre
        declaration.save(update_fields=['registre_presence'])

    def perform_create(self, serializer):
        centre = serializer.validated_data.get('centre_accueil')
        declare_par = self.request.user if self.request.user.is_authenticated else None
        declaration = serializer.save(
            declare_par=declare_par,
            environment=get_active_environment(self.request),
        )

        if centre is not None:
            self._enregistrer_arrivee_centre(declaration, centre, declare_par)

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="DeclarationSecurite",
            objet_id=declaration.id,
            crise=declaration.crise,
            commentaire=(
                f"Déclaration de sécurité : {declaration.prenom_referent} {declaration.nom_referent}"
                + (f" — centre {centre.nom}" if centre else " — auto-déclaration")
            ),
        )

    def perform_update(self, serializer):
        """Permet à l'auteur de faire évoluer sa propre situation (arrivée/départ d'un centre
        d'accueil, relogement, hors zone...) — synchronise le registre de présence du centre
        en conséquence, exactement comme le ferait un opérateur du secrétariat côté centre."""
        declaration_avant = serializer.instance
        ancien_registre = declaration_avant.registre_presence
        ancien_centre_id = declaration_avant.centre_accueil_id

        declaration = serializer.save()

        nouveau_centre = declaration.centre_accueil
        quitte_le_centre = (
            ancien_registre is not None
            and ancien_registre.date_depart is None
            and (declaration.situation != SituationDeclarant.EN_CENTRE or declaration.centre_accueil_id != ancien_centre_id)
        )
        if quitte_le_centre:
            ancien_registre.date_depart = timezone.now()
            ancien_registre.save(update_fields=['date_depart'])

        arrive_en_centre = (
            declaration.situation == SituationDeclarant.EN_CENTRE
            and nouveau_centre is not None
            and (quitte_le_centre or ancien_centre_id != nouveau_centre.id or ancien_registre is None)
        )
        if arrive_en_centre:
            enregistre_par = self.request.user if self.request.user.is_authenticated else declaration.declare_par
            self._enregistrer_arrivee_centre(declaration, nouveau_centre, enregistre_par)

        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="DeclarationSecurite",
            objet_id=declaration.id,
            crise=declaration.crise,
            commentaire=(
                f"Déclaration de sécurité mise à jour : {declaration.prenom_referent} {declaration.nom_referent}"
                f" — {declaration.get_situation_display()}"
            ),
        )

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor])
    def vue_mairie(self, request):
        """Déclarations "je suis en sécurité" liées à un centre d'accueil situé dans la
        commune de l'institution de l'utilisateur appelant — les auto-déclarations sans centre
        (ex: "je ne suis pas sur place") n'ont pas de localisation exploitable et ne peuvent
        pas être rattachées à une commune, elles sont donc exclues ici plutôt que remontées à
        tort. Reverse-géocodage mis en cache (voir geo_lookup), un appel par centre distinct
        au pire, pas par déclaration."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code

        queryset = self.get_queryset().filter(centre_accueil__isnull=False)
        matching_ids = [
            d.id for d in queryset
            if d.centre_accueil.location and commune_code_from_point(d.centre_accueil.location) == commune_code
        ]
        declarations = self.get_queryset().filter(id__in=matching_ids)
        return Response(self.get_serializer(declarations, many=True).data)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def mes_declarations(self, request):
        """Déclarations enregistrées par l'utilisateur connecté lui-même — accessible à
        n'importe quel compte authentifié, pas seulement aux acteurs institutionnels
        (symétrique à Offer/Request/Crisis my_requests-like `?auteur_email=`) : quelqu'un qui
        remplit le formulaire public doit pouvoir retrouver sa propre déclaration, même sans
        droits institutionnels pour voir celles des autres."""
        declarations = self.get_queryset().filter(declare_par=request.user)
        return Response(self.get_serializer(declarations, many=True).data)


class ImplicationInstitutionViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):
    """Rattachement d'une institution à une crise : impliquée et/ou acteur opérationnel."""

    queryset = ImplicationInstitution.objects.select_related("institution", "crise", "utilisateur").all()
    serializer_class = ImplicationInstitutionSerializer
    filterset_fields = ["crise", "institution", "type_implication"]

    def get_permissions(self):
        if self.action == "create":
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        institution = serializer.validated_data.get("institution")

        is_own_institution = ContactInstitution.objects.filter(
            utilisateur=self.request.user, institution=institution, actif=True
        ).exists()
        if not is_own_institution and get_effective_role(self.request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied(
                "Vous ne pouvez déclarer une implication que pour une institution à laquelle vous êtes rattaché."
            )

        responsable_email = serializer.validated_data.pop("responsable_email", "")
        responsable = serializer.validated_data.get("responsable")
        responsable_id = responsable.pk if responsable else None

        resolved_responsable, invited = None, False
        if responsable_id or responsable_email:
            resolved_responsable, invited = resolve_or_invite_responsable(
                responsable_id, responsable_email, institution, self.request
            )

        implication = serializer.save(
            utilisateur=self.request.user, responsable=resolved_responsable,
            environment=get_active_environment(self.request),
        )

        if invited:
            send_crisis_regulateur_invite_email(self.request, resolved_responsable, implication.crise, institution)

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="ImplicationInstitution",
            objet_id=implication.id,
            crise=implication.crise,
            commentaire=(
                f"{implication.institution.nom} déclarée "
                f"{implication.get_type_implication_display().lower()} sur la crise {implication.crise.name}"
            ),
        )

    def perform_destroy(self, instance):
        if not self._can_manage(instance):
            raise PermissionDenied("Seul l'auteur de cette déclaration, un contact de l'institution ou un administrateur peut la retirer.")
        instance.delete()

    def perform_update(self, serializer):
        # Avant ce correctif, seul `create` était restreint : n'importe quel compte
        # authentifié pouvait modifier (thèmes, commentaire, responsable...) l'implication
        # déclarée par une institution tierce.
        if not self._can_manage(serializer.instance):
            raise PermissionDenied("Seul l'auteur de cette déclaration, un contact de l'institution ou un administrateur peut la modifier.")
        implication = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="ImplicationInstitution",
            objet_id=implication.id,
            crise=implication.crise,
            commentaire=f"Modification implication {implication.institution.nom} sur la crise {implication.crise.name}",
        )

    def _can_manage(self, instance: ImplicationInstitution) -> bool:
        user = self.request.user
        if get_effective_role(self.request) == UserRole.ADMINISTRATOR:
            return True
        if instance.utilisateur_id == user.id:
            return True
        return ContactInstitution.objects.filter(
            utilisateur=user, institution=instance.institution, actif=True
        ).exists()

class ContactInstitutionViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        ContactInstitution.objects.all()
    )

    serializer_class = (
        ContactInstitutionSerializer
    )

    def perform_create(self, serializer):
        # "Un seul contact principal par institution" est appliqué par un index unique partiel
        # en base (voir migration 0060) — pas par le serializer, DRF ne traduisant pas les
        # UniqueConstraint conditionnelles en validateur. Sans ce try/except, une vraie
        # tentative de double contact principal remontait en IntegrityError non interceptée
        # (500 générique) au lieu d'un message exploitable côté frontend.
        try:
            # Savepoint dédié : sans lui, l'IntegrityError laisse la transaction de la requête
            # (ATOMIC_REQUESTS) dans un état cassé — toute requête SQL suivante (y compris celles
            # de la gestion d'erreur DRF elle-même) échouerait avec TransactionManagementError.
            with transaction.atomic():
                contact = serializer.save(environment=get_active_environment(self.request))
        except IntegrityError:
            raise ValidationError(
                {"contact_principal": "Cette institution a déjà un contact principal : décochez « Principal » ou retirez-le d'abord de l'autre contact."}
            )
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="ContactInstitution",
            objet_id=contact.id,
            commentaire=f"Création contact institution : {contact.utilisateur} pour {contact.institution.nom}",
        )

class InstitutionDomaineViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    queryset = (
        InstitutionDomaine.objects.all()
    )

    serializer_class = (
        InstitutionDomaineSerializer
    )

    def perform_create(self, serializer):
        domaine = serializer.save(environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InstitutionDomaine",
            objet_id=domaine.id,
            commentaire=f"Création domaine institution : {domaine.domaine} pour {domaine.institution.nom}",
        )

