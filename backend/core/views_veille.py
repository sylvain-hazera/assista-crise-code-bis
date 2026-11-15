"""Veille du territoire : vigilance et mesures Météo-France, événements routiers, stations de
carburant.

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

import json

from . import (
    avalanche, meteo_forets, meteo_france, pluie, restrictions_eau, sources_ouvertes, trafic_routier,
    vigilance_crues,
)
from .models import (
    Commune, ConfigurationAlerteVigilance, ContactInstitution, DangerFeuForet, EvenementRoutier,
    ImagePluie, Institution, ObservationMeteo, ReleveMeteoForets, RestrictionEau, RisqueAvalanche,
    StationCarburant, TronconVigilanceCrues, ZoneBrulee, UserRole, VigilanceMeteo, VignetteVigilanceMeteo,
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


def _distance_km(latitude1, longitude1, latitude2, longitude2):
    """Distance à vol d'oiseau, pour ranger les stations de la plus proche à la plus lointaine."""
    phi1, phi2 = math.radians(latitude1), math.radians(latitude2)
    a = (math.sin((phi2 - phi1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(longitude2 - longitude1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


class ObservationsMeteoView(APIView):
    """GET /api/observations-meteo/ : les dernières mesures des stations Météo-France d'une
    emprise (voir `_emprise`), de la plus proche à la plus lointaine quand un centre est connu."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("OBSERVATIONS_METEO", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "resultats": []})

        stations = list(ObservationMeteo.objects.filter(location__within=emprise)
                        .order_by("nom", "station")[:RESULTATS_MAX + 1])
        resultats = []
        for station in stations[:RESULTATS_MAX]:
            latitude, longitude = _point(station.location)
            resultats.append({
                "station": station.station,
                "nom": station.nom,
                "altitude_m": station.altitude_m,
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"],
                                                   latitude, longitude), 1) if centre else None),
                "mesure_le": station.mesure_le,
                "temperature_c": station.temperature_c,
                "humidite_pct": station.humidite_pct,
                "vent_kmh": station.vent_kmh,
                "vent_direction": station.vent_direction,
                "rafale_kmh": station.rafale_kmh,
                "pluie_6min_mm": station.pluie_6min_mm,
                "neige_cm": station.neige_cm,
                "heure_le": station.heure_le,
                "pluie_1h_mm": station.pluie_1h_mm,
                "rafale_1h_kmh": station.rafale_1h_kmh,
                "pluie_24h_mm": station.pluie_24h_mm,
                "heures_cumulees": station.heures_cumulees,
            })
        if centre:
            resultats.sort(key=lambda r: r["distance_km"])
        return Response({**entete, "emprise_connue": True,
                         "tronque": len(stations) > RESULTATS_MAX, "resultats": resultats})


class PluiePrevueView(APIView):
    """GET /api/pluie-prevue/ : les quarts d'heure pour lesquels une image de pluie prévue est
    disponible, et les quatre coins où la poser sur la carte."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ouest, sud, est, nord = pluie.EMPRISE
        images = list(ImagePluie.objects.order_by("echeance").values("echeance", "calcul"))
        return Response({
            **sources_ouvertes.resume("PLUIE_PREVISION"),
            "calcul": max((i["calcul"] for i in images), default=None),
            # Ordre attendu par la carte : haut-gauche, haut-droite, bas-droite, bas-gauche.
            "coins": [[ouest, nord], [est, nord], [est, sud], [ouest, sud]],
            "echeances": [i["echeance"] for i in images],
        })


class ImagePluieView(APIView):
    """GET /api/pluie-prevue/image/?echeance=… : l'image d'une échéance (PNG transparent).

    Sans authentification, comme la carte de vigilance : une source d'image de la carte
    n'envoie pas le jeton de session, et la donnée est publique. Relit la copie en base."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        from django.utils.dateparse import parse_datetime

        echeance = parse_datetime(request.query_params.get("echeance") or "")
        image = ImagePluie.objects.filter(pk=echeance).first() if echeance else None
        if image is None:
            return HttpResponseNotFound()
        reponse = HttpResponse(bytes(image.image), content_type="image/png")
        # Une échéance d'un calcul donné ne change pas : dix minutes de cache suffisent à
        # rendre l'animation fluide, et laissent passer le calcul suivant.
        reponse["Cache-Control"] = "public, max-age=600"
        return reponse


class VigilanceCruesView(APIView):
    """GET /api/vigilance-crues/ : les tronçons de cours d'eau surveillés par Vigicrues qui
    traversent une emprise (voir `_emprise`), les plus préoccupants d'abord. `?trace=1` joint
    leur tracé (pour la carte) ; sans lui, la réponse reste légère (pour une liste)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("VIGILANCE_CRUES", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "resultats": []})

        avec_trace = request.query_params.get("trace") in ("1", "true")
        troncons = list(TronconVigilanceCrues.objects.filter(geometrie__intersects=emprise)
                        .order_by("-niveau", "nom")[:RESULTATS_MAX + 1])
        resultats = []
        for troncon in troncons[:RESULTATS_MAX]:
            ligne = {
                "code": troncon.code, "nom": troncon.nom, "niveau": troncon.niveau,
                "couleur": vigilance_crues.COULEURS.get(troncon.niveau, "vert"),
                "publie_le": troncon.publie_le,
            }
            if avec_trace:
                ligne["trace"] = json.loads(troncon.geometrie.geojson)
            resultats.append(ligne)
        return Response({**entete, "emprise_connue": True,
                         "tronque": len(troncons) > RESULTATS_MAX, "resultats": resultats})


class RestrictionsEauView(APIView):
    """GET /api/restrictions-eau/ : le niveau de restriction d'usage de l'eau le plus élevé de
    chaque département, et celui de l'appelant (`?departement=42` pour un autre)."""
    permission_classes = [permissions.AllowAny]

    @staticmethod
    def _ligne(restriction):
        return {
            "departement_code": restriction.departement_code,
            "nom": meteo_france.nom_departement(restriction.departement_code),
            "niveau": restriction.niveau,
            "niveau_superficielle": restriction.niveau_superficielle,
            "niveau_souterraine": restriction.niveau_souterraine,
            "niveau_potable": restriction.niveau_potable,
        }

    def get(self, request):
        lignes = {r.departement_code: r for r in RestrictionEau.objects.all()}
        code = request.query_params.get("departement") or _departement_de_l_appelant(request)
        mien = lignes.get(code) if code else None
        rang = {niveau: i for i, niveau in enumerate(restrictions_eau.NIVEAUX)}
        concernes = sorted((r for r in lignes.values() if r.niveau),
                           key=lambda r: (-rang.get(r.niveau, -1), r.departement_code))
        return Response({
            **sources_ouvertes.resume("RESTRICTIONS_EAU"),
            "date_donnees": max((r.date_donnees for r in lignes.values()), default=None),
            "libelles": restrictions_eau.LIBELLES,
            "mon_departement": self._ligne(mien) if mien else None,
            "departements": [self._ligne(r) for r in concernes],
        })


class ZonesBruleesView(APIView):
    """GET /api/zones-brulees/ : les surfaces brûlées des trente derniers jours dans une emprise
    (voir `_emprise`), les plus récentes d'abord. `?trace=1` joint leur contour."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("FEUX_SATELLITE", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "resultats": []})

        avec_trace = request.query_params.get("trace") in ("1", "true")
        zones = list(ZoneBrulee.objects.filter(location__within=emprise)
                     .order_by("-date_feu", "reference")[:RESULTATS_MAX + 1])
        resultats = []
        for zone in zones[:RESULTATS_MAX]:
            latitude, longitude = _point(zone.location)
            ligne = {
                "reference": zone.reference, "date_feu": zone.date_feu,
                "commune_nom": zone.commune_nom, "departement_nom": zone.departement_nom,
                "surface_ha": zone.surface_ha, "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"],
                                                   latitude, longitude), 1) if centre else None),
            }
            if avec_trace:
                ligne["trace"] = json.loads(zone.geometrie.geojson)
            resultats.append(ligne)
        return Response({**entete, "emprise_connue": True,
                         "tronque": len(zones) > RESULTATS_MAX, "resultats": resultats})


class MeteoForetsView(APIView):
    """GET /api/meteo-forets/ : le danger de feu de forêt de demain et d'après-demain, par
    département. `en_saison` est faux d'octobre à mai : Météo-France ne publie alors rien."""
    permission_classes = [permissions.AllowAny]

    @staticmethod
    def _ligne(danger):
        return {
            "departement_code": danger.departement_code,
            "nom": meteo_france.nom_departement(danger.departement_code),
            "niveau_demain": danger.niveau_demain,
            "niveau_apres_demain": danger.niveau_apres_demain,
        }

    def get(self, request):
        etat = ReleveMeteoForets.objects.first()
        lignes = {d.departement_code: d for d in DangerFeuForet.objects.all()}
        code = request.query_params.get("departement") or _departement_de_l_appelant(request)
        mien = lignes.get(code) if code else None
        eleves = sorted(
            (d for d in lignes.values() if max(d.niveau_demain or 0, d.niveau_apres_demain or 0) >= 3),
            key=lambda d: (-max(d.niveau_demain or 0, d.niveau_apres_demain or 0), d.departement_code))
        return Response({
            **sources_ouvertes.resume("METEO_FORETS"),
            "en_saison": bool(etat and etat.en_saison),
            # Une carte publiée que le serveur n'a pas su lire : à dire, plutôt que d'afficher
            # « rien à signaler ».
            "compris": etat.compris if etat else True,
            "libelles": meteo_forets.NIVEAUX,
            "mon_departement": self._ligne(mien) if mien else None,
            "departements": [self._ligne(d) for d in eleves],
        })


class RisqueAvalancheView(APIView):
    """GET /api/risque-avalanche/ : les massifs qui touchent une emprise (voir `_emprise`), le
    risque le plus élevé d'abord. `?trace=1` joint leur contour (pour la carte). Liste vide en
    plaine : c'est ce qui dit à l'écran de ne pas afficher ce bloc."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("AVALANCHE", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "libelles": avalanche.NIVEAUX, "resultats": []})

        avec_trace = request.query_params.get("trace") in ("1", "true")
        massifs = sorted(RisqueAvalanche.objects.filter(geometrie__intersects=emprise),
                         key=lambda m: (-(m.risque or 0), m.nom))
        resultats = []
        for massif in massifs:
            ligne = {
                "massif_code": massif.massif_code, "nom": massif.nom, "chaine": massif.chaine,
                "departement_nom": massif.departement_nom,
                "risque": massif.risque, "risque_demain": massif.risque_demain,
                "commentaire": massif.commentaire, "resume": massif.resume,
                "publie_le": massif.publie_le, "valide_jusqu_a": massif.valide_jusqu_a,
            }
            if avec_trace:
                ligne["trace"] = json.loads(massif.geometrie.geojson)
            resultats.append(ligne)
        return Response({**entete, "emprise_connue": True, "tronque": False,
                         "libelles": avalanche.NIVEAUX, "resultats": resultats})


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
