"""API de la logistique du stock (voir core/stocks_logistique.py) : demandes de transfert entre
points, réservations, « où en a-t-on ? », dotations types, appareils suivis à l'unité."""
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import notifications_dons, stocks, stocks_logistique, stocks_points
from .audit import audit_log
from .models import (
    AppareilStock, ArticleStock, ControleAppareilStock, DemandeTransfertStock, DepotStock, LigneLotTypeStock, LotTypeStock,
    MaterielCatalogue, PointOperationnel, Request, ReservationStock, StatutDemandeTransfert, Team,
)
from .perimetre_admin import institution_regardee, institutions_visibles
from .permissions import INSTITUTIONAL_TYPES, IsInstitutionalActor, _peut_gerer_stock_point, get_active_environment, get_effective_role
from .views_stocks import _StockViewSet, _du_perimetre, _institution_ou_refus


def _erreur(erreur):
    return ValidationError({"detail": str(erreur)})


def _tient(request, point) -> bool:
    """Peut répondre pour ce point : son équipe, ou une institution qui y a du stock."""
    if _peut_gerer_stock_point(request, point):
        return True
    visibles = institutions_visibles(request)
    return get_effective_role(request) in INSTITUTIONAL_TYPES and (
        visibles is None or DepotStock.objects.filter(point=point, institution_id__in=visibles).exists())


# ── Demandes de transfert ────────────────────────────────────────────────────────────────────

class DemandeTransfertSerializer(serializers.ModelSerializer):
    source_nom = serializers.CharField(source="source.nom", read_only=True)
    destination_nom = serializers.CharField(source="destination.nom", read_only=True)
    item_nom = serializers.CharField(source="item.nom", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    demande_par_nom = serializers.SerializerMethodField()
    en_stock_au_depart = serializers.SerializerMethodField()
    je_decide = serializers.SerializerMethodField()
    je_demande = serializers.SerializerMethodField()

    class Meta:
        model = DemandeTransfertStock
        exclude = ["environment"]

    def get_demande_par_nom(self, obj):
        from .views import _nommer_pour
        return _nommer_pour(self.context["request"])(obj.demande_par)

    def get_en_stock_au_depart(self, obj):
        return stocks_points.quantites(obj.source).get(obj.item_id, stocks.ZERO)

    def get_je_decide(self, obj):
        return _tient(self.context["request"], obj.source)

    def get_je_demande(self, obj):
        return obj.demande_par_id == self.context["request"].user.id or _tient(self.context["request"], obj.destination)


class DemandeTransfertViewSet(viewsets.GenericViewSet):
    """`/api/stocks/transferts/` -- on demande, l'autre point accepte (tout ou partie) ou refuse,
    et c'est l'acceptation qui déplace le stock. `?point=` : les demandes qui touchent ce point."""
    queryset = DemandeTransfertStock.objects.select_related("source", "destination", "item", "demande_par")
    serializer_class = DemandeTransfertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset().filter(environment=get_active_environment(self.request))

    def _point(self, identifiant, cle):
        point = PointOperationnel.objects.select_related("crise", "equipe", "responsable").filter(pk=identifiant).first()
        if point is None:
            raise ValidationError({cle: "Point introuvable."})
        return point

    def list(self, request):
        queryset = self.get_queryset()
        if request.query_params.get("point"):
            queryset = queryset.filter(Q(source_id=request.query_params["point"]) | Q(destination_id=request.query_params["point"]))
        if request.query_params.get("crise"):
            queryset = queryset.filter(source__crise_id=request.query_params["crise"])
        visibles = [d for d in queryset[:300] if _tient(request, d.source) or _tient(request, d.destination) or d.demande_par_id == request.user.id]
        return Response(self.get_serializer(visibles, many=True).data)

    def create(self, request):
        """POST {source, destination, item, quantite[, message]} -- par ceux qui tiennent le point d'arrivée."""
        source, destination = self._point(request.data.get("source"), "source"), self._point(request.data.get("destination"), "destination")
        if not _tient(request, destination):
            raise PermissionDenied("Une demande de transfert se fait par ceux qui tiennent le point d'arrivée.")
        item = MaterielCatalogue.objects.filter(pk=request.data.get("item")).first()
        if item is None:
            raise ValidationError({"item": "Besoin du catalogue introuvable."})
        try:
            demande = stocks_logistique.demander_un_transfert(
                source=source, destination=destination, item=item, quantite=request.data.get("quantite"),
                message=request.data.get("message") or "", auteur=request.user, environment=get_active_environment(request))
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="CREATION", objet_type="PointOperationnel", objet_id=source.id, crise=source.crise,
                  commentaire=f"Demande de transfert : {demande.quantite} × {item.nom}, de « {source.nom} » vers « {destination.nom} »")
        # Ceux qui tiennent le point de départ décident : ils sont prévenus.
        institution_source = stocks_points.institution_du_point(source)
        notifications_dons.prevenir(
            de=stocks_points.institution_du_point(destination, a_defaut=institution_regardee(request)), vers=institution_source,
            personnes=source.responsables_effectifs(), request=request, crise=source.crise, environment=demande.environment,
            titre=f"« {destination.nom} » vous demande {demande.quantite} × {item.nom}",
            corps=f"Demande de transfert depuis « {source.nom} » vers « {destination.nom} » : {demande.quantite} × {item.nom}."
                  + (f"\nMessage : {demande.message}" if demande.message else "")
                  + "\nAcceptez (pour tout ou partie) ou refusez depuis la fenêtre « Besoins & stocks » du point : rien ne part sans votre accord.")
        return Response(self.get_serializer(demande).data, status=status.HTTP_201_CREATED)

    def _decider(self, request, pk, accepter):
        demande = self.get_queryset().filter(pk=pk).first()
        if demande is None:
            raise ValidationError({"detail": "Demande introuvable."})
        if not _tient(request, demande.source):
            raise PermissionDenied("La réponse revient à ceux qui tiennent le point de départ.")
        try:
            if accepter:
                stocks_logistique.accepter(demande, quantite=request.data.get("quantite"), reponse=request.data.get("reponse") or "",
                                           auteur=request.user, a_defaut=institution_regardee(request))
            else:
                stocks_logistique.refuser(demande, reponse=request.data.get("reponse") or "", auteur=request.user)
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        demande.refresh_from_db()
        verdict = (f"acceptée : {demande.quantite_accordee} × {demande.item.nom} sont partis" if accepter else "refusée")
        audit_log(request=request, action_code="MODIFICATION", objet_type="PointOperationnel", objet_id=demande.source_id, crise=demande.source.crise,
                  commentaire=f"Demande de transfert vers « {demande.destination.nom} » {verdict}")
        notifications_dons.prevenir(
            de=stocks_points.institution_du_point(demande.source, a_defaut=institution_regardee(request)),
            vers=stocks_points.institution_du_point(demande.destination), personnes=[demande.demande_par], request=request,
            crise=demande.source.crise, environment=demande.environment,
            titre=f"Votre demande à « {demande.source.nom} » est {'acceptée' if accepter else 'refusée'}",
            corps=f"{demande.quantite} × {demande.item.nom} demandés pour « {demande.destination.nom} » : {verdict}."
                  + (f"\nRéponse : {demande.reponse}" if demande.reponse else ""))
        return Response(self.get_serializer(demande).data)

    @action(detail=True, methods=["post"])
    def accepter(self, request, pk=None):
        """POST {[quantite, reponse]} -- le stock part, pour tout ou partie de la demande."""
        return self._decider(request, pk, True)

    @action(detail=True, methods=["post"])
    def refuser(self, request, pk=None):
        return self._decider(request, pk, False)

    @action(detail=True, methods=["post"])
    def annuler(self, request, pk=None):
        """Le demandeur retire sa demande tant qu'elle n'a pas reçu de réponse."""
        demande = self.get_queryset().filter(pk=pk).first()
        if demande is None or not (demande.demande_par_id == request.user.id or _tient(request, demande.destination)):
            raise PermissionDenied("Cette demande n'est pas la vôtre.")
        try:
            stocks_logistique.refuser(demande, auteur=request.user, annuler=True)
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        return Response(self.get_serializer(demande).data)


# ── Disponibilité et réservations ────────────────────────────────────────────────────────────

class DisponibiliteStockView(APIView):
    """GET /api/stocks/disponibilite/?item=<besoin du catalogue>|?demande=<demande>|?recherche=
    -- « on l'a ? où ? ». Pour une demande de matériel d'un habitant, on part de ce qu'elle demande."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        institution, environment = _institution_ou_refus(request), get_active_environment(request)
        item, recherche, demande = None, request.query_params.get("recherche") or "", None
        if request.query_params.get("demande"):
            demande = Request.objects.filter(pk=request.query_params["demande"], environment=environment).first()
            if demande is None:
                raise ValidationError({"demande": "Demande introuvable."})
            item = getattr(demande, "materiel_catalogue", None)
            if item is None and not recherche:
                recherche = (demande.get_materiel_type_display() if getattr(demande, "materiel_type", None) else "") or ""
        elif request.query_params.get("item"):
            item = MaterielCatalogue.objects.filter(pk=request.query_params["item"]).first()
        if item is None and not recherche.strip():
            return Response({"articles": [], "en_stock": False, "cherche": ""})
        articles = stocks_logistique.ou_trouver(institution, environment, item=item, recherche="" if item else recherche)
        return Response({"articles": articles, "en_stock": any(a["libre"] > 0 for a in articles), "cherche": item.nom if item else recherche,
                         "quantite_demandee": getattr(demande, "quantite", None) if demande else None})


class ReservationStockSerializer(serializers.ModelSerializer):
    article_designation = serializers.CharField(source="article.designation", read_only=True)
    unite = serializers.CharField(source="article.unite", read_only=True)
    depot_nom = serializers.CharField(source="depot.nom", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    equipe_nom = serializers.CharField(source="equipe.name", read_only=True, default=None)
    demande_titre = serializers.CharField(source="demande.title", read_only=True, default=None)

    class Meta:
        model = ReservationStock
        exclude = ["environment"]
        read_only_fields = ["statut", "auteur", "date_creation", "date_fin"]


class ReservationStockViewSet(viewsets.GenericViewSet):
    """`/api/stocks/reservations/` -- mettre du stock de côté pour quelqu'un, le lui remettre
    (`servir`) ou le rendre au stock (`liberer`). `?actives=1` : celles qui tiennent encore."""
    queryset = ReservationStock.objects.select_related("article", "depot", "equipe", "demande")
    serializer_class = ReservationStockSerializer
    permission_classes = [IsInstitutionalActor]

    def get_queryset(self):
        return _du_perimetre(self.request, super().get_queryset(), champ="article__institution_id")

    def list(self, request):
        queryset = self.get_queryset()
        if request.query_params.get("actives"):
            queryset = queryset.filter(statut="ACTIVE")
        if request.query_params.get("demande"):
            queryset = queryset.filter(demande_id=request.query_params["demande"])
        return Response(self.get_serializer(queryset[:300], many=True).data)

    def create(self, request):
        article = _du_perimetre(request, ArticleStock.objects.all()).filter(pk=request.data.get("article")).first()
        depot = _du_perimetre(request, DepotStock.objects.all()).filter(pk=request.data.get("depot")).first()
        if article is None or depot is None:
            raise ValidationError({"detail": "Article ou dépôt introuvable dans votre stock."})
        demande = Request.objects.filter(pk=request.data.get("demande")).first() if request.data.get("demande") else None
        equipe = Team.objects.filter(pk=request.data.get("equipe")).first() if request.data.get("equipe") else None
        try:
            reservation = stocks_logistique.reserver(article=article, depot=depot, quantite=request.data.get("quantite"), auteur=request.user,
                                                     demande=demande, equipe=equipe, pour=request.data.get("pour") or "")
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="CREATION", objet_type="ArticleStock", objet_id=article.id,
                  commentaire=f"Stock réservé : {article.reference} dans {depot.nom}")
        return Response(self.get_serializer(reservation).data, status=status.HTTP_201_CREATED)

    def _clore(self, request, pk, geste):
        reservation = self.get_queryset().filter(pk=pk).first()
        if reservation is None:
            raise ValidationError({"detail": "Réservation introuvable."})
        try:
            stocks_logistique.servir(reservation, auteur=request.user) if geste == "servir" else stocks_logistique.liberer(reservation)
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="MODIFICATION", objet_type="ArticleStock", objet_id=reservation.article_id,
                  commentaire=f"Réservation {'servie' if geste == 'servir' else 'annulée'} : {reservation.article.reference}")
        return Response(self.get_serializer(reservation).data)

    @action(detail=True, methods=["post"])
    def servir(self, request, pk=None):
        return self._clore(request, pk, "servir")

    @action(detail=True, methods=["post"])
    def liberer(self, request, pk=None):
        return self._clore(request, pk, "liberer")


# ── Dotations types ──────────────────────────────────────────────────────────────────────────

class LotTypeSerializer(serializers.ModelSerializer):
    lignes = serializers.SerializerMethodField()

    class Meta:
        model = LotTypeStock
        exclude = ["environment"]
        read_only_fields = ["institution", "date_creation"]

    def get_lignes(self, obj):
        return [{"article": str(l.article_id), "designation": l.article.designation, "unite": l.article.unite, "quantite": l.quantite}
                for l in obj.lignes.select_related("article")]


class LotTypeViewSet(_StockViewSet):
    """`/api/stocks/lots-types/` -- la composition d'une dotation (`lignes: [{article, quantite}]`
    remplace la précédente), puis `verifier`, `sortir` et `rentrer` depuis un dépôt."""
    queryset = LotTypeStock.objects.prefetch_related("lignes__article")
    serializer_class = LotTypeSerializer

    def _composer(self, lot):
        if "lignes" not in self.request.data:
            return
        articles = {str(a.id): a for a in ArticleStock.objects.filter(institution=lot.institution, environment=lot.environment)}
        nouvelles = []
        for ligne in self.request.data.get("lignes") or []:
            article = articles.get(str(ligne.get("article")))
            try:
                quantite = stocks.decimal(ligne.get("quantite"))
            except stocks.ErreurStock as erreur:
                raise _erreur(erreur)
            if article is None or quantite <= 0:
                raise ValidationError({"detail": "Chaque ligne demande un article de votre stock et une quantité supérieure à zéro."})
            nouvelles.append(LigneLotTypeStock(lot=lot, article=article, quantite=quantite))
        lot.lignes.all().delete()
        LigneLotTypeStock.objects.bulk_create(nouvelles)

    def perform_create(self, serializer):
        lot = serializer.save(institution=_institution_ou_refus(self.request), environment=get_active_environment(self.request))
        self._composer(lot)

    def perform_update(self, serializer):
        self._composer(serializer.save())

    def _depot(self, request):
        depot = _du_perimetre(request, DepotStock.objects.all()).filter(pk=request.data.get("depot") or request.query_params.get("depot")).first()
        if depot is None:
            raise ValidationError({"depot": "Choisissez le dépôt."})
        return depot

    @action(detail=True, methods=["get"])
    def verifier(self, request, pk=None):
        """GET ?depot= -- ce que la dotation demande, ce qui est libre, ce qui manque."""
        lignes = stocks_logistique.verifier_un_lot(self.get_object(), self._depot(request))
        return Response({"complet": all(l["manque"] == 0 for l in lignes), "lignes": lignes})

    @action(detail=True, methods=["post"])
    def sortir(self, request, pk=None):
        """POST {depot[, equipe, motif]} -- sort toute la dotation, ou rien."""
        lot, depot = self.get_object(), self._depot(request)
        equipe = Team.objects.filter(pk=request.data.get("equipe")).first() if request.data.get("equipe") else None
        try:
            mouvements = stocks_logistique.sortir_un_lot(lot, depot, auteur=request.user, equipe=equipe, motif=request.data.get("motif") or "")
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="MODIFICATION", objet_type="DepotStock", objet_id=depot.id,
                  commentaire=f"Dotation « {lot.nom} » sortie de {depot.nom} ({len(mouvements)} ligne(s))")
        return Response({"lignes": len(mouvements)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def rentrer(self, request, pk=None):
        """POST {depot[, quantites: {article: quantité revenue}, equipe, motif]} -- retour de la dotation."""
        lot, depot = self.get_object(), self._depot(request)
        equipe = Team.objects.filter(pk=request.data.get("equipe")).first() if request.data.get("equipe") else None
        try:
            mouvements = stocks_logistique.rentrer_un_lot(lot, depot, quantites=request.data.get("quantites"), auteur=request.user,
                                                          equipe=equipe, motif=request.data.get("motif") or "")
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="MODIFICATION", objet_type="DepotStock", objet_id=depot.id,
                  commentaire=f"Dotation « {lot.nom} » rentrée dans {depot.nom} ({len(mouvements)} ligne(s))")
        return Response({"lignes": len(mouvements)}, status=status.HTTP_201_CREATED)


# ── Appareils suivis à l'unité ───────────────────────────────────────────────────────────────

class AppareilStockSerializer(serializers.ModelSerializer):
    etat_libelle = serializers.CharField(source="get_etat_display", read_only=True)
    depot_nom = serializers.CharField(source="depot.nom", read_only=True, default=None)
    controle_prochain_le = serializers.DateField(read_only=True)
    controle = serializers.SerializerMethodField()
    controles = serializers.SerializerMethodField()

    class Meta:
        model = AppareilStock
        exclude = ["environment"]
        read_only_fields = ["institution", "date_creation"]

    def get_controle(self, obj):
        """« a_jour », « bientot » (dans les trente jours), « en_retard », ou « » sans contrôle périodique."""
        prochain = obj.controle_prochain_le
        if prochain is None:
            return ""
        jours = (prochain - timezone.localdate()).days
        return "en_retard" if jours < 0 else "bientot" if jours <= 30 else "a_jour"

    def get_controles(self, obj):
        return [{"date": c.date, "conforme": c.conforme, "commentaire": c.commentaire} for c in obj.controles.all()[:5]]


class AppareilStockViewSet(_StockViewSet):
    """`/api/stocks/appareils/` -- un appareil, son état, son contrôle périodique. L'échéance est
    signalée (ici, et dans le relevé d'alertes) ; elle n'empêche jamais de s'en servir."""
    queryset = AppareilStock.objects.select_related("depot", "article").prefetch_related("controles")
    serializer_class = AppareilStockSerializer
    filterset_fields = ["etat", "depot"]

    def _verifier(self, serializer):
        for cle in ("depot", "article"):
            objet = serializer.validated_data.get(cle)
            if objet is not None and not _du_perimetre(self.request, type(objet).objects.filter(pk=objet.pk)).exists():
                raise ValidationError({cle: "Introuvable dans votre stock."})

    def perform_create(self, serializer):
        self._verifier(serializer)
        serializer.save(institution=_institution_ou_refus(self.request), environment=get_active_environment(self.request))

    def perform_update(self, serializer):
        self._verifier(serializer)
        serializer.save()

    @action(detail=True, methods=["post"])
    def controler(self, request, pk=None):
        """POST {[date, conforme, commentaire]} -- un contrôle fait : il repousse l'échéance."""
        appareil = self.get_object()
        date = stocks._date(request.data.get("date")) if request.data.get("date") else timezone.localdate()
        if date is None or date > timezone.localdate():
            raise ValidationError({"date": "Date du contrôle invalide (elle ne peut pas être à venir)."})
        conforme = request.data.get("conforme", True) not in (False, "false", "0", 0)
        ControleAppareilStock.objects.create(appareil=appareil, date=date, conforme=conforme, auteur=request.user,
                                             commentaire=str(request.data.get("commentaire") or ""))
        if appareil.controle_dernier_le is None or date > appareil.controle_dernier_le:
            appareil.controle_dernier_le = date
            appareil.save(update_fields=["controle_dernier_le"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="AppareilStock", objet_id=appareil.id,
                  commentaire=f"Contrôle noté ({'conforme' if conforme else 'à reprendre'}) : {appareil.designation}")
        return Response(self.get_serializer(self.get_queryset().get(pk=appareil.pk)).data)
