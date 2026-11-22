"""Connecteurs SMTP d'une institution (22/11/2026) : liste, ajout, modification, essai.

Réservé au bureau de l'institution et à l'administrateur, comme la configuration Brevo
(`InstitutionViewSet.configuration_envoi`) : confier un accès qui envoie AU NOM de
l'association est un acte de gouvernance. Identifiant et mot de passe en écriture seule.
"""
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .audit import audit_log
from .models import ConnecteurSMTP, ContactInstitution, UserRole
from .permissions import get_active_environment, get_effective_role


class ConnecteurSMTPSerializer(serializers.ModelSerializer):
    identifiant = serializers.CharField(write_only=True, required=False, allow_blank=True)
    mot_de_passe = serializers.CharField(write_only=True, required=False, allow_blank=True)
    identifiant_renseigne = serializers.SerializerMethodField()
    mot_de_passe_renseigne = serializers.SerializerMethodField()

    class Meta:
        model = ConnecteurSMTP
        fields = ["id", "institution", "nom", "hote", "port", "chiffrement", "identifiant", "mot_de_passe",
                  "identifiant_renseigne", "mot_de_passe_renseigne", "expediteur_email", "expediteur_nom", "actif",
                  "dernier_succes", "dernier_echec", "dernier_echec_motif", "date_creation"]
        read_only_fields = ["dernier_succes", "dernier_echec", "dernier_echec_motif", "date_creation"]

    def get_identifiant_renseigne(self, obj):
        return bool(obj.identifiant)

    def get_mot_de_passe_renseigne(self, obj):
        return bool(obj.mot_de_passe)

    def update(self, instance, validated_data):
        # Laissé vide = inchangé : le formulaire ne relit jamais les secrets.
        for champ in ("identifiant", "mot_de_passe"):
            if not validated_data.get(champ):
                validated_data.pop(champ, None)
        validated_data.pop("institution", None)
        return super().update(instance, validated_data)


def _peut_gerer(request, institution) -> bool:
    if get_effective_role(request) == UserRole.ADMINISTRATOR:
        return True
    return ContactInstitution.objects.filter(institution=institution, utilisateur=request.user,
                                             membre_bureau=True, actif=True).exists()


class ConnecteurSMTPViewSet(viewsets.ModelViewSet):
    serializer_class = ConnecteurSMTPSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = ConnecteurSMTP.objects.select_related("institution")
        institution = self.request.query_params.get("institution")
        if institution:
            qs = qs.filter(institution_id=institution)
        if get_effective_role(self.request) == UserRole.ADMINISTRATOR:
            return qs
        bureaux = ContactInstitution.objects.filter(utilisateur=self.request.user, membre_bureau=True, actif=True)
        return qs.filter(institution_id__in=bureaux.values("institution_id"))

    def perform_create(self, serializer):
        institution = serializer.validated_data.get("institution")
        if institution is None or not _peut_gerer(self.request, institution):
            raise PermissionDenied("Seul le bureau de cette institution gère ses connecteurs d'envoi.")
        connecteur = serializer.save(environment=get_active_environment(self.request))
        self._tracer(connecteur, "ajouté")

    def perform_update(self, serializer):
        if not _peut_gerer(self.request, serializer.instance.institution):
            raise PermissionDenied("Seul le bureau de cette institution gère ses connecteurs d'envoi.")
        self._tracer(serializer.save(), "modifié")

    def perform_destroy(self, instance):
        if not _peut_gerer(self.request, instance.institution):
            raise PermissionDenied("Seul le bureau de cette institution gère ses connecteurs d'envoi.")
        self._tracer(instance, "supprimé")
        instance.delete()

    def _tracer(self, connecteur, verbe):
        audit_log(request=self.request, action_code="MODIFICATION", objet_type="ConnecteurSMTP", objet_id=connecteur.id,
                  commentaire=f"Connecteur SMTP « {connecteur.nom} » de « {connecteur.institution.nom} » {verbe}.")

    @action(detail=True, methods=["post"])
    def essai(self, request, pk=None):
        """Un courriel d'essai, à son propre compte, par ce connecteur."""
        from .envoi_connecteurs import EchecEnvoi, envoyer

        connecteur = self.get_object()
        if not _peut_gerer(request, connecteur.institution):
            raise PermissionDenied("Seul le bureau de cette institution gère ses connecteurs d'envoi.")
        if not request.user.email:
            raise ValidationError({"error": "Votre compte n'a pas d'adresse pour recevoir l'essai."})
        try:
            envoyer(f"smtp:{connecteur.id}", f"Essai du connecteur « {connecteur.nom} »",
                    f"Ce courriel d'essai est parti par le connecteur SMTP « {connecteur.nom} » de "
                    f"{connecteur.institution.nom}, depuis {connecteur.expediteur_email}.",
                    request.user.email, institutions_permises=[connecteur.institution])
        except EchecEnvoi as echec:
            return Response({"ok": False, "error": f"L'envoi a échoué : {echec}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"ok": True, "message": f"Essai envoyé à {request.user.email}."})

