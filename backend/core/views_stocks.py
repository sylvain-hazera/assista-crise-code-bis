"""API de la gestion des stocks (voir core/stocks.py) : `/api/stocks/…`.

Réservée aux acteurs institutionnels. Chacun voit et tient le stock de SON institution ;
l'administrateur celui de l'institution qu'il regarde (ou tous, en lecture de liste)."""
from django.db.models import ProtectedError, Sum
from django.http import HttpResponse
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView

from . import stocks, stocks_echanges, stocks_points
from .audit import audit_log
from .models import (
    ArticleStock, CommandeStock, Crisis, DepotStock, Document, EtatMaterielPrete, FactureStock, MaterielCatalogue, MaterielPoint,
    Mission, MouvementStock, PointOperationnel, PretMateriel, SensPret, StatutCommandeStock, StatutPret, Team, TiersStock,
    TypeMouvementStock,
)
from .perimetre_admin import institution_regardee, institutions_visibles
from .permissions import INSTITUTIONAL_TYPES, IsInstitutionalActor, _peut_gerer_stock_point, get_active_environment, get_effective_role


def _du_perimetre(request, queryset, champ="institution_id"):
    """Réduit aux institutions de l'appelant, dans la zone (PROD/DEMO) de la requête."""
    queryset = queryset.filter(environment=get_active_environment(request))
    visibles = institutions_visibles(request)
    return queryset if visibles is None else queryset.filter(**{f"{champ}__in": visibles})


def _institution_ou_refus(request):
    institution = institution_regardee(request)
    if institution is None:
        raise PermissionDenied("Votre compte n'est rattaché à aucune institution : le stock est tenu par institution.")
    return institution


def _nom(utilisateur, request):
    from .views import _nommer_pour
    return _nommer_pour(request)(utilisateur)


class DepotStockSerializer(serializers.ModelSerializer):
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = DepotStock
        exclude = ["location", "environment"]
        read_only_fields = ["institution", "point", "date_creation"]

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None


class ArticleStockSerializer(serializers.ModelSerializer):
    categorie_libelle = serializers.CharField(source="get_categorie_display", read_only=True)

    class Meta:
        model = ArticleStock
        exclude = ["environment"]
        # Le coût moyen se recalcule aux entrées valorisées ; on peut aussi le poser à la main.
        read_only_fields = ["institution", "date_creation", "date_maj"]


class MouvementStockSerializer(serializers.ModelSerializer):
    article_designation = serializers.CharField(source="article.designation", read_only=True)
    article_reference = serializers.CharField(source="article.reference", read_only=True)
    unite = serializers.CharField(source="article.unite", read_only=True)
    depot_nom = serializers.CharField(source="depot.nom", read_only=True)
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    mission_titre = serializers.CharField(source="mission.titre", read_only=True, default=None)
    equipe_nom = serializers.CharField(source="equipe.name", read_only=True, default=None)
    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = MouvementStock
        exclude = ["environment"]

    def get_auteur_nom(self, obj):
        return _nom(obj.auteur, self.context.get("request")) if obj.auteur else ""


class _StockViewSet(viewsets.ModelViewSet):
    permission_classes = [IsInstitutionalActor]

    def get_queryset(self):
        return _du_perimetre(self.request, super().get_queryset())

    def perform_destroy(self, instance):
        # Un article ou un dépôt qui a des mouvements ne se supprime pas : l'historique en dépend.
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError({"detail": "Des mouvements de stock y sont attachés : désactivez-le plutôt que de le supprimer."})


class DepotStockViewSet(_StockViewSet):
    """Les lieux où le stock est rangé : local, garage, armoire, véhicule…"""
    queryset = DepotStock.objects.select_related("institution").order_by("nom")
    serializer_class = DepotStockSerializer

    def _unique(self, serializer, institution, sauf=None):
        nom = (serializer.validated_data.get("nom") or "").strip()
        memes = DepotStock.objects.filter(institution=institution, environment=get_active_environment(self.request), nom__iexact=nom)
        if nom and memes.exclude(pk=sauf).exists():
            raise ValidationError({"nom": "Un dépôt porte déjà ce nom."})

    def _point(self):
        from django.contrib.gis.geos import Point
        donnees = self.request.data
        if donnees.get("latitude") in (None, "") or donnees.get("longitude") in (None, ""):
            return {}
        try:
            return {"location": Point(float(donnees["longitude"]), float(donnees["latitude"]), srid=4326)}
        except (TypeError, ValueError):
            raise ValidationError({"latitude": "Position invalide."})

    def perform_create(self, serializer):
        institution = _institution_ou_refus(self.request)
        self._unique(serializer, institution)
        depot = serializer.save(institution=institution, environment=get_active_environment(self.request), **self._point())
        audit_log(request=self.request, action_code="CREATION", objet_type="DepotStock", objet_id=depot.id,
                  commentaire=f"Dépôt de stock créé : {depot.nom}")

    def perform_update(self, serializer):
        self._unique(serializer, serializer.instance.institution, sauf=serializer.instance.pk)
        depot = serializer.save(**self._point())
        audit_log(request=self.request, action_code="MODIFICATION", objet_type="DepotStock", objet_id=depot.id,
                  commentaire=f"Dépôt de stock modifié : {depot.nom}")


class ArticleStockViewSet(_StockViewSet):
    """Ce que l'institution tient en stock : une référence, un libellé, une unité, un seuil."""
    queryset = ArticleStock.objects.select_related("institution").order_by("designation")
    serializer_class = ArticleStockSerializer

    def _unique(self, serializer, institution, sauf=None):
        reference = (serializer.validated_data.get("reference") or "").strip()
        memes = ArticleStock.objects.filter(institution=institution, environment=get_active_environment(self.request),
                                            reference__iexact=reference)
        if reference and memes.exclude(pk=sauf).exists():
            raise ValidationError({"reference": "Un article porte déjà cette référence."})

    def perform_create(self, serializer):
        institution = _institution_ou_refus(self.request)
        self._unique(serializer, institution)
        article = serializer.save(institution=institution, environment=get_active_environment(self.request))
        audit_log(request=self.request, action_code="CREATION", objet_type="ArticleStock", objet_id=article.id,
                  commentaire=f"Article de stock créé : {article.reference} — {article.designation}")

    def perform_update(self, serializer):
        self._unique(serializer, serializer.instance.institution, sauf=serializer.instance.pk)
        article = serializer.save()
        audit_log(request=self.request, action_code="MODIFICATION", objet_type="ArticleStock", objet_id=article.id,
                  commentaire=f"Article de stock modifié : {article.reference} — {article.designation}")


class MouvementStockViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Le journal des mouvements. On y ajoute, on n'y corrige rien : une erreur se rattrape par
    un mouvement contraire ou par un inventaire (voir core/stocks.py)."""
    queryset = MouvementStock.objects.select_related("article", "depot", "crise", "mission", "equipe", "auteur").order_by(
        "-date_mouvement", "-date_creation")
    serializer_class = MouvementStockSerializer
    permission_classes = [IsInstitutionalActor]
    filterset_fields = ["article", "depot", "type", "crise", "mission", "equipe"]

    def get_queryset(self):
        return _du_perimetre(self.request, super().get_queryset(), champ="article__institution_id")

    def _objet(self, modele, cle, champ="institution_id", obligatoire=True):
        identifiant = self.request.data.get(cle)
        if not identifiant:
            if obligatoire:
                raise ValidationError({cle: "Obligatoire."})
            return None
        objet = _du_perimetre(self.request, modele.objects.all(), champ=champ).filter(pk=identifiant).first()
        if objet is None:
            raise ValidationError({cle: "Introuvable dans votre stock."})
        return objet

    def _lie(self, modele, cle):
        identifiant = self.request.data.get(cle)
        return modele.objects.filter(pk=identifiant).first() if identifiant else None

    def create(self, request, *args, **kwargs):
        """POST /api/stocks/mouvements/ {article, depot, type, quantite[, depot_destination, lot,
        date_peremption, prix_unitaire, motif, tiers, crise, mission, equipe]}.

        `quantite` est toujours positive : entrée, sortie, quantité déplacée (TRANSFERT, avec
        `depot_destination`) ou quantité COMPTÉE (INVENTAIRE)."""
        donnees = request.data
        article, depot = self._objet(ArticleStock, "article"), self._objet(DepotStock, "depot")
        type_mouvement = donnees.get("type")
        if type_mouvement not in TypeMouvementStock.values:
            raise ValidationError({"type": "Type de mouvement inconnu."})
        if not (article.actif and depot.actif) and type_mouvement == TypeMouvementStock.ENTREE:
            raise ValidationError({"detail": "Cet article ou ce dépôt est désactivé : on n'y fait plus d'entrée."})
        peremption = stocks._date(donnees.get("date_peremption")) if donnees.get("date_peremption") else None
        if donnees.get("date_peremption") and peremption is None:
            raise ValidationError({"date_peremption": "Date invalide."})
        commun = {"article": article, "quantite": donnees.get("quantite"), "auteur": request.user, "lot": donnees.get("lot") or "",
                  "date_peremption": peremption, "motif": donnees.get("motif") or ""}
        try:
            if type_mouvement == TypeMouvementStock.TRANSFERT:
                sortie, entree = stocks.transferer(source=depot, destination=self._objet(DepotStock, "depot_destination"), **commun)
                rendus, resume = [sortie, entree], f"transfert de {depot.nom} vers {entree.depot.nom}"
            else:
                prix = donnees.get("prix_unitaire")
                mouvement = stocks.enregistrer(
                    depot=depot, type_mouvement=type_mouvement, prix_unitaire=prix if prix not in (None, "") else None,
                    tiers=donnees.get("tiers") or "", crise=self._lie(Crisis, "crise"), mission=self._lie(Mission, "mission"),
                    equipe=self._lie(Team, "equipe"), **commun)
                if mouvement is None:
                    return Response({"detail": "Le compte correspond déjà au stock enregistré : rien à corriger.", "mouvements": []})
                rendus, resume = [mouvement], f"{mouvement.get_type_display().lower()} — dépôt {depot.nom}"
        except stocks.ErreurStock as erreur:
            raise ValidationError({"detail": str(erreur)})
        # Un mouvement saisi ici sur le dépôt d'un point d'accueil met aussi à jour sa ligne de stock.
        for mouvement in rendus:
            if mouvement.depot.point_id:
                stocks_points.synchroniser(mouvement.depot.point, stocks_points.item_de(article), mouvement.environment)
        audit_log(request=request, action_code="CREATION", objet_type="MouvementStock", objet_id=rendus[0].id,
                  crise=rendus[0].crise, commentaire=f"Stock : {article.reference} — {resume}")
        arrivee = next((m.depot for m in rendus if m.quantite > 0), None)
        manques = stocks.manques_du_lieu(article, arrivee) if arrivee is not None else []
        return Response({"mouvements": MouvementStockSerializer(rendus, many=True, context={"request": request}).data,
                         "stock": str(stocks.quantite_en_stock(article)),
                         "avertissement": f"Attention — « {article.designation} » est {' ; '.join(manques)} ({arrivee.nom})." if manques else ""},
                        status=status.HTTP_201_CREATED)


class EtatStockView(APIView):
    """GET /api/stocks/etat/[?depot=] -- l'état du stock de mon institution, et ses alertes.
    `?format_fichier=csv` : le même état, pour un tableur."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        institution = _institution_ou_refus(request)
        environment = get_active_environment(request)
        depots = list(DepotStock.objects.filter(institution=institution, environment=environment).order_by("nom"))
        depot = next((d for d in depots if str(d.id) == request.query_params.get("depot")), None)
        lignes = stocks.etat(institution, environment, depot=depot)
        if request.query_params.get("format_fichier") == "csv":
            reponse = HttpResponse(stocks.exporter(lignes, {str(d.id): d.nom for d in depots}), content_type="text/csv; charset=utf-8")
            reponse["Content-Disposition"] = 'attachment; filename="etat-du-stock.csv"'
            audit_log(request=request, action_code="EXPORT", objet_type="ArticleStock",
                      commentaire=f"État du stock exporté ({len(lignes)} article(s))")
            return reponse
        if request.query_params.get("format_fichier") == "pdf":
            # La feuille d'inventaire d'un dépôt (?aveugle=1 : sans les quantités attendues).
            from . import stocks_pdf
            if depot is None:
                raise ValidationError({"depot": "Choisissez le dépôt à inventorier."})
            pdf = stocks_pdf.feuille(stocks.etat(institution, environment), depot, institution=institution.nom,
                                     edite_par=_nom(request.user, request), a_l_aveugle=request.query_params.get("aveugle") == "1")
            reponse = HttpResponse(pdf, content_type="application/pdf")
            reponse["Content-Disposition"] = 'attachment; filename="feuille-inventaire.pdf"'
            return reponse
        valeur = sum((l["valeur"] for l in lignes if l["valeur"] is not None), stocks.ZERO)
        return Response({
            "institution": str(institution.id), "institution_nom": institution.nom,
            "depots": DepotStockSerializer(depots, many=True).data,
            "articles": [{
                **ArticleStockSerializer(l["article"]).data, "total": l["total"], "par_depot": l["par_depot"], "lots": l["lots"],
                "sous_seuil": l["sous_seuil"], "perime": l["perime"], "bientot_perime": l["bientot_perime"],
                "prochaine_peremption": l["prochaine_peremption"], "valeur": l["valeur"], "mal_range": l["mal_range"], "reserve": l["reserve"], "disponible": l["disponible"],
            } for l in lignes],
            "alertes": {"sous_seuil": sum(1 for l in lignes if l["sous_seuil"]), "perimes": sum(1 for l in lignes if l["perime"] > 0),
                        "bientot_perimes": sum(1 for l in lignes if l["bientot_perime"] > 0),
                        "mal_ranges": sum(1 for l in lignes if l["mal_range"])},
            "valeur_totale": valeur, "jours_alerte_peremption": stocks.JOURS_ALERTE_PEREMPTION,
        })


class InventaireStockView(APIView):
    """`/api/stocks/inventaire/` -- GET ?depot= : les lignes à compter dans un dépôt (ce que dit la
    feuille) ; POST {depot, comptes: [{article, quantite[, lot, date_peremption]}]} : ce qu'on a
    compté, saisi d'un bloc. Une ligne laissée vide n'est ni comptée ni corrigée."""
    permission_classes = [IsInstitutionalActor]

    def _depot(self, request, identifiant):
        depot = _du_perimetre(request, DepotStock.objects.all()).filter(pk=identifiant).first() if identifiant else None
        if depot is None:
            raise ValidationError({"depot": "Choisissez le dépôt à inventorier."})
        return depot

    def get(self, request):
        from . import stocks_pdf
        depot = self._depot(request, request.query_params.get("depot"))
        lignes = stocks_pdf.lignes_d_inventaire(stocks.etat(depot.institution, depot.environment), depot)
        return Response({"depot": str(depot.id), "depot_nom": depot.nom, "lignes": [
            {"article": str(l["article"].id), "reference": l["article"].reference, "designation": l["article"].designation,
             "unite": l["article"].unite, "lot": l["lot"], "date_peremption": l["date_peremption"], "attendu": l["attendu"]} for l in lignes]})

    def post(self, request):
        depot = self._depot(request, request.data.get("depot"))
        articles = {str(a.id): a for a in ArticleStock.objects.filter(institution=depot.institution, environment=depot.environment)}
        try:
            bilan = stocks.inventorier(depot, request.data.get("comptes"), articles, auteur=request.user,
                                       motif=(request.data.get("motif") or "Inventaire du dépôt")[:300])
        except stocks.ErreurStock as erreur:
            raise ValidationError({"detail": str(erreur)})
        for mouvement in bilan["corrections"]:
            if depot.point_id:
                stocks_points.synchroniser(depot.point, stocks_points.item_de(mouvement.article), depot.environment)
        audit_log(request=request, action_code="MODIFICATION", objet_type="DepotStock", objet_id=depot.id,
                  commentaire=f"Inventaire de « {depot.nom} » : {bilan['comptees']} ligne(s) comptée(s), {len(bilan['corrections'])} correction(s)")
        return Response({"comptees": bilan["comptees"], "corrections": MouvementStockSerializer(
            bilan["corrections"], many=True, context={"request": request}).data}, status=status.HTTP_201_CREATED)


class ImportStockView(APIView):
    """POST /api/stocks/import/ (fichier CSV[, depot, simuler]) -- reprend un export Dolibarr ou
    un tableur. `simuler=1` dit ce qui serait fait sans rien écrire."""
    permission_classes = [IsInstitutionalActor]
    TAILLE_MAX = 5 * 1024 * 1024

    def post(self, request):
        institution = _institution_ou_refus(request)
        environment = get_active_environment(request)
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ValidationError({"fichier": "Joignez le fichier CSV exporté."})
        if fichier.size > self.TAILLE_MAX:
            raise ValidationError({"fichier": "Fichier trop volumineux (5 Mo au plus)."})
        depot = DepotStock.objects.filter(institution=institution, environment=environment, pk=request.data.get("depot")).first() \
            if request.data.get("depot") else None
        simuler = str(request.data.get("simuler") or "").lower() in ("1", "true", "oui")
        try:
            bilan = stocks.importer(fichier.read(), institution, environment, auteur=request.user, depot_par_defaut=depot, simuler=simuler)
        except stocks.ErreurStock as erreur:
            raise ValidationError({"fichier": str(erreur)})
        if not simuler:
            audit_log(request=request, action_code="IMPORT_LISTE", objet_type="ArticleStock",
                      commentaire=f"Reprise d'un fichier de stock : {bilan['articles_crees']} article(s) créé(s), "
                                  f"{bilan['quantites_posees']} quantité(s) posée(s), {len(bilan['erreurs'])} ligne(s) en erreur")
        return Response(bilan)


# ── Le stock d'un point d'accueil (core/stocks_points.py) ────────────────────────────────────

class StockPointView(APIView):
    """`/api/stocks/points/<point>/[doter|recevoir|distribuer|compter|rapatrier]/`.

    GET : ce qu'il y a au point d'après le journal, et ses derniers mouvements. L'équipe du point
    reçoit, distribue et compte ; doter le point depuis un dépôt et rapatrier le reste reviennent
    à l'institution à qui le stock appartient."""
    permission_classes = [IsAuthenticated]

    def _point(self, request, point_id):
        point = PointOperationnel.objects.select_related("crise", "equipe", "responsable").filter(pk=point_id).first()
        if point is None:
            raise ValidationError({"detail": "Point introuvable."})
        tient = _peut_gerer_stock_point(request, point)
        institutionnel = get_effective_role(request) in INSTITUTIONAL_TYPES
        if not (tient or institutionnel):
            raise PermissionDenied("Le stock d'un point se consulte par son équipe ou par une institution.")
        return point, tient, institutionnel

    def _item(self, request):
        item = MaterielCatalogue.objects.filter(pk=request.data.get("item")).first()
        if item is None:
            raise ValidationError({"item": "Besoin du catalogue introuvable."})
        return item

    def _etat(self, request, point, tient, institutionnel):
        environment = get_active_environment(request)
        totaux = stocks_points.quantites(point)
        lignes = {l.item_id: l for l in MaterielPoint.objects.filter(point=point).select_related("item")}
        items = {i.id: i for i in MaterielCatalogue.objects.filter(pk__in=set(totaux) | set(lignes))}
        mouvements = MouvementStock.objects.filter(depot__point=point, environment=environment).select_related(
            "article", "depot", "crise", "mission", "equipe", "auteur").order_by("-date_mouvement", "-date_creation")[:60]
        mon_institution = institution_regardee(request) if institutionnel else None
        denrees = stocks_points.denrees(point)
        return {
            "point": str(point.id), "point_nom": point.nom, "peut_distribuer": tient or institutionnel,
            "peut_doter": bool(mon_institution), "institution_nom": mon_institution.nom if mon_institution else "",
            "a_rapatrier": bool(mon_institution) and MouvementStock.objects.filter(
                depot__point=point, depot__institution=mon_institution).values("depot").annotate(t=Sum("quantite")).filter(t__gt=0).exists(),
            "lignes": sorted(({
                "item": str(i), "item_nom": items[i].nom, "quantite": totaux.get(i),
                "unite": lignes[i].unite if i in lignes else "unité",
                "niveau_stock": lignes[i].niveau_stock if i in lignes else None,
                "suivi": i in totaux, **denrees.get(i, {"conservation": "AMBIANT", "preparation": "", "manques": []}),
            } for i in items), key=lambda l: l["item_nom"].casefold()),
            "moyens": {"froid_positif": point.froid_positif, "froid_negatif": point.froid_negatif, "cuisson": point.cuisson},
            "mouvements": MouvementStockSerializer(mouvements, many=True, context={"request": request}).data,
        }

    def get(self, request, point_id, geste=None):
        point, tient, institutionnel = self._point(request, point_id)
        return Response(self._etat(request, point, tient, institutionnel))

    def post(self, request, point_id, geste=None):
        point, tient, institutionnel = self._point(request, point_id)
        environment = get_active_environment(request)
        donnees = request.data
        if point.crise is not None and point.crise.end_date is not None and geste != "rapatrier":
            raise ValidationError({"detail": "Cette crise est close : on peut seulement rapatrier le stock restant."})
        try:
            if geste == "doter":
                institution = _institution_ou_refus(request) if institutionnel else None
                if institution is None:
                    raise PermissionDenied("Doter un point depuis un dépôt revient à l'institution à qui le stock appartient.")
                article = _du_perimetre(request, ArticleStock.objects.all()).filter(pk=donnees.get("article")).first()
                source = _du_perimetre(request, DepotStock.objects.all()).filter(pk=donnees.get("depot"), point__isnull=True).first()
                if article is None or source is None:
                    raise ValidationError({"detail": "Article ou dépôt introuvable dans votre stock."})
                peremption = stocks._date(donnees.get("date_peremption")) if donnees.get("date_peremption") else None
                stocks_points.doter(point=point, article=article, source=source, quantite=donnees.get("quantite"), auteur=request.user,
                                    lot=donnees.get("lot") or "", date_peremption=peremption, motif=donnees.get("motif") or "")
                resume = f"dotation de {article.reference} depuis {source.nom}"
            elif geste in ("recevoir", "compter"):
                if not (tient or institutionnel):
                    raise PermissionDenied("Réservé à l'équipe du point.")
                institution = stocks_points.institution_du_point(point, a_defaut=institution_regardee(request))
                if institution is None:
                    raise ValidationError({"detail": "Ce point n'est rattaché à aucune institution : affectez-lui une équipe pour tenir son stock."})
                item = self._item(request)
                if geste == "recevoir":
                    stocks_points.recevoir(point=point, item=item, quantite=donnees.get("quantite"), institution=institution,
                                           environment=environment, auteur=request.user, tiers=donnees.get("tiers") or "",
                                           unite=donnees.get("unite") or "unité")
                else:
                    stocks_points.compter(point=point, item=item, quantite=donnees.get("quantite"), institution=institution,
                                          environment=environment, auteur=request.user)
                resume = f"{'réception' if geste == 'recevoir' else 'inventaire'} — {item.nom}"
            elif geste == "distribuer":
                item = self._item(request)
                stocks_points.distribuer(point=point, item=item, quantite=donnees.get("quantite"), environment=environment,
                                         auteur=request.user, motif=donnees.get("motif") or "", tiers=donnees.get("tiers") or "")
                resume = f"distribution — {item.nom}"
            elif geste == "transferer":
                raise ValidationError({"detail": "Un transfert entre deux points se demande d'abord : le point d'arrivée fait sa demande, "
                                                 "ceux qui tiennent le point de départ l'acceptent, et c'est alors que le stock part."})
            elif geste == "moyens":
                # Ce que le point a pour garder et préparer des denrées.
                from .models import CuissonLieu
                if "cuisson" in donnees and donnees["cuisson"] not in CuissonLieu.values:
                    raise ValidationError({"cuisson": "Valeur inconnue."})
                for champ in ("froid_positif", "froid_negatif"):
                    if champ in donnees:
                        setattr(point, champ, bool(donnees[champ]))
                point.cuisson = donnees.get("cuisson", point.cuisson)
                point.save(update_fields=["froid_positif", "froid_negatif", "cuisson"])
                resume = "moyens de conservation et de préparation mis à jour"
            elif geste == "rapatrier":
                institution = _institution_ou_refus(request) if institutionnel else None
                destination = _du_perimetre(request, DepotStock.objects.all()).filter(pk=donnees.get("depot"), point__isnull=True).first() \
                    if institution else None
                if destination is None:
                    raise ValidationError({"depot": "Choisissez le dépôt de votre institution où ranger le stock."})
                nombre = stocks_points.rapatrier(point=point, institution=institution, destination=destination, environment=environment,
                                                 auteur=request.user)
                resume = f"retour de {nombre} ligne(s) vers {destination.nom}"
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except stocks.ErreurStock as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="PointOperationnel", objet_id=point.id, crise=point.crise,
                  commentaire=f"Stock du point « {point.nom} » : {resume}")
        return Response(self._etat(request, point, tient, institutionnel), status=status.HTTP_201_CREATED)


# ── Tiers, commandes, factures, prêts (core/stocks_echanges.py) ──────────────────────────────

class TiersStockSerializer(serializers.ModelSerializer):
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = TiersStock
        exclude = ["environment"]
        read_only_fields = ["institution", "date_creation"]


class TiersStockViewSet(_StockViewSet):
    """Fournisseurs, donateurs, emprunteurs, prêteurs. `?recherche=` filtre sur le nom et le
    contact APRÈS déchiffrement (ces champs sont chiffrés, la base ne sait pas y chercher)."""
    queryset = TiersStock.objects.all().order_by("-date_creation")
    serializer_class = TiersStockSerializer
    filterset_fields = ["type", "est_fournisseur", "actif"]

    def get_queryset(self):
        queryset = super().get_queryset()
        cherche = (self.request.query_params.get("recherche") or "").strip().casefold()
        if cherche and self.action == "list":
            queryset = queryset.filter(pk__in=[t.pk for t in queryset if cherche in f"{t.nom} {t.contact}".casefold()])
        return queryset

    def perform_create(self, serializer):
        tiers = serializer.save(institution=_institution_ou_refus(self.request), environment=get_active_environment(self.request))
        audit_log(request=self.request, action_code="CREATION", objet_type="TiersStock", objet_id=tiers.id,
                  commentaire="Tiers de stock créé")


def _du_stock(request, modele, identifiant, champ="institution_id"):
    return _du_perimetre(request, modele.objects.all(), champ=champ).filter(pk=identifiant).first() if identifiant else None


class CommandeStockSerializer(serializers.ModelSerializer):
    tiers_nom = serializers.CharField(source="tiers.nom", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    depot_nom = serializers.CharField(source="depot.nom", read_only=True, default=None)
    lignes = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = CommandeStock
        exclude = ["environment"]
        read_only_fields = ["institution", "numero", "statut", "cree_par", "date_creation"]

    def get_lignes(self, obj):
        return [{"id": str(l.id), "article": str(l.article_id), "article_designation": l.article.designation,
                 "article_reference": l.article.reference, "unite": l.article.unite, "quantite": l.quantite,
                 "prix_unitaire": l.prix_unitaire, "quantite_recue": l.quantite_recue} for l in obj.lignes.select_related("article")]

    def get_total(self, obj):
        return stocks_echanges.total_de(obj)


class CommandeStockViewSet(_StockViewSet):
    """Commandes aux fournisseurs : brouillon -> commandée -> reçue (en partie ou en tout). La
    réception crée les entrées en stock, au prix des lignes."""
    queryset = CommandeStock.objects.select_related("tiers", "depot").prefetch_related("lignes__article")
    serializer_class = CommandeStockSerializer
    filterset_fields = ["statut", "tiers"]

    def _verifier(self, serializer):
        for cle in ("tiers", "depot"):
            objet = serializer.validated_data.get(cle)
            if objet is not None and not _du_perimetre(self.request, type(objet).objects.filter(pk=objet.pk)).exists():
                raise ValidationError({cle: "Introuvable dans votre stock."})

    def _lignes(self, commande):
        if "lignes" not in self.request.data:
            return
        articles = {str(a.id): a for a in ArticleStock.objects.filter(institution=commande.institution, environment=commande.environment)}
        try:
            stocks_echanges.poser_les_lignes(commande, self.request.data.get("lignes"), articles)
        except stocks.ErreurStock as erreur:
            raise ValidationError({"detail": str(erreur)})

    def perform_create(self, serializer):
        from django.db import transaction
        institution, environment = _institution_ou_refus(self.request), get_active_environment(self.request)
        self._verifier(serializer)
        with transaction.atomic():
            commande = serializer.save(institution=institution, environment=environment, cree_par=self.request.user,
                                       numero=stocks_echanges.numero_de_commande(institution, environment))
            self._lignes(commande)
        audit_log(request=self.request, action_code="CREATION", objet_type="CommandeStock", objet_id=commande.id,
                  commentaire=f"Commande {commande.numero} créée")

    def perform_update(self, serializer):
        from django.db import transaction
        self._verifier(serializer)
        with transaction.atomic():
            commande = serializer.save()
            self._lignes(commande)

    def perform_destroy(self, instance):
        if instance.statut != StatutCommandeStock.BROUILLON:
            raise ValidationError({"detail": "Seul un brouillon se supprime : une commande passée s'annule."})
        instance.delete()

    def _rendre(self, commande):
        commande = self.get_queryset().get(pk=commande.pk)
        return Response(self.get_serializer(commande).data)

    @action(detail=True, methods=["post"])
    def passer(self, request, pk=None):
        """Le brouillon devient une commande passée : ses lignes ne bougent plus."""
        commande = self.get_object()
        if commande.statut != StatutCommandeStock.BROUILLON:
            raise ValidationError({"detail": "Cette commande est déjà passée."})
        if not commande.lignes.exists():
            raise ValidationError({"detail": "Une commande sans ligne ne se passe pas."})
        from django.utils import timezone
        commande.statut = StatutCommandeStock.COMMANDEE
        commande.date_commande = commande.date_commande or timezone.localdate()
        commande.save(update_fields=["statut", "date_commande"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="CommandeStock", objet_id=commande.id,
                  commentaire=f"Commande {commande.numero} passée")
        return self._rendre(commande)

    @action(detail=True, methods=["post"])
    def annuler(self, request, pk=None):
        commande = self.get_object()
        if commande.statut not in (StatutCommandeStock.BROUILLON, StatutCommandeStock.COMMANDEE):
            raise ValidationError({"detail": "Une commande déjà reçue, même en partie, ne s'annule plus."})
        commande.statut = StatutCommandeStock.ANNULEE
        commande.save(update_fields=["statut"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="CommandeStock", objet_id=commande.id,
                  commentaire=f"Commande {commande.numero} annulée")
        return self._rendre(commande)

    @action(detail=True, methods=["post"])
    def recevoir(self, request, pk=None):
        """POST {receptions: [{ligne, quantite[, lot, date_peremption]}][, depot]}."""
        commande = self.get_object()
        depot = _du_stock(request, DepotStock, request.data.get("depot")) or commande.depot
        try:
            mouvements = stocks_echanges.recevoir(commande, request.data.get("receptions"), depot, auteur=request.user)
        except stocks.ErreurStock as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="CommandeStock", objet_id=commande.id,
                  commentaire=f"Commande {commande.numero} : {len(mouvements)} ligne(s) reçue(s) dans {depot.nom}")
        return self._rendre(commande)


class FactureStockSerializer(serializers.ModelSerializer):
    tiers_nom = serializers.CharField(source="tiers.nom", read_only=True)
    commande_numero = serializers.CharField(source="commande.numero", read_only=True, default=None)
    a_une_piece = serializers.SerializerMethodField()
    en_retard = serializers.SerializerMethodField()

    class Meta:
        model = FactureStock
        exclude = ["environment"]
        read_only_fields = ["institution", "cree_par", "date_creation"]
        extra_kwargs = {"fichier": {"write_only": True, "required": False}}

    def get_a_une_piece(self, obj):
        return bool(obj.fichier)

    def get_en_retard(self, obj):
        from django.utils import timezone
        return obj.payee_le is None and obj.echeance is not None and obj.echeance < timezone.localdate()


class FactureStockViewSet(_StockViewSet):
    """Factures de fournisseurs, rangées avec leur commande. Pas une comptabilité (voir le modèle)."""
    queryset = FactureStock.objects.select_related("tiers", "commande")
    serializer_class = FactureStockSerializer
    filterset_fields = ["tiers", "commande"]
    TAILLE_MAX = 10 * 1024 * 1024

    def _verifier(self, serializer):
        for cle in ("tiers", "commande"):
            objet = serializer.validated_data.get(cle)
            if objet is not None and not _du_perimetre(self.request, type(objet).objects.filter(pk=objet.pk)).exists():
                raise ValidationError({cle: "Introuvable dans votre stock."})
        fichier = serializer.validated_data.get("fichier")
        if fichier is not None and fichier.size > self.TAILLE_MAX:
            raise ValidationError({"fichier": "Pièce trop volumineuse (10 Mo au plus)."})

    def perform_create(self, serializer):
        self._verifier(serializer)
        facture = serializer.save(institution=_institution_ou_refus(self.request), environment=get_active_environment(self.request),
                                  cree_par=self.request.user)
        audit_log(request=self.request, action_code="CREATION", objet_type="FactureStock", objet_id=facture.id,
                  commentaire=f"Facture {facture.numero} enregistrée")

    def perform_update(self, serializer):
        self._verifier(serializer)
        serializer.save()

    def perform_destroy(self, instance):
        if instance.fichier:
            instance.fichier.delete(save=False)             # le fichier, pas seulement la ligne
        instance.delete()

    @action(detail=True, methods=["get"])
    def piece(self, request, pk=None):
        """La pièce jointe, déchiffrée à la volée."""
        facture = self.get_object()
        if not facture.fichier:
            raise ValidationError({"detail": "Aucune pièce n'est jointe à cette facture."})
        import mimetypes
        import re
        with facture.fichier.open("rb") as flux:
            contenu = flux.read()
        nom = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"facture-{facture.numero}") + (
            "." + facture.fichier.name.rsplit(".", 1)[-1][:5] if "." in facture.fichier.name else "")
        reponse = HttpResponse(contenu, content_type=mimetypes.guess_type(nom)[0] or "application/octet-stream")
        reponse["Content-Disposition"] = f'attachment; filename="{nom}"'
        audit_log(request=request, action_code="TELECHARGEMENT", objet_type="FactureStock", objet_id=facture.id,
                  commentaire=f"Pièce de la facture {facture.numero} téléchargée")
        return reponse


class PretMaterielSerializer(serializers.ModelSerializer):
    tiers_nom = serializers.CharField(source="tiers.nom", read_only=True)
    tiers_type = serializers.CharField(source="tiers.get_type_display", read_only=True)
    sens_libelle = serializers.CharField(source="get_sens_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    etat_depart_libelle = serializers.CharField(source="get_etat_depart_display", read_only=True)
    etat_retour_libelle = serializers.SerializerMethodField()
    depot_nom = serializers.CharField(source="depot.nom", read_only=True, default=None)
    unite = serializers.CharField(source="article.unite", read_only=True, default="")
    en_retard = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()

    class Meta:
        model = PretMateriel
        exclude = ["environment"]
        read_only_fields = ["institution", "statut", "etat_retour", "constat_retour", "quantite_rendue", "date_retour", "cree_par",
                            "rendu_par", "date_creation"]
        extra_kwargs = {"designation": {"required": False, "allow_blank": True}}

    def get_etat_retour_libelle(self, obj):
        return obj.get_etat_retour_display() if obj.etat_retour else ""

    def get_en_retard(self, obj):
        return stocks_echanges.en_retard(obj)

    def get_photos(self, obj):
        return {"depart": sum(1 for d in obj.documents.all() if d.moment_pret == "DEPART"),
                "retour": sum(1 for d in obj.documents.all() if d.moment_pret == "RETOUR")}


class PretMaterielViewSet(_StockViewSet):
    """Prêts de matériel dans les deux sens, avec fiche d'état au départ et au retour. Les photos
    se déposent par `/api/documents/` (champs `pret` et `moment_pret`)."""
    queryset = PretMateriel.objects.select_related("tiers", "article", "depot", "crise", "institution").prefetch_related("documents")
    serializer_class = PretMaterielSerializer
    filterset_fields = ["sens", "statut", "tiers", "crise"]
    #: Une fois le prêt parti, ce qui a fait bouger le stock ne se retouche plus.
    FIGES = ("sens", "tiers", "article", "depot", "quantite", "date_debut")

    def perform_create(self, serializer):
        for cle in ("tiers", "article", "depot"):
            objet = serializer.validated_data.get(cle)
            if objet is not None and not _du_perimetre(self.request, type(objet).objects.filter(pk=objet.pk)).exists():
                raise ValidationError({cle: "Introuvable dans votre stock."})
        pret = PretMateriel(institution=_institution_ou_refus(self.request), environment=get_active_environment(self.request),
                            **serializer.validated_data)
        try:
            stocks_echanges.ouvrir(pret, auteur=self.request.user)
        except stocks.ErreurStock as erreur:
            raise ValidationError({"detail": str(erreur)})
        serializer.instance = pret
        audit_log(request=self.request, action_code="CREATION", objet_type="PretMateriel", objet_id=pret.id, crise=pret.crise,
                  commentaire=f"Prêt enregistré ({pret.get_sens_display().lower()}) : {pret.designation}")

    def perform_update(self, serializer):
        if any(c in serializer.validated_data and serializer.validated_data[c] != getattr(serializer.instance, c) for c in self.FIGES):
            raise ValidationError({"detail": "Le sens, le tiers, l'article, le dépôt, la quantité et la date de début d'un prêt "
                                             "enregistré ne se modifient plus : ils ont fait bouger le stock."})
        serializer.save()

    def perform_destroy(self, instance):
        raise ValidationError({"detail": "Un prêt ne se supprime pas : il se clôt par sa fiche de retour."})

    @action(detail=True, methods=["post"])
    def rendre(self, request, pk=None):
        """POST {etat_retour[, constat_retour, quantite_rendue, date_retour]} -- la fiche de retour."""
        pret = self.get_object()
        date_retour = stocks._date(request.data.get("date_retour")) if request.data.get("date_retour") else None
        try:
            stocks_echanges.rendre(pret, etat_retour=request.data.get("etat_retour"), constat_retour=request.data.get("constat_retour") or "",
                                   quantite_rendue=request.data.get("quantite_rendue"), date_retour=date_retour, auteur=request.user)
        except stocks.ErreurStock as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="PretMateriel", objet_id=pret.id, crise=pret.crise,
                  commentaire=f"Prêt rendu ({pret.get_statut_display().lower()}) : {pret.designation}")
        return Response(self.get_serializer(self.get_queryset().get(pk=pret.pk)).data)

    @action(detail=True, methods=["get"])
    def fiche(self, request, pk=None):
        """La fiche de prêt en PDF : les deux parties, le matériel, l'état au départ et au retour,
        les photos, et la place des signatures."""
        from . import rapports_pdf
        from .views import _nommer_pour, _reponse_pdf

        pret = self.get_object()
        nommer = _nommer_pour(request)

        def photos_de(moment):
            return [p for p in (rapports_pdf._photo(d.fichier, ("Au départ" if moment == "DEPART" else "Au retour")
                                                    + (f" — {d.commentaire}" if d.commentaire else ""), d.date_upload, d.sha256)
                                for d in pret.documents.filter(moment_pret=moment).order_by("date_upload")) if p]

        pdf = rapports_pdf.generer("pret", stocks_echanges.resume(pret, nommer, photos_de), edite_par=nommer(request.user),
                                   toutes_les_photos=request.query_params.get("photos") == "toutes")
        audit_log(request=request, action_code="EXPORT", objet_type="PretMateriel", objet_id=pret.id, crise=pret.crise,
                  commentaire=f"Fiche de prêt éditée : {pret.designation}")
        return _reponse_pdf(pdf, "fiche-de-pret")
