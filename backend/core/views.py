from django.shortcuts import render
from django.http import FileResponse, StreamingHttpResponse, HttpResponse
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework import viewsets, status, generics, permissions, mixins
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
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from urllib.parse import quote
from django_filters import rest_framework as filters
from django.db import IntegrityError, transaction
from django.db.models import Q, F, Prefetch, Count
from django.db.models.functions import TruncDate
from dateutil.relativedelta import relativedelta
from django.contrib.gis.db.models.functions import Distance
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .auth_validation import InstitutionEmailValidator
import csv
import io
import datetime
import os
import secrets
import uuid
import hashlib
from django.core.files.base import ContentFile
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

from .audit import audit_log, get_client_ip, send_mail_logged
from .export import build_crisis_export_zip
from .institution_attachment import (
    find_institution_for_pending_user, attach_user_with_role,
    attach_secours_user_to_institution, resolve_or_invite_responsable,
)
from .permissions import (
    IsInstitutionalActor, IsAdministrator, IsOwnDeclarationOrInstitutional, IsOwnerOrInstitutional,
    IsSelfOrInstitutional, IsInstitutionMemberOrAdministrator, IsOfferOwnerOrInstitutional,
    INSTITUTIONAL_TYPES, user_can_view_photo,
    get_active_environment, get_effective_role, effective_role_or_none, mask_email, mask_phone,
    send_mail_env_aware, _peut_gerer_stock_point,
)
from .geo_lookup import commune_code_from_point, commune_secteur_codes, commune_risques, commune_risques_date_maj
from .imports import (
    CHAMPS_PERSONNEL_COMMUNAL,
    exemple_csv_personnel_communal,
    importer_personnel_communal,
    parse_fichier,
)
from .pagination import OptionalPageNumberPagination, InstitutionPagination
from .zone_scoping import (
    SECTEUR_CHAMP_PAR_NIVEAU,
    _institution_commune_or_400,
    _institution_secteur_or_400,
    filter_queryset_to_viewer_zone,
    object_in_viewer_zone,
    viewer_zone_code,
)
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
    User, Crisis, TypeCrise, Request, RequestPhoto, Offer, OfferPhoto, OfferMessage, Information, DisponibiliteOffre, DisponibilitePointEquipe, MaterielPoint,
    MaterielCatalogue, ContributionMateriel, StatutMateriel, TypeMateriel, NiveauStock, RegistrePresence, TypePersonneAccueillie, DeclarationSecurite, SituationDeclarant,
    AffectationPointBenevole, StatutAffectation,
    RecherchePersonne, RecherchePersonneCommentaire, Besoin, Notification, DossierParticipant,
    RecherchePersonneCommentairePhoto, RecherchePersonneLecture, RecherchePersonneLectureHistorique,
    Document, DossierCommentaire, DossierHistorique, BesoinCompetence, Competence, Dossier, Mission,
    AuditLog, AuditAction,
    RecherchePersonneHistorique, RecherchePersonnePhoto,
    AffectationCompetence, RequestType, RequestTypeBesoin, OfferType, InformationType, Team,
    TeamDelegation,
    EngagementRessource, StatutEngagementRessource,
    Status,
    DernierePositionUtilisateur,
    Zone,
    Plan,
    JournalCollectivite,
    Commune,
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

    send_mail_logged(
        request,
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

    send_mail_logged(
        request,
        subject="Vous avez été désigné responsable d'une crise sur Assista-Crise",
        message=message,
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )

from .serializers import (
    validate_crisis_open,
    AuditLogSerializer,
    AuditLogAdminSerializer,
    JournalCollectiviteSerializer,
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
    RequestPhotoSerializer,
    OfferSerializer,
    OfferNationalPartialSerializer,
    OfferPhotoSerializer,
    OfferMessageSerializer,
    DisponibiliteOffreSerializer,
    DisponibilitePointEquipeSerializer,
    MaterielPointSerializer,
    MaterielCatalogueSerializer,
    ContributionMaterielSerializer,
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
    ZoneSerializer,
    PlanSerializer,
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
    queryset = BesoinCompetence.objects.select_related('besoin', 'competence').all()
    serializer_class = BesoinCompetenceSerializer

class RequestTypeBesoinViewSet(viewsets.ModelViewSet):
    queryset = RequestTypeBesoin.objects.select_related('request_type', 'besoin').all()
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
    # AllowAny, comme InformationTypeViewSet : recherchée/créée depuis des formulaires publics
    # (propose-help-form) où le visiteur n'a pas forcément de compte — sans ça, le widget de
    # recherche de compétences échoue silencieusement (401 avalé par le catchError du
    # composant), symptôme remonté par un bêta-testeur ("le champ compétence ne fonctionne
    # pas").
    queryset = Competence.objects.all()
    serializer_class = CompetenceSerializer

    def get_permissions(self):
        # AllowAny restreint à list/retrieve/create (voir commentaire de classe) : update/
        # destroy doivent rester réservés aux comptes authentifiés, contrairement à avant où
        # permission_classes=[AllowAny] s'appliquait à toute la classe et permettait à
        # n'importe qui, sans compte, de modifier/supprimer une compétence.
        if self.action in ('list', 'retrieve', 'create'):
            return [AllowAny()]
        return super().get_permissions()

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

    def perform_destroy(self, instance):
        # BesoinCompetence.competence et Dossier.competence sont en PROTECT : supprimer une
        # compétence encore utilisée lève ProtectedError (500 non géré) au lieu d'un message
        # exploitable.
        nb = instance.besoins.count() + instance.dossiers.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer la compétence « {instance.nom} » : "
                f"{nb} élément(s) (besoins/dossiers) l'utilisent encore."
            )
        instance.delete()

class AffectationCompetenceViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = AffectationCompetence.objects.select_related('crise', 'competence', 'equipe')
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
    # DossierSerializer déréférence crise/competence/equipe/mission/information/demande (FK)
    # pour chaque dossier — sans select_related, ~6 requêtes SQL par dossier rien que pour ça
    # (372 requêtes mesurées pour 76 dossiers DEMO, avant même unread_count, voir sa
    # dé-duplication ci-dessus). Le reste du coût restant (get_regulateurs) est une recherche
    # légitime par dossier (compétence/équipe), pas un N+1 à corriger.
    queryset = Dossier.objects.select_related('crise', 'competence', 'equipe', 'mission', 'information', 'demande')
    serializer_class = DossierSerializer

    def get_permissions(self):
        # La lecture reste ouverte à tout utilisateur authentifié concerné (filtrée par
        # get_queryset : participant du dossier, ou compte institutionnel). Modifier ou
        # supprimer un dossier restait jusqu'ici possible à n'importe quel participant
        # (ex: un simple demandeur) faute de restriction dédiée — désormais réservé aux
        # comptes institutionnels, comme pour les autres écritures sensibles de l'app. La
        # création directe (sans passer par TeamViewSet.creer_dossier, seul chemin qui peuple
        # DossierParticipant/DossierHistorique correctement) était jusqu'ici ouverte à
        # n'importe quel compte authentifié — resserrée pour la même raison.
        if self.action in ("create", "update", "partial_update", "destroy", "vue_mairie"):
            return [IsInstitutionalActor()]
        return super().get_permissions()

    @action(detail=False, methods=["get"])
    def vue_mairie(self, request):
        """Dossiers dont la demande, le signalement, ou l'équipe rattachée relève de la
        commune de l'institution de l'utilisateur appelant — même garde que les autres
        actions vue_mairie de ce fichier."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code
        queryset = Dossier.objects.filter(
            Q(demande__commune_code=commune_code)
            | Q(information__commune_code=commune_code)
            | Q(equipe__institution__commune_code=commune_code),
            environment=get_active_environment(request),
        ).distinct()
        return Response(self.get_serializer(queryset, many=True).data)

    def get_queryset(self):
        # Reconstruit depuis self.queryset (pas Dossier.objects.* directement) pour conserver
        # le select_related de la classe — sinon chaque branche ci-dessous repart d'un
        # queryset "nu" et le redéréférence à chaque objet en sérialisation.
        base = self.queryset
        user = self.request.user
        environment = get_active_environment(self.request)
        if not user.is_authenticated:
            return base.none()
        if get_effective_role(self.request) in INSTITUTIONAL_TYPES:
            # AVANT ce correctif, cette branche renvoyait TOUS les dossiers de l'environnement
            # actif, sans aucun filtre géographique — n'importe quel acteur institutionnel
            # voyait les dossiers de n'importe quelle institution tierce. Même union que
            # vue_mairie (demande/information/équipe rattachée), généralisée à tous les
            # niveaux de secteur via filter_queryset_to_viewer_zone — mais seulement sur la
            # liste par défaut : retrieve/update/destroy/cloturer restent ouverts à tout acteur
            # institutionnel indépendamment de sa zone, pour ne pas interférer avec le contrôle
            # d'accès déjà en place (régulateur/responsable de crise = 200, institutionnel
            # non-lié = 403) — "mon institution doit être ACTEUR sur la crise", hors scope ici.
            qs = base.filter(environment=environment)
            if self.action == 'list':
                return filter_queryset_to_viewer_zone(
                    self.request, qs,
                    resolver=lambda niveau, code: (
                        Q(**{f"demande__{SECTEUR_CHAMP_PAR_NIVEAU[niveau]}": code})
                        | Q(**{f"information__{SECTEUR_CHAMP_PAR_NIVEAU[niveau]}": code})
                        | Q(**{f"equipe__institution__{SECTEUR_CHAMP_PAR_NIVEAU[niveau]}": code})
                    ),
                ).distinct()
            return qs
        # Un chef d'équipe de terrain (leader/régulateur d'une équipe) doit voir TOUS les
        # dossiers de cette équipe, pas seulement ceux où il est lui-même participant — sinon
        # aucune vue d'ensemble possible pour coordonner plusieurs équipes à la fois.
        return base.filter(
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

    @action(detail=True, methods=["post"], url_path="marquer-important")
    def marquer_important(self, request, pk=None):
        """Signale une urgence sur ce dossier — accessible à tout participant (pas réservé aux
        institutionnels, contrairement à update/partial_update) : un bénévole terrain doit
        pouvoir alerter le régulateur lui-même, sans attendre un point de situation. get_object()
        (via get_queryset()) garantit déjà que l'appelant est participant, chef/régulateur de
        l'équipe affectée, ou institutionnel — même garde que DossierCommentaireViewSet.
        perform_create. Bascule le flag (un second appel désactive) ; notifie les régulateurs
        uniquement au passage à True, jamais à la désactivation."""
        dossier = self.get_object()
        dossier.important = not dossier.important
        dossier.date_signalement_important = timezone.now() if dossier.important else None
        dossier.save(update_fields=["important", "date_signalement_important"])

        if dossier.important:
            regulateurs = _regulateurs_pour_dossier(dossier, dossier.equipe)
            for regulateur in regulateurs:
                Notification.objects.create(
                    utilisateur=regulateur,
                    dossier=dossier,
                    titre="Dossier marqué important",
                    message=f"Le dossier {dossier.numero} ({dossier.titre}) a été signalé important par {request.user.email}.",
                    environment=dossier.environment,
                )
                try:
                    send_mail_env_aware(
                        request,
                        subject=f"Urgent : dossier {dossier.numero} marqué important",
                        message=(
                            f"Bonjour,\n\n"
                            f"Le dossier {dossier.numero} ({dossier.titre}) a été signalé "
                            f"comme important par {request.user.email}.\n\n"
                            "Connectez-vous pour plus de détails.\n\n"
                            "Cordialement,\n"
                            "L'équipe Assista-Crise"
                        ),
                        from_email=None,
                        recipient_list=[regulateur.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    print(f"Erreur envoi email dossier important : {e}")
            audit_log(
                request=request,
                action_code="MODIFICATION",
                objet_type="Dossier",
                objet_id=dossier.id,
                crise=dossier.crise,
                commentaire=f"Dossier {dossier.numero} marqué important par {request.user.email}",
            )

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

    @action(detail=True, methods=["post"], url_path="affecter-equipe", permission_classes=[IsInstitutionalActor])
    def affecter_equipe(self, request, pk=None):
        """Affecte (ou réaffecte) une équipe à ce dossier directement depuis la vue régulateur.
        Jusqu'ici, seule la création via assign_team/creer_dossier peuplait correctement
        DossierParticipant et notifiait les régulateurs — un dossier déjà existant sans équipe
        (ou à réaffecter) n'avait aucun chemin dédié, seulement le PATCH générique qui ne fait
        ni l'un ni l'autre. Fait passer le statut à AFFECTE s'il n'était qu'en attente."""
        dossier = self.get_object()
        team_id = request.data.get('equipe')
        if not team_id:
            return Response({"error": "Équipe requise."}, status=status.HTTP_400_BAD_REQUEST)
        team = get_object_or_404(Team, pk=team_id)

        ancien_statut = dossier.statut
        dossier.equipe = team
        if dossier.statut in (
            Dossier.Statut.NOUVEAU, Dossier.Statut.EN_ATTENTE_AFFECTATION,
            Dossier.Statut.EN_ATTENTE_DISTRIBUTION,
        ):
            dossier.statut = Dossier.Statut.AFFECTE
        dossier.save(update_fields=['equipe', 'statut'])

        DossierHistorique.objects.create(
            dossier=dossier, auteur=request.user,
            evenement=f"Équipe affectée : {team.name}", environment=dossier.environment,
        )
        populate_dossier_participants_and_notify(
            dossier, equipe=team,
            notification_titre="Dossier affecté à votre équipe",
            notification_message=f"Le dossier {dossier.numero} ({dossier.titre}) a été affecté à l'équipe {team.name}.",
        )
        audit_log(
            request=request, action_code="MODIFICATION", objet_type="Dossier",
            objet_id=dossier.id, crise=dossier.crise,
            ancien_etat=ancien_statut, nouvel_etat=dossier.statut,
            commentaire=f"Équipe affectée au dossier {dossier.numero} : {team.name}",
        )
        return Response(DossierSerializer(dossier, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="definir-statut", permission_classes=[permissions.IsAuthenticated])
    def definir_statut(self, request, pk=None):
        """Change le statut du dossier directement depuis la vue régulateur — ou depuis "Mes
        interventions" pour le chef/régulateur de l'équipe affectée (même garde que
        definir_priorite/marquer_important ci-dessus : un chef d'équipe non-institutionnel doit
        pouvoir faire évoluer le statut de ses propres dossiers sans attendre un institutionnel).
        Pour les statuts intermédiaires (avant clôture) uniquement. CLOTURE/RESOLU restent
        exclusivement gérés par cloturer(), qui a sa propre garde plus stricte (régulateur du
        dossier ou responsable de la crise, pas n'importe quel institutionnel) — jamais
        dupliquée ici."""
        dossier = self.get_object()
        equipe = dossier.equipe
        est_chef_equipe = equipe is not None and request.user.id in (equipe.leader_id, equipe.regulateur_id)
        if not est_chef_equipe and get_effective_role(request) not in INSTITUTIONAL_TYPES:
            return Response(
                {"error": "Seul le chef ou le régulateur de l'équipe affectée peut changer le statut."},
                status=status.HTTP_403_FORBIDDEN,
            )

        nouveau_statut = request.data.get('statut')
        statuts_autorises = (
            Dossier.Statut.NOUVEAU, Dossier.Statut.EN_ATTENTE_DISTRIBUTION,
            Dossier.Statut.EN_ATTENTE_AFFECTATION, Dossier.Statut.AFFECTE, Dossier.Statut.EN_COURS,
        )
        if nouveau_statut not in statuts_autorises:
            return Response(
                {"error": "Statut invalide pour cette action (utilisez plutôt cloturer pour clôturer/résoudre)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ancien_statut = dossier.statut
        dossier.statut = nouveau_statut
        dossier.save(update_fields=['statut'])

        DossierHistorique.objects.create(
            dossier=dossier, auteur=request.user,
            evenement=f"Statut changé : {dossier.get_statut_display()}", environment=dossier.environment,
        )
        audit_log(
            request=request, action_code="MODIFICATION", objet_type="Dossier",
            objet_id=dossier.id, crise=dossier.crise,
            ancien_etat=ancien_statut, nouvel_etat=nouveau_statut,
            commentaire=f"Statut du dossier {dossier.numero} changé : {ancien_statut} → {nouveau_statut}",
        )
        return Response(DossierSerializer(dossier, context=self.get_serializer_context()).data)

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
    # Exclut un type d'offre (ex: "Bénévolat") — utilisé par le tableau de triage régulateur
    # (ReportingComponent) pour ne pas charger l'annuaire permanent de bénévoles au côté des
    # offres de crise en attente d'action : sémantiquement différent (pas de crise rattachée,
    # potentiellement des milliers de fiches), à consulter via /offres/vue_secteur/ à la place.
    exclude_type = filters.CharFilter(method='filter_exclude_type')

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

    def filter_exclude_type(self, queryset, name, value):
        return queryset.exclude(offer_type__type=value)

class UserViewSet(viewsets.ModelViewSet):
    # select_related('institution') : UserSerializer.get_ma_zone lit obj.institution sur
    # CHAQUE utilisateur sérialisé (list compris), sans ce select_related ce serait une requête
    # par utilisateur listé.
    queryset = User.objects.select_related('institution').all()
    serializer_class = UserSerializer

    def get_queryset(self):
        # ?institution=<uuid> (répétable : ?institution=<uuid1>&institution=<uuid2>) restreint
        # la liste aux membres actifs d'une de ces institutions (via ContactInstitution, la
        # relation faisant autorité pour "qui appartient à cette institution" — User.institution
        # n'est pas posé de façon fiable par tous les chemins d'inscription/rattachement) —
        # utilisé par le sélecteur de membres d'une équipe pour ne proposer que les gens de
        # l'institution responsable ET, le cas échéant, de l'institution délégataire, jamais
        # tous les comptes de la plateforme.
        queryset = super().get_queryset()
        if self.action == 'list':
            institution_ids = [v for v in self.request.query_params.getlist('institution') if v]
            if institution_ids:
                queryset = queryset.filter(
                    institutions__institution_id__in=institution_ids,
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
        if self.action in ('reactiver', 'actualiser_risques'):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=["post"], url_path="actualiser-risques")
    def actualiser_risques(self, request):
        """Force le rafraîchissement des risques du territoire de l'institution de
        l'utilisateur appelant (ignore le cache et le cooldown, contrairement à la lecture
        normale via UserSerializer.get_ma_zone) — bouton "Actualiser" de la Vue Ma
        Collectivité."""
        institution = getattr(request.user, 'institution', None)
        if institution is None or not institution.commune_code:
            return Response(
                {"error": "Aucune commune associée à votre institution."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        risques = commune_risques(institution.commune_code, force=True)
        return Response({
            "risques": risques,
            "risques_date_maj": commune_risques_date_maj(institution.commune_code),
        })

    def perform_destroy(self, instance):
        # Même effet que reject_account (is_active=False, voir le commentaire "Désactiver le
        # compte (ou le supprimer)" ci-dessus) : jamais de suppression réelle d'un compte,
        # cohérent avec la politique de désactivation appliquée à Offer/Request/Information/
        # Team. `enabled` n'est pas touché ici : un compte déjà approuvé le reste, il suffit de
        # reposer is_active=True pour le réactiver (voir reactiver ci-dessous).
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        audit_log(
            request=self.request,
            action_code="DESACTIVATION",
            objet_type="User",
            objet_id=instance.id,
            commentaire=f"Désactivation compte : {instance.email}",
        )

    @action(detail=True, methods=["post"])
    def reactiver(self, request, pk=None):
        """Réactive un compte désactivé (voir perform_destroy) — réservé aux acteurs
        institutionnels, comme approve_account/reject_account."""
        user_to_reactivate = self.get_object()
        user_to_reactivate.is_active = True
        user_to_reactivate.save(update_fields=['is_active'])
        audit_log(
            request=request,
            action_code="REACTIVATION",
            objet_type="User",
            objet_id=user_to_reactivate.id,
            commentaire=f"Réactivation compte : {user_to_reactivate.email}",
        )
        return Response(UserSerializer(user_to_reactivate).data)

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
                    send_mail_logged(
                        request,
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
                        send_mail_logged(
                            request,
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
                        send_mail_logged(
                            request,
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

    @action(detail=False, methods=['get'])
    def institution_suggestion(self, request):
        """Institution retrouvée pour l'utilisateur connecté à partir de ce qu'il a déclaré à
        l'inscription (voir find_institution_for_pending_user) — sans rien rattacher, appelable
        plusieurs fois sans effet de bord. Alimente l'écran "Finalisez votre inscription" affiché
        après activation pour un compte Autorité locale. 400 si rien à résoudre (compte déjà
        rattaché, ou pas de ce type)."""
        user = request.user
        if not user.pending_institution_name:
            return Response(
                {"error": "Aucune institution en attente de rattachement pour ce compte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        institution = find_institution_for_pending_user(user, request)
        return Response({
            "institution": InstitutionSerializer(institution, context=self.get_serializer_context()).data if institution else None,
            # Pour préremplir le formulaire de création si rien n'est trouvé (voir
            # creer_mon_institution) — ces champs sont write_only sur UserSerializer, donc pas
            # récupérables autrement par le frontend une fois soumis à l'inscription.
            "pending_institution_name": user.pending_institution_name,
            "pending_commune_name": user.pending_commune_name,
            "pending_commune_code": user.pending_commune_code,
        })

    @action(detail=False, methods=['post'], url_path='confirmer-institution')
    def confirmer_institution(self, request):
        """Confirme le rattachement à l'institution retrouvée par institution_suggestion, avec
        le rôle choisi par l'utilisateur — au lieu du rôle deviné automatiquement comme avant ce
        correctif."""
        user = request.user
        if not user.pending_institution_name:
            return Response(
                {"error": "Aucune institution en attente de rattachement pour ce compte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        role_code = request.data.get('role_code')
        if not role_code:
            return Response({"error": "role_code est requis."}, status=status.HTTP_400_BAD_REQUEST)

        institution = find_institution_for_pending_user(user, request)
        if institution is None:
            return Response(
                {"error": "Aucune institution trouvée — utilisez creer_mon_institution pour la créer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            attach_user_with_role(user, institution, role_code, request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(UserSerializer(user, context=self.get_serializer_context()).data)

    @action(detail=False, methods=['post'], url_path='creer-mon-institution')
    def creer_mon_institution(self, request):
        """Quand institution_suggestion ne renvoie rien : la personne crée elle-même son
        institution (mêmes champs que le formulaire admin, voir InstitutionSerializer/
        InstitutionViewSet) et s'y rattache directement avec le rôle choisi, comme créatrice."""
        user = request.user
        if not user.pending_institution_name:
            return Response(
                {"error": "Aucune institution en attente de rattachement pour ce compte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        role_code = request.data.get('role_code')
        if not role_code:
            return Response({"error": "role_code est requis."}, status=status.HTTP_400_BAD_REQUEST)

        institution_serializer = InstitutionSerializer(data=request.data, context=self.get_serializer_context())
        institution_serializer.is_valid(raise_exception=True)
        institution = institution_serializer.save(environment=get_active_environment(request))
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="Institution",
            objet_id=institution.id,
            commentaire=f"Création institution par {user.email} lors de la finalisation d'inscription : {institution.nom}",
        )

        try:
            attach_user_with_role(
                user, institution, role_code, request,
                fonction='Créateur', contact_principal=True,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            UserSerializer(user, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

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

        # Rattachement institution pour les comptes SECOURS (AASC/RCSC) : pas de lien magique
        # d'activation pour ce type (voir register()), donc c'est ICI — au moment où un humain
        # de confiance (admin ou mairie) approuve réellement le compte — que ça doit se jouer,
        # jamais avant. Capturé avant l'appel : attach_secours_user_to_institution efface les
        # pending_* en sortie, donc plus moyen de savoir après coup si c'était une RCSC.
        pending_type_secours = (user_to_approve.pending_institution_type or '').strip().lower()
        if user_to_approve.type == UserRole.ORGANIZED_RESCUE:
            matched_institution = attach_secours_user_to_institution(user_to_approve, request)
            if pending_type_secours == 'rcsc' and matched_institution is None:
                try:
                    send_mail_logged(
                        request,
                        subject="Compte RCSC validé sans mairie rattachée",
                        message=(
                            f"Bonjour,\n\n"
                            f"Un compte réserviste RCSC a été approuvé mais aucune mairie "
                            f"n'est enregistrée pour sa commune ({user_to_approve.pending_commune_name or 'non renseignée'}).\n\n"
                            f"- Nom : {user_to_approve.first_name} {user_to_approve.last_name}\n"
                            f"- Email : {user_to_approve.email}\n\n"
                            "Un rattachement manuel à la bonne mairie est nécessaire dès qu'elle "
                            "sera enregistrée sur la plateforme."
                        ),
                        from_email=None,
                        recipient_list=['contact@assista-crise.fr'],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(f"Erreur envoi email rattachement RCSC manuel : {e}")

        # Envoyer email de confirmation
        try:
            send_mail_logged(
                request,
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
            send_mail_logged(
                request,
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


class ImportApercuView(APIView):
    """Étape 1 de l'import CSV/XLS (n'importe quel type de liste, voir imports.py) : renvoie les
    en-têtes détectées et un aperçu (10 premières lignes) pour que l'utilisateur associe chaque
    colonne de son fichier à un champ cible avant de lancer l'import réel — jamais d'import à
    l'aveugle sur la seule foi de l'ordre des colonnes."""
    permission_classes = [IsInstitutionalActor]

    def post(self, request):
        fichier = request.FILES.get('fichier')
        if not fichier:
            return Response({"error": "Aucun fichier reçu."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            colonnes, lignes = parse_fichier(fichier)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"error": "Impossible de lire ce fichier — vérifiez qu'il s'agit bien d'un CSV ou XLSX valide."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "colonnes": colonnes,
            "apercu": lignes[:10],
            "total_lignes": len(lignes),
        })


class ImportPersonnelCommunalView(APIView):
    """Étape 2 : import réel du personnel communal/élus de l'institution de l'utilisateur
    appelant, en comptes complets (voir imports.importer_personnel_communal) — jamais une
    donnée de santé : seuls prénom/nom/email/téléphone/fonction sont lus, quelle que soit la
    colonne du fichier source qui leur est associée."""
    permission_classes = [IsInstitutionalActor]

    def post(self, request):
        institution = getattr(request.user, 'institution', None)
        if institution is None:
            return Response(
                {"error": "Aucune institution associée à votre compte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fichier = request.FILES.get('fichier')
        if not fichier:
            return Response({"error": "Aucun fichier reçu."}, status=status.HTTP_400_BAD_REQUEST)
        mapping = {champ: request.data.get(f"mapping_{champ}") for champ in CHAMPS_PERSONNEL_COMMUNAL}
        if not mapping.get("email") or not mapping.get("nom"):
            return Response(
                {"error": "Les colonnes Email et Nom doivent être associées avant de lancer l'import."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            _colonnes, lignes = parse_fichier(fichier)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        resultat = importer_personnel_communal(request, institution, lignes, mapping)
        return Response(resultat)


class ImportPersonnelCommunalExempleView(APIView):
    """Fichier CSV d'exemple téléchargeable juste à côté du formulaire d'import, pour que la
    mairie prépare son propre fichier dans le bon format avant de l'envoyer."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        response = HttpResponse(exemple_csv_personnel_communal(), content_type="text/csv; charset=utf-8")
        response['Content-Disposition'] = 'attachment; filename="exemple-personnel-communal.csv"'
        return response


def _dashboard_zone_filter(request):
    """(niveau, code) de la zone du viewer pour le tableau de bord — jamais bloquant : un
    administrateur ou un utilisateur sans zone résolvable (pas institutionnel, institution
    sans commune) obtient `None`, traité comme "vue nationale" par l'appelant plutôt qu'un
    tableau vide (contrairement à filter_queryset_to_viewer_zone, qui renvoie .none() faute
    de zone connue — approprié pour des listes de contenu, pas pour un dashboard accessible à
    tout utilisateur authentifié, y compris un bénévole simple sans institution)."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return None
    zone = viewer_zone_code(request)
    if zone is None or zone[0] == "national":
        return None
    return zone


class DashboardStatsView(APIView):
    """Agrégats pour le tableau de bord admin (cartes de synthèse, courbe d'évolution 30
    jours, camembert des types de crise, éléments récents) — calculés en base par COUNT/
    GROUP BY plutôt qu'en chargeant les listes complètes de crises/offres/demandes côté
    frontend (voir dashboard.component.ts : l'ancienne implémentation faisait un getAll()
    sur les 3 endpoints, sérialisant chaque objet avec toutes ses relations et son lookup
    géo juste pour en compter la longueur)."""

    permission_classes = [permissions.IsAuthenticated]

    FILTER_DELTAS = {
        "week": relativedelta(days=7),
        "month": relativedelta(months=1),
        "quarter": relativedelta(months=3),
        "half_year": relativedelta(months=6),
        "year": relativedelta(years=1),
    }

    def _base_querysets(self, env):
        crises = Crisis.objects.filter(environment=env)
        # exclude Bénévolat : annuaire permanent de bénévoles (potentiellement des milliers de
        # fiches, sans crise rattachée) — hors-sujet pour le suivi de crise du dashboard,
        # même motif que ReportingComponent.loadAll côté frontend. Compté séparément (carte
        # "Bénévoles") plutôt qu'exclu silencieusement.
        offres = Offer.objects.filter(environment=env).exclude(offer_type__type='Bénévolat')
        demandes = Request.objects.filter(environment=env)
        signalements = Information.objects.filter(environment=env)
        benevoles = Offer.objects.filter(environment=env, offer_type__type='Bénévolat')
        return {
            "crises": crises, "offres": offres, "demandes": demandes,
            "signalements": signalements, "benevoles": benevoles,
        }

    def _scope_to_zone(self, querysets, zone):
        """Restreint chaque queryset à la zone (niveau, code) donnée. Offer/Request ont un code
        géo dénormalisé complet (commune_code/epci_code/departement_code/region_code, voir
        SECTEUR_CHAMP_PAR_NIVEAU) ; Information n'a que commune_code — voir
        _information_zone_resolver, qui passe par le référentiel Commune pour les niveaux
        epci/departement/region. Crisis n'a aucun code dénormalisé (zone_communes/
        zone_departements, une crise pouvant couvrir plusieurs secteurs) — approximé par
        containment sur ces listes pour les niveaux commune/departement ; best-effort pour
        epci/region (aucune correspondance directe possible sans agréger les communes
        membres), la carte "Crises" restant alors nationale pour ces deux niveaux-là."""
        niveau, code = zone
        result = dict(querysets)
        champ = SECTEUR_CHAMP_PAR_NIVEAU.get(niveau)
        if champ:
            for key in ("offres", "demandes", "benevoles"):
                result[key] = result[key].filter(**{champ: code})
        result["signalements"] = result["signalements"].filter(_information_zone_resolver(niveau, code))
        if niveau == "commune":
            result["crises"] = result["crises"].filter(zone_communes__contains=[code])
        elif niveau == "departement":
            result["crises"] = result["crises"].filter(zone_departements__contains=[code])
        return result

    def _period_counts(self, querysets, filter_start, now):
        crises_qs, offres_qs, demandes_qs = querysets["crises"], querysets["offres"], querysets["demandes"]
        signalements_qs, benevoles_qs = querysets["signalements"], querysets["benevoles"]
        if filter_start:
            crises_qs = crises_qs.filter(start_date__gte=filter_start, start_date__lte=now)
            offres_qs = offres_qs.filter(created_at__gte=filter_start, created_at__lte=now)
            demandes_qs = demandes_qs.filter(created_at__gte=filter_start, created_at__lte=now)
            signalements_qs = signalements_qs.filter(created_at__gte=filter_start, created_at__lte=now)
            benevoles_qs = benevoles_qs.filter(created_at__gte=filter_start, created_at__lte=now)

        current = {
            "crises": crises_qs.count(), "offres": offres_qs.count(), "demandes": demandes_qs.count(),
            "signalements": signalements_qs.count(), "benevoles": benevoles_qs.count(),
        }

        previous = {"crises": 0, "offres": 0, "demandes": 0, "signalements": 0, "benevoles": 0}
        if filter_start:
            duree = now - filter_start
            prev_end = filter_start
            prev_start = prev_end - duree
            previous = {
                "crises": querysets["crises"].filter(start_date__gte=prev_start, start_date__lte=prev_end).count(),
                "offres": querysets["offres"].filter(created_at__gte=prev_start, created_at__lte=prev_end).count(),
                "demandes": querysets["demandes"].filter(created_at__gte=prev_start, created_at__lte=prev_end).count(),
                "signalements": querysets["signalements"].filter(created_at__gte=prev_start, created_at__lte=prev_end).count(),
                "benevoles": querysets["benevoles"].filter(created_at__gte=prev_start, created_at__lte=prev_end).count(),
            }
        return current, previous

    def get(self, request):
        env = get_active_environment(request)
        filter_key = request.query_params.get("filter", "all")
        now = timezone.now()

        national_qs = self._base_querysets(env)
        zone = _dashboard_zone_filter(request)
        zone_qs = self._scope_to_zone(national_qs, zone) if zone else national_qs

        crises_all, offres_all, demandes_all = zone_qs["crises"], zone_qs["offres"], zone_qs["demandes"]
        totals = {
            "crises": crises_all.count(),
            "offres": offres_all.count(),
            "demandes": demandes_all.count(),
        }
        total_items = totals["crises"] + totals["offres"] + totals["demandes"]

        delta = self.FILTER_DELTAS.get(filter_key)
        filter_start = now - delta if delta else None

        current, previous = self._period_counts(zone_qs, filter_start, now)
        national_current, national_previous = (
            self._period_counts(national_qs, filter_start, now) if zone else (current, previous)
        )

        crises_qs, offres_qs, demandes_qs = crises_all, offres_all, demandes_all
        if filter_start:
            crises_qs = crises_qs.filter(start_date__gte=filter_start, start_date__lte=now)
            offres_qs = offres_qs.filter(created_at__gte=filter_start, created_at__lte=now)
            demandes_qs = demandes_qs.filter(created_at__gte=filter_start, created_at__lte=now)

        # Courbe d'évolution : toujours les 30 derniers jours calendaires, bornés en plus par
        # la période sélectionnée (réplique le comportement de l'ancien buildLineChart, qui
        # comptait les occurrences par jour dans le sous-ensemble déjà filtré par période).
        window_start = (now - datetime.timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        effective_start = max(window_start, filter_start) if filter_start else window_start

        def day_counts(queryset, date_field):
            rows = (
                queryset.filter(**{f"{date_field}__gte": effective_start, f"{date_field}__lte": now})
                .annotate(day=TruncDate(date_field))
                .values("day")
                .annotate(n=Count("id"))
            )
            return {row["day"]: row["n"] for row in rows}

        crises_by_day = day_counts(crises_all, "start_date")
        offres_by_day = day_counts(offres_all, "created_at")
        demandes_by_day = day_counts(demandes_all, "created_at")

        day_points = []
        for i in range(29, -1, -1):
            d = (now - datetime.timedelta(days=i)).date()
            day_points.append({
                "date": d.isoformat(),
                "crises": crises_by_day.get(d, 0),
                "offres": offres_by_day.get(d, 0),
                "demandes": demandes_by_day.get(d, 0),
            })

        # Camembert des types de crise, sur la période filtrée.
        type_labels = dict(TypeCrise.choices)
        pie = [
            {"type": row["type"], "type_display": type_labels.get(row["type"], row["type"]), "count": row["n"]}
            for row in crises_qs.values("type").annotate(n=Count("id")).order_by("-n")[:6]
        ]

        # Éléments récents (8 plus récents, tous types confondus, sur la période filtrée).
        recent = (
            [
                {"id": str(c["id"]), "title": c["name"], "type": "Crise", "date": c["start_date"], "status": "NON_TRAITEE"}
                for c in crises_qs.order_by("-start_date").values("id", "name", "start_date")[:8]
            ]
            + [
                {"id": str(o["id"]), "title": o["title"], "type": "Ressource", "date": o["created_at"], "status": o["status"]}
                for o in offres_qs.order_by("-created_at").values("id", "title", "created_at", "status")[:8]
            ]
            + [
                {"id": str(r["id"]), "title": r["title"], "type": "Besoin", "date": r["created_at"], "status": r["status"]}
                for r in demandes_qs.order_by("-created_at").values("id", "title", "created_at", "status")[:8]
            ]
        )
        recent.sort(key=lambda item: item["date"], reverse=True)
        recent = recent[:8]

        return Response({
            "stats": current,
            "previous": previous,
            "totals": totals,
            "day_points": day_points,
            "pie": pie,
            "recent_items": recent,
            "total_items": total_items,
            # National toujours présent (identique à "stats"/"previous" si aucune zone n'a pu
            # être appliquée — administrateur ou utilisateur sans zone résolvable) : alimente la
            # 6ᵉ fenêtre miniature du dashboard, à côté des 5 cartes "ma zone".
            "national": {"stats": national_current, "previous": national_previous},
            "is_zone_scoped": zone is not None,
        })


class CrisisViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    # author_nom déréférence author (FK) ; has_responsable_actif touche implications (reverse
    # FK), prefetch + vérification en Python dans get_has_responsable_actif ci-dessous plutôt
    # qu'un .filter().exists() par crise.
    queryset = Crisis.objects.select_related('author').prefetch_related('implications')
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

        # Purge définitive des offres/demandes/signalements de cette crise déjà désactivés
        # (voir la politique de désactivation, perform_destroy des 3 ViewSets concernés) — les
        # éléments toujours actifs restent en revanche comme archive permanente de la crise,
        # jamais purgés automatiquement. Team/User ne sont pas rattachés à UNE crise unique
        # (une équipe/un compte peut survivre à plusieurs crises) : ils ne sont donc jamais
        # purgés ici, seulement désactivés indéfiniment.
        Offer.objects.filter(crisis=crise, actif=False).delete()
        Request.objects.filter(crisis=crise, actif=False).delete()
        Information.objects.filter(crisis=crise, actif=False).delete()

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
                "materiel_point_id": str(m.id),
                "niveau_stock": m.niveau_stock,
                "niveau_stock_libelle": m.get_niveau_stock_display(),
                "quantite": m.quantite,
                "unite": m.unite,
            }

        items = []
        for item in MaterielCatalogue.objects.all().order_by("nom"):
            par_point = niveaux.get(str(item.id), {})
            items.append({
                "item": str(item.id),
                "item_nom": item.nom,
                "niveaux": {
                    str(p.id): par_point.get(str(p.id), {
                        "materiel_point_id": None,
                        "niveau_stock": NiveauStock.NUL,
                        "niveau_stock_libelle": NiveauStock.NUL.label,
                        "quantite": None,
                        "unite": None,
                    })
                    for p in points
                },
            })

        return Response({
            "points": [
                {
                    "id": str(p.id), "nom": p.nom, "type_libelle": p.type.libelle if p.type else None,
                    "responsables_contacts": PointOperationnelSerializer(p).get_responsables_contacts(p),
                }
                for p in points
            ],
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


def _notify_regulateurs_creneau_a_valider(affectation, request):
    """Prévient le(s) régulateur(s) du point (responsable + leader d'équipe, sans doublon)
    qu'un bénévole a répondu « oui » à une sollicitation et attend une validation avant
    confirmation définitive (voir PointOperationnelViewSet.valider_benevole). Silencieux si le
    point n'a ni responsable ni leader d'équipe joignable."""
    point = affectation.point
    destinataires = {u for u in (point.responsable, point.equipe.leader if point.equipe else None) if u}
    if not destinataires:
        return

    message = (
        f"{affectation.benevole.first_name} {affectation.benevole.last_name} a confirmé sa "
        f"disponibilité pour le point « {point.nom} » — validation requise avant confirmation "
        f"définitive."
    )
    for user in destinataires:
        Notification.objects.create(
            utilisateur=user, titre="Créneau bénévole à valider",
            message=message, environment=affectation.environment,
        )
        try:
            send_mail_env_aware(
                request,
                subject=f"Créneau à valider — {point.nom}",
                message=f"Bonjour {user.first_name},\n\n{message}\n\nCordialement,\nL'équipe Assista-Crise",
                from_email=None,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Erreur envoi email validation créneau bénévole : {e}")


def send_benevole_validation_result_email(request, affectation, decision):
    """Email envoyé au bénévole une fois son créneau arbitré par le régulateur (voir
    PointOperationnelViewSet.valider_benevole) — deuxième et dernier email de ce flux, après
    celui de send_point_volunteer_confirmation_email."""
    point = affectation.point
    if decision == "confirmer":
        subject = f"Créneau confirmé — {point.nom}"
        message = (
            f"Bonjour,\n\nVotre créneau sur le point « {point.nom} » du "
            f"{affectation.date_attendue.strftime('%d/%m/%Y à %H:%M')} a été validé par le "
            f"régulateur : votre participation est définitivement confirmée.\n\n"
            "Cordialement,\nL'équipe Assista-Crise"
        )
    else:
        subject = f"Créneau non retenu — {point.nom}"
        message = (
            f"Bonjour,\n\nMerci pour votre disponibilité sur le point « {point.nom} ». Le "
            f"régulateur n'a finalement pas retenu ce créneau. N'hésitez pas à consulter "
            f"d'autres opportunités sur la plateforme.\n\nCordialement,\nL'équipe Assista-Crise"
        )
    try:
        send_mail_env_aware(
            request, subject=subject, message=message, from_email=None,
            recipient_list=[affectation.benevole.email], fail_silently=True,
        )
    except Exception as e:
        print(f"Erreur envoi email résultat validation créneau bénévole : {e}")


def send_engagement_confirmation_email(request, engagement):
    """Email envoyé quand une offre est affectée comme ressource à une équipe (voir
    TeamViewSet.assigner_ressource) — lien opaque vers une page frontend persistante
    (contrairement à ConfirmerAffectationBenevoleView, à sens unique) : la personne/
    l'entreprise peut y revenir à chaque étape (confirmer, signaler le départ, signaler
    l'arrivée) avec le même lien."""
    offer = engagement.offer
    destinataire = offer.author.email if offer.author_id else offer.email_offer
    if not destinataire:
        return

    base_url = settings.SERVER_URL.rstrip('/')
    lien = f"{base_url}/confirmation-ressource/{engagement.token_confirmation}"

    lignes = [
        f"Bonjour {offer.first_name_offer},",
        "",
        f"Votre offre « {offer.title} » a été affectée à l'équipe {engagement.team.name}"
        + (f" pour la mission « {engagement.team.mission_active.titre} »" if engagement.team.mission_active_id else "")
        + ".",
        "",
        "Merci de confirmer votre disponibilité, puis de signaler votre départ et votre",
        "arrivée depuis la même page, en cliquant sur ce lien à chaque étape :",
        "",
        lien,
        "",
        "Cordialement,",
        "L'équipe Assista-Crise",
    ]

    send_mail_env_aware(
        request,
        subject=f"Confirmez votre disponibilité — {offer.title}",
        message="\n".join(lignes),
        from_email=None,
        recipient_list=[destinataire],
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


def parse_datetime_param(value):
    """Accepte aussi bien une date seule (YYYY-MM-DD, ce qu'envoie un <input type=date>) qu'un
    datetime ISO complet — parse_datetime seul renvoie None sur une date seule."""
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed:
        return parsed
    try:
        d = datetime.date.fromisoformat(value)
    except ValueError:
        return None
    return timezone.make_aware(datetime.datetime.combine(d, datetime.time.min))


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


def _regulateurs_pour_dossier(dossier, equipe=None):
    """Régulateur·s réellement concerné·s par ce dossier — extrait de
    populate_dossier_participants_and_notify pour être réutilisé ailleurs (ex: notifier au
    passage d'un dossier en "important") sans dupliquer cette logique. Priorité à la
    compétence du dossier (indépendante de l'équipe) ; à défaut, régulateur·s parmi les
    membres de l'équipe affectée."""
    if dossier.competence:
        return User.objects.filter(
            affectations_roles__competence=dossier.competence,
            affectations_roles__role__code="REGULATEUR",
            affectations_roles__actif=True,
        ).distinct()
    if equipe:
        member_ids = equipe.members.values_list('id', flat=True)
        regulateur_affectations = AffectationRoleOperationnel.objects.filter(
            utilisateur_id__in=member_ids, role__code="REGULATEUR", actif=True,
        )
        competence_ids = list(equipe.competences.values_list('id', flat=True))
        if competence_ids:
            regulateur_affectations = regulateur_affectations.filter(competence_id__in=competence_ids)
        return User.objects.filter(
            id__in=regulateur_affectations.values_list('utilisateur_id', flat=True)
        ).distinct()
    return User.objects.none()


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

    regulateurs = _regulateurs_pour_dossier(dossier, equipe)

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
    # RequestSerializer déréférence author/crisis pour chaque demande — même optimisation que
    # OfferViewSet.queryset (221 requêtes mesurées pour 220 demandes DEMO sans select_related).
    queryset = Request.objects.select_related('author', 'crisis')
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
        if self.action in ('assign_team', 'bulk_assign_mission', 'vue_mairie', 'vue_secteur', 'transformer', 'reactiver'):
            return [IsInstitutionalActor()]
        return [AllowAny()]

    def get_queryset(self):
        qs = annotate_distance_from_crisis(
            super().get_queryset().select_related('crisis', 'author')
        )
        # L'action reactiver doit pouvoir retrouver une demande désactivée pour la réactiver —
        # déjà réservée à IsInstitutionalActor, pas besoin de repasser par ?actif=all ici.
        if self.action == 'reactiver':
            return qs
        return _filter_actif(self.request, qs)

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def reactiver(self, request, pk=None):
        """Réactive une demande désactivée (voir perform_destroy) — reste dans l'historique
        jusqu'à la clôture de la crise rattachée, purge automatique uniquement des demandes
        toujours désactivées à ce moment-là."""
        demande = self.get_object()
        demande.actif = True
        demande.save(update_fields=['actif'])
        audit_log(
            request=request,
            action_code="REACTIVATION",
            objet_type="Request",
            objet_id=demande.id,
            crise=demande.crisis,
            commentaire=f"Réactivation demande : {demande.title}",
        )
        return Response(RequestSerializer(demande, context={'request': request}).data)

    def perform_destroy(self, instance):
        instance.actif = False
        instance.save(update_fields=['actif'])
        audit_log(
            request=self.request,
            action_code="DESACTIVATION",
            objet_type="Request",
            objet_id=instance.id,
            crise=instance.crisis,
            commentaire=f"Désactivation demande : {instance.title}",
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

        # Résout commune_code/epci_code/departement_code/region_code une seule fois ici plutôt
        # qu'à chaque consultation (même correctif que OfferViewSet.perform_create) : sans
        # commune_code, RequestSerializer.get_commune retombe sur commune_from_point à CHAQUE
        # lecture — mesuré en direct sur la carte DEMO, 9.3s pour seulement 112 demandes
        # (commune_code jamais renseigné jusqu'ici, aucune vue ne le posait à la création).
        # Les trois autres champs alimentent vue_secteur (EPCI/département/région).
        if demande.location and not demande.commune_code:
            commune_code = commune_code_from_point(demande.location)
            if commune_code:
                secteur = commune_secteur_codes(commune_code)
                demande.commune_code = commune_code
                demande.epci_code = secteur["epci_code"]
                demande.departement_code = secteur["departement_code"]
                demande.region_code = secteur["region_code"]
                demande.save(update_fields=["commune_code", "epci_code", "departement_code", "region_code"])

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

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor],
            pagination_class=OptionalPageNumberPagination)
    def vue_secteur(self, request):
        """Demandes du secteur de l'institution de l'utilisateur appelant, même patron que
        OfferViewSet.vue_secteur (commune/EPCI/département/région/national selon le type
        d'institution ou secteur_override) — voir _institution_secteur_or_400. Annote
        nb_equipes_affectees (1 requête pour toute la liste, voir RequestSerializer.get_est_affectee)
        pour le récapitulatif affectée/non affectée du frontend, sans requête par demande."""
        secteur = _institution_secteur_or_400(request)
        if isinstance(secteur, Response):
            return secteur
        niveau, code = secteur

        base = self.get_queryset().annotate(nb_equipes_affectees=Count('assigned_teams', distinct=True))
        if niveau == "national":
            demandes = base.order_by("-created_at")
            hors_zone_recap = []
        else:
            demandes = base.filter(**{SECTEUR_CHAMP_PAR_NIVEAU[niveau]: code}).order_by("-created_at")
            # Hors zone = récapitulatif agrégé, jamais une liste d'items réduits (contrairement
            # à Team/PointOperationnel/Dossier/DeclarationSecurite/Information, en exclusion
            # totale) : juste une quantité par type de demande, pour donner une vue d'ensemble
            # nationale sans exposer le détail (ni a fortiori la PII) des demandes d'une autre
            # institution.
            hors_zone_recap = list(
                base.exclude(**{SECTEUR_CHAMP_PAR_NIVEAU[niveau]: code})
                .values('request_type__type')
                .annotate(count=Count('id'))
                .order_by('request_type__type')
            )
        page = self.paginate_queryset(demandes)
        if page is not None:
            response = self.get_paginated_response(self.get_serializer(page, many=True).data)
            response.data['hors_zone_recap'] = hors_zone_recap
            return response
        return Response({
            'results': self.get_serializer(demandes, many=True).data,
            'hors_zone_recap': hors_zone_recap,
        })

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        demande = self.get_object()
        if not demande.photo or not user_can_view_photo(
            request, demande, teams_field='assigned_teams', dossiers_field='dossiers'
        ):
            return Response(status=403)
        return FileResponse(open(demande.photo.path, "rb"))


class RequestPhotoViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Galerie de photos additionnelles d'une demande d'aide (voir RequestPhoto.__doc__) —
    create public comme la demande elle-même ; preview soumise à la même confidentialité que
    Request.photo (voir RequestViewSet.preview)."""
    queryset = RequestPhoto.objects.all()
    serializer_class = RequestPhotoSerializer
    filterset_fields = ["request"]

    def get_permissions(self):
        if self.action in ("create", "preview"):
            return [AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        photo = self.get_object()
        if not user_can_view_photo(
            request, photo.request, teams_field='assigned_teams', dossiers_field='dossiers'
        ):
            return Response(status=403)
        return FileResponse(open(photo.image.path, "rb"))


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


def _creer_equipe_pour_point(point, nom, institution, request):
    """Crée une équipe et l'assigne à ce point — factorisé entre la création du point
    (PointOperationnelViewSet.perform_create) et son édition ultérieure (perform_update),
    qui permettent toutes deux de créer une équipe à la volée plutôt que d'imposer un
    aller-retour séparé par l'écran équipes."""
    team = Team.objects.create(name=nom, institution=institution, environment=point.environment)
    point.equipe = team
    point.save(update_fields=['equipe'])
    audit_log(
        request=request,
        action_code="CREATION",
        objet_type="Team",
        objet_id=team.id,
        crise=point.crise,
        commentaire=f"Équipe créée avec le point opérationnel {point.nom}",
    )
    if institution is not None:
        _notify_institution_referent_of_team(team, institution, request)
    return team


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


def _filter_actif(request, queryset):
    """Filtre par défaut sur `actif=True` pour Offer/Request/Information/Team — masque les
    éléments désactivés (voir perform_destroy de ces ViewSets) sauf pour un acteur
    institutionnel qui demande explicitement `?actif=all` (ex: reporting/vue équipe/vue
    utilisateurs, qui doivent pouvoir retrouver et réactiver un élément désactivé). Un acteur
    non institutionnel qui passerait ce paramètre ne voit aucune différence : il ne doit de
    toute façon jamais voir le contenu désactivé d'autrui."""
    if (
        request.query_params.get('actif') == 'all'
        and request.user.is_authenticated
        and get_effective_role(request) in INSTITUTIONAL_TYPES
    ):
        return queryset
    return queryset.filter(actif=True)


def _appartient_a_institution(request, institution) -> bool:
    """Un admin plateforme n'est jamais limité par cette vérification ; sinon, l'appelant doit
    être un contact actif de l'institution donnée — même garde-fou territorial que
    approve_account/reject_account, appliqué ici aux actions qui agissent sur une équipe."""
    if get_effective_role(request) == UserRole.ADMINISTRATOR:
        return True
    return ContactInstitution.objects.filter(
        institution=institution, utilisateur=request.user, actif=True,
    ).exists()


def _appartient_a_equipe(request, team) -> bool:
    """Vrai si l'utilisateur appartient à l'institution responsable OU à l'institution
    délégataire de l'équipe — une fois une délégation active, l'institution délégataire gère
    l'équipe au quotidien à égalité avec l'institution responsable (invitations, mission,
    ressources, dossiers). Changer l'institution responsable ou la délégation elle-même reste
    en revanche réservé à l'institution responsable seule (voir perform_update,
    definir_delegation/retirer_delegation)."""
    if _appartient_a_institution(request, team.institution):
        return True
    return bool(team.institution_delegataire_id) and _appartient_a_institution(
        request, team.institution_delegataire
    )


def _institutions_liees(institution):
    """Institutions considérées comme "déjà liées" à `institution` : celles co-impliquées avec
    elle sur au moins une même crise (ImplicationInstitution), au sens le plus large (peu
    importe le type d'implication ou si elle est encore active) — le périmètre retenu pour
    autoriser le recrutement, dans une équipe, d'un membre appartenant à une institution tierce
    (voir TeamViewSet.perform_update/institutions_liees), en plus de l'institution délégataire
    qui l'est déjà par ailleurs."""
    crise_ids = ImplicationInstitution.objects.filter(institution=institution).values_list('crise_id', flat=True)
    return Institution.objects.filter(implications_crises__crise_id__in=crise_ids).exclude(pk=institution.pk).distinct()


def _resolve_institution_or_400(request):
    """Institution explicitement choisie dans le payload si l'appelant y a accès (ou est
    administrateur), sinon celle de son propre rattachement actif (ContactInstitution, la
    relation faisant autorité — voir UserSerializer.get_institution_id) — lève une erreur de
    validation si aucune des deux n'est disponible. Utilisé par ZoneViewSet/PlanViewSet, qui
    exigent toujours une institution (contrairement à PointOperationnel, qui peut s'en passer,
    voir PointOperationnelViewSet._resolve_institution_for_new_team)."""
    institution = None
    institution_id = request.data.get('institution')
    if institution_id:
        candidate = Institution.objects.filter(pk=institution_id).first()
        is_own = candidate and ContactInstitution.objects.filter(
            utilisateur=request.user, institution=candidate, actif=True
        ).exists()
        if candidate and (is_own or get_effective_role(request) == UserRole.ADMINISTRATOR):
            institution = candidate

    if institution is None:
        contact = ContactInstitution.objects.filter(
            utilisateur=request.user, actif=True
        ).select_related("institution").first()
        institution = contact.institution if contact else None

    if institution is None:
        raise ValidationError(
            {"institution": "Impossible de déterminer l'institution : précisez-la explicitement."}
        )
    return institution


class ZoneViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Catalogue de zones nommées d'une institution (voir Zone) — support du dispositif
    pré-enregistré (Plan) : chaque équipe/point peut en référencer une pour dire "je couvre le
    Quartier Nord" sans redessiner sa géométrie."""

    queryset = Zone.objects.select_related('institution').all()
    serializer_class = ZoneSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = _filter_actif(self.request, super().get_queryset())
        institution_ids = [v for v in self.request.query_params.getlist('institution') if v]
        if institution_ids:
            return qs.filter(institution_id__in=institution_ids)
        if get_effective_role(self.request) == UserRole.ADMINISTRATOR:
            return qs
        mes_institutions = ContactInstitution.objects.filter(
            utilisateur=self.request.user, actif=True
        ).values_list('institution_id', flat=True)
        return qs.filter(institution_id__in=mes_institutions)

    def perform_create(self, serializer):
        institution = _resolve_institution_or_400(self.request)
        zone = serializer.save(institution=institution, environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Zone",
            objet_id=zone.id,
            commentaire=f"Création zone : {zone.nom} ({institution.nom})",
        )

    def perform_destroy(self, instance):
        # Même politique de désactivation que Team/Offer/Request/Information : jamais de
        # suppression réelle, une zone référencée par des équipes/points/plans ne doit pas
        # casser leurs FK/M2M.
        instance.actif = False
        instance.save(update_fields=['actif'])


class PlanViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Dispositif pré-enregistré d'une institution (voir Plan) : sous-ensemble d'équipes/points/
    zones déjà existants, activable en un geste sur une crise réelle (voir `activer`)."""

    queryset = Plan.objects.select_related('institution').prefetch_related(
        'zones', 'equipes', 'points'
    ).all()
    serializer_class = PlanSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'activer'):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = _filter_actif(self.request, super().get_queryset())
        institution_ids = [v for v in self.request.query_params.getlist('institution') if v]
        if institution_ids:
            return qs.filter(institution_id__in=institution_ids)
        if get_effective_role(self.request) == UserRole.ADMINISTRATOR:
            return qs
        mes_institutions = ContactInstitution.objects.filter(
            utilisateur=self.request.user, actif=True
        ).values_list('institution_id', flat=True)
        return qs.filter(institution_id__in=mes_institutions)

    def perform_create(self, serializer):
        institution = _resolve_institution_or_400(self.request)
        plan = serializer.save(institution=institution, environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Plan",
            objet_id=plan.id,
            commentaire=f"Création plan : {plan.nom} ({institution.nom})",
        )

    def perform_destroy(self, instance):
        instance.actif = False
        instance.save(update_fields=['actif'])

    @action(detail=True, methods=["post"])
    def activer(self, request, pk=None):
        """Applique un sous-ensemble choisi des équipes/points du plan à une crise réelle
        (existante ou créée à la volée) : `equipes` peut ajuster les thèmes de chaque équipe
        pour cette activation précise (sinon ses thèmes actuels sont conservés tels quels),
        `points` les rattache simplement à la crise. Idempotent : ré-appeler pour ajouter une
        équipe plus tard dans la même crise ne casse rien. N'affecte jamais les équipes/points
        eux-mêmes de façon destructive — voir Plan (docstring) et le point de vigilance sur
        `cloturer()` dans le plan d'implémentation. `get_object()` s'appuie sur `get_queryset()`
        (scopé à l'institution de l'appelant, ou admin) : un plan d'une autre institution renvoie
        déjà 404 avant d'atteindre ce code, pas besoin d'un contrôle de permission distinct ici."""
        plan = self.get_object()

        crise_id = request.data.get('crise_id')
        nouvelle_crise = request.data.get('nouvelle_crise')
        if crise_id:
            crise = Crisis.objects.filter(pk=crise_id).first()
            if not crise:
                return Response({"error": "Crise introuvable."}, status=status.HTTP_400_BAD_REQUEST)
        elif nouvelle_crise:
            crisis_serializer = CrisisSerializer(data=nouvelle_crise)
            crisis_serializer.is_valid(raise_exception=True)
            crise = crisis_serializer.save(
                author=request.user, environment=get_active_environment(request)
            )
        else:
            return Response(
                {"error": "Précisez crise_id (crise existante) ou nouvelle_crise (à créer)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan_team_ids = set(plan.equipes.values_list('id', flat=True))
        plan_point_ids = set(plan.points.values_list('id', flat=True))

        equipes_activees = []
        for entry in (request.data.get('equipes') or []):
            team_id = entry.get('team_id')
            team = Team.objects.filter(pk=team_id, id__in=plan_team_ids).first()
            if not team:
                continue
            team.assigned_crises.add(crise)
            themes_ids = entry.get('themes_ids')
            if themes_ids is not None:
                team.themes.set(themes_ids)
            equipes_activees.append(team)

        points_actives = []
        for point_id in (request.data.get('points') or []):
            point = PointOperationnel.objects.filter(pk=point_id, id__in=plan_point_ids).first()
            if not point:
                continue
            point.crise = crise
            point.save(update_fields=['crise'])
            points_actives.append(point)

        audit_log(
            request=request,
            action_code="ACTIVATION",
            objet_type="Plan",
            objet_id=plan.id,
            crise=crise,
            commentaire=(
                f"Activation du plan {plan.nom} sur la crise {crise.name} "
                f"({len(equipes_activees)} équipe(s), {len(points_actives)} point(s))"
            ),
        )

        return Response({
            "crise": CrisisSerializer(crise).data,
            "equipes_activees": [str(t.id) for t in equipes_activees],
            "points_actives": [str(p.id) for p in points_actives],
        })


class TeamViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    # TeamSerializer déréférence aussi institution/institution_delegataire/regulateur (FK) et
    # themes/competences/assigned_informations (M2M) en plus de ce qui était déjà prefetch —
    # 77 requêtes mesurées pour 13 équipes DEMO avant cet ajout.
    queryset           = Team.objects.prefetch_related(
        'members',
        Prefetch('assigned_offers', queryset=Offer.objects.select_related('offer_type')),
        'assigned_crises', 'assigned_requests', 'sous_equipes',
        'themes', 'competences', 'assigned_informations',
    ).select_related('leader', 'equipe_parente', 'institution', 'institution_delegataire', 'regulateur').all()
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
            'definir_delegation', 'retirer_delegation', 'creer_dossier',
            'lier_point', 'delier_point',
            'rattacher_equipe', 'detacher_equipe',
            'definir_statut_ressource', 'reactiver', 'vue_mairie', 'institutions_liees',
        ):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == 'reactiver':
            return qs
        qs = _filter_actif(self.request, qs)
        if self.action == 'list':
            # retrieve reste ouvert (voir get_permissions ci-dessus : un bénévole doit pouvoir
            # consulter SA propre équipe même hors de sa zone) — seule la liste est réduite à
            # la zone de compétence de l'appelant, généralisant le filtre déjà appliqué par
            # vue_mairie (qui ne couvrait que le niveau commune) à tous les niveaux.
            qs = filter_queryset_to_viewer_zone(
                self.request, qs,
                resolver=lambda niveau, code: Q(**{
                    f"institution__{SECTEUR_CHAMP_PAR_NIVEAU[niveau]}": code
                }),
            )
        return qs

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def reactiver(self, request, pk=None):
        """Réactive une équipe désactivée (voir perform_destroy)."""
        team = self.get_object()
        team.actif = True
        team.save(update_fields=['actif'])
        audit_log(
            request=request,
            action_code="REACTIVATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Réactivation équipe : {team.name}",
        )
        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor])
    def vue_mairie(self, request):
        """Équipes de l'institution de l'utilisateur appelant (typiquement une mairie) —
        interprété comme "mes équipes", pas la notion plus large de zone d'intervention
        couvrant cette commune (communes/departements/zone_precise, hors périmètre ici)."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code
        queryset = self.get_queryset().filter(institution__commune_code=commune_code)
        return Response(self.get_serializer(queryset, many=True).data)

    def perform_destroy(self, instance):
        instance.actif = False
        instance.save(update_fields=['actif'])
        audit_log(
            request=self.request,
            action_code="DESACTIVATION",
            objet_type="Team",
            objet_id=instance.id,
            commentaire=f"Désactivation équipe : {instance.name}",
        )

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
        # Un PATCH générique n'était jusqu'ici scopé par AUCUNE vérification d'appartenance :
        # tout acteur institutionnel de la plateforme (n'importe quelle institution) pouvait
        # modifier N'IMPORTE QUELLE équipe tierce (membres, chef, régulateur, couleur...) tant
        # qu'il ne touchait pas le champ `institution` lui-même (seul champ déjà gardé, voir
        # plus bas). Une équipe encore sans institution (cas normal, voir perform_create) reste
        # ouverte à tout acteur institutionnel, comme avant ce correctif.
        instance = serializer.instance
        if instance.institution_id and not _appartient_a_equipe(self.request, instance):
            raise PermissionDenied(
                "Vous ne pouvez modifier que les équipes de votre institution (ou de l'institution déléguée)."
            )

        # Changer l'institution responsable est une décision structurante : réservée à
        # l'institution ACTUELLE de l'équipe (jamais à la déléguée, ni à une institution tierce)
        # — avant ce correctif, n'importe quel acteur institutionnel pouvait réaffecter
        # n'importe quelle équipe via un PATCH générique, sans contrôle ni trace. Une équipe
        # SANS institution actuelle (cas normal, voir perform_create — c'est même le cas de
        # toutes les équipes DEMO créées jusqu'ici) est un cas à part : `_appartient_a_institution`
        # ne peut par construction jamais être vrai pour `None` (aucun ContactInstitution n'a
        # institution=NULL), ce qui bloquerait DÉFINITIVEMENT toute première affectation — donc
        # tout acteur institutionnel peut poser l'institution d'une équipe encore orpheline,
        # cohérent avec le paragraphe ci-dessus (déjà ouverte à tout acteur institutionnel tant
        # qu'elle n'a pas d'institution).
        previous_institution = instance.institution
        new_institution = serializer.validated_data.get('institution', previous_institution)
        institution_changed = new_institution != previous_institution
        if (
            institution_changed
            and previous_institution is not None
            and not _appartient_a_institution(self.request, previous_institution)
        ):
            raise PermissionDenied(
                "Seule l'institution responsable actuelle peut changer l'institution de l'équipe."
            )

        # Un membre ajouté qui appartient DÉJÀ à une institution tierce (via ContactInstitution)
        # doit que celle-ci soit "autorisée" pour cette équipe : la sienne, sa déléguée, ou une
        # institution co-impliquée avec elle sur une même crise (voir _institutions_liees/
        # institutions_liees) — jusqu'ici seul le frontend restreignait le sélecteur de
        # candidats, rien ne l'empêchait côté serveur (member_ids n'était pas validé). Un membre
        # SANS AUCUNE institution (bénévole ordinaire, cas normal — la plupart des membres
        # d'équipe, ex: l'auteur d'une offre rattaché automatiquement depuis ReportingComponent)
        # reste toujours ajoutable : seule l'affiliation à une institution tierce est bloquée.
        # Un admin plateforme n'est pas concerné par cette limite.
        previous_member_ids = set(instance.members.values_list('id', flat=True))
        if 'members' in serializer.validated_data and instance.institution_id and get_effective_role(self.request) != UserRole.ADMINISTRATOR:
            added_ids = {u.id for u in serializer.validated_data['members']} - previous_member_ids
            if added_ids:
                allowed_institution_ids = {instance.institution_id}
                if instance.institution_delegataire_id:
                    allowed_institution_ids.add(instance.institution_delegataire_id)
                allowed_institution_ids.update(
                    _institutions_liees(instance.institution).values_list('id', flat=True)
                )
                disallowed_ids = set(
                    ContactInstitution.objects.filter(utilisateur_id__in=added_ids, actif=True)
                    .exclude(institution_id__in=allowed_institution_ids)
                    .values_list('utilisateur_id', flat=True)
                )
                if disallowed_ids:
                    raise ValidationError({
                        "member_ids": "Certains membres ajoutés appartiennent à une institution tierce "
                        "non autorisée pour cette équipe (ni la sienne, ni sa déléguée, ni une "
                        "institution co-impliquée sur une même crise)."
                    })

        # Ne notifier que les membres réellement NOUVEAUX (jamais ceux déjà présents avant
        # cette modification, pour ne pas ré-envoyer le mail à chaque édition de l'équipe qui
        # ne touche pas member_ids, ex: changement de couleur ou de zone).
        team = serializer.save()

        if institution_changed:
            audit_log(
                request=self.request,
                action_code="MODIFICATION",
                objet_type="Team",
                objet_id=team.id,
                commentaire=(
                    f"Institution responsable — "
                    f"{previous_institution.nom if previous_institution else 'aucune'} → "
                    f"{new_institution.nom if new_institution else 'aucune'}"
                ),
            )

        current_member_ids = set(team.members.values_list('id', flat=True))
        new_members = team.members.filter(id__in=current_member_ids - previous_member_ids)
        for membre in new_members:
            _notify_new_team_member(team, membre, self.request)

        # Journalise l'ajout/retrait de membres — jusqu'ici la seule action de TeamViewSet non
        # tracée dans la main courante (voir AuditLogViewSet, onglet Historique de l'équipe).
        added = current_member_ids - previous_member_ids
        removed = previous_member_ids - current_member_ids
        if added or removed:
            noms = lambda ids: ", ".join(
                (f"{u.first_name} {u.last_name}".strip() or u.username)
                for u in User.objects.filter(id__in=ids)
            )
            parts = []
            if added:
                parts.append(f"ajouté(s) : {noms(added)}")
            if removed:
                parts.append(f"retiré(s) : {noms(removed)}")
            audit_log(
                request=self.request,
                action_code="MODIFICATION",
                objet_type="Team",
                objet_id=team.id,
                commentaire=f"Membres — {' / '.join(parts)}",
            )

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

    @action(detail=True, methods=['get'], url_path='institutions-liees')
    def institutions_liees(self, request, pk=None):
        """Institutions "déjà liées" à celle de cette équipe (voir _institutions_liees) : sa
        délégataire, et toute institution co-impliquée avec elle sur une même crise — le
        périmètre dans lequel le frontend va chercher des candidats à ajouter comme membre
        externe (voir teams.component.ts, loadCandidateMembers). Réservé aux gestionnaires de
        cette équipe : ne pas révéler ce rattachement à un tiers sans lien avec elle."""
        team = self.get_object()
        if team.institution_id and not _appartient_a_equipe(request, team) and get_effective_role(request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied("Réservé aux gestionnaires de cette équipe.")
        if not team.institution_id:
            return Response([])
        institutions = list(_institutions_liees(team.institution))
        if team.institution_delegataire_id and team.institution_delegataire not in institutions:
            institutions.append(team.institution_delegataire)
        return Response([{"id": str(i.id), "nom": i.nom} for i in institutions])

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

        # Une mairie ne doit pouvoir inviter que dans SES propres équipes (ou celles qui lui
        # sont déléguées), pas dans celles d'une institution tierce — un admin plateforme
        # n'est pas concerné par cette limite.
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez inviter des membres que pour les équipes de votre institution (ou de l'institution déléguée)."},
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

        # Rattache le nouveau membre à l'institution de l'acteur qui invite (responsable ou
        # déléguée) plutôt qu'à team.institution en dur — un référent de l'institution
        # délégataire invite dans SA propre institution, pas dans celle du responsable qu'il ne
        # représente pas.
        target_institution = team.institution
        if team.institution_delegataire_id and _appartient_a_institution(request, team.institution_delegataire):
            target_institution = team.institution_delegataire

        user = User.objects.filter(email__iexact=email).first()
        invited = False
        if user is None:
            user = User.objects.create_user(
                username=email, email=email,
                first_name=first_name, last_name=last_name, phone_number=phone_number,
                password=None, type=UserRole.LOCAL_AUTHORITY, institution=target_institution,
                enabled=False, is_active=False,
            )
            invited = True

        ContactInstitution.objects.get_or_create(
            institution=target_institution, utilisateur=user,
            defaults={'fonction': role.libelle, 'actif': True},
        )
        AffectationRoleOperationnel.objects.get_or_create(
            utilisateur=user, institution=target_institution, role=role, competence=None,
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
        """Définit (ou remplace) la mission courante de l'équipe, en texte libre et rattachée
        optionnellement à une crise — une équipe n'a qu'une seule mission active à la fois ; la
        redéfinir n'efface pas l'historique (voir AuditLog), elle change simplement ce sur quoi
        portent les prochaines ressources affectées."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez définir la mission que pour les équipes de votre institution (ou de l'institution déléguée)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        titre = (request.data.get('titre') or '').strip()
        if not titre:
            return Response({"error": "Le titre de la mission est obligatoire."}, status=status.HTTP_400_BAD_REQUEST)

        crise = None
        crise_id = request.data.get('crise_id')
        if crise_id:
            try:
                crise = Crisis.objects.get(id=crise_id)
            except (Crisis.DoesNotExist, ValueError, TypeError):
                return Response({"error": "Crise introuvable."}, status=status.HTTP_400_BAD_REQUEST)
            validate_crisis_open(crise, field_name="crise_id")

        mission = Mission.objects.create(titre=titre, crise=crise, environment=get_active_environment(request))
        mission.equipes.add(team)
        team.mission_active = mission
        team.save(update_fields=['mission_active'])

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=(
                f"Mission de l'équipe définie : « {mission.titre} »"
                + (f" (crise : {crise.name})" if crise else "")
            ),
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='definir-delegation')
    def definir_delegation(self, request, pk=None):
        """Délègue l'équipe à une institution/association qui la gère au quotidien pour le
        compte de l'institution responsable — réservé à l'institution responsable elle-même
        (déléguer plus loin reste sa décision, jamais celle de la déléguée en place)."""
        team = self.get_object()
        if not _appartient_a_institution(request, team.institution):
            return Response(
                {"error": "Seule l'institution responsable de l'équipe peut la déléguer."},
                status=status.HTTP_403_FORBIDDEN,
            )

        institution_id = request.data.get('institution_id')
        try:
            institution = Institution.objects.get(id=institution_id)
        except (Institution.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Institution introuvable."}, status=status.HTTP_400_BAD_REQUEST)
        if institution.id == team.institution_id:
            return Response(
                {"error": "L'institution délégataire doit être différente de l'institution responsable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        commentaire = (request.data.get('commentaire') or '').strip()

        TeamDelegation.objects.filter(team=team, active=True).update(
            active=False, date_fin=timezone.now()
        )
        TeamDelegation.objects.create(
            team=team, institution=institution, commentaire=commentaire,
            environment=get_active_environment(request),
        )
        team.institution_delegataire = institution
        team.save(update_fields=['institution_delegataire'])

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Équipe déléguée à {institution.nom}",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='retirer-delegation')
    def retirer_delegation(self, request, pk=None):
        """Met fin à la délégation en cours de l'équipe — réservé à l'institution responsable."""
        team = self.get_object()
        if not _appartient_a_institution(request, team.institution):
            return Response(
                {"error": "Seule l'institution responsable de l'équipe peut retirer sa délégation."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not team.institution_delegataire_id:
            return Response({"error": "Cette équipe n'est pas déléguée."}, status=status.HTTP_400_BAD_REQUEST)

        ancienne = team.institution_delegataire
        TeamDelegation.objects.filter(team=team, active=True).update(
            active=False, date_fin=timezone.now()
        )
        team.institution_delegataire = None
        team.save(update_fields=['institution_delegataire'])

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Délégation à {ancienne.nom} retirée",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='assigner-ressource')
    def assigner_ressource(self, request, pk=None):
        """Ajoute une offre (bénévole seul, bénévole+matériel, ou matériel seul) comme
        ressource de l'équipe, rattachée à sa mission active — voir Team.mission_active. Ajoute
        aussi l'auteur de l'offre comme membre de l'équipe, comme le faisait déjà l'ancien
        mécanisme de "missions" assignées."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez affecter des ressources qu'aux équipes de votre institution (ou de l'institution déléguée)."},
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
        # N'ajoute l'auteur comme membre que si sa présence physique n'est pas explicitement
        # exclue (ex: un simple prêteur de chambre) — None (offres antérieures à ce champ)
        # garde l'ancien comportement, seul False l'exclut désormais.
        if offer.author_id and offer.presence_physique is not False:
            team.members.add(offer.author_id)

        # Un engagement neuf à chaque affectation — jamais partagé entre deux affectations
        # successives, comme offer.mission (une réaffectation ailleurs repart de zéro).
        EngagementRessource.objects.filter(offer=offer).delete()
        engagement = EngagementRessource.objects.create(
            offer=offer, team=team, token_confirmation=secrets.token_urlsafe(32),
            environment=get_active_environment(request),
        )
        send_engagement_confirmation_email(request, engagement)

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
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez retirer des ressources que pour les équipes de votre institution (ou de l'institution déléguée)."},
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
        EngagementRessource.objects.filter(offer=offer, team=team).delete()

        audit_log(
            request=request,
            action_code="SUPPRESSION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Ressource retirée : « {offer.title} »",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='definir-statut-ressource')
    def definir_statut_ressource(self, request, pk=None):
        """Fait avancer manuellement le statut d'engagement d'une ressource assignée (en
        attente / confirmé / en transit / arrivé / décliné) — sans contrainte de séquence,
        contrairement au canal public (EngagementRessourcePublicView) : l'équipe peut sauter
        directement à "arrivé" si elle l'apprend par un autre biais."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez modifier le statut des ressources que pour les équipes de votre institution (ou de l'institution déléguée)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        offer_id = request.data.get('offer_id')
        try:
            offer = Offer.objects.get(id=offer_id)
        except (Offer.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Offre introuvable."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            engagement = offer.engagement
        except EngagementRessource.DoesNotExist:
            return Response({"error": "Cette offre n'a pas d'engagement à suivre."}, status=status.HTTP_400_BAD_REQUEST)

        statut = request.data.get('statut')
        if statut not in StatutEngagementRessource.values:
            return Response({"error": "Statut invalide."}, status=status.HTTP_400_BAD_REQUEST)

        engagement.statut = statut
        now = timezone.now()
        if statut == StatutEngagementRessource.CONFIRME and not engagement.date_confirmation:
            engagement.date_confirmation = now
        elif statut == StatutEngagementRessource.EN_TRANSIT and not engagement.date_transit:
            engagement.date_transit = now
        elif statut == StatutEngagementRessource.ARRIVE and not engagement.date_arrivee:
            engagement.date_arrivee = now
        engagement.save()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Ressource « {offer.title} » — statut : {engagement.get_statut_display()}",
        )

        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='creer-dossier')
    def creer_dossier(self, request, pk=None):
        """Crée un dossier directement pour l'équipe, sans demande/signalement d'origine — pour
        une mission générale (garde du feu, surveillance d'un site...). Peuple les participants
        et l'historique comme les dossiers créés par affectation d'une demande (voir
        populate_dossier_participants_and_notify), pour que Suivi/commentaires/photos
        fonctionnent identiquement."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez créer un dossier que pour les équipes de votre institution (ou de l'institution déléguée)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        titre = (request.data.get('titre') or '').strip()
        description = (request.data.get('description') or '').strip()
        if not titre or not description:
            return Response(
                {"error": "Le titre et la description du dossier sont obligatoires."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        crise_id = request.data.get('crise_id')
        try:
            crise = Crisis.objects.get(id=crise_id)
        except (Crisis.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Crise introuvable."}, status=status.HTTP_400_BAD_REQUEST)
        validate_crisis_open(crise, field_name="crise_id")

        priorite = request.data.get('priorite') or Dossier.Priorite.NORMALE
        if priorite not in Dossier.Priorite.values:
            return Response({"error": "Priorité invalide."}, status=status.HTTP_400_BAD_REQUEST)

        dossier = Dossier.objects.create(
            numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
            crise=crise,
            equipe=team,
            mission=team.mission_active,
            titre=titre,
            description=description,
            priorite=priorite,
            statut=Dossier.Statut.AFFECTE,
            environment=get_active_environment(request),
        )
        populate_dossier_participants_and_notify(dossier, equipe=team)
        DossierHistorique.objects.create(
            dossier=dossier, auteur=request.user, evenement="Création",
            commentaire=f"Dossier créé directement pour la mission de l'équipe {team.name}",
            environment=dossier.environment,
        )

        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="Dossier",
            objet_id=dossier.id,
            commentaire=f"Création dossier (sans demande) : {dossier}",
        )

        return Response(DossierSerializer(dossier, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='lier-point')
    def lier_point(self, request, pk=None):
        """Rattache un point opérationnel existant (regroupement des moyens, carburant...) à
        l'équipe, pour se regrouper/se restaurer/faire le plein avant ou pendant une mission —
        voir PointOperationnel.equipe. Réservé aux points pas déjà rattachés à une AUTRE
        équipe : reprendre le point de quelqu'un d'autre depuis ce raccourci serait surprenant,
        la réaffectation manuelle reste possible depuis la fiche du point elle-même."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez lier un point qu'aux équipes de votre institution (ou de l'institution déléguée)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        point_id = request.data.get('point_id')
        try:
            point = PointOperationnel.objects.get(id=point_id)
        except (PointOperationnel.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Point introuvable."}, status=status.HTTP_400_BAD_REQUEST)
        if point.equipe_id and point.equipe_id != team.id:
            return Response(
                {"error": "Ce point est déjà rattaché à une autre équipe."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        point.equipe = team
        point.save(update_fields=['equipe'])

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Point lié : « {point.nom} » ({point.type.libelle})",
        )

        return Response(PointOperationnelSerializer(point, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='delier-point')
    def delier_point(self, request, pk=None):
        """Détache un point de l'équipe — ne touche jamais un point déjà repris par une autre
        équipe entre-temps."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez délier un point que pour les équipes de votre institution (ou de l'institution déléguée)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        point_id = request.data.get('point_id')
        try:
            point = PointOperationnel.objects.get(id=point_id)
        except (PointOperationnel.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Point introuvable."}, status=status.HTTP_400_BAD_REQUEST)
        if point.equipe_id != team.id:
            return Response({"error": "Ce point n'est pas rattaché à cette équipe."}, status=status.HTTP_400_BAD_REQUEST)

        point.equipe = None
        point.save(update_fields=['equipe'])

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Point délié : « {point.nom} »",
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='rattacher-equipe')
    def rattacher_equipe(self, request, pk=None):
        """Rattache une autre équipe à celle-ci comme une ressource (ex: l'équipe d'une
        entreprise avec ses camions, rattachée à une équipe de secteur) — l'équipe qui accueille
        agit sur son propre endpoint, même patron qu'assigner_ressource/lier_point. Le
        rattachement n'affecte jamais l'autonomie opérationnelle de la sous-équipe (institution,
        mission, points, dossiers restent les siens propres) ; aucune contrainte d'institution
        commune : une équipe hors de toute institution mairie doit pouvoir rejoindre une équipe
        de secteur qui, elle, en a une."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez rattacher une équipe qu'aux équipes de votre institution (ou de l'institution déléguée)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        equipe_id = request.data.get('equipe_id')
        try:
            sous_equipe = Team.objects.get(id=equipe_id)
        except (Team.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Équipe introuvable."}, status=status.HTTP_400_BAD_REQUEST)
        if sous_equipe.id == team.id:
            return Response({"error": "Une équipe ne peut pas se rattacher à elle-même."}, status=status.HTTP_400_BAD_REQUEST)
        if sous_equipe.equipe_parente_id and sous_equipe.equipe_parente_id != team.id:
            return Response(
                {"error": "Cette équipe est déjà rattachée à une autre équipe : détachez-la d'abord."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Garde anti-cycle : si l'équipe à rattacher apparaît dans la lignée d'ancêtres de
        # `team`, l'attacher créerait une boucle (ex: A parente de B, on tente B parente de A).
        ancetre = team
        while ancetre is not None:
            if ancetre.id == sous_equipe.id:
                return Response(
                    {"error": "Impossible : cette équipe est déjà une équipe parente dans cette hiérarchie (créerait une boucle)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ancetre = ancetre.equipe_parente

        sous_equipe.equipe_parente = team
        sous_equipe.save(update_fields=['equipe_parente'])

        for cible, commentaire in (
            (team, f"Équipe rattachée : « {sous_equipe.name} »"),
            (sous_equipe, f"Rattachée à l'équipe : « {team.name} »"),
        ):
            audit_log(
                request=request, action_code="MODIFICATION", objet_type="Team",
                objet_id=cible.id, commentaire=commentaire,
            )

        # `team` vient de self.get_object(), dont le queryset précharge sous_equipes — le cache
        # de prefetch ne voit pas l'ajout qu'on vient de faire, d'où une relecture fraîche
        # avant de sérialiser la réponse.
        team = Team.objects.prefetch_related('sous_equipes').get(id=team.id)
        return Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], url_path='detacher-equipe')
    def detacher_equipe(self, request, pk=None):
        """Détache une sous-équipe — ne touche jamais une équipe déjà repartie sous une autre
        équipe entre-temps."""
        team = self.get_object()
        if not _appartient_a_equipe(request, team):
            return Response(
                {"error": "Vous ne pouvez détacher une équipe que pour les équipes de votre institution (ou de l'institution déléguée)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        equipe_id = request.data.get('equipe_id')
        try:
            sous_equipe = Team.objects.get(id=equipe_id)
        except (Team.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Équipe introuvable."}, status=status.HTTP_400_BAD_REQUEST)
        if sous_equipe.equipe_parente_id != team.id:
            return Response({"error": "Cette équipe n'est pas rattachée à cette équipe."}, status=status.HTTP_400_BAD_REQUEST)

        sous_equipe.equipe_parente = None
        sous_equipe.save(update_fields=['equipe_parente'])

        for cible, commentaire in (
            (team, f"Équipe détachée : « {sous_equipe.name} »"),
            (sous_equipe, f"Détachée de l'équipe : « {team.name} »"),
        ):
            audit_log(
                request=request, action_code="MODIFICATION", objet_type="Team",
                objet_id=cible.id, commentaire=commentaire,
            )

        team = Team.objects.prefetch_related('sous_equipes').get(id=team.id)
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
    # OfferSerializer déréférence author/crisis/mission/materiel_catalogue/offer_type/engagement
    # (FK ou OneToOne inverse) et competences (M2M) pour chaque offre — sans select_related/
    # prefetch_related, ça vaut ~5 requêtes SQL par offre (1313 requêtes mesurées pour 262
    # offres DEMO). Purement une optimisation de requête, aucun changement de comportement.
    queryset = Offer.objects.select_related(
        'author', 'crisis', 'mission', 'materiel_catalogue', 'offer_type', 'engagement',
    ).prefetch_related('competences')
    serializer_class = OfferSerializer
    permission_classes = [AllowAny]
    filterset_class = OfferSearchFilter

    def get_permissions(self):
        # Voir le commentaire équivalent sur RequestViewSet.get_permissions : même correctif
        # (update/partial_update/destroy n'avaient aucune restriction avant ce changement).
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwnerOrInstitutional()]
        if self.action in ('assign_dossier', 'bulk_create_team', 'transformer', 'reactiver', 'vue_mairie', 'vue_secteur'):
            return [IsInstitutionalActor()]
        if self.action == 'affecter_stock':
            # Pas IsInstitutionalActor : un bénévole simple membre de l'équipe du point (voir
            # _peut_gerer_stock_point) peut légitimement gérer son stock, comme pour
            # MaterielPointViewSet — la vérification fine se fait dans l'action elle-même.
            return [permissions.IsAuthenticated()]
        if self.action == 'messages':
            return [IsInstitutionalActor()]
        return [AllowAny()]

    def get_queryset(self):
        qs = annotate_distance_from_crisis(
            super().get_queryset().select_related('crisis', 'author')
        )
        if self.action == 'reactiver':
            return qs
        return _filter_actif(self.request, qs)

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def reactiver(self, request, pk=None):
        """Réactive une offre désactivée (voir perform_destroy)."""
        offre = self.get_object()
        offre.actif = True
        offre.save(update_fields=['actif'])
        audit_log(
            request=request,
            action_code="REACTIVATION",
            objet_type="Offer",
            objet_id=offre.id,
            crise=offre.crisis,
            commentaire=f"Réactivation offre : {offre.title}",
        )
        return Response(OfferSerializer(offre, context={'request': request}).data)

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        """Fil de discussion avec le propriétaire de cette offre — voir OfferMessage. GET liste
        (tout acteur institutionnel), POST envoie un message côté équipe : génère
        reponse_token si besoin et notifie le propriétaire par email avec le lien public de
        réponse/édition (voir OfferReponsePublicView)."""
        offre = self.get_object()
        if request.method == "GET":
            return Response(OfferMessageSerializer(offre.messages.all(), many=True).data)

        contenu = (request.data.get('contenu') or '').strip()
        if not contenu:
            return Response({"error": "Le message ne peut pas être vide."}, status=status.HTTP_400_BAD_REQUEST)

        if not offre.reponse_token:
            offre.reponse_token = secrets.token_urlsafe(32)
            offre.save(update_fields=['reponse_token'])

        message = OfferMessage.objects.create(
            offer=offre, auteur_equipe=request.user, contenu=contenu, environment=offre.environment,
        )

        reponse_url = f"{settings.SERVER_URL.rstrip('/')}/repondre-offre/{offre.reponse_token}/"
        try:
            send_mail_env_aware(
                request,
                subject=f"Nouveau message à propos de votre offre « {offre.title} »",
                message=(
                    f"Bonjour {offre.first_name_offer},\n\n"
                    "Vous avez reçu un nouveau message à propos de votre offre :\n\n"
                    f"« {contenu} »\n\n"
                    f"Vous pouvez y répondre ou modifier votre offre ici :\n{reponse_url}\n\n"
                    "Cordialement,\nL'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[offre.email_offer],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Erreur envoi email message offre : {e}")

        return Response(OfferMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor],
            pagination_class=OptionalPageNumberPagination)
    def vue_mairie(self, request):
        """Offres de la commune de l'institution de l'utilisateur appelant. Filtre sur
        Offer.commune_code (résolu une seule fois à la création, voir perform_create) — plus
        de reverse-géocodage par offre à chaque appel (l'ancienne version rappelait l'API
        externe pour CHAQUE offre de la queryset à CHAQUE requête, non borné par le volume)."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code

        offres = self.get_queryset().filter(commune_code=commune_code).order_by("-created_at")
        page = self.paginate_queryset(offres)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(offres, many=True).data)

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor],
            pagination_class=OptionalPageNumberPagination)
    def vue_secteur(self, request):
        """Offres du secteur de l'institution de l'utilisateur appelant, à l'échelle adaptée à
        son type : commune (mairie), EPCI (communauté de communes), département (SDIS,
        gendarmerie, préfecture...), région (conseil régional), ou national (aucun filtre
        géographique) — voir _institution_secteur_or_400. Un `secteur_override` posé sur
        l'institution (usage test) prend le pas sur le niveau déduit du type. Toujours soit
        aucun filtre (national), soit un simple filtre sur colonne indexée déjà dénormalisée
        (commune_code/epci_code/departement_code/region_code), jamais de jointure géographique
        en lecture. Pagination recommandée (`?page=1&page_size=`) : un secteur large peut
        compter plusieurs milliers de fiches — typiquement l'annuaire de bénévoles (type
        Bénévolat), voir `?type=`/`?exclude_type=` ci-dessous pour le séparer des offres de
        crise plutôt que de tout charger d'un bloc (voir VueMairieComponent).

        `?echelle=national` force le niveau national quel que soit le secteur propre de
        l'appelant — "Voir toute la France (partiel)" côté frontend : donne à N'IMPORTE QUEL
        acteur institutionnel (même une simple mairie) une vue d'ensemble nationale, toujours
        servie par OfferNationalPartialSerializer (jamais les coordonnées/contact d'une
        institution tierce), jamais le serializer complet même quand le niveau national est
        celui, propre, de l'appelant."""
        secteur = _institution_secteur_or_400(request)
        if isinstance(secteur, Response):
            return secteur
        niveau, code = secteur
        if request.query_params.get('echelle') == 'national':
            niveau = 'national'

        if niveau == "national":
            offres = self.get_queryset().order_by("-created_at")
        else:
            offres = self.get_queryset().filter(**{SECTEUR_CHAMP_PAR_NIVEAU[niveau]: code}).order_by("-created_at")

        type_filter = request.query_params.get('type')
        if type_filter:
            offres = offres.filter(offer_type__type=type_filter)
        exclude_type = request.query_params.get('exclude_type')
        if exclude_type:
            offres = offres.exclude(offer_type__type=exclude_type)

        serializer_class = OfferNationalPartialSerializer if niveau == "national" else self.get_serializer_class()
        page = self.paginate_queryset(offres)
        if page is not None:
            return self.get_paginated_response(serializer_class(page, many=True, context=self.get_serializer_context()).data)
        return Response(serializer_class(offres, many=True, context=self.get_serializer_context()).data)

    def perform_destroy(self, instance):
        instance.actif = False
        instance.save(update_fields=['actif'])
        audit_log(
            request=self.request,
            action_code="DESACTIVATION",
            objet_type="Offer",
            objet_id=instance.id,
            crise=instance.crisis,
            commentaire=f"Désactivation offre : {instance.title}",
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
        # Distinct de deletion_token (voir Offer.reponse_token) : permet au propriétaire de
        # répondre à un message et d'éditer son offre via un lien reçu par email, sans lui
        # donner accès à la suppression.
        reponse_token = secrets.token_urlsafe(32)

        # Si user authentifié, il est autheur
        environment = get_active_environment(self.request)
        if self.request.user.is_authenticated:
            offre = serializer.save(author=self.request.user, deletion_token=deletion_token, reponse_token=reponse_token, environment=environment)
        else:
            # Sinon il est none
            offre = serializer.save(author=None, deletion_token=deletion_token, reponse_token=reponse_token, environment=environment)

        # Résout commune_code/epci_code/departement_code/region_code une seule fois ici plutôt
        # qu'à chaque consultation (voir vue_secteur, et le commentaire sur Offer.commune_code) :
        # le seul appel externe payé sur cette donnée est celui-ci, à la création.
        if offre.location:
            commune_code = commune_code_from_point(offre.location)
            if commune_code:
                secteur = commune_secteur_codes(commune_code)
                offre.commune_code = commune_code
                offre.epci_code = secteur["epci_code"]
                offre.departement_code = secteur["departement_code"]
                offre.region_code = secteur["region_code"]
                offre.save(update_fields=["commune_code", "epci_code", "departement_code", "region_code"])

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
        # Même garde que assigner_ressource : n'ajoute pas comme membre un offreur dont la
        # présence physique est explicitement exclue.
        members = {o.author for o in offres if o.author_id and o.presence_physique is not False}
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

    @action(detail=True, methods=["post"], url_path="affecter-stock")
    def affecter_stock(self, request, pk=None):
        """Ajoute cette offre de matériel au stock d'un point (centre d'accueil ou de
        regroupement des moyens) : crée un apport individuel (ContributionMateriel) rattaché à
        l'offre, sur la ligne de stock (point, item) — créée si besoin. Ne modifie jamais le
        `niveau_stock` qualitatif de la ligne : c'est à l'équipe du point de l'ajuster
        ensuite en connaissance de cause (voir MaterielPointViewSet)."""
        offer = self.get_object()
        if offer.materiel_type is None:
            return Response({"error": "Cette offre n'est pas de type Matériel."}, status=status.HTTP_400_BAD_REQUEST)

        point_id = request.data.get("point_id")
        point = get_object_or_404(PointOperationnel, pk=point_id)
        if not _peut_gerer_stock_point(request, point):
            return Response(
                {"error": "Seul le responsable, un membre de l'équipe du point, ou un administrateur peut recevoir du matériel sur ce point."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            validate_crisis_open(point.crise, field_name="crise")
        except ValidationError as exc:
            return Response({"error": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

        # Résout l'item catalogue : celui explicitement précisé pour un matériel "Autre", sinon
        # l'entrée du catalogue partagé correspondant au libellé du type fixe choisi (même
        # dédoublonnage insensible à la casse que TagLikeViewSetMixin, pour que "Cuve" du menu
        # rejoigne le même catalogue qu'une "Cuve" tapée en Autre).
        if offer.materiel_type == TypeMateriel.AUTRE and offer.materiel_catalogue:
            item = offer.materiel_catalogue
        else:
            libelle = offer.get_materiel_type_display()
            item = MaterielCatalogue.objects.filter(nom__iexact=libelle).first()
            if not item:
                item = MaterielCatalogue.objects.create(nom=libelle)

        materiel_point, _ = MaterielPoint.objects.get_or_create(
            point=point, item=item, defaults={"environment": get_active_environment(request)},
        )

        quantite = request.data.get("quantite") or offer.quantite or 1
        unite = request.data.get("unite") or offer.unite or "unité"
        fournisseur_nom = f"{offer.first_name_offer} {offer.last_name_offer}".strip()

        contribution = ContributionMateriel.objects.create(
            materiel_point=materiel_point,
            offre=offer,
            fournisseur_nom=fournisseur_nom,
            quantite=quantite,
            unite=unite,
            responsable=request.user,
            environment=get_active_environment(request),
        )

        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="MaterielPoint",
            objet_id=materiel_point.id,
            crise=point.crise,
            commentaire=f"Apport reçu : {item.nom} ({quantite} {unite}) fourni par {fournisseur_nom or 'anonyme'}",
        )

        return Response(MaterielPointSerializer(materiel_point).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        offer = self.get_object()
        if not offer.photo or not user_can_view_photo(
            request, offer, teams_field='assigned_teams'
        ):
            return Response(status=403)
        return FileResponse(open(offer.photo.path, "rb"))


class OfferPhotoViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Galerie de photos additionnelles d'une offre d'aide (voir OfferPhoto.__doc__) — même
    patron que RequestPhotoViewSet."""
    queryset = OfferPhoto.objects.all()
    serializer_class = OfferPhotoSerializer
    filterset_fields = ["offer"]

    def get_permissions(self):
        if self.action in ("create", "preview"):
            return [AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        photo = self.get_object()
        if not user_can_view_photo(request, photo.offer, teams_field='assigned_teams'):
            return Response(status=403)
        return FileResponse(open(photo.image.path, "rb"))


class DisponibiliteOffreViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Créneaux de disponibilité (matin/midi/soir/nuit, 8 jours) déclarés avec une offre d'aide."""
    queryset = DisponibiliteOffre.objects.all()
    serializer_class = DisponibiliteOffreSerializer
    filterset_fields = ["offer"]

    def get_permissions(self):
        # list/retrieve/create restent AllowAny : la déclaration de créneaux fait partie du
        # formulaire public "proposer une aide" (Offer.permission_classes est aussi AllowAny en
        # création), y compris pour un bénévole anonyme. update/partial_update/destroy exigeaient
        # avant ce correctif AUCUNE permission du tout — voir IsOfferOwnerOrInstitutional.
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOfferOwnerOrInstitutional()]
        return [AllowAny()]

def _information_zone_resolver(niveau, code):
    """Resolver pour filter_queryset_to_viewer_zone(InformationViewSet) : Information n'a,
    contrairement à Offer/Request, que commune_code (pas epci_code/departement_code/
    region_code dénormalisés) — sans ce resolver, le filtre par défaut de zone_scoping.py
    tentait `.filter(epci_code=...)` sur un champ inexistant et levait une FieldError pour
    toute institution de niveau EPCI/département/région (reproduit en appelant la liste des
    signalements avec un compte SDIS/préfecture). Résout la liste des communes membres du
    secteur via le référentiel Commune (déjà utilisé ailleurs, ex: commune_secteur_codes)
    plutôt que d'improviser une correspondance directe qui n'existe pas sur ce modèle."""
    if niveau == "commune":
        return Q(commune_code=code)
    champ_commune = {"epci": "epci_code", "departement": "departement_code", "region": "region_code"}[niveau]
    communes = Commune.objects.filter(**{champ_commune: code}).values_list("code", flat=True)
    return Q(commune_code__in=communes)


class InformationViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Information.objects.select_related('author', 'crisis')
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
        if self.action in ('vue_mairie', 'bulk_assign_team', 'transformer', 'reactiver'):
            return [IsInstitutionalActor()]
        return [AllowAny()]

    def get_queryset(self):
        qs = annotate_distance_from_crisis(
            super().get_queryset().select_related('crisis', 'author')
        )
        if self.action == 'reactiver':
            return qs
        qs = _filter_actif(self.request, qs)
        # get_effective_role (appelé par effective_role_or_none) suppose un utilisateur
        # authentifié (accès direct à request.user.type) — contrairement à Request/Offer, la
        # liste ici est AllowAny (voir get_permissions), donc bien atteignable anonymement :
        # sans ce garde, un visiteur anonyme provoque une 500 (AttributeError sur AnonymousUser).
        if (
            self.action == 'list'
            and self.request.user.is_authenticated
            and effective_role_or_none(self.request) in INSTITUTIONAL_TYPES
        ):
            # Hors zone = exclusion totale (pas de résumé, contrairement à RequestViewSet.
            # vue_secteur) : un acteur institutionnel ne voit plus, sur la liste par défaut,
            # les signalements hors de sa zone de compétence — l'accès public (anonyme/simple
            # utilisateur) à l'existence d'un signalement (titre/type/date, jamais la PII, déjà
            # masquée par InformationSerializer._location_visible) reste inchangé.
            qs = filter_queryset_to_viewer_zone(self.request, qs, resolver=_information_zone_resolver)
        return qs

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def reactiver(self, request, pk=None):
        """Réactive un signalement désactivé (voir perform_destroy)."""
        signalement = self.get_object()
        signalement.actif = True
        signalement.save(update_fields=['actif'])
        audit_log(
            request=request,
            action_code="REACTIVATION",
            objet_type="Information",
            objet_id=signalement.id,
            crise=signalement.crisis,
            commentaire=f"Réactivation signalement : {signalement.title}",
        )
        return Response(InformationSerializer(signalement, context={'request': request}).data)

    def perform_destroy(self, instance):
        instance.actif = False
        instance.save(update_fields=['actif'])
        audit_log(
            request=self.request,
            action_code="DESACTIVATION",
            objet_type="Information",
            objet_id=instance.id,
            crise=instance.crisis,
            commentaire=f"Désactivation signalement : {instance.title}",
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

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor],
            pagination_class=OptionalPageNumberPagination)
    def vue_mairie(self, request):
        """Signalements de la commune de l'institution de l'utilisateur appelant — même
        contrat que RequestViewSet.vue_mairie. Pagination opt-in (`?page=1&page_size=`) pour
        permettre à la Vue Ma Collectivité de plafonner le volume chargé, comme pour
        Offer/Request.vue_secteur."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code
        queryset = self.get_queryset().filter(commune_code=commune_code).order_by("-created_at")
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
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

    def get_permissions(self):
        # AllowAny restreint à list/retrieve (voir commentaire de classe) : create/update/
        # destroy doivent rester réservés aux comptes authentifiés, contrairement à avant où
        # permission_classes=[AllowAny] s'appliquait à toute la classe et permettait à
        # n'importe qui, sans compte, de créer/modifier/supprimer un type de demande.
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        return RequestType.objects.filter(actif=True)

    def perform_destroy(self, instance):
        # Request.request_type est en PROTECT : supprimer un type encore utilisé lève
        # ProtectedError (500 non géré) au lieu d'un message exploitable.
        nb = instance.requests.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer le type « {instance.type} » : "
                f"{nb} demande(s) l'utilisent encore. Désactivez-le plutôt (champ « actif »)."
            )
        instance.delete()

class OfferTypeViewSet(viewsets.ModelViewSet):
    queryset = OfferType.objects.all()
    serializer_class = OfferTypeSerializer

    def get_permissions(self):
        # AllowAny restreint à list/retrieve, même correctif que RequestTypeViewSet ci-dessus.
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        return OfferType.objects.filter(actif=True)

    def perform_destroy(self, instance):
        # Offer.offer_type est en PROTECT : même garde que RequestTypeViewSet ci-dessus.
        nb = instance.offers.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer le type « {instance.type} » : "
                f"{nb} offre(s) l'utilisent encore. Désactivez-le plutôt (champ « actif »)."
            )
        instance.delete()

class InformationTypeViewSet(TagLikeViewSetMixin, viewsets.ModelViewSet):
    # AllowAny : la page de signalement (other-declaration-form) est accessible sans compte,
    # au même titre que les autres formulaires publics (demande/offre/crise) — un passant qui
    # signale un arbre sur la chaussée ne doit pas avoir à se connecter, y compris pour lister
    # les types existants ou en proposer un nouveau.
    queryset = InformationType.objects.all()
    serializer_class = InformationTypeSerializer
    tag_field = "type"

    def get_permissions(self):
        # AllowAny restreint à list/retrieve/create (voir commentaire de classe) : update/
        # destroy doivent rester réservés aux comptes authentifiés, contrairement à avant où
        # permission_classes=[AllowAny] s'appliquait à toute la classe et permettait à
        # n'importe qui, sans compte, de modifier/supprimer un type de signalement.
        if self.action in ('list', 'retrieve', 'create'):
            return [AllowAny()]
        return super().get_permissions()

    def perform_create(self, serializer):
        information_type = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InformationType",
            objet_id=information_type.id,
            commentaire=f"Création type de signalement : {information_type.type}",
        )

    def perform_destroy(self, instance):
        # Information.information_type est en PROTECT : même garde que RequestType/OfferType.
        nb = instance.informations.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer le type « {instance.type} » : "
                f"{nb} signalement(s) l'utilisent encore."
            )
        instance.delete()

# --- VUES POUR LA SUPPRESSION VIA TOKEN ---
from django.views import View
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

class DeleteRequestView(View):
    """Vue pour supprimer une demande via token"""
    def get(self, request, token):
        # Désactive plutôt que supprimer (politique de désactivation, voir RequestViewSet.
        # perform_destroy) : le message affiché reste "supprimée" pour l'expéditeur, la
        # distinction technique est invisible pour lui — purge réelle seulement à la clôture
        # de la crise rattachée.
        demande = get_object_or_404(Request, deletion_token=token)
        titre = demande.title
        demande.actif = False
        demande.save(update_fields=['actif'])
        audit_log(
            request=request, action_code="DESACTIVATION", objet_type="Request",
            objet_id=demande.id, crise=demande.crisis,
            commentaire=f"Désactivation demande (lien email) : {titre}",
        )
        return HttpResponse(f"<h1>Demande supprimée</h1><p>La demande '{titre}' a bien été supprimée.</p>")

class DeleteOfferView(View):
    """Vue pour supprimer une offre via token"""
    def get(self, request, token):
        # Voir le commentaire équivalent sur DeleteRequestView.
        offre = get_object_or_404(Offer, deletion_token=token)
        titre = offre.title
        offre.actif = False
        offre.save(update_fields=['actif'])
        audit_log(
            request=request, action_code="DESACTIVATION", objet_type="Offer",
            objet_id=offre.id, crise=offre.crisis,
            commentaire=f"Désactivation offre (lien email) : {titre}",
        )
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

        # Un "oui" n'engage plus directement le bénévole : il passe par une validation du
        # régulateur avant confirmation définitive (retour terrain — jusqu'ici la réponse du
        # bénévole valait confirmation immédiate et sans arbitrage possible). Un "non" reste en
        # revanche définitif et immédiat, rien à valider dans ce sens.
        affectation.statut = StatutAffectation.EN_VALIDATION if reponse == "oui" else StatutAffectation.DECLINE
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
            message = (
                "Merci ! Votre disponibilité a bien été enregistrée. Elle est en attente de "
                "validation par le régulateur, qui vous confirmera votre créneau."
            )
            _notify_regulateurs_creneau_a_valider(affectation, request)

        return HttpResponse(f"<h1>{message}</h1>")


class EngagementRessourcePublicView(APIView):
    """Page de suivi/confirmation publique d'une ressource affectée à une équipe — jeton
    opaque, pas de compte requis. Contrairement à ConfirmerAffectationBenevoleView (lien à
    sens unique, HTML brut), cette page reste consultable et actionnable à chaque étape avec
    le même lien : GET renvoie l'état courant, POST fait avancer d'une étape (séquence stricte,
    contrairement à TeamViewSet.definir_statut_ressource côté équipe qui peut sauter des
    étapes)."""
    permission_classes = [AllowAny]

    ACTIONS_PAR_STATUT = {
        StatutEngagementRessource.EN_ATTENTE: ["confirmer", "decliner"],
        StatutEngagementRessource.CONFIRME: ["transit"],
        StatutEngagementRessource.EN_TRANSIT: ["arrivee"],
        StatutEngagementRessource.DECLINE: [],
        StatutEngagementRessource.ARRIVE: [],
    }

    def _serialize(self, engagement):
        return {
            "offer_title": engagement.offer.title,
            "team_nom": engagement.team.name,
            "mission_titre": engagement.team.mission_active.titre if engagement.team.mission_active_id else None,
            "statut": engagement.statut,
            "statut_libelle": engagement.get_statut_display(),
            "actions_possibles": self.ACTIONS_PAR_STATUT.get(engagement.statut, []),
        }

    def get(self, request, token):
        engagement = get_object_or_404(EngagementRessource, token_confirmation=token)
        return Response(self._serialize(engagement))

    def post(self, request, token):
        engagement = get_object_or_404(EngagementRessource, token_confirmation=token)
        action_demandee = request.data.get('action')
        if action_demandee not in self.ACTIONS_PAR_STATUT.get(engagement.statut, []):
            return Response(
                {"error": "Cette action n'est plus disponible pour cette étape."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        if action_demandee == "confirmer":
            engagement.statut = StatutEngagementRessource.CONFIRME
            engagement.date_confirmation = now
        elif action_demandee == "decliner":
            engagement.statut = StatutEngagementRessource.DECLINE
        elif action_demandee == "transit":
            engagement.statut = StatutEngagementRessource.EN_TRANSIT
            engagement.date_transit = now
        elif action_demandee == "arrivee":
            engagement.statut = StatutEngagementRessource.ARRIVE
            engagement.date_arrivee = now
        engagement.save()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Team",
            objet_id=engagement.team_id,
            commentaire=f"Ressource « {engagement.offer.title} » — statut (auto-confirmation) : {engagement.get_statut_display()}",
        )

        return Response(self._serialize(engagement))


def _notify_equipes_hebergement(request, offer, titre, message_texte):
    """Notifie (Notification + email) tous les membres des équipes ayant le thème
    "Hébergement" et assignées à la crise de cette offre (Team.themes/Team.assigned_crises) —
    utilisé quand le propriétaire d'une offre répond à un message ou modifie son offre via
    OfferReponsePublicView."""
    if not offer.crisis_id:
        return
    equipes = Team.objects.filter(themes__nom='Hébergement', assigned_crises=offer.crisis_id).distinct()
    destinataires = User.objects.filter(teams__in=equipes).distinct()
    for user in destinataires:
        Notification.objects.create(utilisateur=user, titre=titre, message=message_texte)
        if user.email:
            try:
                send_mail_logged(
                    request, subject=titre, message=message_texte, from_email=None,
                    recipient_list=[user.email], fail_silently=True,
                )
            except Exception as e:
                print(f"Erreur envoi email notification équipe hébergement : {e}")


class OfferReponsePublicView(APIView):
    """Page publique (jeton opaque, pas de compte requis) permettant au propriétaire d'une
    offre de consulter/répondre au fil de messages et d'éditer son offre — voir
    Offer.reponse_token et OfferMessage. Même esprit qu'EngagementRessourcePublicView, mais
    consultable/actionnable librement (pas de séquence stricte d'étapes)."""
    permission_classes = [AllowAny]

    def get(self, request, token):
        offre = get_object_or_404(Offer, reponse_token=token)
        return Response({
            "offer": OfferSerializer(offre, context={'request': request}).data,
            "messages": OfferMessageSerializer(offre.messages.all(), many=True).data,
        })

    def post(self, request, token):
        offre = get_object_or_404(Offer, reponse_token=token)
        contenu = (request.data.get('contenu') or '').strip()
        if not contenu:
            return Response({"error": "Le message ne peut pas être vide."}, status=status.HTTP_400_BAD_REQUEST)
        message = OfferMessage.objects.create(
            offer=offre, auteur_equipe=None, contenu=contenu, environment=offre.environment,
        )
        _notify_equipes_hebergement(
            request,
            offre,
            titre=f"Réponse reçue sur l'offre « {offre.title} »",
            message_texte=f"{offre.first_name_offer} {offre.last_name_offer} a répondu :\n\n« {contenu} »",
        )
        return Response(OfferMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    def patch(self, request, token):
        offre = get_object_or_404(Offer, reponse_token=token)
        serializer = OfferSerializer(offre, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        _notify_equipes_hebergement(
            request,
            offre,
            titre=f"Offre modifiée : « {offre.title} »",
            message_texte=f"{offre.first_name_offer} {offre.last_name_offer} a modifié son offre.",
        )
        return Response(OfferSerializer(offre, context={'request': request}).data)


class DeleteInformationView(View):
    """Vue pour supprimer une information via token"""
    def get(self, request, token):
        # Voir le commentaire équivalent sur DeleteRequestView.
        info = get_object_or_404(Information, deletion_token=token)
        titre = info.title
        info.actif = False
        info.save(update_fields=['actif'])
        audit_log(
            request=request, action_code="DESACTIVATION", objet_type="Information",
            objet_id=info.id, crise=info.crisis,
            commentaire=f"Désactivation signalement (lien email) : {titre}",
        )
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

    def perform_create(self, serializer):
        user = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="User",
            objet_id=user.id,
            commentaire=f"Création de compte : {user.email}",
        )

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

        # La RECHERCHE d'institution (domaine connu, puis annuaire officiel) se fait ici, une
        # fois la possession de la boîte mail prouvée par ce clic — jamais à la simple
        # inscription. Le RATTACHEMENT effectif (ContactInstitution + rôle), lui, n'a plus lieu
        # automatiquement : l'utilisateur le confirme explicitement ensuite (voir
        # UserViewSet.institution_suggestion/confirmer_institution/creer_mon_institution),
        # avec le rôle de son choix plutôt qu'un rôle deviné. Idempotent (find_... ne modifie
        # rien côté utilisateur) : un second clic ne duplique rien.
        if not already_enabled and getattr(user, 'type', None) == UserRole.LOCAL_AUTHORITY:
            matched_institution = find_institution_for_pending_user(user, request)
            audit_log(
                request=request,
                action_code="CONNEXION",
                objet_type="User",
                objet_id=user.id,
                commentaire=f"Activation de compte confirmée par email : {user.email}",
            )
            # Le compte est activé dans tous les cas (la possession de la boîte mail est
            # prouvée). S'il n'a pu être rapproché d'aucune institution automatiquement (ni
            # domaine déjà connu, ni correspondance dans l'annuaire officiel), la personne se
            # verra proposer de créer elle-même son institution (voir creer_mon_institution) —
            # mais contact@ est notifié dans tous les cas, en filet de sécurité si elle
            # n'achève jamais cette étape.
            if matched_institution is None:
                try:
                    send_mail_logged(
                        request,
                        subject="Compte mairie activé sans institution rattachée",
                        message=(
                            f"Bonjour,\n\n"
                            f"Un compte mairie a confirmé son email mais n'a pu être rattaché "
                            f"automatiquement à aucune institution (ni domaine connu, ni "
                            f"correspondance dans l'annuaire officiel).\n\n"
                            f"- Nom : {user.first_name} {user.last_name}\n"
                            f"- Email : {user.email}\n\n"
                            "Un rattachement manuel à l'institution correcte est nécessaire."
                        ),
                        from_email=None,
                        recipient_list=['contact@assista-crise.fr'],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(f"Erreur envoi email rattachement manuel : {e}")

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
    pas, même logique que la localisation précise des demandes/offres).

    Une position n'est capturée qu'à l'occasion d'une autre action (jamais de traçage en tâche
    de fond, voir DernierePositionUtilisateur) : au-delà de POSITION_TTL, elle ne reflète plus
    fiablement où se trouve la personne — on ne l'affiche plus plutôt que de laisser croire
    qu'elle est toujours là."""

    POSITION_TTL = datetime.timedelta(hours=3)

    serializer_class = DernierePositionUtilisateurSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = DernierePositionUtilisateur.objects.filter(
            environment=get_active_environment(self.request),
            utilisateur__teams__isnull=False,
            horodatage__gte=timezone.now() - self.POSITION_TTL,
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

class AuditLogViewSet(EnvironmentScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Lecture seule de la main courante. Deux modes :
    - Fiche précise (?objet_type=&objet_id=) : widget d'historique par objet, ouvert à tout
      acteur institutionnel (Team scopé à sa propre institution, tout le reste réservé à un
      admin) — comportement historique, inchangé.
    - Consultation globale (sans objet_type/objet_id) : la main courante GÉNÉRALE (toutes
      institutions confondues) n'est visible que du super-admin Django (`is_superuser`, même
      choix que pour Institution.secteur_override en PROD) ; un acteur institutionnel non
      super-admin ne voit que les actes de SA PROPRE institution (`request.user.institution`),
      jamais ceux d'une institution tierce — voir _browse_queryset_for_user. Filtrable
      (date_debut/date_fin/action/objet_type/utilisateur/succes), paginée (voir
      OptionalPageNumberPagination — ce mode peut légitimement compter des dizaines de milliers
      de lignes depuis AuditTraceMiddleware). Voir aussi l'action `export` pour un CSV, scopé de
      la même façon."""
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsInstitutionalActor]
    pagination_class = OptionalPageNumberPagination

    def get_serializer_class(self):
        if self._is_browse_mode():
            return AuditLogAdminSerializer
        return AuditLogSerializer

    def _is_browse_mode(self):
        params = self.request.query_params
        return not (params.get('objet_type') and params.get('objet_id'))

    def get_queryset(self):
        if self._is_browse_mode():
            return self._browse_queryset_for_user()

        objet_type = self.request.query_params.get('objet_type')
        objet_id = self.request.query_params.get('objet_id')
        queryset = AuditLog.objects.filter(
            objet_type=objet_type, objet_id=objet_id, environment=get_active_environment(self.request),
        ).select_related('utilisateur', 'action').order_by('-date_action')

        if objet_type == 'Team':
            team = Team.objects.filter(id=objet_id).first()
            if not team or not _appartient_a_equipe(self.request, team):
                return AuditLog.objects.none()
            return queryset

        if get_effective_role(self.request) != UserRole.ADMINISTRATOR:
            return AuditLog.objects.none()
        return queryset

    def _browse_queryset_for_user(self):
        """Périmètre de la consultation globale pour l'utilisateur appelant — voir le
        docstring de la classe. Le super-admin voit tout ; un acteur institutionnel ne voit que
        les AuditLog de SA PROPRE institution (`institution`, posée par audit_log() depuis
        request.user.institution au moment de l'écriture) ; sans institution, rien."""
        if self.request.user.is_superuser:
            return self._filtered_browse_queryset()
        institution = getattr(self.request.user, 'institution', None)
        if institution is None:
            return AuditLog.objects.none()
        return self._filtered_browse_queryset().filter(institution=institution)

    def _filtered_browse_queryset(self):
        params = self.request.query_params
        queryset = AuditLog.objects.filter(
            environment=get_active_environment(self.request),
        ).select_related('utilisateur', 'institution', 'action').order_by('-date_action')

        date_debut = parse_datetime_param(params.get('date_debut'))
        if date_debut:
            queryset = queryset.filter(date_action__gte=date_debut)
        date_fin = parse_datetime_param(params.get('date_fin'))
        if date_fin:
            queryset = queryset.filter(date_action__lte=date_fin)
        if params.get('action'):
            queryset = queryset.filter(action__code=params['action'])
        if params.get('objet_type'):
            queryset = queryset.filter(objet_type=params['objet_type'])
        if params.get('utilisateur'):
            queryset = queryset.filter(utilisateur__email__icontains=params['utilisateur'])
        if params.get('succes') in ('true', 'false'):
            queryset = queryset.filter(succes=(params['succes'] == 'true'))
        return queryset

    @action(detail=False, methods=["get"])
    def export(self, request):
        """Export CSV de la main courante — mêmes filtres et même périmètre que la
        consultation globale (voir _browse_queryset_for_user) : le super-admin exporte tout,
        un acteur institutionnel n'exporte que les actes de sa propre institution. Colonnes en
        clair (pas d'UUID d'action, pas de JSON) pour rester lisible par quelqu'un qui ouvre le
        fichier dans un tableur, pas seulement par un développeur."""
        queryset = self._browse_queryset_for_user()
        total = queryset.count()

        def generate():
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=';')
            writer.writerow([
                "Date", "Heure", "Utilisateur", "Institution", "Adresse IP", "Action",
                "Type d'objet", "ID objet", "Commentaire", "Succès", "Environnement", "Navigateur",
            ])
            yield buffer.getvalue()
            buffer.seek(0); buffer.truncate(0)

            for entry in queryset.iterator(chunk_size=500):
                utilisateur = entry.utilisateur
                nom_utilisateur = (
                    (f"{utilisateur.first_name} {utilisateur.last_name}".strip() or utilisateur.email)
                    if utilisateur else "Système / anonyme"
                )
                writer.writerow([
                    entry.date_action.strftime("%d/%m/%Y"),
                    entry.date_action.strftime("%H:%M:%S"),
                    nom_utilisateur,
                    entry.institution.nom if entry.institution else "",
                    entry.adresse_ip or "",
                    entry.action.libelle if entry.action else "",
                    entry.objet_type,
                    str(entry.objet_id) if entry.objet_id else "",
                    entry.commentaire or "",
                    "Oui" if entry.succes else "Non",
                    entry.environment,
                    entry.user_agent or "",
                ])
                yield buffer.getvalue()
                buffer.seek(0); buffer.truncate(0)

        audit_log(
            request=request,
            action_code="EXPORT",
            objet_type="AuditLog",
            commentaire=f"Export CSV de la main courante ({total} lignes)",
        )

        horodatage = timezone.now().strftime("%Y-%m-%d_%H%M")
        response = StreamingHttpResponse(generate(), content_type="text/csv; charset=utf-8")
        response['Content-Disposition'] = f'attachment; filename="main-courante-{horodatage}.csv"'
        return response


class JournalCollectiviteViewSet(
    EnvironmentScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Journal de bord de la Vue Ma Collectivité — texte libre saisi par un membre de
    l'institution (typiquement le secrétaire de mairie). Volontairement PAS un ModelViewSet :
    aucune route update/partial_update/destroy n'existe (ni ici, ni dans le router — voir
    core/urls.py), pour qu'une entrée soit structurellement immuable une fois créée, comme
    demandé ("ne peuvent pas être supprimées ou modifiées")."""

    queryset = JournalCollectivite.objects.select_related('auteur', 'institution', 'crise').all()
    serializer_class = JournalCollectiviteSerializer
    permission_classes = [IsInstitutionalActor]
    filterset_fields = ["crise"]

    def get_queryset(self):
        # Scopé à la SEULE institution de l'utilisateur appelant (User.institution, le FK
        # direct — même source que _institution_commune_or_400/_institution_secteur_or_400
        # utilisées par la Vue Ma Collectivité, pas ContactInstitution) : jamais le journal
        # d'une autre collectivité.
        institution = getattr(self.request.user, 'institution', None)
        if institution is None:
            return JournalCollectivite.objects.none()
        return super().get_queryset().filter(institution=institution)

    def perform_create(self, serializer):
        institution = getattr(self.request.user, 'institution', None)
        if institution is None:
            raise PermissionDenied("Aucune institution associée à votre compte.")

        # Une institution peut être impliquée sur plusieurs crises actives simultanément — le
        # journal doit être rattaché à une crise précise où elle est effectivement impliquée,
        # jamais une crise arbitraire choisie côté client. Même pattern que
        # DelegationCompetenceSerializer.validate.
        crise = serializer.validated_data.get('crise')
        implique = ImplicationInstitution.objects.filter(
            crise=crise, institution=institution,
            type_implication__in=[TypeImplication.ACTEUR, TypeImplication.IMPLIQUE],
            actif=True,
        ).exists()
        if not implique:
            raise ValidationError({
                "crise": "Votre institution doit être impliquée sur cette crise pour y ajouter une entrée de journal.",
            })

        entry = serializer.save(
            institution=institution,
            auteur=self.request.user,
            environment=get_active_environment(self.request),
        )
        audit_log(
            request=self.request,
            action_code="JOURNAL_BORD",
            objet_type="JournalCollectivite",
            objet_id=entry.id,
            commentaire=f"Journal de bord ({institution.nom}) : {entry.contenu[:200]}",
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

    # crise_nom déréférence crise (FK) ; dernier_commentaire/nb_photos_dernier_commentaire/
    # date_dernier_commentaire/etat_utilisateur touchent tous commentaires (reverse FK), voir
    # RecherchePersonneSerializer._dernier_commentaire (dédupliqué à 1 requête/fiche).
    queryset = (
        RecherchePersonne.objects
        .select_related('crise')
        .order_by("-date_creation")
    )

    serializer_class = (
        RecherchePersonneSerializer
    )

    permission_classes = [
        permissions.IsAuthenticated
    ]
    def get_queryset(self):
        # Depuis self.queryset (pas RecherchePersonne.objects.* directement) pour conserver le
        # select_related de la classe.
        base = self.queryset
        if not self.request.user.is_authenticated:
            return base.none()
        if not self.request.user.enabled:
            return base.none()
        return base.filter(
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

    # auteur_nom déréférence auteur (FK).
    queryset = (
        RecherchePersonneHistorique
        .objects
        .select_related('auteur')
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

    def get_permissions(self):
        # list/retrieve doivent rester accessibles sans compte : le formulaire d'inscription
        # public (register.component) en a besoin pour peupler son sélecteur de type
        # d'institution avant même que le visiteur ait un compte — comme InformationTypeViewSet
        # pour les formulaires publics équivalents. Écriture inchangée (défaut IsAuthenticated).
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return super().get_permissions()

    def perform_create(self, serializer):
        institution_type = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InstitutionType",
            objet_id=institution_type.id,
            commentaire=f"Création type d'institution : {institution_type.libelle}",
        )

    def perform_destroy(self, instance):
        # Institution.type est en PROTECT : la suppression d'un type encore utilisé
        # lève ProtectedError (erreur 500 non gérée) au lieu d'un message exploitable.
        # On renvoie plutôt un 400 indiquant combien d'institutions le référencent
        # encore, pour guider une réaffectation avant suppression.
        nb_institutions = instance.institutions.count()
        if nb_institutions:
            raise ValidationError(
                f"Impossible de supprimer le type « {instance.libelle} » : "
                f"{nb_institutions} institution(s) l'utilisent encore. "
                "Réaffectez-les à un autre type avant de le supprimer."
            )
        instance.delete()

class InstitutionViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    # InstitutionSerializer déréférence type (FK) pour chaque institution. order_by('nom') :
    # requis pour une pagination stable (désormais toujours active, voir InstitutionPagination)
    # — sans ordre explicite, DRF pagine sur un ordre de résultats non garanti par Postgres, ce
    # qui peut dupliquer ou sauter des lignes d'une page à l'autre.
    queryset = (
        Institution.objects.select_related('type').order_by('nom')
    )

    serializer_class = (
        InstitutionSerializer
    )

    pagination_class = InstitutionPagination

    def get_permissions(self):
        # Avant ce correctif, update/partial_update/destroy n'avaient aucune restriction
        # (n'importe quel compte authentifié pouvait modifier ou supprimer l'institution de
        # n'importe qui d'autre) — vérifié en le reproduisant.
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsInstitutionMemberOrAdministrator()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """Règle à sens unique (voir plan zone de démo) : les vraies institutions (PROD)
        restent visibles en DEMO pour permettre de s'appuyer sur les vraies mairies/
        associations dans une démonstration, mais une institution créée en DEMO ne doit
        jamais apparaître en PROD."""
        # Depuis self.queryset (pas Institution.objects.* directement) pour conserver le
        # select_related de la classe.
        base = self.queryset
        environment = get_active_environment(self.request)
        if environment == Environment.DEMO:
            qs = base.filter(environment__in=[Environment.PROD, Environment.DEMO])
        else:
            qs = base.filter(environment=Environment.PROD)

        if self.action != 'list':
            # retrieve reste ouvert (même patron que Team/Dossier/PointOperationnel) : accéder
            # à une institution précise déjà connue (ex: profil affiché dans le cadre d'une
            # crise partagée) n'est pas un vecteur de découverte, contrairement à la liste.
            return qs
        if effective_role_or_none(self.request) == UserRole.ADMINISTRATOR:
            return qs

        # AVANT ce correctif, list ne filtrait QUE par environnement : n'importe quel compte
        # authentifié listait TOUTES les institutions de la plateforme. Désormais "chez moi"
        # (ma propre institution, même si sa zone n'est pas résolvable) + "ma zone" — jamais la
        # liste complète, sauf ADMIN. Comparaison directe (pas filter_queryset_to_viewer_zone,
        # dont le .none() par défaut masquerait aussi "chez moi" quand la zone n'est pas
        # résolvable) pour ne jamais comparer un champ de secteur à None (Q(champ=None)
        # matcherait toute institution où ce champ est NULL en base, une fuite, pas juste "moi").
        user = self.request.user
        own_institution_id = getattr(user, 'institution_id', None) if user.is_authenticated else None
        condition = Q(pk=own_institution_id) if own_institution_id else Q(pk=None)
        zone = viewer_zone_code(self.request)
        if zone is not None:
            niveau, code = zone
            if niveau == "national":
                return qs
            champ = SECTEUR_CHAMP_PAR_NIVEAU.get(niveau)
            if champ and code:
                condition = condition | Q(**{champ: code})
        return qs.filter(condition)

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

    def perform_destroy(self, instance):
        # Zone.institution, Team.institution et Plan.institution sont en PROTECT : supprimer
        # une institution encore rattachée à l'un de ces éléments lève ProtectedError (500 non
        # géré) au lieu d'un message exploitable.
        nb = instance.zones.count() + instance.teams.count() + instance.plans.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer l'institution « {instance.nom} » : "
                f"{nb} élément(s) (zones/équipes/plans) y sont encore rattachés."
            )
        instance.delete()

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

    def perform_destroy(self, instance):
        # Affectation.role est en PROTECT : supprimer un rôle encore affecté lève
        # ProtectedError (500 non géré) au lieu d'un message exploitable.
        nb = instance.affectations.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer le rôle « {instance.libelle} » : "
                f"{nb} affectation(s) l'utilisent encore."
            )
        instance.delete()
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

    def perform_destroy(self, instance):
        # PointOperationnel.type est en PROTECT : supprimer un type encore utilisé lève
        # ProtectedError (500 non géré) au lieu d'un message exploitable.
        nb = instance.points.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer le type « {instance.libelle} » : "
                f"{nb} point(s) opérationnel(s) l'utilisent encore."
            )
        instance.delete()

class PointOperationnelViewSet(
    EnvironmentScopedViewSetMixin, viewsets.ModelViewSet
):

    # PointOperationnelSerializer déréférence type/equipe/crise/responsable (FK), le leader de
    # chaque équipe de gestion (via responsables_effectifs()), et 4 M2M (responsables,
    # competences_requises, equipes_gestion, equipes_ravitaillement) — sans ces select_related/
    # prefetch_related, ~16 requêtes SQL par point (198 requêtes mesurées pour 12 points DEMO).
    queryset = (
        PointOperationnel.objects.select_related('type', 'equipe', 'equipe__leader', 'crise', 'responsable')
        .prefetch_related(
            'responsables', 'competences_requises',
            'equipes_gestion', 'equipes_gestion__leader',
            'equipes_ravitaillement',
        )
    )

    serializer_class = (
        PointOperationnelSerializer
    )

    filterset_fields = ["crise"]

    def get_queryset(self):
        """`?mine=true` restreint aux points dont l'utilisateur est responsable, leader ou
        membre de l'équipe — alimente la page "Mes centres" (accès direct, toutes crises
        confondues, sans repasser par la fiche de chaque crise) : reste une vue personnelle,
        jamais réduite par zone (comme TeamViewSet.get_queryset avec `retrieve`)."""
        qs = super().get_queryset()
        if self.request.query_params.get("mine") == "true":
            user = self.request.user
            return qs.filter(
                Q(responsable=user) | Q(equipe__leader=user) | Q(equipe__members=user)
            ).distinct()
        if self.action == 'list':
            qs = self._filter_points_to_viewer_zone(qs)
        return qs

    def _filter_points_to_viewer_zone(self, qs):
        """PointOperationnel n'a pas de code commune/EPCI/département/région dénormalisé
        (contrairement à Request/Offer/Information) : combine un filtre direct sur les points
        rattachés à une équipe elle-même rattachée à une institution
        (`Q(equipe__institution__{champ}=code)`, comme DossierViewSet.vue_mairie) et, pour les
        points sans équipe ou dont l'équipe n'a pas d'institution, un géocodage inverse point
        par point (`commune_code_from_point`, même mécanisme que vue_mairie) résolu au niveau
        de secteur de l'appelant via le référentiel Commune."""
        if effective_role_or_none(self.request) == UserRole.ADMINISTRATOR:
            return qs
        zone = viewer_zone_code(self.request)
        if zone is None:
            return qs.none()
        niveau, code = zone
        if niveau == "national":
            return qs
        champ = SECTEUR_CHAMP_PAR_NIVEAU[niveau]
        direct = Q(**{f"equipe__institution__{champ}": code})
        sans_institution = qs.filter(
            Q(equipe__isnull=True) | Q(equipe__institution__isnull=True),
            location__isnull=False,
        )
        matching_ids = []
        for point in sans_institution:
            point_commune_code = commune_code_from_point(point.location)
            if not point_commune_code:
                continue
            if niveau == "commune":
                point_code = point_commune_code
            else:
                commune = Commune.objects.filter(code=point_commune_code).first()
                point_code = getattr(commune, champ, None) if commune else None
            if point_code == code:
                matching_ids.append(point.id)
        return qs.filter(direct | Q(id__in=matching_ids))

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
        if self.action in ("centres_accueil", "carte_publique"):
            return [AllowAny()]
        if self.action == "vue_mairie":
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=["get"], permission_classes=[IsInstitutionalActor])
    def vue_mairie(self, request):
        """Points opérationnels situés dans la commune de l'institution de l'utilisateur
        appelant — même patron que OfferViewSet.vue_mairie (PointOperationnel n'a pas de
        commune_code stocké, reverse-géocodage de `location`). Les points sans localisation
        sont exclus ici, sans que ça affecte leur existence par ailleurs."""
        commune_code = _institution_commune_or_400(request)
        if isinstance(commune_code, Response):
            return commune_code

        queryset = self.get_queryset().filter(location__isnull=False)
        matching_ids = [
            p.id for p in queryset
            if commune_code_from_point(p.location) == commune_code
        ]
        points = self.get_queryset().filter(id__in=matching_ids)
        return Response(self.get_serializer(points, many=True).data)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def carte_publique(self, request):
        """Centres visibles sans authentification sur la carte de la page d'accueil : centres
        d'accueil (HEBERGEMENT) et postes de secours (SECOURS) actifs, toutes crises confondues
        — contrairement à centres_accueil (scopé à une seule crise pour le formulaire "je suis
        en sécurité"), cette liste alimente une carte globale, sans crise présélectionnée."""
        queryset = PointOperationnel.objects.filter(
            actif=True, type__code__in=["HEBERGEMENT", "SECOURS"],
            environment=get_active_environment(request),
        ).select_related("type")
        return Response(PointOperationnelPublicSerializer(queryset, many=True).data)

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

        # Même mécanisme qu'à la création (voir perform_create) : un point déjà existant mais
        # encore sans équipe pouvait jusqu'ici seulement se voir assigner une équipe EXISTANTE
        # (select "Équipe responsable") — créer une équipe à la volée n'était possible qu'au
        # moment de la création du point, obligeant sinon un aller-retour par l'écran équipes.
        # Ignoré si le point a déjà une équipe : remplacer l'équipe en place n'est pas le rôle
        # de ce paramètre (utiliser le select existant pour ça).
        nouvelle_equipe_nom = (self.request.data.get('nouvelle_equipe_nom') or '').strip()
        if nouvelle_equipe_nom and not point.equipe_id:
            _creer_equipe_pour_point(
                point, nouvelle_equipe_nom, self._resolve_institution_for_new_team(), self.request
            )

    def _resolve_institution_for_new_team(self):
        """Institution à rattacher à une équipe créée à la volée (voir perform_create/
        perform_update) : celle explicitement choisie dans le payload si l'appelant y a accès,
        sinon celle de son propre rattachement actif — jamais d'erreur si aucune des deux
        n'est disponible, l'équipe reste alors sans institution plutôt que de bloquer."""
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

        return institution

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
        # rattachement) plutôt que d'échouer silencieusement. Résolue même sans crise : sert
        # aussi à rattacher la nouvelle équipe créée avec le point (voir plus bas), qui n'exige
        # pas de crise.
        nouvelle_equipe_nom = (self.request.data.get('nouvelle_equipe_nom') or '').strip()
        if point.crise_id or nouvelle_equipe_nom:
            institution = self._resolve_institution_for_new_team()

            if point.crise_id and institution:
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

            # Créer une équipe en même temps que le point, plutôt que d'obliger à en créer une
            # séparément avant de pouvoir en assigner une — seulement si aucune équipe n'a déjà
            # été choisie dans le formulaire (mutuellement exclusifs côté frontend). Même
            # mécanisme réutilisé depuis perform_update pour un point déjà existant.
            if nouvelle_equipe_nom and not point.equipe_id:
                _creer_equipe_pour_point(point, nouvelle_equipe_nom, institution, self.request)

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

    @action(detail=True, methods=["post"], url_path="valider-benevole")
    def valider_benevole(self, request, pk=None):
        """Arbitrage du régulateur sur un créneau bénévole préalablement accepté par ce dernier
        (statut EN_VALIDATION, voir ConfirmerAffectationBenevoleView) — étape intermédiaire
        ajoutée entre la réponse « oui » du bénévole et son engagement définitif, pour laisser
        le régulateur valider ou finalement écarter le créneau avant confirmation (retour
        terrain — jusqu'ici la réponse du bénévole valait confirmation immédiate)."""
        point = self.get_object()

        if point.responsable_id != request.user.id and not (
            point.equipe and point.equipe.leader_id == request.user.id
        ) and get_effective_role(request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied(
                "Seul le responsable ou le leader de l'équipe du point peut valider un créneau bénévole."
            )

        decision = request.data.get("decision")
        if decision not in ("confirmer", "refuser"):
            return Response({"error": "decision doit être 'confirmer' ou 'refuser'."}, status=status.HTTP_400_BAD_REQUEST)

        affectation_id = request.data.get("affectation_id")
        affectation = get_object_or_404(AffectationPointBenevole, pk=affectation_id, point=point)
        if affectation.statut != StatutAffectation.EN_VALIDATION:
            return Response(
                {"error": "Ce créneau n'est pas en attente de validation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        affectation.statut = StatutAffectation.CONFIRME if decision == "confirmer" else StatutAffectation.DECLINE
        affectation.save()

        if decision == "refuser":
            # Même traitement qu'un "non" du bénévole (voir ConfirmerAffectationBenevoleView) :
            # les créneaux liés à une affectation écartée n'ont plus lieu d'être.
            affectation.creneaux.all().delete()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="AffectationPointBenevole",
            objet_id=affectation.id,
            crise=point.crise,
            commentaire=(
                f"Créneau de {affectation.benevole.email} "
                f"{'validé' if decision == 'confirmer' else 'écarté'} par {request.user.email}"
            ),
        )

        send_benevole_validation_result_email(request, affectation, decision)

        return Response(AffectationPointBenevoleSerializer(affectation).data)

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

    @action(detail=True, methods=["post"], url_path="demander-transfert")
    def demander_transfert(self, request, pk=None):
        """Demande de transfert de matériel depuis CE point (pk, le point source où le stock a
        été repéré comme "en trop") vers un point de destination — envoie un email et une
        notification à tous les responsables du point source (voir
        PointOperationnel.responsables_effectifs). Ne modifie aucun stock : reste une simple
        demande, à charge des responsables du point source de l'honorer sur place."""
        point_source = self.get_object()
        destination_id = request.data.get("destination_point_id")
        destination = get_object_or_404(PointOperationnel, pk=destination_id)
        items = request.data.get("items") or []
        message_libre = (request.data.get("message") or "").strip()

        if not items:
            return Response({"error": "Sélectionnez au moins un article à transférer."}, status=status.HTTP_400_BAD_REQUEST)

        lignes = []
        for entry in items:
            mp = MaterielPoint.objects.filter(pk=entry.get("materiel_point_id"), point=point_source).select_related("item").first()
            if not mp:
                continue
            quantite_demandee = entry.get("quantite_demandee")
            lignes.append(f"- {mp.item.nom}" + (f" : {quantite_demandee}" if quantite_demandee else ""))

        if not lignes:
            return Response({"error": "Aucun des articles sélectionnés n'a été trouvé sur ce point."}, status=status.HTTP_400_BAD_REQUEST)

        demandeur = request.user
        demandeur_nom = f"{demandeur.first_name} {demandeur.last_name}".strip() or demandeur.email

        titre = f"Demande de transfert depuis « {point_source.nom} » vers « {destination.nom} »"
        corps = (
            f"{demandeur_nom} demande le transfert des articles suivants depuis « {point_source.nom} » "
            f"vers « {destination.nom} » :\n\n" + "\n".join(lignes)
        )
        if message_libre:
            corps += f"\n\nMessage :\n{message_libre}"

        destinataires = point_source.responsables_effectifs()
        for user in destinataires:
            Notification.objects.create(utilisateur=user, titre=titre, message=corps)
            if user.email:
                try:
                    send_mail_env_aware(
                        request, subject=titre, message=corps, from_email=None,
                        recipient_list=[user.email], fail_silently=True,
                    )
                except Exception as e:
                    print(f"Erreur envoi email demande de transfert : {e}")

        return Response({"notifies": len(destinataires)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="vue-operationnelle")
    def vue_operationnelle(self, request, pk=None):
        """Vue opérationnelle d'un point : équipes le tenant (par spécialité), équipes de
        terrain qu'il ravitaille, et civils actuellement accueillis — pour chaque équipe,
        effectif et matériel (offres de type Matériel qui lui ont été affectées comme
        ressources, seule source de "leur matériel" existante à ce jour)."""
        point = self.get_object()

        def equipe_info(team):
            materiel_offres = team.assigned_offers.filter(offer_type__type="Matériel")
            return {
                "id": str(team.id),
                "nom": team.name,
                "effectif": team.members.count(),
                "materiel": [
                    {
                        "titre": o.title,
                        "materiel_type": o.materiel_type,
                        "materiel_catalogue_nom": o.materiel_catalogue.nom if o.materiel_catalogue_id else None,
                        "quantite": o.quantite,
                        "unite": o.unite,
                    }
                    for o in materiel_offres
                ],
            }

        equipes_gestion = list(point.equipes_gestion.all())
        if point.equipe and point.equipe not in equipes_gestion:
            equipes_gestion.append(point.equipe)

        return Response({
            "equipes_gestion": [equipe_info(t) for t in equipes_gestion],
            "equipes_ravitaillement": [equipe_info(t) for t in point.equipes_ravitaillement.all()],
            "civils_accueillis": PointOperationnelSerializer(point).get_civils_accueillis(point),
        })


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
    réutilisable par tous les autres (voir PointOperationnelViewSet.stocks). AllowAny comme
    ces deux autres : recherché/créé aussi depuis propose-help-form (matériel "Autre"), un
    formulaire public sans compte requis — même correctif que CompetenceViewSet."""

    queryset = MaterielCatalogue.objects.all()
    serializer_class = MaterielCatalogueSerializer

    def get_permissions(self):
        # AllowAny restreint à list/retrieve/create (voir docstring de classe) : update/
        # destroy doivent rester réservés aux comptes authentifiés, contrairement à avant où
        # permission_classes=[AllowAny] s'appliquait à toute la classe et permettait à
        # n'importe qui, sans compte, de modifier/supprimer un item du catalogue.
        if self.action in ('list', 'retrieve', 'create'):
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        categorie = self.request.query_params.get("categorie")
        if categorie:
            queryset = queryset.filter(categorie=categorie)
        return queryset

    def perform_destroy(self, instance):
        # MaterielPoint.item est en PROTECT : supprimer un item encore utilisé lève
        # ProtectedError (500 non géré) au lieu d'un message exploitable.
        nb = instance.stocks.count()
        if nb:
            raise ValidationError(
                f"Impossible de supprimer l'item « {instance.nom} » : "
                f"{nb} ligne(s) de stock l'utilisent encore."
            )
        instance.delete()




class ContributionMaterielViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Apports individuels de matériel sur une ligne de stock — voir ContributionMateriel."""

    queryset = ContributionMateriel.objects.select_related(
        "materiel_point__point", "materiel_point__item", "offre", "responsable"
    ).all()
    serializer_class = ContributionMaterielSerializer
    filterset_fields = ["materiel_point"]

    def perform_create(self, serializer):
        materiel_point = serializer.validated_data.get('materiel_point')
        if not _peut_gerer_stock_point(self.request, materiel_point.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut enregistrer un apport."
            )
        contribution = serializer.save(responsable=self.request.user, environment=get_active_environment(self.request))
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="MaterielPoint",
            objet_id=contribution.materiel_point.id,
            crise=contribution.materiel_point.point.crise,
            commentaire=(
                f"Apport reçu : {contribution.materiel_point.item.nom} "
                f"({contribution.quantite} {contribution.unite}) fourni par {contribution.fournisseur_nom or 'anonyme'}"
            ),
        )

    def perform_update(self, serializer):
        if not _peut_gerer_stock_point(self.request, serializer.instance.materiel_point.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier un apport."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if not _peut_gerer_stock_point(self.request, instance.materiel_point.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut supprimer un apport."
            )
        instance.delete()


class MaterielPointViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """État du stock (niveau qualitatif + suivi quantitatif optionnel) d'un item du catalogue
    matériel sur un point opérationnel."""

    queryset = MaterielPoint.objects.select_related("point", "item", "responsable").all()
    serializer_class = MaterielPointSerializer
    filterset_fields = ["point", "statut", "item"]

    def _can_manage(self, request, point):
        return _peut_gerer_stock_point(request, point)

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
        return _peut_gerer_stock_point(request, point)

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

    def get_queryset(self):
        # Exclusion totale hors zone sur la LISTE par défaut uniquement (pas de résumé,
        # contrairement à Request) : une déclaration "je suis en sécurité" est une coordonnée
        # personnelle. Ne s'applique pas à retrieve/update/destroy/vue_mairie/mes_declarations :
        # vue_mairie fait déjà son propre filtrage par géocodage inverse (les déclarations
        # rattachées à un centre n'ont pas d'epci/departement/region_code propres) ;
        # update/destroy doivent rester visibles pour laisser IsOwnDeclarationOrInstitutional
        # distinguer 403 (trouvé, refusé) de 404 (jamais visible) ; mes_declarations doit
        # retrouver la déclaration de son auteur quelle que soit sa zone.
        qs = super().get_queryset()
        if self.action != 'list':
            return qs
        zone_qs = filter_queryset_to_viewer_zone(self.request, qs)
        user = self.request.user
        if user.is_authenticated:
            return (qs.filter(declare_par=user) | zone_qs).distinct()
        return zone_qs

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
        # Une entrée saisie depuis le secrétariat d'un centre n'envoie pas `crise` (le centre
        # la détermine déjà sans ambiguïté) — contrairement au formulaire public "je suis en
        # sécurité", qui la fait choisir explicitement. Sans cette déduction, la création
        # échouait systématiquement en 400 pour toute saisie côté secrétariat (crise absente
        # du payload, champ pourtant obligatoire en base).
        if not serializer.validated_data.get('crise'):
            if centre is None:
                raise ValidationError({"crise": "Ce champ est obligatoire."})
            serializer.validated_data['crise'] = centre.crise
        declare_par = self.request.user if self.request.user.is_authenticated else None
        declaration = serializer.save(
            declare_par=declare_par,
            environment=get_active_environment(self.request),
        )

        # Résout epci_code/departement_code/region_code une seule fois ici — même correctif
        # que RequestViewSet.perform_create (voir son commentaire) : nécessaire pour exclure
        # une déclaration hors zone (object_in_viewer_zone) au-delà du seul niveau commune.
        if declaration.commune_code and not declaration.epci_code:
            secteur = commune_secteur_codes(declaration.commune_code)
            declaration.epci_code = secteur["epci_code"]
            declaration.departement_code = secteur["departement_code"]
            declaration.region_code = secteur["region_code"]
            declaration.save(update_fields=["epci_code", "departement_code", "region_code"])

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

    # responsable_nom/themes_libelles déréférencent responsable (FK) et themes (M2M), absents
    # du select_related/prefetch_related existant.
    queryset = ImplicationInstitution.objects.select_related(
        "institution", "crise", "utilisateur", "responsable"
    ).prefetch_related("themes").all()
    serializer_class = ImplicationInstitutionSerializer
    filterset_fields = ["crise", "institution", "type_implication", "actif"]

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

    # utilisateur_nom/utilisateur_email déréférencent utilisateur (FK).
    queryset = (
        ContactInstitution.objects.select_related('institution', 'utilisateur')
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

