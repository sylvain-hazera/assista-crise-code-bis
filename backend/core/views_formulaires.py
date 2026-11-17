"""Accès aux formulaires de terrain — voir core/formulaires_terrain.py pour le pourquoi."""
import json
import uuid

from django.contrib.gis.geos import Point
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import formulaires_terrain as ft
from .audit import audit_log
from .models import FormulaireTerrain, ReponseFormulaireTerrain
from .perimetre_admin import institution_regardee
from .permissions import IsInstitutionalActor, get_active_environment
from .zone_scoping import _memo


def _gerees(request):
    return _memo(request, "formulaires_gerees", lambda: ft.institutions_gerees(request))


def _delegantes(request):
    return _memo(request, "formulaires_delegantes", lambda: ft.institutions_delegantes(request))


class TypesQuestionView(APIView):
    """Les types de question proposés au compositeur, et si l'appelant peut composer."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        return Response({
            "types": [{"code": code, "libelle": libelle} for code, libelle in ft.TYPES.items()],
            "peut_composer": bool(_gerees(request)),
            "peut_repondre": bool(_gerees(request) or _delegantes(request)),
        })


class FormulaireTerrainSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source="institution.nom", read_only=True)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    nb_reponses = serializers.SerializerMethodField()
    peut_gerer = serializers.SerializerMethodField()

    class Meta:
        model = FormulaireTerrain
        exclude = ["environment"]
        read_only_fields = ["institution", "cree_par", "date_creation", "date_modification"]

    def get_nb_reponses(self, obj):
        request = self.context.get("request")
        if request is not None and obj.institution_id in _gerees(request):
            return obj.reponses.count()
        # Un délégué ne compte que les siennes : le total dirait ce que font les autres.
        return obj.reponses.filter(auteur=getattr(request, "user", None)).count()

    def get_peut_gerer(self, obj):
        request = self.context.get("request")
        return request is not None and obj.institution_id in _gerees(request)

    def validate_questions(self, valeur):
        try:
            return ft.nettoyer_questions(valeur)
        except ft.ErreurFormulaire as erreur:
            raise serializers.ValidationError(str(erreur))


class FormulaireTerrainViewSet(viewsets.ModelViewSet):
    """Questionnaires de terrain. La collectivité compose, lit et exporte ; une institution
    déléguée voit les questionnaires ouverts et y répond."""
    queryset = FormulaireTerrain.objects.select_related("institution", "crise")
    serializer_class = FormulaireTerrainSerializer
    permission_classes = [IsInstitutionalActor]
    filterset_fields = ["crise", "actif"]

    def get_queryset(self):
        request = self.request
        queryset = super().get_queryset().filter(environment=get_active_environment(request))
        gerees, delegantes = _gerees(request), _delegantes(request)
        if not gerees and not delegantes:
            return queryset.none()
        from django.db.models import Q
        return queryset.filter(
            Q(institution_id__in=gerees) | Q(institution_id__in=delegantes, actif=True))

    def _exiger_gestion(self, formulaire):
        if formulaire.institution_id not in _gerees(self.request):
            raise PermissionDenied("Seule la collectivité qui a composé ce questionnaire peut le gérer.")

    def perform_create(self, serializer):
        institution = institution_regardee(self.request)
        if institution is None or institution.id not in _gerees(self.request):
            raise PermissionDenied(
                "Les questionnaires de terrain sont composés par une collectivité : votre compte "
                "n'en représente pas une."
            )
        formulaire = serializer.save(
            institution=institution, cree_par=self.request.user,
            environment=get_active_environment(self.request),
        )
        audit_log(request=self.request, action_code="CREATION", objet_type="FormulaireTerrain",
                  objet_id=formulaire.id, crise=formulaire.crise,
                  commentaire=f"Questionnaire de terrain « {formulaire.titre} » créé.")

    def perform_update(self, serializer):
        formulaire = serializer.instance
        self._exiger_gestion(formulaire)
        nouvelles = serializer.validated_data.get("questions")
        if nouvelles is not None and formulaire.reponses.exists():
            # Des réponses existent : on peut ajouter des questions ou en retoucher l'intitulé,
            # pas retirer ni changer de type celles auxquelles on a déjà répondu — les
            # réponses rangées n'auraient plus de question en face.
            avant = {q["cle"]: q["type"] for q in formulaire.questions}
            apres = {q["cle"]: q["type"] for q in nouvelles}
            perdues = [c for c, t in avant.items() if apres.get(c) != t]
            if perdues:
                raise ValidationError({"questions": (
                    "Ce questionnaire a déjà des réponses : ses questions existantes ne peuvent "
                    "être ni retirées ni changer de type. Fermez-le et composez-en un nouveau."
                )})
        serializer.save()

    def perform_destroy(self, instance):
        self._exiger_gestion(instance)
        if instance.reponses.exists():
            raise ValidationError({"detail": (
                "Ce questionnaire a des réponses : fermez-le plutôt que de le supprimer."
            )})
        instance.delete()

    @action(detail=True, methods=["post"])
    def repondre(self, request, pk=None):
        """Enregistre une réponse. Rejouable : le même `identifiant_client` renvoyé après une
        coupure de réseau rend la réponse déjà rangée, sans doublon."""
        formulaire = self.get_object()
        if not formulaire.actif:
            raise ValidationError({"detail": "Ce questionnaire est fermé : il n'accepte plus de réponse."})
        try:
            identifiant = uuid.UUID(str(request.data.get("identifiant_client")))
        except ValueError:
            raise ValidationError({"identifiant_client": "Identifiant de saisie attendu."})

        existante = formulaire.reponses.filter(identifiant_client=identifiant).first()
        if existante is not None:
            return Response({"id": str(existante.id), "deja_recue": True})

        try:
            donnees = ft.nettoyer_reponses(formulaire.questions, request.data.get("donnees"))
        except ft.ErreurFormulaire as erreur:
            raise ValidationError({"detail": str(erreur)})

        location = None
        latitude, longitude = request.data.get("latitude"), request.data.get("longitude")
        if latitude not in (None, "") and longitude not in (None, ""):
            try:
                latitude, longitude = float(latitude), float(longitude)
            except (TypeError, ValueError):
                raise ValidationError({"detail": "Position illisible."})
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValidationError({"detail": "Position hors du globe."})
            location = Point(longitude, latitude, srid=4326)

        saisie_le = parse_datetime(str(request.data.get("saisie_le") or "")) or timezone.now()
        if timezone.is_naive(saisie_le):
            saisie_le = timezone.make_aware(saisie_le)
        # L'heure d'un appareil mal réglé ne doit pas dater une réponse dans le futur.
        saisie_le = min(saisie_le, timezone.now())

        reponse = ReponseFormulaireTerrain.objects.create(
            formulaire=formulaire, auteur=request.user, institution_auteur=institution_regardee(request),
            identifiant_client=identifiant, donnees=json.dumps(donnees, ensure_ascii=False),
            location=location, saisie_le=saisie_le, environment=get_active_environment(request),
        )
        return Response({"id": str(reponse.id), "deja_recue": False}, status=status.HTTP_201_CREATED)

    def _tableau(self, formulaire):
        from .views import _nommer_pour

        reponses = formulaire.reponses.select_related("auteur", "institution_auteur")
        if formulaire.institution_id not in _gerees(self.request):
            reponses = reponses.filter(auteur=self.request.user)
        return ft.lignes(formulaire, reponses, _nommer_pour(self.request))

    @action(detail=True, methods=["get"])
    def reponses(self, request, pk=None):
        """Les réponses : toutes pour la collectivité, les siennes pour un délégué."""
        formulaire = self.get_object()
        return Response(self._tableau(formulaire))

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """`?type=csv` (défaut) pour un tableur, `?type=geojson` pour une carte. Réservé à la
        collectivité : un export sort les réponses de l'application."""
        formulaire = self.get_object()
        self._exiger_gestion(formulaire)
        tableau = self._tableau(formulaire)
        audit_log(request=request, action_code="EXPORT", objet_type="FormulaireTerrain",
                  objet_id=formulaire.id, crise=formulaire.crise,
                  commentaire=f"Export des {len(tableau)} réponse(s) de « {formulaire.titre} ».")
        if request.query_params.get("type") == "geojson":
            reponse = HttpResponse(json.dumps(ft.en_geojson(formulaire, tableau), ensure_ascii=False),
                                   content_type="application/geo+json; charset=utf-8")
            reponse["Content-Disposition"] = 'attachment; filename="reponses.geojson"'
            return reponse
        reponse = HttpResponse(ft.en_csv(formulaire, tableau), content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = 'attachment; filename="reponses.csv"'
        return reponse
