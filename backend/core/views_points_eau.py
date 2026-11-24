"""API des points d'eau incendie (24/11/2026) — voir core/points_eau.py. Tout est réservé aux
comptes connectés ; aucune de ces vues n'appelle l'extérieur (le relevé OSM est planifié)."""
import datetime
import hashlib
import logging
import uuid

from django.contrib.gis.geos import Point
from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import points_eau
from .audit import audit_log
from .permissions import get_active_environment
from .views_veille import RESULTATS_MAX, _distance_km, _emprise

logger = logging.getLogger(__name__)


def _nombre(valeur, champ, mini=None, maxi=None, obligatoire=False):
    if valeur in (None, ""):
        if obligatoire:
            raise ValidationError({champ: "Champ obligatoire."})
        return None
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        raise ValidationError({champ: "Nombre attendu."})
    if (mini is not None and nombre < mini) or (maxi is not None and nombre > maxi):
        raise ValidationError({champ: "Valeur hors des bornes."})
    return nombre


class PointsEauView(APIView):
    """GET /api/points-eau/?bbox=ouest,sud,est,nord (ou lat, lon, rayon_km) : les points d'eau de
    l'emprise. `osm=tous` montre aussi l'OSM là où une base SDIS est importée."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        emprise, centre, _rayon = _emprise(request, rayon_defaut=5)
        if emprise is None:
            return Response({"emprise_connue": False, "tronque": False, "total": 0, "resultats": []})
        qs = points_eau.visibles(get_active_environment(request), request.query_params.get("osm") == "tous") \
            .filter(location__within=emprise)
        total = qs.count()
        resultats = []
        for point in qs.order_by("source", "ref_source")[:RESULTATS_MAX]:
            distance = (round(_distance_km(centre["latitude"], centre["longitude"], point.location.y, point.location.x), 2)
                        if centre else None)
            resultats.append(points_eau.en_dict(point, distance))
        if centre:
            resultats.sort(key=lambda r: r["distance_km"])
        return Response({"emprise_connue": True, "tronque": total > RESULTATS_MAX, "total": total,
                         "resultats": resultats})


class PointsEauProchesView(APIView):
    """GET /api/points-eau/proches/?lat=&lon= : les points à moins de 50 m (doublon possible)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        lat = _nombre(request.query_params.get("lat"), "lat", -90, 90, True)
        lon = _nombre(request.query_params.get("lon"), "lon", -180, 180, True)
        trouves = points_eau.proches(get_active_environment(request), lat, lon)
        return Response({"rayon_m": points_eau.RAYON_DOUBLON_M,
                         "resultats": [points_eau.en_dict(p, round(_distance_km(lat, lon, p.location.y, p.location.x), 3))
                                       for p in trouves]})


class SignalementsPEIView(APIView):
    """GET : les signalements que je peux voir (ma commune, les miens ; tous pour l'admin),
    `?statut=`. POST : un signalement, idempotent par son `id` tiré sur le téléphone."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.db.models import Q

        from .models import SignalementPEI, UserRole
        from .permissions import get_effective_role

        qs = SignalementPEI.objects.filter(environment=get_active_environment(request)) \
            .select_related("auteur", "traite_par").prefetch_related("documents")
        if get_effective_role(request) != UserRole.ADMINISTRATOR:
            commune = points_eau.ma_commune(request) if get_effective_role(request) == UserRole.LOCAL_AUTHORITY else ""
            qs = qs.filter(Q(auteur=request.user) | (Q(commune_code=commune) if commune else Q(pk__in=[])))
        statut = request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut=statut)
        return Response([points_eau.signalement_en_dict(s, request) for s in qs[:300]])

    def post(self, request):
        from .models import Crisis, GenreSignalementPEI, PointEauIncendie, SignalementPEI, TypePEI

        if not points_eau.peut_signaler(request):
            raise PermissionDenied("Signaler un point d'eau est réservé aux comptes d'une mairie, aux secours et aux intervenants d'une équipe.")
        donnees = request.data
        try:
            identifiant = uuid.UUID(str(donnees.get("id")))
        except (TypeError, ValueError):
            raise ValidationError({"id": "Identifiant (UUID) attendu."})
        existant = SignalementPEI.objects.filter(pk=identifiant).first()
        if existant is not None:
            if existant.auteur_id != request.user.id:
                raise PermissionDenied("Cet identifiant appartient à un autre signalement.")
            return Response(points_eau.signalement_en_dict(existant, request), status=status.HTTP_200_OK)
        genre = str(donnees.get("genre") or "")
        if genre not in GenreSignalementPEI.values:
            raise ValidationError({"genre": "Attendu : " + ", ".join(GenreSignalementPEI.values)})
        lat = _nombre(donnees.get("latitude"), "latitude", -90, 90, True)
        lon = _nombre(donnees.get("longitude"), "longitude", -180, 180, True)
        environment = get_active_environment(request)
        pei = None
        if genre != GenreSignalementPEI.NOUVEAU:
            pei = points_eau.visibles(environment, True).filter(pk=donnees.get("pei")).first() if donnees.get("pei") else None
            if pei is None:
                raise ValidationError({"pei": "Point d'eau visé introuvable : choisissez-le sur la carte."})
        type_pei = str(donnees.get("type_pei") or "")
        if type_pei and type_pei not in TypePEI.values:
            raise ValidationError({"type_pei": "Attendu : PI, BI, PA ou CI."})
        if genre == GenreSignalementPEI.NOUVEAU and not type_pei:
            raise ValidationError({"type_pei": "Précisez la nature du point d'eau."})
        observe_le = parse_datetime(str(donnees.get("observe_le") or "")) or timezone.now()
        if timezone.is_naive(observe_le):
            observe_le = timezone.make_aware(observe_le)
        maintenant = timezone.now()
        if observe_le > maintenant + datetime.timedelta(minutes=10) or observe_le < maintenant - datetime.timedelta(days=30):
            observe_le = maintenant
        crise = Crisis.objects.filter(pk=donnees.get("crise")).first() if donnees.get("crise") else None
        signalement = SignalementPEI.objects.create(
            id=identifiant, genre=genre, pei=pei, pei_source=pei.source if pei else "", pei_ref=pei.ref_source if pei else "",
            location=Point(lon, lat, srid=4326),
            precision_m=int(_nombre(donnees.get("precision_m"), "precision_m", 0, 100000) or 0) or None,
            type_pei=type_pei, source_eau=str(donnees.get("source_eau") or "")[:20],
            debit_estime=_nombre(donnees.get("debit_estime"), "debit_estime", 0, 10000),
            volume_estime=_nombre(donnees.get("volume_estime"), "volume_estime", 0, 1000000),
            commentaire=" ".join(str(donnees.get("commentaire") or "").split())[:1000],
            auteur=request.user, crise=crise, commune_code=(pei.insee if pei and pei.insee else points_eau.commune_du_point(lat, lon)),
            observe_le=observe_le, environment=environment,
        )
        audit_log(request=request, action_code="CREATION", objet_type="SignalementPEI", objet_id=signalement.id,
                  crise=crise, commentaire=f"Signalement de point d'eau : {signalement.get_genre_display()}")
        points_eau.notifier_commune(signalement, request)
        doublons = []
        if genre == GenreSignalementPEI.NOUVEAU:
            doublons = [points_eau.en_dict(p) for p in points_eau.proches(environment, lat, lon)
                        if not (p.source == "TERRAIN" and p.ref_source == str(signalement.id))]
        return Response({**points_eau.signalement_en_dict(signalement, request), "doublons_possibles": doublons},
                        status=status.HTTP_201_CREATED)


def _signalement(request, ident):
    from .models import SignalementPEI

    signalement = SignalementPEI.objects.filter(pk=ident, environment=get_active_environment(request)).first()
    if signalement is None:
        raise ValidationError({"detail": "Signalement introuvable."})
    return signalement


class PhotoSignalementPEIView(APIView):
    """POST /api/points-eau/signalements/photo/ (multipart : signalement, fichier, commentaire),
    après le signalement. Même traitement que les photos de constat : empreinte, EXIF privé."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from .models import Document, SignalementPEI
        from .views import extract_exif_metadata

        try:
            identifiant = uuid.UUID(str(request.data.get("signalement")))
        except (TypeError, ValueError):
            identifiant = None
        signalement = SignalementPEI.objects.filter(pk=identifiant).first() if identifiant else None
        if signalement is None:
            return Response({"error": "Signalement inconnu : il doit être reçu avant ses photos."}, status=status.HTTP_404_NOT_FOUND)
        if signalement.auteur_id != request.user.id and points_eau.motif_refus_decision(request, signalement.commune_code):
            raise PermissionDenied("Une photo ne peut être jointe que par l'auteur du signalement ou la commune.")
        fichier = request.FILES.get("fichier")
        if fichier is None:
            return Response({"error": "fichier manquant."}, status=status.HTTP_400_BAD_REQUEST)
        document = Document.objects.create(fichier=fichier, auteur=request.user, signalement_pei=signalement,
                                           commentaire=" ".join(str(request.data.get("commentaire") or "").split())[:500],
                                           environment=signalement.environment)
        try:
            with open(document.fichier.path, "rb") as flux:
                document.sha256 = hashlib.sha256(flux.read()).hexdigest()
            document.metadata_publiques, document.metadata_privees = extract_exif_metadata(document.fichier.path)
            document.save()
        except Exception:   # noqa: BLE001 - même tolérance que les photos de constat
            logger.exception("Photo de signalement de point d'eau : empreinte ou métadonnées illisibles")
        return Response({"id": str(document.id), "sha256": document.sha256}, status=status.HTTP_201_CREATED)


class DeciderSignalementPEIView(APIView):
    """POST /api/points-eau/signalements/<id>/decider/ {geste: valider|rejeter, motif} : la
    commune du signalement (ou l'administrateur)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, ident):
        signalement = _signalement(request, ident)
        refus = points_eau.motif_refus_decision(request, signalement.commune_code)
        if refus:
            raise PermissionDenied(refus)
        geste = str(request.data.get("geste") or "")
        try:
            points_eau.decider(signalement, geste, request.data.get("motif"), request)
        except ValueError as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="SignalementPEI", objet_id=signalement.id,
                  crise=signalement.crise, commentaire=f"Signalement de point d'eau {signalement.get_statut_display().lower()}")
        return Response(points_eau.signalement_en_dict(signalement, request))


class TransmisSignalementPEIView(APIView):
    """POST /api/points-eau/signalements/<id>/transmis/ {numero_sdis} : la commune note la remise
    au SDIS d'un signalement validé."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, ident):
        from .models import StatutSignalementPEI

        signalement = _signalement(request, ident)
        refus = points_eau.motif_refus_decision(request, signalement.commune_code)
        if refus:
            raise PermissionDenied(refus)
        if signalement.statut not in (StatutSignalementPEI.VALIDE, StatutSignalementPEI.TRANSMIS_SDIS):
            raise ValidationError({"detail": "Seul un signalement validé se transmet au SDIS."})
        signalement.statut = StatutSignalementPEI.TRANSMIS_SDIS
        signalement.transmis_le = timezone.now()
        signalement.numero_sdis = " ".join(str(request.data.get("numero_sdis") or "").split())[:40]
        signalement.save(update_fields=["statut", "transmis_le", "numero_sdis"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="SignalementPEI", objet_id=signalement.id,
                  crise=signalement.crise, commentaire="Signalement de point d'eau transmis au SDIS")
        return Response(points_eau.signalement_en_dict(signalement, request))


class ExportPEIView(APIView):
    """GET /api/points-eau/export/?commune= : CSV au schéma national pour le SDIS (ma commune
    par défaut ; toute commune pour l'administrateur)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        commune = request.query_params.get("commune") or points_eau.ma_commune(request)
        refus = points_eau.motif_refus_decision(request, commune)
        if refus:
            raise PermissionDenied(refus)
        contenu = points_eau.export_csv(commune, get_active_environment(request))
        audit_log(request=request, action_code="EXPORT", objet_type="SignalementPEI",
                  commentaire=f"Export des points d'eau de la commune {commune} au schéma national")
        reponse = HttpResponse(contenu, content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = f'attachment; filename="pei-{commune}.csv"'
        return reponse


class ImportPEIView(APIView):
    """POST /api/points-eau/import/ (multipart : departement, fichier) : la base d'un SDIS au
    schéma national. Réservé à l'administrateur."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from . import points_eau_sdis
        from .models import UserRole
        from .permissions import get_effective_role

        if get_effective_role(request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied("L'import d'une base de SDIS est réservé à l'administrateur.")
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ValidationError({"fichier": "Fichier manquant."})
        departement = str(request.data.get("departement") or "").upper()
        try:
            rapport = points_eau_sdis.importer(departement, fichier.read(points_eau_sdis.TAILLE_MAX + 1), fichier.name)
        except (ValueError, UnicodeDecodeError) as erreur:
            raise ValidationError({"detail": str(erreur)})
        except Exception as erreur:   # noqa: BLE001 - fichier malformé : on le dit
            logger.exception("Import PEI")
            raise ValidationError({"detail": f"Fichier illisible : {type(erreur).__name__}."})
        audit_log(request=request, action_code="IMPORT_LISTE", objet_type="PointEauIncendie",
                  commentaire=f"Import SDIS du département {departement} : {rapport['importes']} points, {rapport['refuses']} refusés")
        return Response(rapport)


class CouverturePEIView(APIView):
    """GET /api/points-eau/couverture/ : par département, le dernier relevé OSM et la base SDIS."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .models import PointEauIncendie, ReleveDepartementPEI, SignalementPEI, StatutSignalementPEI
        from .points_eau_osm import ATTRIBUTION, DEPARTEMENTS

        etats = {r.departement_code: r for r in ReleveDepartementPEI.objects.all()}
        terrain = dict(PointEauIncendie.objects.filter(source="TERRAIN", environment=get_active_environment(request))
                       .values_list("departement_code").annotate(n=Count("id")).values_list("departement_code", "n"))
        lignes = []
        for code in DEPARTEMENTS:
            r = etats.get(code)
            lignes.append({
                "departement": code, "osm_releve_le": r.releve_le.isoformat() if r and r.releve_le else None,
                "osm_nombre": r.nombre if r else 0, "osm_erreur": (r.erreur or None) if r else None,
                "sdis_importe_le": r.sdis_importe_le.isoformat() if r and r.sdis_importe_le else None,
                "sdis_nombre": r.sdis_nombre if r else 0, "terrain_nombre": terrain.get(code, 0),
            })
        a_valider = SignalementPEI.objects.filter(environment=get_active_environment(request),
                                                  statut=StatutSignalementPEI.A_VALIDER)
        commune = points_eau.ma_commune(request)
        return Response({
            "attribution_osm": ATTRIBUTION, "departements": lignes,
            "releves": sum(1 for l in lignes if l["osm_releve_le"]),
            "a_valider_ma_commune": a_valider.filter(commune_code=commune).count() if commune else 0,
        })
