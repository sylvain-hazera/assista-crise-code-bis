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


class EngagementPersonnelView(APIView):
    """« Je pars », « je rentre » pour le personnel et les membres d'association — voir
    core/engagements_personnels.py.

    GET : où j'en suis, et sur quelles crises et avec quelles équipes je peux partir.
    POST {geste: "partir", crise, equipe?} ou {geste: "rentrer"}.

    Ouvert à tout compte connecté : c'est l'appartenance à une équipe ou à une institution
    engagée sur la crise qui autorise le départ, pas le rôle sur la plateforme — un bénévole
    d'association est un compte ordinaire."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def _etat(self, request):
        from . import engagements_personnels as ep

        environment = get_active_environment(request)
        ouvert = ep.en_cours(request.user, environment)
        return {
            "en_cours": None if ouvert is None else {
                "crise": str(ouvert.crise_id), "crise_nom": ouvert.crise.name,
                "equipe_nom": ouvert.equipe.name if ouvert.equipe_id else None,
                "parti_le": ouvert.parti_le, "depart_de": ouvert.depart_de,
                "hebergement": ouvert.hebergement,
            },
            # `hebergement` : le logement de la personne sur cette crise si elle y est « en
            # déplacement sur site » — c'est alors de là qu'elle part et là qu'elle rentre.
            "crises": [{"id": str(c.id), "nom": c.name, "hebergement": ep.hebergement_de(request.user, c)}
                       for c in ep.crises_ouvertes_pour(request.user, environment)],
            "equipes": [{"id": str(e.id), "nom": e.name} for e in ep.equipes_de(request.user).order_by("name")],
        }

    def get(self, request):
        return Response(self._etat(request))

    def post(self, request):
        from . import engagements_personnels as ep
        from .models import Team

        environment = get_active_environment(request)
        geste = request.data.get("geste")
        try:
            if geste == "partir":
                crise = Crisis.objects.filter(id=request.data.get("crise"), environment=environment).first() \
                    if request.data.get("crise") else None
                if crise is None:
                    raise ValidationError({"detail": "Indiquez la crise sur laquelle vous partez."})
                equipe = Team.objects.filter(id=request.data.get("equipe")).first() if request.data.get("equipe") else None
                ep.partir(request.user, environment, crise, equipe, depart_de=request.data.get("depart_de"))
            elif geste == "rentrer":
                ep.rentrer(request.user, environment, retour_a=request.data.get("retour_a"))
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(self._etat(request))


def _ligne_de_releve(engagement) -> dict:
    duree = engagement.duree
    return {
        "id": str(engagement.id), "crise": str(engagement.crise_id), "crise_nom": engagement.crise.name,
        "equipe": str(engagement.equipe_id) if engagement.equipe_id else None,
        "equipe_nom": engagement.equipe.name if engagement.equipe_id else "",
        "parti_le": engagement.parti_le, "rentre_le": engagement.rentre_le,
        "depart_de": engagement.depart_de, "retour_a": engagement.retour_a,
        "hebergement": engagement.hebergement, "saisie_manuelle": engagement.saisie_manuelle,
        "heures": round(duree.total_seconds() / 3600, 2) if duree is not None else None,
        "validee": engagement.valide_le is not None, "validee_le": engagement.valide_le,
        "remarque_chef": engagement.remarque_chef,
    }


def _instant(valeur, champ):
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    instant = parse_datetime(str(valeur or ""))
    if instant is None:
        raise ValidationError({"detail": f"{champ} : date et heure attendues."})
    return timezone.make_aware(instant) if timezone.is_naive(instant) else instant


class MonReleveView(APIView):
    """Le relevé d'heures de la personne, en forme de tableau, avec en regard son activité et
    celle de ses équipes pour l'aider à retrouver ce qu'elle a oublié de déclarer.

    GET ?du=AAAA-MM-JJ&au=AAAA-MM-JJ (30 derniers jours par défaut).
    POST : ajoute une sortie oubliée (départ ET retour)."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime

        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from . import engagements_personnels as ep
        from .models import EngagementPersonnel, LieuDeDepart

        environment = get_active_environment(request)
        aujourdhui = timezone.localdate()
        au = parse_date(str(request.query_params.get("au") or "")) or aujourdhui
        du = parse_date(str(request.query_params.get("du") or "")) or au - datetime.timedelta(days=30)
        if du > au or (au - du).days > 366:
            raise ValidationError({"detail": "Période invalide (un an au plus)."})
        debut = timezone.make_aware(datetime.datetime.combine(du, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(au, datetime.time.max))
        lignes = (EngagementPersonnel.objects.filter(
            utilisateur=request.user, environment=environment, parti_le__gte=debut, parti_le__lte=fin)
            .select_related("crise", "equipe").order_by("-parti_le"))
        lignes = [_ligne_de_releve(l) for l in lignes]
        return Response({
            "du": du, "au": au,
            "lignes": lignes,
            "total_heures": round(sum(l["heures"] or 0 for l in lignes), 2),
            "activite": ep.activite(request.user, environment, debut, fin),
            "crises": [{"id": str(c.id), "nom": c.name} for c in ep.crises_declarables(request.user, environment)],
            "equipes": [{"id": str(e.id), "nom": e.name} for e in ep.equipes_de(request.user).order_by("name")],
            "lieux": [{"code": c, "libelle": l} for c, l in LieuDeDepart.choices],
            # Vrai si la personne encadre au moins une équipe : elle a alors un second onglet.
            "encadre": ep.equipes_encadrees(request.user).exists(),
        })

    def post(self, request):
        from . import engagements_personnels as ep
        from .models import Team

        environment = get_active_environment(request)
        crise = Crisis.objects.filter(id=request.data.get("crise"), environment=environment).first() \
            if request.data.get("crise") else None
        if crise is None:
            raise ValidationError({"detail": "Indiquez la crise."})
        equipe = Team.objects.filter(id=request.data.get("equipe")).first() if request.data.get("equipe") else None
        try:
            ligne = ep.completer(
                request.user, environment, crise=crise, equipe=equipe,
                parti_le=_instant(request.data.get("parti_le"), "Départ"),
                rentre_le=_instant(request.data.get("rentre_le"), "Retour"),
                depart_de=request.data.get("depart_de"), retour_a=request.data.get("retour_a"),
            )
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_ligne_de_releve(ligne), status=status.HTTP_201_CREATED)


class MonReleveLigneView(APIView):
    """PATCH : corrige une de SES lignes (le retour oublié, une heure fausse). DELETE : retire
    une ligne qu'on a soi-même ajoutée à la main — une déclaration faite sur le moment se
    corrige, elle ne s'efface pas."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def _ligne(self, request, ligne_id):
        from django.shortcuts import get_object_or_404

        from .models import EngagementPersonnel
        return get_object_or_404(
            EngagementPersonnel.objects.select_related("crise", "equipe"),
            id=ligne_id, utilisateur=request.user, environment=get_active_environment(request))

    def patch(self, request, ligne_id):
        from . import engagements_personnels as ep

        ligne = self._ligne(request, ligne_id)
        donnees = request.data
        try:
            ep.corriger(
                ligne,
                parti_le=_instant(donnees["parti_le"], "Départ") if donnees.get("parti_le") else None,
                rentre_le=_instant(donnees["rentre_le"], "Retour") if donnees.get("rentre_le") else None,
                depart_de=donnees.get("depart_de"), retour_a=donnees.get("retour_a"),
            )
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_ligne_de_releve(ligne))

    def delete(self, request, ligne_id):
        ligne = self._ligne(request, ligne_id)
        if ligne.valide_le is not None:
            raise ValidationError({"detail": "Cette ligne a été validée par votre encadrement."})
        if not ligne.saisie_manuelle:
            raise ValidationError({"detail": (
                "Cette ligne a été déclarée sur le moment : corrigez-la, elle ne se supprime pas."
            )})
        ligne.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RelevesEquipeView(APIView):
    """Les relevés des équipes que l'appelant encadre : il les lit et les valide, il ne les
    corrige pas (décision du 17/11/2026 : seule la personne complète son relevé).

    GET ?du=&au= : les lignes, personne par personne.
    POST {ligne, geste: "valider" | "renvoyer", remarque?}."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime

        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from . import engagements_personnels as ep
        from .views import _nommer_pour

        environment = get_active_environment(request)
        au = parse_date(str(request.query_params.get("au") or "")) or timezone.localdate()
        du = parse_date(str(request.query_params.get("du") or "")) or au - datetime.timedelta(days=30)
        debut = timezone.make_aware(datetime.datetime.combine(du, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(au, datetime.time.max))
        nommer = _nommer_pour(request)
        personnes = {}
        for ligne in ep.a_relire_par(request.user, environment).filter(
                parti_le__gte=debut, parti_le__lte=fin).order_by("utilisateur_id", "-parti_le"):
            fiche = personnes.setdefault(ligne.utilisateur_id, {
                "personne": nommer(ligne.utilisateur) or "Membre d'équipe", "lignes": [],
                "total_heures": 0, "heures_validees": 0, "a_valider": 0,
            })
            donnees = _ligne_de_releve(ligne)
            fiche["lignes"].append(donnees)
            heures = donnees["heures"] or 0
            fiche["total_heures"] = round(fiche["total_heures"] + heures, 2)
            if donnees["validee"]:
                fiche["heures_validees"] = round(fiche["heures_validees"] + heures, 2)
            elif donnees["heures"] is not None and not donnees["remarque_chef"]:
                fiche["a_valider"] += 1
        return Response({
            "du": du, "au": au,
            "fiches": sorted(personnes.values(), key=lambda f: f["personne"].casefold()),
        })

    def post(self, request):
        from django.shortcuts import get_object_or_404

        from . import engagements_personnels as ep
        from .models import EngagementPersonnel

        environment = get_active_environment(request)
        ligne = get_object_or_404(
            EngagementPersonnel.objects.select_related("crise", "equipe"),
            id=request.data.get("ligne"), environment=environment)
        try:
            if request.data.get("geste") == "valider":
                ep.valider(ligne, request.user, environment)
            elif request.data.get("geste") == "renvoyer":
                ep.renvoyer(ligne, request.user, environment, request.data.get("remarque"))
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_ligne_de_releve(ligne))


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
        from .views import _nommer_pour
        return Response(point_situation.construire(
            crise, _institution_ou_refus(request), get_active_environment(request),
            nommer=_nommer_pour(request)))
