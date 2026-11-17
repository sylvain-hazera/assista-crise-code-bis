"""API des appels aux dons (voir core/appels_dons.py) : `/api/dons/…`.

Acteurs institutionnels seulement. Une institution gère SES foyers et SES appels ; elle voit les
appels OUVERTS des autres, peut s'y engager, annoncer un envoi — jamais leurs foyers."""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from . import appels_dons, notifications_dons, stocks
from .audit import audit_log
from .models import (
    AppelAuxDons, BesoinDon, BesoinFoyer, DepotStock, EngagementDon, EnvoiDon, FoyerSinistre, PersonneFoyer, PublicDon,
    StatutAppelDons, StatutEngagementDon, StatutEnvoiDon,
)
from .perimetre_admin import institution_regardee, institutions_visibles
from .permissions import IsInstitutionalActor, get_active_environment
from .views_stocks import _du_perimetre, _institution_ou_refus


def _erreur(erreur):
    return ValidationError({"detail": str(erreur)})


def _est_a_moi(request, institution_id) -> bool:
    visibles = institutions_visibles(request)
    return visibles is None or institution_id in visibles


class CatalogueDonsView(APIView):
    """GET /api/dons/catalogue/ -- familles, articles, publics et grilles de tailles."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        return Response({"familles": appels_dons.catalogue(), "publics": [{"code": p.value, "libelle": p.label} for p in PublicDon]})


# ── Foyers ───────────────────────────────────────────────────────────────────────────────────

class FoyerSinistreSerializer(serializers.ModelSerializer):
    personnes = serializers.SerializerMethodField()
    besoins = serializers.SerializerMethodField()
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)

    class Meta:
        model = FoyerSinistre
        exclude = ["environment"]
        read_only_fields = ["institution", "reference", "cree_par", "date_creation"]

    def get_personnes(self, obj):
        return [{"id": str(p.id), "public": p.public, "age": p.age, "taille_haut": p.taille_haut, "taille_bas": p.taille_bas,
                 "pointure": p.pointure} for p in obj.personnes.all()]

    def get_besoins(self, obj):
        return [{"id": str(b.id), "famille": b.famille, "designation": b.designation, "public": b.public, "taille": b.taille,
                 "neuf_exige": b.neuf_exige, "quantite": b.quantite, "quantite_urgence": b.quantite_urgence,
                 "quantite_remise": b.quantite_remise, "message": b.message, "etat": b.etat} for b in obj.besoins.all()]


def _ligne_valide(ligne, champ_quantite="quantite"):
    """Une ligne de besoin vérifiée : désignation, public connu, quantité entière positive."""
    designation = " ".join(str(ligne.get("designation") or "").split())[:120]
    public = ligne.get("public") or ""
    try:
        quantite = int(ligne.get(champ_quantite) or 0)
    except (TypeError, ValueError):
        raise ValidationError({"detail": f"« {designation} » : quantité entière attendue."})
    if not designation or quantite <= 0 or (public and public not in PublicDon.values):
        raise ValidationError({"detail": "Chaque ligne demande une désignation, une quantité supérieure à zéro et un public connu."})
    return {"famille": str(ligne.get("famille") or "DIVERS")[:30], "designation": designation, "public": public,
            "taille": str(ligne.get("taille") or "").strip()[:20], "neuf_exige": bool(ligne.get("neuf_exige")),
            "message": " ".join(str(ligne.get("message") or "").split())[:300]}, quantite


def _urgence(ligne, quantite) -> int:
    """La part urgente d'une ligne : celle qu'on donne, sinon la moitié (au moins une pièce)."""
    try:
        urgence = int(ligne.get("quantite_urgence"))
    except (TypeError, ValueError):
        urgence = appels_dons.urgence_de(quantite)
    return max(1, min(urgence, quantite))


class FoyerSinistreViewSet(viewsets.ModelViewSet):
    """Les foyers sinistrés que l'institution accompagne, leur composition et leurs besoins.
    `personnes` et `besoins`, s'ils sont donnés, remplacent ceux du foyer."""
    queryset = FoyerSinistre.objects.select_related("crise").prefetch_related("personnes", "besoins")
    serializer_class = FoyerSinistreSerializer
    permission_classes = [IsInstitutionalActor]
    filterset_fields = ["crise"]

    def get_queryset(self):
        return _du_perimetre(self.request, super().get_queryset())

    def _composer(self, foyer):
        donnees = self.request.data
        if "personnes" in donnees:
            foyer.personnes.all().delete()
            for p in donnees.get("personnes") or []:
                if p.get("public") not in PublicDon.values:
                    raise ValidationError({"detail": "Chaque personne du foyer demande un profil connu."})
                PersonneFoyer.objects.create(
                    foyer=foyer, public=p["public"], age=p.get("age") if str(p.get("age") or "").isdigit() else None,
                    taille_haut=str(p.get("taille_haut") or "")[:12], taille_bas=str(p.get("taille_bas") or "")[:12],
                    pointure=str(p.get("pointure") or "")[:6])
        if "besoins" in donnees:
            anciens = {appels_dons._cle(b): b for b in foyer.besoins.all()}
            gardes = set()
            for ligne in donnees.get("besoins") or []:
                champs, quantite = _ligne_valide(ligne)
                cle = (champs["famille"], champs["designation"], champs["public"], champs["taille"], champs["message"])
                ancien = anciens.get(cle)
                if ancien is not None and cle not in gardes:
                    # Ce qui a déjà été remis reste remis : la quantité ne descend pas en dessous.
                    ancien.quantite, ancien.neuf_exige = max(quantite, ancien.quantite_remise), champs["neuf_exige"]
                    ancien.quantite_urgence = _urgence(ligne, ancien.quantite)
                    ancien.save(update_fields=["quantite", "quantite_urgence", "neuf_exige"])
                else:
                    # Une seconde ligne identique est une AUTRE personne du foyer : elle garde sa
                    # ligne, c'est ce qui permet de dire « pour deux personnes ».
                    BesoinFoyer.objects.create(foyer=foyer, quantite=quantite, quantite_urgence=_urgence(ligne, quantite), **champs)
                gardes.add(cle)
            for cle, ancien in anciens.items():
                if cle not in gardes and ancien.quantite_remise == 0:
                    ancien.delete()

    def perform_create(self, serializer):
        institution, environment = _institution_ou_refus(self.request), get_active_environment(self.request)
        with transaction.atomic():
            foyer = serializer.save(institution=institution, environment=environment, cree_par=self.request.user,
                                    reference=appels_dons.reference_de_foyer(institution, environment))
            self._composer(foyer)
        audit_log(request=self.request, action_code="CREATION", objet_type="FoyerSinistre", objet_id=foyer.id, crise=foyer.crise,
                  commentaire=f"Foyer sinistré {foyer.reference} enregistré")

    def perform_update(self, serializer):
        with transaction.atomic():
            self._composer(serializer.save())

    @action(detail=True, methods=["get"])
    def trousseau(self, request, pk=None):
        """Ce qu'on propose pour chaque personne du foyer, d'après son profil et ses tailles."""
        foyer = self.get_object()
        return Response([{"personne": str(p.id), "public": p.public, "age": p.age, "lignes": appels_dons.trousseau_pour(p)}
                         for p in foyer.personnes.all()])

    @action(detail=True, methods=["post"])
    def remettre(self, request, pk=None):
        """POST {besoin, quantite[, depot]} -- ce qui est remis au foyer ne lui manque plus."""
        foyer = self.get_object()
        besoin = foyer.besoins.filter(pk=request.data.get("besoin")).first()
        if besoin is None:
            raise ValidationError({"besoin": "Ligne introuvable dans ce foyer."})
        depot = _du_perimetre(request, DepotStock.objects.all()).filter(pk=request.data.get("depot")).first() if request.data.get("depot") else None
        try:
            appels_dons.remettre(besoin, request.data.get("quantite"), depot=depot, auteur=request.user)
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="MODIFICATION", objet_type="FoyerSinistre", objet_id=foyer.id, crise=foyer.crise,
                  commentaire=f"Remise au foyer {foyer.reference} : {besoin.designation}")
        return Response(self.get_serializer(self.get_queryset().get(pk=foyer.pk)).data)


# ── Appels ───────────────────────────────────────────────────────────────────────────────────

class AppelAuxDonsSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source="institution.nom", read_only=True)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    point_nom = serializers.CharField(source="point.nom", read_only=True, default=None)
    depot_nom = serializers.SerializerMethodField()
    le_mien = serializers.SerializerMethodField()
    portee = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    besoins = serializers.SerializerMethodField()
    envois = serializers.SerializerMethodField()
    avancement = serializers.SerializerMethodField()

    class Meta:
        model = AppelAuxDons
        exclude = ["environment", "centre", "institutions_prevenues"]
        read_only_fields = ["institution", "statut", "date_ouverture", "date_cloture", "cree_par", "date_creation"]

    def validate_portee_km(self, valeur):
        if valeur is not None and valeur not in appels_dons.PORTEES_KM:
            raise serializers.ValidationError(f"Portée attendue : {', '.join(str(p) for p in appels_dons.PORTEES_KM)} km, ou vide pour toute la France.")
        return valeur

    def get_portee(self, obj):
        return appels_dons.libelle_portee(obj)

    def get_distance_km(self, obj):
        """À combien l'institution qui regarde se trouve de l'appel (None : la sienne, ou inconnue)."""
        if self._mien(obj):
            return None
        distance = appels_dons.distance_a(obj, self._moi())
        return round(distance) if distance is not None else None

    def _mien(self, obj) -> bool:
        return _est_a_moi(self.context["request"], obj.institution_id)

    def _moi(self):
        return institution_regardee(self.context["request"])

    def get_le_mien(self, obj):
        return self._mien(obj)

    def get_depot_nom(self, obj):
        # Le nom d'un dépôt est une affaire interne : seul le propriétaire de l'appel le lit.
        return obj.depot.nom if obj.depot_id and self._mien(obj) else None

    def _lignes(self, obj):
        if not hasattr(obj, "_lignes_calculees"):
            mien, moi = self._mien(obj), self._moi()
            lignes = []
            for besoin in obj.besoins.all():
                engagements = list(besoin.engagements.all())
                promis = sum(e.quantite for e in engagements if e.statut in appels_dons.EN_COURS)
                visibles = [e for e in engagements if mien or (moi is not None and e.institution_id == moi.id)]
                lignes.append({
                    "id": str(besoin.id), "famille": besoin.famille, "designation": besoin.designation, "public": besoin.public,
                    "taille": besoin.taille, "neuf_exige": besoin.neuf_exige, "precision": besoin.precision, "libelle": appels_dons.libelle(besoin),
                    "message": besoin.message, "nb_beneficiaires": besoin.nb_beneficiaires, "pour_qui": appels_dons.pour_qui(besoin),
                    "formulation": appels_dons.formulation(besoin), "quantite_urgente": besoin.quantite_urgente,
                    "urgent": besoin.quantite_urgente > besoin.quantite_recue,
                    "quantite_voulue": besoin.quantite_voulue, "quantite_recue": besoin.quantite_recue, "quantite_promise": promis,
                    "reste": max(besoin.quantite_voulue - besoin.quantite_recue - promis, 0),
                    # Le propriétaire voit qui s'est engagé ; une autre institution ne voit que les siens.
                    "engagements": [{"id": str(e.id), "institution": str(e.institution_id), "institution_nom": e.institution.nom,
                                     "quantite": e.quantite, "quantite_recue": e.quantite_recue, "statut": e.statut,
                                     "statut_libelle": e.get_statut_display(), "expire_le": e.expire_le,
                                     "envoi": str(e.envoi_id) if e.envoi_id else None,
                                     "le_mien": moi is not None and e.institution_id == moi.id} for e in visibles],
                })
            obj._lignes_calculees = lignes
        return obj._lignes_calculees

    def get_besoins(self, obj):
        return self._lignes(obj)

    def get_avancement(self, obj):
        lignes = self._lignes(obj)
        voulu = sum(l["quantite_voulue"] for l in lignes)
        return {"lignes": len(lignes), "lignes_couvertes": sum(1 for l in lignes if l["reste"] == 0), "pieces_voulues": voulu,
                "pieces_recues": sum(min(l["quantite_recue"], l["quantite_voulue"]) for l in lignes),
                "pieces_promises": sum(l["quantite_promise"] for l in lignes), "pieces_restantes": sum(l["reste"] for l in lignes)}

    def get_envois(self, obj):
        mien, moi = self._mien(obj), self._moi()
        return [{"id": str(e.id), "institution_nom": e.institution.nom, "statut": e.statut, "statut_libelle": e.get_statut_display(),
                 "date_expedition": e.date_expedition, "arrivee_prevue": e.arrivee_prevue, "transporteur": e.transporteur,
                 "contact": e.contact, "commentaire": e.commentaire, "recu_le": e.recu_le,
                 "lignes": [{"engagement": str(g.id), "libelle": appels_dons.libelle(g.besoin), "quantite": g.quantite,
                             "quantite_recue": g.quantite_recue} for g in e.engagements.all()]}
                for e in obj.envois.all() if mien or (moi is not None and e.institution_id == moi.id)]


class AppelAuxDonsViewSet(viewsets.ModelViewSet):
    """Mes appels (tous états) et les appels ouverts des autres institutions. `?miens=1` ou
    `?autres=1` pour n'avoir que les uns ou les autres."""
    queryset = AppelAuxDons.objects.select_related("institution", "crise", "point", "depot").prefetch_related(
        "besoins__engagements__institution", "envois__institution", "envois__engagements__besoin")
    serializer_class = AppelAuxDonsSerializer
    permission_classes = [IsInstitutionalActor]
    filterset_fields = ["crise", "statut"]

    def get_queryset(self):
        queryset = super().get_queryset().filter(environment=get_active_environment(self.request))
        visibles = institutions_visibles(self.request)
        if visibles is None:
            return queryset
        miens, ouverts = Q(institution_id__in=visibles), Q(statut=StatutAppelDons.OUVERT) & ~Q(institution_id__in=visibles)
        # Un appel clos reste lisible de qui s'y était engagé : il doit pouvoir suivre son envoi.
        engages = Q(besoins__engagements__institution_id__in=visibles)
        if self.action == "list" and self.request.query_params.get("miens"):
            return queryset.filter(miens)
        # Un appel ouvert ne s'adresse qu'aux institutions de son périmètre (portée en kilomètres).
        moi = institution_regardee(self.request)
        hors_portee = [a.pk for a in AppelAuxDons.objects.filter(ouverts, environment=get_active_environment(self.request), portee_km__isnull=False)
                       .select_related("institution") if not appels_dons.a_portee(a, moi)]
        ouverts = ouverts & ~Q(pk__in=hors_portee)
        if self.action == "list" and self.request.query_params.get("autres"):
            return queryset.filter(ouverts | (engages & ~miens)).distinct()
        return queryset.filter(miens | ouverts | engages).distinct()

    def _le_mien(self, appel):
        if not _est_a_moi(self.request, appel.institution_id):
            raise PermissionDenied("Cet appel est celui d'une autre institution.")
        return appel

    def _lieu(self, serializer):
        depot = serializer.validated_data.get("depot")
        if depot is not None and not _du_perimetre(self.request, DepotStock.objects.filter(pk=depot.pk)).exists():
            raise ValidationError({"depot": "Introuvable dans votre stock."})

    def _centrer(self, appel):
        """Fixe le point d'où se mesure la portée. Un appel à portée limitée qu'on ne sait pas
        situer serait visible de personne ou de tous : on le dit plutôt que de deviner."""
        from django.contrib.gis.geos import Point
        centre = appels_dons.centre_de(appel)
        if centre is None and appel.portee_km:
            raise ValidationError({"portee_km": "On ne sait pas situer cet appel (ni crise localisée, ni commune de votre institution) : "
                                                "lancez-le sur toute la France, ou rattachez-le à une crise."})
        appel.centre = Point(centre[0], centre[1], srid=4326) if centre else None
        appel.save(update_fields=["centre"])

    def perform_create(self, serializer):
        self._lieu(serializer)
        appel = serializer.save(institution=_institution_ou_refus(self.request), environment=get_active_environment(self.request),
                                cree_par=self.request.user)
        self._centrer(appel)
        audit_log(request=self.request, action_code="CREATION", objet_type="AppelAuxDons", objet_id=appel.id, crise=appel.crise,
                  commentaire=f"Appel aux dons « {appel.titre} » créé")

    def perform_update(self, serializer):
        self._le_mien(serializer.instance)
        self._lieu(serializer)
        avant = serializer.instance.portee_km
        appel = serializer.save()
        self._centrer(appel)
        # Périmètre élargi sur un appel ouvert : les institutions nouvellement à portée sont prévenues.
        if appel.statut == StatutAppelDons.OUVERT and appel.portee_km != avant:
            self._prevenir_le_reseau(appel)

    @staticmethod
    def _prevenir_le_reseau(appel):
        """En tâche de fond ; si la file n'est pas joignable, l'ouverture ne doit pas échouer pour autant."""
        import logging
        try:
            from .tasks import prevenir_le_reseau_des_dons_task
            # Sans nouvelle tentative : si la file d'attente est injoignable, on le sait tout de suite.
            prevenir_le_reseau_des_dons_task.apply_async(args=[str(appel.id)], retry=False)
        except Exception as exc:
            logging.getLogger(__name__).warning("Réseau non prévenu de l'appel aux dons (%s).", type(exc).__name__)

    def perform_destroy(self, instance):
        self._le_mien(instance)
        if instance.statut != StatutAppelDons.BROUILLON:
            raise ValidationError({"detail": "Seul un brouillon se supprime : un appel ouvert se clôt."})
        instance.delete()

    def retrieve(self, request, *args, **kwargs):
        appels_dons.relacher_les_retards(self.get_object())
        return super().retrieve(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        appels_dons.relacher_les_retards()
        return super().list(request, *args, **kwargs)

    def _rendre(self, appel, code=status.HTTP_200_OK, **extra):
        donnees = self.get_serializer(self.get_queryset().get(pk=appel.pk)).data
        return Response({**donnees, **extra}, status=code)

    @action(detail=True, methods=["post"])
    def lignes(self, request, pk=None):
        """POST {lignes: [{famille, designation, public, taille, quantite_voulue, neuf_exige, precision}]}
        -- ajoute des lignes, ou ajuste celles qui existent. Une quantité ne descend jamais sous
        ce qui est déjà promis ou reçu ; à zéro, la ligne est retirée si personne ne s'y est engagé."""
        appel = self._le_mien(self.get_object())
        if appel.statut == StatutAppelDons.CLOS:
            raise ValidationError({"detail": "Cet appel est clos."})
        with transaction.atomic():
            existantes = {appels_dons._cle(b): b for b in appel.besoins.all()}
            for ligne in request.data.get("lignes") or []:
                if str(ligne.get("quantite_voulue")) in ("0", "0.0"):
                    champs = {"famille": str(ligne.get("famille") or "DIVERS")[:30], "designation": " ".join(str(ligne.get("designation") or "").split())[:120],
                              "public": ligne.get("public") or "", "taille": str(ligne.get("taille") or "").strip()[:20],
                              "message": " ".join(str(ligne.get("message") or "").split())[:300]}
                    besoin = existantes.get((champs["famille"], champs["designation"], champs["public"], champs["taille"], champs["message"]))
                    if besoin is not None:
                        if appels_dons.couvert(besoin) > 0:
                            raise ValidationError({"detail": f"« {appels_dons.libelle(besoin)} » : des dons sont déjà promis ou reçus, la ligne ne se retire plus."})
                        besoin.delete()
                    continue
                champs, quantite = _ligne_valide(ligne, "quantite_voulue")
                precision = str(ligne.get("precision") or "")[:200]
                try:
                    personnes = max(1, min(int(ligne.get("nb_beneficiaires") or 1), quantite))
                except (TypeError, ValueError):
                    personnes = 1
                besoin = existantes.get((champs["famille"], champs["designation"], champs["public"], champs["taille"], champs["message"]))
                if besoin is None:
                    besoin = BesoinDon.objects.create(appel=appel, quantite_voulue=quantite, precision=precision, nb_beneficiaires=personnes, **champs)
                    existantes[appels_dons._cle(besoin)] = besoin
                else:
                    besoin.quantite_voulue = max(quantite, appels_dons.couvert(besoin))
                    besoin.neuf_exige, besoin.precision = champs["neuf_exige"], precision
                    if "nb_beneficiaires" in ligne:
                        besoin.nb_beneficiaires = min(personnes, besoin.quantite_voulue)
                    besoin.save(update_fields=["quantite_voulue", "neuf_exige", "precision", "nb_beneficiaires"])
        return self._rendre(appel)

    @action(detail=True, methods=["post"], url_path="reprendre-foyers")
    def reprendre_foyers(self, request, pk=None):
        """Pose sur l'appel la somme de ce qui manque encore aux foyers de la crise."""
        appel = self._le_mien(self.get_object())
        if appel.statut == StatutAppelDons.CLOS:
            raise ValidationError({"detail": "Cet appel est clos."})
        return self._rendre(appel, reprise=appels_dons.reprendre_les_foyers(appel))

    @action(detail=True, methods=["post"])
    def ouvrir(self, request, pk=None):
        appel = self._le_mien(self.get_object())
        if appel.statut == StatutAppelDons.OUVERT:
            raise ValidationError({"detail": "Cet appel est déjà ouvert."})
        if not appel.besoins.exists():
            raise ValidationError({"detail": "Un appel sans aucune ligne ne s'ouvre pas : dites ce qu'il faut."})
        if not (appel.point_id or appel.depot_id or appel.livraison_adresse):
            raise ValidationError({"detail": "Dites où livrer : un point de regroupement, un dépôt ou une adresse."})
        appel.statut, appel.date_ouverture, appel.date_cloture = StatutAppelDons.OUVERT, timezone.now(), None
        appel.save(update_fields=["statut", "date_ouverture", "date_cloture"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="AppelAuxDons", objet_id=appel.id, crise=appel.crise,
                  commentaire=f"Appel aux dons « {appel.titre} » ouvert aux autres institutions")
        # L'équipe de l'institution l'apprend dans son salon ; l'avis, lui, est public.
        notifications_dons.prevenir(
            de=appel.institution, vers=appel.institution, request=request, crise=appel.crise, environment=appel.environment,
            titre=f"Appel ouvert : « {appel.titre} »",
            corps=f"{appel.besoins.count()} ligne(s), {sum(b.quantite_voulue for b in appel.besoins.all())} pièce(s) demandée(s). "
                  "L'avis est public ; les institutions du périmètre sont prévenues et peuvent s'y engager.")
        self._prevenir_le_reseau(appel)
        return self._rendre(appel)

    @action(detail=True, methods=["post"])
    def clore(self, request, pk=None):
        """Clôt l'appel : plus d'engagement possible. Ce qui est déjà en route reste à recevoir."""
        appel = self._le_mien(self.get_object())
        appel.statut, appel.date_cloture = StatutAppelDons.CLOS, timezone.now()
        appel.save(update_fields=["statut", "date_cloture"])
        EngagementDon.objects.filter(besoin__appel=appel, statut=StatutEngagementDon.PROMIS).update(statut=StatutEngagementDon.ANNULE)
        audit_log(request=request, action_code="CLOTURE", objet_type="AppelAuxDons", objet_id=appel.id, crise=appel.crise,
                  commentaire=f"Appel aux dons « {appel.titre} » clos")
        return self._rendre(appel)

    @action(detail=True, methods=["post"])
    def engager(self, request, pk=None):
        """POST {besoin, quantite} -- mon institution s'engage sur une part d'une ligne."""
        appel = self.get_object()
        besoin = appel.besoins.filter(pk=request.data.get("besoin")).first()
        if besoin is None:
            raise ValidationError({"besoin": "Ligne introuvable dans cet appel."})
        try:
            engagement = appels_dons.engager(besoin, _institution_ou_refus(request), request.data.get("quantite"), auteur=request.user)
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="CREATION", objet_type="AppelAuxDons", objet_id=appel.id, crise=appel.crise,
                  commentaire=f"Engagement de don : {engagement.quantite} × {appels_dons.libelle(besoin)}")
        personnes, courriels = notifications_dons.contacts_de(appel)
        notifications_dons.prevenir(
            de=engagement.institution, vers=appel.institution, personnes=personnes, courriels=courriels, request=request, crise=appel.crise,
            environment=appel.environment, titre=f"{engagement.institution.nom} s'engage sur votre appel « {appel.titre} »",
            corps=f"{engagement.institution.nom} s'engage à fournir {engagement.quantite} pièce(s) : {appels_dons.libelle(besoin)}.\n"
                  f"Il reste {appels_dons.reste(besoin)} pièce(s) à couvrir sur cette ligne.")
        return self._rendre(appel, code=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="annuler-engagement")
    def annuler_engagement(self, request, pk=None):
        """POST {engagement} -- je renonce à une promesse pas encore expédiée : la part est rendue."""
        appel = self.get_object()
        moi = _institution_ou_refus(request)
        modifies = EngagementDon.objects.filter(pk=request.data.get("engagement"), besoin__appel=appel, institution=moi,
                                                statut=StatutEngagementDon.PROMIS).update(statut=StatutEngagementDon.ANNULE)
        if not modifies:
            raise ValidationError({"detail": "Cet engagement n'est pas le vôtre, ou il est déjà parti."})
        return self._rendre(appel)

    @action(detail=True, methods=["post"], url_path="annoncer-envoi")
    def annoncer_envoi(self, request, pk=None):
        """POST {engagements: [...], date_expedition[, arrivee_prevue, transporteur, contact, commentaire]}."""
        appel = self.get_object()
        donnees = request.data
        date_expedition = stocks._date(donnees.get("date_expedition")) or timezone.localdate()
        try:
            appels_dons.annoncer_un_envoi(
                appel, _institution_ou_refus(request), donnees.get("engagements") or [], date_expedition=date_expedition,
                arrivee_prevue=stocks._date(donnees.get("arrivee_prevue")) if donnees.get("arrivee_prevue") else None,
                transporteur=donnees.get("transporteur") or "", contact=donnees.get("contact") or "",
                commentaire=donnees.get("commentaire") or "", auteur=request.user, environment=get_active_environment(request))
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        moi = _institution_ou_refus(request)
        envoi = appel.envois.filter(institution=moi).order_by("-date_creation").first()
        contenu = "\n".join(f"- {g.quantite} × {appels_dons.libelle(g.besoin)}" for g in envoi.engagements.select_related("besoin"))
        personnes, courriels = notifications_dons.contacts_de(appel)
        notifications_dons.prevenir(
            de=moi, vers=appel.institution, personnes=personnes, courriels=courriels, request=request, crise=appel.crise,
            environment=appel.environment, titre=f"Un envoi part pour votre appel « {appel.titre} »",
            corps=f"{moi.nom} annonce un envoi, parti le {envoi.date_expedition:%d/%m/%Y}"
                  + (f", attendu le {envoi.arrivee_prevue:%d/%m/%Y}" if envoi.arrivee_prevue else "")
                  + (f" ({envoi.transporteur})" if envoi.transporteur else "") + f" :\n{contenu}"
                  + (f"\nContact du convoi : {envoi.contact}" if envoi.contact else "")
                  + "\nÀ l'arrivée, comptez ce qui est là : c'est ce qui fait entrer les dons en stock.")
        audit_log(request=request, action_code="CREATION", objet_type="AppelAuxDons", objet_id=appel.id, crise=appel.crise,
                  commentaire="Envoi de dons annoncé")
        return self._rendre(appel, code=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="recevoir-envoi")
    def recevoir_envoi(self, request, pk=None):
        """POST {envoi[, comptes: {engagement: quantité comptée}, depot]} -- on compte ce qui arrive."""
        appel = self._le_mien(self.get_object())
        envoi = EnvoiDon.objects.filter(pk=request.data.get("envoi"), appel=appel).select_related("institution", "appel").first()
        if envoi is None:
            raise ValidationError({"envoi": "Envoi introuvable sur cet appel."})
        depot = _du_perimetre(request, DepotStock.objects.all()).filter(pk=request.data.get("depot")).first() if request.data.get("depot") else appel.depot
        if depot is None and appel.point_id:
            from .stocks_points import depot_du_point
            depot = depot_du_point(appel.point, appel.institution, appel.environment)
        try:
            mouvements = appels_dons.recevoir(envoi, request.data.get("comptes") or {}, depot=depot, auteur=request.user)
        except stocks.ErreurStock as erreur:
            raise _erreur(erreur)
        audit_log(request=request, action_code="MODIFICATION", objet_type="AppelAuxDons", objet_id=appel.id, crise=appel.crise,
                  commentaire=f"Envoi de dons reçu de {envoi.institution.nom} : {len(mouvements)} ligne(s) entrée(s) en stock")
        comptees = list(envoi.engagements.select_related("besoin", "cree_par"))
        ecarts = [g for g in comptees if g.quantite_recue != g.quantite]
        notifications_dons.prevenir(
            de=appel.institution, vers=envoi.institution, personnes=[envoi.cree_par, *(g.cree_par for g in comptees)], request=request,
            crise=appel.crise, environment=appel.environment, titre=f"Votre envoi pour « {appel.titre} » est bien arrivé",
            corps=f"{appel.institution.nom} a reçu et compté votre envoi :\n"
                  + "\n".join(f"- {g.quantite_recue} × {appels_dons.libelle(g.besoin)}"
                               + (f" (annoncé : {g.quantite})" if g.quantite_recue != g.quantite else "") for g in comptees)
                  + ("\nCertaines quantités diffèrent de ce qui était annoncé : la différence est de nouveau à couvrir." if ecarts else "")
                  + "\nMerci.")
        return self._rendre(appel, entre_en_stock=depot is not None, depot_nom=depot.nom if depot else None)


class AvisDonsPublicsView(APIView):
    """GET /api/dons/avis/ -- les avis d'appels aux dons, lisibles de tous (décision de Sylvain du
    17/11/2026 : « les avis d'appels aux dons doivent être publics, mais pour lancer une collecte
    il faut passer par une institution — asso, mairie… — qui doit rejoindre le réseau,
    gratuitement »). On y lit ce qu'il faut et ce qui reste à couvrir ; ni contact, ni lieu de
    livraison, ni qui s'est engagé : ceux-là se lisent une fois dans le réseau."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from .models import Environment
        return Response({
            "avis": appels_dons.avis_publics(Environment.PROD),
            "comment_aider": ("Pour organiser une collecte, passez par une association, une mairie ou toute autre institution : elle "
                              "rejoint le réseau gratuitement, s'engage sur une quantité précise et reçoit le lieu de livraison. "
                              "C'est ce qui évite que dix collectes couvrent le même besoin."),
        })
