"""Cellule de crise dans le pilotage : décisions, actions, relève (23/11/2026).

« Décisions et actions de la cellule : un journal des décisions, distinct de la main courante.
Chaque décision peut produire des actions, avec un responsable, une échéance et un état. » Et
la relève : « une fiche de passation au changement d'équipe, préremplie, signée par celui qui
reprend ».

Même règle que la main courante (JournalCollectiviteViewSet) : chaque institution tient SA
cellule, et ne l'ouvre que sur une crise où elle est impliquée et validée. Tout ce qui est
saisi est chiffré ; chaque geste est inscrit à la main courante de la plateforme.
"""
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .audit import audit_log
from .models import (
    ActionCellule, Crisis, DecisionCellule, ImplicationInstitution, MessageTerrain, ReleveCellule,
    StatutImplication, Team, TypeImplication, UserRole,
)
from .permissions import INSTITUTIONAL_TYPES, get_active_environment, get_effective_role


def _nom(u):
    return (f"{u.first_name} {u.last_name}".strip() or u.username) if u else ""


def institution_de_la_cellule(request, crise):
    """L'institution dont la cellule travaille sur cette crise -- celle du compte, impliquée et
    validée (un administrateur : la sienne, sans condition d'implication)."""
    if get_effective_role(request) not in INSTITUTIONAL_TYPES:
        raise PermissionDenied("Réservé aux cellules de crise des institutions.")
    institution = getattr(request.user, "institution", None)
    if institution is None:
        raise PermissionDenied("Aucune institution associée à votre compte.")
    if get_effective_role(request) == UserRole.ADMINISTRATOR:
        return institution
    implique = ImplicationInstitution.objects.filter(
        crise=crise, institution=institution, actif=True, statut=StatutImplication.VALIDEE,
        type_implication__in=[TypeImplication.ACTEUR, TypeImplication.IMPLIQUE],
    ).exists()
    if not implique:
        raise PermissionDenied("Votre institution doit être impliquée sur cette crise pour en tenir la cellule.")
    return institution


def _crise(request, ident):
    crise = Crisis.objects.filter(pk=ident or None).first()
    if crise is None:
        raise ValidationError({"error": "Crise introuvable."})
    return crise


class ActionCelluleSerializer(serializers.ModelSerializer):
    responsable_nom = serializers.SerializerMethodField()
    equipe_nom = serializers.CharField(source="equipe.name", read_only=True, default=None)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    en_retard = serializers.BooleanField(read_only=True)
    decision_texte = serializers.SerializerMethodField()

    class Meta:
        model = ActionCellule
        fields = ["id", "crise", "decision", "decision_texte", "intitule", "responsable", "responsable_nom", "responsable_libre",
                  "equipe", "equipe_nom", "echeance", "statut", "statut_libelle", "faite_le", "commentaire", "en_retard",
                  "cree_le", "maj_le"]
        read_only_fields = ["id", "crise", "faite_le", "cree_le", "maj_le"]

    def get_responsable_nom(self, obj):
        return _nom(obj.responsable) if obj.responsable_id else obj.responsable_libre

    def get_decision_texte(self, obj):
        return obj.decision.texte if obj.decision_id else None


class DecisionCelluleSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()
    actions = ActionCelluleSerializer(many=True, read_only=True)

    class Meta:
        model = DecisionCellule
        fields = ["id", "crise", "texte", "auteur_nom", "decidee_le", "actions"]
        read_only_fields = ["id", "crise", "auteur_nom", "actions"]

    def get_auteur_nom(self, obj):
        return _nom(obj.auteur)


def _valider_responsable(institution, data):
    """Un responsable avec compte doit être de l'institution ; une équipe, de l'institution aussi."""
    responsable = data.get("responsable")
    if responsable and not (responsable.institution_id == institution.id
                            or responsable.institutions.filter(institution=institution, actif=True).exists()):
        raise ValidationError({"error": "Le responsable doit être un membre de votre institution (ou saisi en texte libre)."})
    equipe = data.get("equipe")
    if equipe and equipe.institution_id != institution.id:
        raise ValidationError({"error": "Cette équipe n'est pas de votre institution."})


class DecisionCelluleViewSet(viewsets.GenericViewSet):
    """GET ?crise= : les décisions de ma cellule, avec leurs actions. POST : une décision et ses
    actions d'un coup ({crise, texte, decidee_le?, actions: [{intitule, responsable?,
    responsable_libre?, equipe?, echeance?}]})."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DecisionCelluleSerializer

    def list(self, request):
        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        qs = DecisionCellule.objects.filter(crise=crise, institution=institution, environment=get_active_environment(request)) \
            .select_related("auteur").prefetch_related("actions__responsable", "actions__equipe")
        return Response(DecisionCelluleSerializer(qs, many=True).data)

    def create(self, request):
        crise = _crise(request, request.data.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        texte = (request.data.get("texte") or "").strip()
        if not texte:
            raise ValidationError({"error": "Quelle décision ?"})
        decidee = parse_datetime(request.data.get("decidee_le") or "") or timezone.now()
        actions = request.data.get("actions") or []
        if not isinstance(actions, list):
            raise ValidationError({"error": "actions : une liste."})
        validees = []
        for a in actions:
            s = ActionCelluleSerializer(data=a)
            s.is_valid(raise_exception=True)
            _valider_responsable(institution, s.validated_data)
            validees.append(s)
        env = get_active_environment(request)
        decision = DecisionCellule.objects.create(crise=crise, institution=institution, auteur=request.user,
                                                  texte=texte[:4000], decidee_le=decidee, environment=env)
        for s in validees:
            s.save(crise=crise, institution=institution, decision=decision, cree_par=request.user, environment=env)
        audit_log(request=request, action_code="CREATION", objet_type="DecisionCellule", objet_id=decision.id, crise=crise,
                  commentaire=f"Décision de cellule ({institution.nom}), {len(validees)} action(s)")
        return Response(DecisionCelluleSerializer(decision).data, status=status.HTTP_201_CREATED)


class ActionCelluleViewSet(viewsets.GenericViewSet):
    """GET ?crise=[&miennes=1] : les actions de ma cellule. POST : une action (avec ou sans
    décision). PATCH <id> : statut, échéance, responsable, commentaire."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ActionCelluleSerializer

    def list(self, request):
        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        qs = ActionCellule.objects.filter(crise=crise, institution=institution, environment=get_active_environment(request)) \
            .select_related("responsable", "equipe", "decision")
        if request.query_params.get("miennes") in ("1", "true"):
            qs = qs.filter(responsable=request.user)
        return Response(ActionCelluleSerializer(qs, many=True).data)

    def create(self, request):
        crise = _crise(request, request.data.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        s = ActionCelluleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        decision = s.validated_data.get("decision")
        if decision and (decision.crise_id != crise.id or decision.institution_id != institution.id):
            raise ValidationError({"error": "Cette décision n'est pas de votre cellule."})
        _valider_responsable(institution, s.validated_data)
        action_ = s.save(crise=crise, institution=institution, cree_par=request.user, environment=get_active_environment(request))
        audit_log(request=request, action_code="CREATION", objet_type="ActionCellule", objet_id=action_.id, crise=crise,
                  commentaire=f"Action de cellule ({institution.nom})")
        return Response(ActionCelluleSerializer(action_).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        action_ = ActionCellule.objects.select_related("crise").filter(pk=pk).first()
        if action_ is None:
            raise ValidationError({"error": "Action introuvable."})
        institution = institution_de_la_cellule(request, action_.crise)
        if action_.institution_id != institution.id:
            raise PermissionDenied("Cette action n'est pas de votre cellule.")
        ancien = action_.statut
        s = ActionCelluleSerializer(action_, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        _valider_responsable(institution, s.validated_data)
        action_ = s.save()
        if action_.statut == ActionCellule.Statut.FAIT and ancien != ActionCellule.Statut.FAIT:
            action_.faite_le = timezone.now()
            action_.save(update_fields=["faite_le"])
        elif action_.statut != ActionCellule.Statut.FAIT and action_.faite_le:
            action_.faite_le = None
            action_.save(update_fields=["faite_le"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="ActionCellule", objet_id=action_.id, crise=action_.crise,
                  commentaire=f"Action de cellule : {action_.get_statut_display()}" + ("" if ancien == action_.statut else f" (était : {ActionCellule.Statut(ancien).label})"))
        return Response(ActionCelluleSerializer(action_).data)


def instantane(crise, institution, environment, depuis=None):
    """L'état de la cellule à passer à la relève : chiffres, décisions depuis la dernière relève
    (ou 12 h), actions ouvertes, alertes du terrain non prises en compte."""
    from datetime import timedelta

    from .models import Dossier

    depuis = depuis or (timezone.now() - timedelta(hours=12))
    dossiers = Dossier.objects.filter(crise=crise, environment=environment).exclude(statut__in=["CLOTURE", "RESOLU"])
    actions = ActionCellule.objects.filter(crise=crise, institution=institution, environment=environment,
                                           statut__in=[ActionCellule.Statut.A_FAIRE, ActionCellule.Statut.EN_COURS]) \
        .select_related("responsable", "equipe")
    decisions = DecisionCellule.objects.filter(crise=crise, institution=institution, environment=environment, decidee_le__gte=depuis)
    alertes = MessageTerrain.objects.filter(crise=crise, environment=environment, type__in=["DANGER", "PREMIERS_SECOURS"],
                                            pris_en_compte_le__isnull=True).select_related("auteur")
    return {
        "le": timezone.now().isoformat(),
        "chiffres": {
            "dossiers_ouverts": dossiers.count(),
            "dossiers_urgents": dossiers.filter(Q(priorite="URGENTE") | Q(important=True)).count(),
            "dossiers_sans_equipe": dossiers.filter(equipe__isnull=True).count(),
            "equipes_engagees": Team.objects.filter(assigned_crises=crise, actif=True).count(),
        },
        "decisions": [{"le": d.decidee_le.isoformat(), "texte": d.texte} for d in decisions],
        "actions_ouvertes": [{"intitule": a.intitule, "responsable": _nom(a.responsable) if a.responsable_id else a.responsable_libre,
                              "echeance": a.echeance.isoformat() if a.echeance else None, "statut": a.get_statut_display(),
                              "en_retard": a.en_retard} for a in actions],
        "alertes_terrain": [{"type": m.get_type_display(), "auteur": _nom(m.auteur), "le": m.emis_le.isoformat(), "texte": m.texte}
                            for m in alertes],
    }


class ReleveCelluleSerializer(serializers.ModelSerializer):
    redigee_par_nom = serializers.SerializerMethodField()
    reprise_par_nom = serializers.SerializerMethodField()
    instantane = serializers.SerializerMethodField()

    class Meta:
        model = ReleveCellule
        fields = ["id", "crise", "redigee_par_nom", "redigee_le", "instantane", "points_vigilance", "reprise_par_nom", "reprise_le"]
        read_only_fields = fields

    def get_redigee_par_nom(self, obj):
        return _nom(obj.redigee_par)

    def get_instantane(self, obj):
        """Le champ chiffré rend un objet relu de la base, mais un texte juste après création."""
        import json
        valeur = obj.instantane
        if isinstance(valeur, str):
            try:
                return json.loads(valeur)
            except ValueError:
                return {}
        return valeur or {}

    def get_reprise_par_nom(self, obj):
        return _nom(obj.reprise_par) if obj.reprise_par_id else None


class ReleveCelluleViewSet(viewsets.GenericViewSet):
    """GET ?crise= : les relèves de ma cellule. GET apercu/?crise= : l'instantané qu'une relève
    contiendrait maintenant. POST {crise, points_vigilance} : rédiger. POST <id>/reprendre/ : la
    reprendre (un autre compte que le rédacteur)."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReleveCelluleSerializer

    def list(self, request):
        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        qs = ReleveCellule.objects.filter(crise=crise, institution=institution, environment=get_active_environment(request)) \
            .select_related("redigee_par", "reprise_par")
        return Response(ReleveCelluleSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def apercu(self, request):
        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        env = get_active_environment(request)
        derniere = ReleveCellule.objects.filter(crise=crise, institution=institution, environment=env).first()
        return Response(instantane(crise, institution, env, depuis=derniere.redigee_le if derniere else None))

    def create(self, request):
        crise = _crise(request, request.data.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        env = get_active_environment(request)
        derniere = ReleveCellule.objects.filter(crise=crise, institution=institution, environment=env).first()
        releve = ReleveCellule.objects.create(
            crise=crise, institution=institution, redigee_par=request.user, environment=env,
            instantane=instantane(crise, institution, env, depuis=derniere.redigee_le if derniere else None),
            points_vigilance=(request.data.get("points_vigilance") or "").strip()[:4000])
        audit_log(request=request, action_code="CREATION", objet_type="ReleveCellule", objet_id=releve.id, crise=crise,
                  commentaire=f"Relève de la cellule rédigée ({institution.nom})")
        return Response(ReleveCelluleSerializer(releve).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reprendre(self, request, pk=None):
        releve = ReleveCellule.objects.select_related("crise", "redigee_par").filter(pk=pk).first()
        if releve is None:
            raise ValidationError({"error": "Relève introuvable."})
        institution = institution_de_la_cellule(request, releve.crise)
        if releve.institution_id != institution.id:
            raise PermissionDenied("Cette relève n'est pas de votre cellule.")
        if releve.redigee_par_id == request.user.id:
            raise ValidationError({"error": "La relève se reprend par la personne qui arrive, pas par celle qui part."})
        if releve.reprise_le:
            raise ValidationError({"error": f"Déjà reprise par {_nom(releve.reprise_par)}."})
        releve.reprise_par = request.user
        releve.reprise_le = timezone.now()
        releve.save(update_fields=["reprise_par", "reprise_le"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="ReleveCellule", objet_id=releve.id, crise=releve.crise,
                  commentaire=f"Relève de la cellule reprise ({institution.nom})")
        return Response(ReleveCelluleSerializer(releve).data)
