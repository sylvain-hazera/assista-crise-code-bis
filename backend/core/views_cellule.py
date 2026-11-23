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


# ── Lot D (23/11/2026) : chronologie, points de situation, RETEX ──────────────────────────────

def _json(valeur):
    """Un champ JSON chiffré : objet relu de la base, texte juste après création."""
    import json
    if isinstance(valeur, str):
        try:
            return json.loads(valeur)
        except ValueError:
            return {}
    return valeur or {}


class ChronologieViewSet(viewsets.GenericViewSet):
    """GET ?crise= : la chronologie -- jalons saisis par ma cellule, et jalons automatiques
    (ouverture de la crise, décisions, centres ouverts et fermés, missions, points de situation,
    relèves). POST {crise, libelle, survenu_le?, journal?} : un jalon (ou une entrée de main
    courante marquée comme jalon)."""
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        from .models import JalonCrise, Mission, PointOperationnel, PointSituation

        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        env = get_active_environment(request)
        jalons = [{"le": crise.start_date.isoformat(), "genre": "CRISE", "libelle": f"Ouverture de la crise « {crise.name} »"}] \
            if crise.start_date else []
        for j in JalonCrise.objects.filter(crise=crise, institution=institution, environment=env).select_related("auteur"):
            jalons.append({"le": j.survenu_le.isoformat(), "genre": "JALON", "libelle": j.libelle, "par": _nom(j.auteur), "id": str(j.id)})
        for d in DecisionCellule.objects.filter(crise=crise, institution=institution, environment=env):
            jalons.append({"le": d.decidee_le.isoformat(), "genre": "DECISION", "libelle": d.texte})
        for p in PointOperationnel.objects.filter(crise=crise, environment=env).select_related("type"):
            libelle = p.type.libelle if p.type_id else "Point"
            if p.date_ouverture:
                jalons.append({"le": p.date_ouverture.isoformat(), "genre": "CENTRE", "libelle": f"Ouverture : {p.nom} ({libelle})"})
            if p.date_fermeture:
                jalons.append({"le": p.date_fermeture.isoformat(), "genre": "CENTRE", "libelle": f"Fermeture : {p.nom}"})
        for m in Mission.objects.filter(crise=crise, environment=env):
            if m.date_creation:
                jalons.append({"le": m.date_creation.isoformat(), "genre": "MISSION", "libelle": f"Mission engagée : {m.titre}"})
        for p in PointSituation.objects.filter(crise=crise, institution=institution, environment=env):
            jalons.append({"le": p.diffuse_le.isoformat(), "genre": "POINT", "libelle": "Point de situation diffusé"})
        for r in ReleveCellule.objects.filter(crise=crise, institution=institution, environment=env):
            jalons.append({"le": r.redigee_le.isoformat(), "genre": "RELEVE", "libelle": "Relève de la cellule"})
        jalons.sort(key=lambda j: j["le"], reverse=True)
        return Response(jalons)

    def create(self, request):
        from .models import JalonCrise, JournalCollectivite

        crise = _crise(request, request.data.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        journal = None
        libelle = (request.data.get("libelle") or "").strip()
        if request.data.get("journal"):
            journal = JournalCollectivite.objects.filter(pk=request.data["journal"], crise=crise, institution=institution).first()
            if journal is None:
                raise ValidationError({"error": "Entrée de main courante introuvable."})
            libelle = libelle or journal.contenu
        if not libelle:
            raise ValidationError({"error": "Quel jalon ?"})
        survenu = parse_datetime(request.data.get("survenu_le") or "") or (journal.date_creation if journal else timezone.now())
        jalon = JalonCrise.objects.create(crise=crise, institution=institution, libelle=libelle[:2000], survenu_le=survenu,
                                          auteur=request.user, journal=journal, environment=get_active_environment(request))
        audit_log(request=request, action_code="CREATION", objet_type="JalonCrise", objet_id=jalon.id, crise=crise,
                  commentaire=f"Jalon de la chronologie ({institution.nom})")
        return Response({"id": str(jalon.id), "le": jalon.survenu_le.isoformat(), "libelle": jalon.libelle}, status=status.HTTP_201_CREATED)


def _chiffres_du_point(crise, institution, env):
    """Les chiffres du moment pour un point de situation : ceux de la relève et des tableaux."""
    from . import pilotage_situation
    base = instantane(crise, institution, env)
    tableaux = pilotage_situation.situation(crise, env)
    return {
        "le": base["le"], "chiffres": base["chiffres"],
        "accueil": {k: tableaux["accueil"].get(k) for k in ("places", "presents", "mises_en_securite", "relogement")}
                   if "erreur" not in tableaux["accueil"] else None,
        "degats": {k: tableaux["degats"].get(k) for k in ("par_statut", "evalues", "part_evaluee")}
                  if "erreur" not in tableaux["degats"] else None,
        "alertes_terrain": len(base["alertes_terrain"]),
        "actions_ouvertes": len(base["actions_ouvertes"]),
    }


class PointSituationViewSet(viewsets.GenericViewSet):
    """GET ?crise= : les points de ma cellule, et la cadence (prochain point dû). GET apercu/ :
    les chiffres qu'un point contiendrait maintenant. POST {crise, texte} : diffuser.
    POST cadence/ {crise, heures} : fixer la cadence (vide : aucun rappel)."""
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        from datetime import timedelta

        from .models import PointSituation

        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        points = list(PointSituation.objects.filter(crise=crise, institution=institution, environment=get_active_environment(request))
                      .select_related("redige_par")[:50])
        dernier = points[0].diffuse_le if points else crise.start_date
        echeance = (dernier + timedelta(hours=crise.cadence_points_h)) if (crise.cadence_points_h and dernier) else None
        return Response({
            "cadence_h": crise.cadence_points_h,
            "prochain": echeance.isoformat() if echeance else None,
            "du": bool(echeance and echeance <= timezone.now()),
            "points": [{"id": str(p.id), "diffuse_le": p.diffuse_le.isoformat(), "redige_par": _nom(p.redige_par), "texte": p.texte,
                        "instantane": _json(p.instantane)} for p in points],
        })

    @action(detail=False, methods=["get"])
    def apercu(self, request):
        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        return Response(_chiffres_du_point(crise, institution, get_active_environment(request)))

    def create(self, request):
        from .models import PointSituation

        crise = _crise(request, request.data.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        env = get_active_environment(request)
        point = PointSituation.objects.create(crise=crise, institution=institution, redige_par=request.user, environment=env,
                                              texte=(request.data.get("texte") or "").strip()[:8000],
                                              instantane=_chiffres_du_point(crise, institution, env))
        audit_log(request=request, action_code="CREATION", objet_type="PointSituation", objet_id=point.id, crise=crise,
                  commentaire=f"Point de situation diffusé ({institution.nom})")
        return Response({"id": str(point.id), "diffuse_le": point.diffuse_le.isoformat(), "redige_par": _nom(request.user),
                         "texte": point.texte, "instantane": _json(point.instantane)}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def cadence(self, request):
        crise = _crise(request, request.data.get("crise"))
        institution_de_la_cellule(request, crise)
        heures = request.data.get("heures")
        try:
            heures = int(heures) if heures not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            raise ValidationError({"error": "Une cadence en heures (1 à 48), ou vide."})
        if heures is not None and not 1 <= heures <= 48:
            raise ValidationError({"error": "Une cadence en heures (1 à 48), ou vide."})
        crise.cadence_points_h = heures
        crise.save(update_fields=["cadence_points_h"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="Crisis", objet_id=crise.id, crise=crise,
                  commentaire=f"Cadence des points de situation : {f'toutes les {heures} h' if heures else 'aucune'}")
        return Response({"cadence_h": heures})


def delais_intervention(crise, environment):
    """Délais d'intervention en agrégats (médianes, en minutes), sans aucune donnée nominative :
    dossier créé → affecté → « arrivé sur les lieux » (bouton de terrain) → résolu."""
    import statistics

    from django.db.models import Min

    from .models import Dossier

    dossiers = list(Dossier.objects.filter(crise=crise, environment=environment)
                    .values("id", "date_creation", "date_affectation", "date_resolution"))
    arrivees = dict(MessageTerrain.objects.filter(crise=crise, environment=environment, type="ARRIVE", dossier__isnull=False)
                    .values_list("dossier_id").annotate(m=Min("emis_le")).values_list("dossier_id", "m"))

    def mediane(paires):
        minutes = [(b - a).total_seconds() / 60 for a, b in paires if a and b and b >= a]
        return {"mediane_min": round(statistics.median(minutes)) if minutes else None, "nombre": len(minutes)}

    return {
        "dossiers": len(dossiers),
        "creation_affectation": mediane((d["date_creation"], d["date_affectation"]) for d in dossiers),
        "affectation_arrivee": mediane((d["date_affectation"], arrivees.get(d["id"])) for d in dossiers),
        "creation_resolution": mediane((d["date_creation"], d["date_resolution"]) for d in dossiers),
    }


class RetexViewSet(viewsets.GenericViewSet):
    """GET ?crise= : le RETEX de ma cellule et le rapport de clôture (chronologie, décisions et
    actions, délais d'intervention). PUT/POST {crise, ce_qui_a_marche, ce_qui_a_manque,
    ameliorations} : l'enregistrer."""
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        from .models import RetexCrise

        crise = _crise(request, request.query_params.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        env = get_active_environment(request)
        retex = RetexCrise.objects.filter(crise=crise, institution=institution, environment=env).select_related("maj_par").first()
        actions = ActionCellule.objects.filter(crise=crise, institution=institution, environment=env)
        faites = [a for a in actions if a.statut == ActionCellule.Statut.FAIT and a.faite_le]
        return Response({
            "crise": {"nom": crise.name, "debut": crise.start_date.isoformat() if crise.start_date else None,
                      "fin": crise.end_date.isoformat() if crise.end_date else None},
            "retex": {"ce_qui_a_marche": retex.ce_qui_a_marche, "ce_qui_a_manque": retex.ce_qui_a_manque,
                      "ameliorations": retex.ameliorations, "maj_par": _nom(retex.maj_par), "maj_le": retex.maj_le.isoformat()}
                     if retex else None,
            "decisions": DecisionCellule.objects.filter(crise=crise, institution=institution, environment=env).count(),
            "actions": {"total": actions.count(), "faites": len(faites),
                        "faites_en_retard": sum(1 for a in faites if a.echeance and a.faite_le > a.echeance),
                        "ouvertes": actions.filter(statut__in=[ActionCellule.Statut.A_FAIRE, ActionCellule.Statut.EN_COURS]).count()},
            "delais": delais_intervention(crise, env),
        })

    def create(self, request):
        from .models import RetexCrise

        crise = _crise(request, request.data.get("crise"))
        institution = institution_de_la_cellule(request, crise)
        env = get_active_environment(request)
        retex, _ = RetexCrise.objects.get_or_create(crise=crise, institution=institution, environment=env)
        for champ in ("ce_qui_a_marche", "ce_qui_a_manque", "ameliorations"):
            if champ in request.data:
                setattr(retex, champ, (request.data.get(champ) or "").strip()[:8000])
        retex.maj_par = request.user
        retex.save()
        audit_log(request=request, action_code="MODIFICATION", objet_type="RetexCrise", objet_id=retex.id, crise=crise,
                  commentaire=f"Retour d'expérience mis à jour ({institution.nom})")
        return Response({"ok": True, "maj_le": retex.maj_le.isoformat()})
