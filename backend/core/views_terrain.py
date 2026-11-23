"""API des messages de terrain (22/11/2026) : voir core/messages_terrain.py."""
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from . import messages_terrain as mt
from .models import MessageTerrain, Mission
from .permissions import INSTITUTIONAL_TYPES, get_effective_role


class MessageTerrainSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)
    equipe_nom = serializers.CharField(source="equipe.name", read_only=True, default=None)
    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True, default=None)
    dossier_titre = serializers.SerializerMethodField()
    prioritaire = serializers.SerializerMethodField()
    pris_en_compte_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = MessageTerrain
        fields = ["id", "auteur", "auteur_nom", "mission", "dossier", "dossier_numero", "dossier_titre", "equipe", "equipe_nom", "type", "type_libelle", "texte", "nombre",
                  "latitude", "longitude", "canal", "canaux_recus", "emis_le", "recu_le", "prioritaire",
                  "pris_en_compte_le", "pris_en_compte_par_nom"]
        read_only_fields = fields

    def get_auteur_nom(self, obj):
        u = obj.auteur
        return (f"{u.first_name} {u.last_name}".strip() or u.username) if u else ""

    def get_dossier_titre(self, obj):
        return obj.dossier.titre if obj.dossier_id else None

    def get_prioritaire(self, obj):
        return obj.type in mt.PRIORITAIRES

    def get_pris_en_compte_par_nom(self, obj):
        u = obj.pris_en_compte_par
        return (f"{u.first_name} {u.last_name}".strip() or u.username) if u else None


def _voit_la_mission(request, mission) -> bool:
    if get_effective_role(request) in INSTITUTIONAL_TYPES:
        return True
    return mt.peut_ecrire(request.user, mission)


class MessageTerrainViewSet(viewsets.GenericViewSet):
    """POST : un message de terrain (membre d'une équipe de la mission). GET ?mission= : le fil
    de la mission. GET statuts/?mission= : le dernier statut de chaque intervenant."""
    serializer_class = MessageTerrainSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = MessageTerrain.objects.select_related("auteur", "equipe")

    def _mission(self, request, ident):
        mission = Mission.objects.filter(pk=ident).first() if ident else None
        if mission is None:
            raise ValidationError({"error": "Mission introuvable."})
        return mission

    def create(self, request):
        # En formation (X-Environment: DEMO), le compte doit avoir un rôle de démonstration :
        # get_effective_role refuse sinon, comme partout ailleurs.
        get_effective_role(request)
        d = request.data
        type_ = d.get("type")
        if type_ not in MessageTerrain.Type.values:
            raise ValidationError({"error": "Type de message inconnu."})
        mission = self._mission(request, d.get("mission")) if d.get("mission") else None
        dossier = None
        if d.get("dossier"):
            from .models import Dossier
            dossier = Dossier.objects.select_related("mission", "equipe").filter(pk=d.get("dossier")).first()
            if dossier is None:
                raise ValidationError({"error": "Dossier introuvable."})
            mission = mission or dossier.mission
            mon_equipe = dossier.equipe_id and request.user.teams.filter(pk=dossier.equipe_id).exists()
            if not mon_equipe and not (mission is not None and mt.peut_ecrire(request.user, mission)):
                raise PermissionDenied("Ce dossier n'est pas confié à vos équipes.")
        elif mission is not None and not mt.peut_ecrire(request.user, mission):
            raise PermissionDenied("Réservé aux membres des équipes de la mission.")
        if mission is None and not request.user.teams.exists():
            raise PermissionDenied("Réservé aux membres d'une équipe.")
        canal = d.get("canal") if d.get("canal") in MessageTerrain.Canal.values else "DONNEES"
        emis = parse_datetime(d.get("emis_le") or "") if d.get("emis_le") else None
        nombre = d.get("nombre")
        try:
            message, cree = mt.enregistrer(
                request.user, mission, type_, texte=(d.get("texte") or "").strip(),
                nombre=int(nombre) if nombre not in (None, "") else None, latitude=d.get("latitude"),
                longitude=d.get("longitude"), canal=canal, emis_le=emis,
                identifiant_client=(d.get("identifiant_client") or "")[:16], request=request, dossier=dossier)
        except ValueError as exc:
            raise ValidationError({"error": str(exc)})
        return Response(MessageTerrainSerializer(message).data, status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK)

    def list(self, request):
        mission = self._mission(request, request.query_params.get("mission"))
        if not _voit_la_mission(request, mission):
            raise PermissionDenied("Mission non visible.")
        lignes = self.get_queryset().filter(mission=mission)[:300]
        return Response(MessageTerrainSerializer(lignes, many=True).data)

    @action(detail=False, methods=["get"])
    def crise(self, request):
        """GET crise/?crise= : le terrain en direct pour le pilotage (23/11/2026) -- alertes
        Danger et Premiers secours non prises en compte en tête, le dernier statut de chaque
        intervenant sur toutes les missions de la crise, et les derniers messages."""
        from .models import Crisis
        from .permissions import get_active_environment

        if get_effective_role(request) not in INSTITUTIONAL_TYPES:
            raise PermissionDenied("Réservé au poste de commandement.")
        crise = Crisis.objects.filter(pk=request.query_params.get("crise") or None).first()
        if crise is None:
            raise ValidationError({"error": "Crise introuvable."})
        qs = self.get_queryset().select_related("dossier", "pris_en_compte_par").filter(
            crise=crise, environment=get_active_environment(request))
        alertes = qs.filter(type__in=mt.PRIORITAIRES, pris_en_compte_le__isnull=True)
        vus, statuts = set(), []
        for m in qs.exclude(type="SITUATION")[:2000]:
            if m.auteur_id in vus:
                continue
            vus.add(m.auteur_id)
            statuts.append({**MessageTerrainSerializer(m).data, "statut": mt.STATUT_DU_TYPE.get(m.type, m.get_type_display())})
        return Response({
            "alertes": MessageTerrainSerializer(alertes, many=True).data,
            "statuts": statuts,
            "derniers": MessageTerrainSerializer(qs[:40], many=True).data,
        })

    @action(detail=True, methods=["post"], url_path="prendre-en-compte")
    def prendre_en_compte(self, request, pk=None):
        """POST <id>/prendre-en-compte/ : le poste de commandement a vu l'alerte et s'en occupe."""
        from django.utils import timezone

        from .audit import audit_log

        if get_effective_role(request) not in INSTITUTIONAL_TYPES:
            raise PermissionDenied("Réservé au poste de commandement.")
        message = MessageTerrain.objects.select_related("auteur").filter(pk=pk).first()
        if message is None:
            raise ValidationError({"error": "Message introuvable."})
        if message.pris_en_compte_le is None:
            message.pris_en_compte_par = request.user
            message.pris_en_compte_le = timezone.now()
            message.save(update_fields=["pris_en_compte_par", "pris_en_compte_le"])
            audit_log(request=request, action_code="MODIFICATION", objet_type="MessageTerrain", objet_id=message.id,
                      crise=message.crise,
                      commentaire=f"{message.get_type_display()} de {mt._nom(message.auteur)} pris en compte au poste de commandement")
        return Response(MessageTerrainSerializer(message).data)

    @action(detail=False, methods=["get"])
    def statuts(self, request):
        """Le dernier statut connu de chaque intervenant de la mission (le PC le lit)."""
        mission = self._mission(request, request.query_params.get("mission"))
        if not _voit_la_mission(request, mission):
            raise PermissionDenied("Mission non visible.")
        vus, resultat = set(), []
        for m in self.get_queryset().filter(mission=mission).exclude(type="SITUATION"):
            if m.auteur_id in vus:
                continue
            vus.add(m.auteur_id)
            resultat.append({**MessageTerrainSerializer(m).data, "statut": mt.STATUT_DU_TYPE.get(m.type, m.get_type_display())})
        return Response(resultat)

