"""Veille du territoire : vigilance Météo-France, événements routiers, stations de carburant.

Aucune de ces vues n'appelle l'extérieur : elles lisent ce que `relever_sources_ouvertes` a
copié en base (voir core/sources_ouvertes.py). Une requête d'utilisateur ne déclenche donc
jamais d'appel sortant.

Les trois lectures sont publiques : ce sont des données publiques, sans rien de personnel, et
savoir où trouver du carburant ou quelle route est coupée sert autant à un habitant qu'à une
mairie. Seul le RÉGLAGE de l'annonce de vigilance est réservé aux acteurs institutionnels."""
import math

from django.contrib.gis.geos import Polygon
from django.db.models import Case, IntegerField, Value, When
from django.http import HttpResponse, HttpResponseNotFound
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import meteo_france, sources_ouvertes, trafic_routier
from .models import (
    Commune, ConfigurationAlerteVigilance, ContactInstitution, EvenementRoutier, Institution,
    StationCarburant, UserRole, VigilanceMeteo, VignetteVigilanceMeteo,
)
from .permissions import IsInstitutionalActor, get_active_environment, get_effective_role
from .serializers import ConfigurationAlerteVigilanceSerializer, VigilanceMeteoSerializer
from .views import EnvironmentScopedViewSetMixin, _resolve_institution_or_400


RAYON_DEFAUT_KM, RAYON_MAX_KM = 30, 150
# Plafond d'une réponse : une carte ne sait rien faire de plus, et une emprise qui en rend
# davantage est trop large pour être lue.
RESULTATS_MAX = 500


def _institution_de_l_appelant(request):
    if not request.user.is_authenticated:
        return None
    contact = (ContactInstitution.objects
               .filter(utilisateur=request.user, actif=True)
               .select_related("institution").first())
    return contact.institution if contact else None


def _departement_de_l_appelant(request):
    """Département de l'institution à laquelle la personne est rattachée, ou None."""
    institution = _institution_de_l_appelant(request)
    return meteo_france.departement_de(institution) if institution else None


def _nombre(valeur):
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return None
    return nombre if math.isfinite(nombre) else None


def _emprise(request):
    """Zone demandée -> (polygone, centre, rayon_km), ou (None, None, None) si rien ne la fixe.

    Trois façons de la donner, dans cet ordre : `bbox=ouest,sud,est,nord` (la carte), `lat` et
    `lon` avec un `rayon_km` facultatif, et à défaut la commune de l'institution de l'appelant.
    Le rayon devient un rectangle : à cette échelle l'écart avec un cercle est sans effet sur ce
    qu'on affiche, et un rectangle se sert de l'index spatial sans calcul de distance."""
    brut = request.query_params.get("bbox")
    if brut:
        bornes = [_nombre(v) for v in brut.split(",")]
        if len(bornes) == 4 and None not in bornes:
            ouest, sud, est, nord = bornes
            if -180 <= ouest < est <= 180 and -90 <= sud < nord <= 90:
                return Polygon.from_bbox((ouest, sud, est, nord)), None, None
        raise ValidationError({"bbox": "Attendu : ouest,sud,est,nord en degrés."})

    latitude, longitude = _nombre(request.query_params.get("lat")), _nombre(request.query_params.get("lon"))
    if latitude is None or longitude is None:
        institution = _institution_de_l_appelant(request)
        commune = (Commune.objects.filter(code=institution.commune_code).first()
                   if institution and institution.commune_code else None)
        if commune is None or commune.centre_latitude is None or commune.centre_longitude is None:
            return None, None, None
        latitude, longitude = commune.centre_latitude, commune.centre_longitude
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValidationError({"lat": "Position hors des bornes."})

    rayon = _nombre(request.query_params.get("rayon_km")) or RAYON_DEFAUT_KM
    rayon = max(1, min(RAYON_MAX_KM, rayon))
    ecart_lat = rayon / 111.0
    ecart_lon = rayon / (111.0 * max(0.1, math.cos(math.radians(latitude))))
    emprise = Polygon.from_bbox((longitude - ecart_lon, latitude - ecart_lat,
                                 longitude + ecart_lon, latitude + ecart_lat))
    return emprise, {"latitude": latitude, "longitude": longitude}, rayon


def _entete(code, centre, rayon):
    return {**sources_ouvertes.resume(code), "centre": centre, "rayon_km": rayon}


class VigilanceMeteoView(APIView):
    """GET /api/vigilance-meteo/ : la France, les départements en vigilance, et celui de
    l'appelant avec son bulletin.

    `?departement=42` remplace le département de l'appelant par un autre (donnée publique : nul
    besoin d'y être rattaché)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        lignes = {ligne.departement_code: ligne for ligne in VigilanceMeteo.objects.all()}
        france = lignes.pop(meteo_france.FRANCE, None)
        code = request.query_params.get("departement") or _departement_de_l_appelant(request)
        mien = lignes.get(code) if code else None

        en_vigilance = sorted(
            (ligne for ligne in lignes.values() if max(ligne.couleur_j, ligne.couleur_j1) >= 2),
            key=lambda ligne: (-max(ligne.couleur_j, ligne.couleur_j1), ligne.departement_code),
        )
        dernier = max((ligne.releve_le for ligne in lignes.values()), default=None)
        avec_bulletin = {"avec_bulletin": True}
        return Response({
            "disponible": bool(lignes),
            "source": sources_ouvertes.SOURCES["VIGILANCE_METEO"].attribution,
            "releve_le": dernier,
            "publie_le": france.publie_le if france else None,
            "perime": bool(dernier) and (timezone.now() - dernier) > meteo_france.FRAICHEUR_MAX,
            "phenomenes": meteo_france.PHENOMENES,
            "couleurs": meteo_france.COULEURS,
            "france": VigilanceMeteoSerializer(france, context=avec_bulletin).data if france else None,
            "mon_departement": VigilanceMeteoSerializer(mien, context=avec_bulletin).data if mien else None,
            "departements": VigilanceMeteoSerializer(en_vigilance, many=True).data,
            "vignettes": sorted(VignetteVigilanceMeteo.objects.values_list("echeance", flat=True)),
        })


class VignetteVigilanceMeteoView(APIView):
    """GET /api/vigilance-meteo/vignette/<J|J1>/ : la carte nationale officielle (PNG).

    Sans authentification : une balise <img> n'envoie pas le jeton de session, et l'image est
    publique. La vue ne fait que relire la copie en base."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, echeance):
        vignette = VignetteVigilanceMeteo.objects.filter(pk=echeance).first()
        if vignette is None:
            return HttpResponseNotFound()
        reponse = HttpResponse(bytes(vignette.image), content_type="image/png")
        reponse["Cache-Control"] = "public, max-age=300"
        return reponse


def _point(position):
    return (None, None) if position is None else (position.y, position.x)


class EvenementsRoutiersView(APIView):
    """GET /api/evenements-routiers/ : les événements du réseau routier national dans une
    emprise (voir `_emprise`), les plus contraignants d'abord. `?categorie=FERMETURE,ACCIDENT`
    restreint la liste."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("TRAFIC_ROUTIER", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "resultats": []})

        evenements = EvenementRoutier.objects.filter(location__within=emprise)
        categories = [c for c in (request.query_params.get("categorie") or "").split(",") if c]
        if categories:
            evenements = evenements.filter(categorie__in=categories)
        # Tri fait par la base, AVANT le plafond : si l'emprise déborde, ce sont les travaux
        # qu'on laisse de côté, jamais une route fermée.
        rang = Case(
            *[When(categorie=categorie, then=Value(i))
              for i, categorie in enumerate(trafic_routier.ORDRE_CATEGORIES)],
            default=Value(99), output_field=IntegerField(),
        )
        lignes = list(evenements.annotate(rang=rang)
                      .order_by("rang", "route", "reference")[:RESULTATS_MAX + 1])
        resultats = []
        for evenement in lignes[:RESULTATS_MAX]:
            latitude, longitude = _point(evenement.location)
            latitude_fin, longitude_fin = _point(evenement.location_fin)
            resultats.append({
                "reference": evenement.reference,
                "categorie": evenement.categorie,
                "categorie_libelle": evenement.get_categorie_display(),
                "natures": evenement.natures,
                "gravite": evenement.gravite,
                "route": evenement.route,
                "commune_nom": evenement.commune_nom,
                "description": evenement.description,
                "localisation": evenement.localisation,
                "gestionnaire": evenement.gestionnaire,
                "departement_code": evenement.departement_code,
                "latitude": latitude, "longitude": longitude,
                "latitude_fin": latitude_fin, "longitude_fin": longitude_fin,
                "debut": evenement.debut, "fin": evenement.fin,
                "mis_a_jour_le": evenement.mis_a_jour_le,
            })
        return Response({**entete, "emprise_connue": True,
                         "tronque": len(lignes) > RESULTATS_MAX, "resultats": resultats})


class StationsCarburantView(APIView):
    """GET /api/stations-carburant/ : les stations d'une emprise (voir `_emprise`), avec ce
    qu'elles délivrent encore. `?rupture=1` ne garde que celles où un carburant manque."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("CARBURANTS", centre, rayon)
        vide = {"total": 0, "en_rupture": 0, "a_sec": 0}
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "bilan": vide, "resultats": []})

        dans_l_emprise = StationCarburant.objects.filter(location__within=emprise)
        en_rupture = dans_l_emprise.exclude(ruptures_temporaires=[])
        # Le bilan est compté par la base sur TOUTE l'emprise : il reste juste même quand la
        # liste est plafonnée.
        bilan = {
            "total": dans_l_emprise.count(),
            "en_rupture": en_rupture.count(),
            # À sec : plus rien à délivrer alors qu'au moins un carburant manque temporairement.
            "a_sec": en_rupture.filter(carburants_disponibles=[]).count(),
        }
        choisies = en_rupture if request.query_params.get("rupture") in ("1", "true") else dans_l_emprise
        stations = list(choisies.order_by("ville", "reference")[:RESULTATS_MAX + 1])
        tronque = len(stations) > RESULTATS_MAX
        stations = stations[:RESULTATS_MAX]
        resultats = []
        for station in stations:
            latitude, longitude = _point(station.location)
            resultats.append({
                "reference": station.reference,
                "adresse": station.adresse, "ville": station.ville,
                "code_postal": station.code_postal,
                "latitude": latitude, "longitude": longitude,
                "carburants_disponibles": station.carburants_disponibles,
                "ruptures_temporaires": station.ruptures_temporaires,
                "ruptures_definitives": station.ruptures_definitives,
                "prix": station.prix,
                "automate_24_24": station.automate_24_24,
                "mis_a_jour_le": station.mis_a_jour_le,
            })
        return Response({**entete, "emprise_connue": True, "tronque": tronque,
                         "bilan": bilan, "resultats": resultats})


class ConfigurationAlerteVigilanceViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Réglage de l'annonce de vigilance d'une institution -- même patron que
    ConfigurationAlerteSismiqueViewSet : zéro ou un enregistrement par institution, créé au
    premier réglage, modifié ensuite."""

    queryset = ConfigurationAlerteVigilance.objects.select_related('institution').all()
    serializer_class = ConfigurationAlerteVigilanceSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        institution_id = self.request.query_params.get('institution')
        if institution_id:
            qs = qs.filter(institution_id=institution_id)
        if get_effective_role(self.request) == UserRole.ADMINISTRATOR:
            return qs
        mes_institutions = ContactInstitution.objects.filter(
            utilisateur=self.request.user, actif=True
        ).values_list('institution_id', flat=True)
        return qs.filter(institution_id__in=mes_institutions)

    def perform_create(self, serializer):
        institution_id = self.request.data.get('institution')
        institution = Institution.objects.filter(pk=institution_id).first() if institution_id else None
        if institution is None:
            institution = _resolve_institution_or_400(self.request)
        if ConfigurationAlerteVigilance.objects.filter(institution=institution).exists():
            raise ValidationError("Un réglage d'alerte de vigilance existe déjà pour cette institution.")
        serializer.save(institution=institution, environment=get_active_environment(self.request))
