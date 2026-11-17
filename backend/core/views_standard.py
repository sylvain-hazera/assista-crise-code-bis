"""Accès au standard de crise et au point de situation — voir core/standard_crise.py et
core/point_situation.py pour le pourquoi."""
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import point_situation, standard_crise
from .audit import audit_log
from .models import AppelStandard, Crisis, Dossier, NatureAppelStandard, SuiteAppelStandard
from .permissions import IsInstitutionalActor, get_active_environment
from .views_stocks import _du_perimetre, _institution_ou_refus


class AppelStandardSerializer(serializers.ModelSerializer):
    nature_libelle = serializers.CharField(source="get_nature_display", read_only=True)
    suite_libelle = serializers.CharField(source="get_suite_display", read_only=True)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    recu_par_nom = serializers.SerializerMethodField()
    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True, default=None)

    class Meta:
        model = AppelStandard
        exclude = ["environment"]
        read_only_fields = ["institution", "numero", "recu_par", "date_appel", "dossier",
                            "suite", "suite_donnee", "traite_par", "traite_le"]

    def get_recu_par_nom(self, obj):
        from .views import _nommer_pour
        return _nommer_pour(self.context.get("request"))(obj.recu_par) if obj.recu_par_id else ""

    def validate_objet(self, valeur):
        if not (valeur or "").strip():
            raise serializers.ValidationError("Notez en une phrase l'objet de l'appel.")
        return valeur.strip()


class AppelStandardViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """Fiches d'appel du standard de crise. On crée et on donne une suite ; une fiche ne se
    modifie ni ne se supprime — c'est une trace."""
    queryset = AppelStandard.objects.select_related("crise", "recu_par", "dossier")
    serializer_class = AppelStandardSerializer
    permission_classes = [IsInstitutionalActor]
    filterset_fields = ["crise", "nature", "suite"]

    def get_queryset(self):
        return _du_perimetre(self.request, super().get_queryset())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        appel = standard_crise.enregistrer(
            _institution_ou_refus(request), get_active_environment(request), request.user,
            nature=donnees["nature"], objet=donnees["objet"], crise=donnees.get("crise"),
            appelant_nom=donnees.get("appelant_nom", ""), appelant_telephone=donnees.get("appelant_telephone", ""),
            lieu=donnees.get("lieu", ""),
        )
        return Response(self.get_serializer(appel).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def clore(self, request, pk=None):
        """Donne sa suite à l'appel : traité, ou sans suite, avec ce qui a été fait."""
        appel = self.get_object()
        suite = request.data.get("suite")
        if suite not in (SuiteAppelStandard.TRAITE, SuiteAppelStandard.SANS_SUITE, SuiteAppelStandard.A_TRAITER):
            raise ValidationError({"suite": "Suite inconnue."})
        standard_crise.clore(appel, request.user, suite, str(request.data.get("suite_donnee") or "").strip())
        return Response(self.get_serializer(appel).data)

    @action(detail=True, methods=["post"], url_path="ouvrir-dossier")
    def ouvrir_dossier(self, request, pk=None):
        """Ouvre le dossier que les équipes traiteront. Une fiche n'en ouvre qu'un."""
        appel = self.get_object()
        priorite = request.data.get("priorite") or Dossier.Priorite.NORMALE
        if priorite not in Dossier.Priorite.values:
            raise ValidationError({"priorite": "Priorité invalide."})
        try:
            dossier = standard_crise.ouvrir_un_dossier(appel, request.user, priorite)
        except ValueError as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="CREATION", objet_type="Dossier", objet_id=dossier.id,
                  crise=appel.crise, commentaire=f"Dossier ouvert depuis la fiche d'appel n° {appel.numero} du standard.")
        return Response(self.get_serializer(appel).data)

    @action(detail=False, methods=["get"])
    def synthese(self, request):
        crise = Crisis.objects.filter(id=request.query_params.get("crise")).first() \
            if request.query_params.get("crise") else None
        return Response({
            "natures": [{"code": c, "libelle": l} for c, l in NatureAppelStandard.choices],
            **standard_crise.synthese(_institution_ou_refus(request), get_active_environment(request), crise),
        })


class PointDeSituationView(APIView):
    """GET /api/point-de-situation/?crise=<id> — les chiffres de la crise pour la collectivité
    de l'appelant, rassemblés et en texte prêt à coller."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        crise = Crisis.objects.filter(
            id=request.query_params.get("crise"), environment=get_active_environment(request)).first() \
            if request.query_params.get("crise") else None
        if crise is None:
            raise ValidationError({"crise": "Indiquez la crise."})
        return Response(point_situation.construire(
            crise, _institution_ou_refus(request), get_active_environment(request)))
