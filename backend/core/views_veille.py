"""Veille du territoire : vigilance et mesures Météo-France, événements routiers, stations de
carburant.

Aucune de ces vues n'appelle l'extérieur : elles lisent ce que `relever_sources_ouvertes` a
copié en base (voir core/sources_ouvertes.py). Une requête d'utilisateur ne déclenche donc
jamais d'appel sortant.

Les trois lectures sont publiques : ce sont des données publiques, sans rien de personnel, et
savoir où trouver du carburant ou quelle route est coupée sert autant à un habitant qu'à une
mairie. Seul le RÉGLAGE de l'annonce de vigilance est réservé aux acteurs institutionnels."""
import datetime
import math

from django.contrib.gis.geos import Polygon
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.http import HttpResponse, HttpResponseNotFound
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

import json

from . import (
    antennes_mobiles, arretes_circulation, avalanche, circulation, hauteurs_eau, meteo_forets, sante_urgences, seismes, meteo_france, niveaux_mer, pluie, precipitations_hiver, qualite_air, rafales, restrictions_eau, sources_ouvertes, trafic_routier, vent,
    vigilance_crues,
)
from .models import (
    AntenneIndisponible, ChampVent, ArreteCirculation, Commune, ConfigurationAlerteFeu, ConfigurationAlerteVigilance, FoyerActif, Defibrillateur, MesureRadioactivite,
    Seisme, ContactInstitution, DangerFeuForet, EvenementRoutier,
    ImagePluie, Maregraphe, PointQualiteAir, ImagePrecipitationHiver, ImageRafales, IndicateurSante, Institution, ObservationMeteo, ReleveMeteoForets, RestrictionEau, RisqueAvalanche, StationCirculation, StationHydrometrique,
    StationCarburant, TronconVigilanceCrues, ZoneBrulee, UserRole, VigilanceMeteo, VignetteVigilanceMeteo,
)
from .permissions import IsInstitutionalActor, get_active_environment, get_effective_role
from .serializers import (
    ConfigurationAlerteFeuSerializer, ConfigurationAlerteVigilanceSerializer, VigilanceMeteoSerializer,
)
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


def _emprise(request, rayon_defaut=None):
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

    rayon = _nombre(request.query_params.get("rayon_km")) or rayon_defaut or RAYON_DEFAUT_KM
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
            # Métropole et outre-mer sont relevés à part : ce qui compte pour l'appelant, c'est
            # l'âge de SON département, pas celui du relevé le plus récent de l'autre.
            "perime": bool(dernier) and (
                timezone.now() - (mien.releve_le if mien else dernier)) > meteo_france.FRAICHEUR_MAX,
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


def _image_d_une_echeance(modele, request):
    """Réponse PNG de l'image d'une série (pluie, rafales) pour `?echeance=…`, ou 404."""
    from django.utils.dateparse import parse_datetime

    echeance = parse_datetime(request.query_params.get("echeance") or "")
    image = modele.objects.filter(pk=echeance).first() if echeance else None
    if image is None:
        return HttpResponseNotFound()
    reponse = HttpResponse(bytes(image.image), content_type="image/png")
    # Une échéance d'un calcul donné ne change pas : dix minutes de cache suffisent à
    # rendre l'animation fluide, et laissent passer le calcul suivant.
    reponse["Cache-Control"] = "public, max-age=600"
    return reponse


class ImagePluieView(APIView):
    """GET /api/pluie-prevue/image/?echeance=… : l'image d'une échéance (PNG transparent).

    Sans authentification, comme la carte de vigilance : une source d'image de la carte
    n'envoie pas le jeton de session, et la donnée est publique. Relit la copie en base."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return _image_d_une_echeance(ImagePluie, request)


class RafalesPrevuesView(APIView):
    """GET /api/rafales-prevues/ : les quarts d'heure pour lesquels une image de rafales prévues
    est disponible, les quatre coins où la poser sur la carte et la légende de ses teintes.

    Avec `lat` et `lon`, ou `ici=1` pour la commune de l'institution de l'appelant, la réponse
    dit aussi le palier prévu À CET ENDROIT pour chaque échéance. C'est lu dans les images déjà
    copiées : aucun appel sortant, la position ne quitte pas ce serveur."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ouest, sud, est, nord = rafales.EMPRISE_IMAGE
        images = list(ImageRafales.objects.order_by("echeance"))
        ici = None
        if request.query_params.get("ici") or request.query_params.get("lat"):
            _emprise_inutile, centre, _rayon = _emprise(request)
            if centre:
                paliers = [{"echeance": image.echeance,
                            "a_partir_de_kmh": rafales.palier_au_point(
                                bytes(image.image), centre["latitude"], centre["longitude"])}
                           for image in images]
                connus = [p["a_partir_de_kmh"] for p in paliers if p["a_partir_de_kmh"] is not None]
                ici = {**centre, "couvert": bool(connus) or not images,
                       "maximum_kmh": max(connus, default=None), "paliers": paliers}
        return Response({
            **sources_ouvertes.resume("RAFALES_PREVISION"),
            "calcul": max((image.calcul for image in images), default=None),
            "coins": [[ouest, nord], [est, nord], [est, sud], [ouest, sud]],
            "echeances": [image.echeance for image in images],
            "legende": rafales.legende(),
            "ici": ici,
        })


#: Rayon par défaut autour de la commune pour les orages : une cellule à 60 km et à 60 km/h
#: arrive dans l'heure.
RAYON_ORAGES_KM = 60


class OragesView(APIView):
    """GET /api/orages/ : orages et pluies intenses autour du territoire (core/orages.py).

    Trois natures d'information, que la réponse ne mélange pas :
    - `releves` : ce que le radar a VU (contour, intensité, communes sous la pluie) et ce que les
      stations ont MESURÉ ;
    - `estimations` : NOS estimations, qui ne sont pas des prévisions — le déplacement et les
      communes atteintes si la cellule gardait sa vitesse et sa direction ;
    - `prevision_meteo_france` : ce que Météo-France prévoit au même endroit (AROME-PI).

    Même emprise que le reste de la veille (`bbox`, `lat`/`lon`/`rayon_km`, ou la commune de
    l'institution), 60 km par défaut. `?france=1` : toutes les cellules du pays."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from . import orages
        from .models import CelluleOrage, ImageRadarOrage

        image = ImageRadarOrage.objects.order_by("-heure").first()
        cellules = CelluleOrage.objects.all()
        centre, rayon, couvert, emprise = None, None, None, None
        if not request.query_params.get("france"):
            emprise, centre, rayon = _emprise(request, RAYON_ORAGES_KM)
            if emprise is None:
                cellules = CelluleOrage.objects.none()
            else:
                cellules = cellules.filter(Q(contour__intersects=emprise) | Q(couloir__intersects=emprise))
            if centre and image is not None:
                grille = orages.GrilleRadar(None, image.projdef, image.x0, image.y0, image.heure, [], [])
                (ligne,), (colonne,) = grille.depuis_geo([centre["longitude"]], [centre["latitude"]])
                ligne, colonne = int(round(ligne)), int(round(colonne))
                if 0 <= ligne < image.hauteur and 0 <= colonne < image.largeur:
                    valeurs = orages.GrilleRadar.depuis_compacte(image.grille, image.largeur, image.hauteur)
                    couvert = not math.isnan(float(valeurs[ligne, colonne]))
                else:
                    couvert = False

        def distance_km(cellule):
            if not centre:
                return None
            dlat = math.radians(cellule.centre.y - centre["latitude"])
            dlon = math.radians(cellule.centre.x - centre["longitude"]) * math.cos(math.radians(centre["latitude"]))
            return round(6371 * math.hypot(dlat, dlon))

        resultats = []
        for c in cellules.order_by("-max_mmh")[:RESULTATS_MAX]:
            resultats.append({
                "identifiant": c.identifiant,
                "distance_km": distance_km(c),
                "contour": json.loads(c.contour.geojson),
                "couloir": json.loads(c.couloir.geojson) if c.couloir else None,
                "releves": {
                    "intensite_max_mmh": c.max_mmh, "intensite_moyenne_mmh": c.moyenne_mmh,
                    "libelle": orages.palier(c.max_mmh), "surface_km2": c.surface_km2,
                    "tendance_mmh": c.tendance_mmh, "communes_sous_la_pluie": c.communes_touchees,
                    "rafale_mesuree": c.rafale_mesuree, "trace": c.trace,
                    "eclairs": c.eclairs,
                },
                "estimations": {
                    "cap_deg": c.cap_deg, "vers": orages.vers(c.cap_deg) if c.cap_deg is not None else None,
                    "vitesse_kmh": c.vitesse_kmh, "communes_atteintes": c.communes_estimees,
                    "ligne_de_grain": c.ligne_de_grain, "longueur_km": c.longueur_km,
                },
                "prevision_meteo_france": {
                    "grele": c.grele_prevue, "rafale_kmh": c.rafale_prevue_kmh,
                    "grele_diagnostic_kgm2": c.grele_diagnostic_kgm2,
                    "grele_niveau": orages.niveau_grele(c.grele_diagnostic_kgm2),
                },
            })
        if centre:
            resultats.sort(key=lambda r: r["distance_km"])
        # Cumuls de pluie selon le radar : la commune de l'appelant, puis les plus arrosées de
        # l'emprise. Lus dans la table recalculée à chaque image : aucun calcul ici.
        cumuls = None
        if not request.query_params.get("france") and emprise is not None:
            from .models import CumulPluieCommune
            ouest, sud, est, nord = emprise.extent
            proches = dict(Commune.objects.filter(
                centre_longitude__gte=ouest, centre_longitude__lte=est,
                centre_latitude__gte=sud, centre_latitude__lte=nord).values_list("code", "nom"))
            lignes = {c.commune_code: c for c in CumulPluieCommune.objects.filter(commune_code__in=list(proches))}
            institution = _institution_de_l_appelant(request)
            ma_commune = institution.commune_code if institution and institution.commune_code else None

            def ligne(code, nom):
                c = lignes.get(code)
                valeurs = {"1h": c.mm_1h if c else 0, "3h": c.mm_3h if c else 0, "24h": c.mm_24h if c else 0}
                return {"code": code, "nom": nom or code, "mm": valeurs,
                        "fort": [f for f, v in valeurs.items() if v >= orages.SEUILS_CUMUL_MM[f]]}
            plus_arrosees = sorted(lignes.values(), key=lambda c: (-c.mm_3h, -c.mm_24h))[:10]
            cumuls = {
                "fenetres": image.images_par_fenetre if image else {},
                "attendues": orages.FENETRES_CUMUL, "seuils_mm": orages.SEUILS_CUMUL_MM,
                "ma_commune": ligne(ma_commune, proches.get(ma_commune) or Commune.objects.filter(
                    code=ma_commune).values_list("nom", flat=True).first()) if ma_commune else None,
                "plus_arrosees": [ligne(c.commune_code, proches[c.commune_code]) for c in plus_arrosees if c.mm_24h >= 1],
            }
        # Foudre vue par satellite dans l'emprise : 15 minutes et une heure de produits.
        foudre = None
        if not request.query_params.get("france") and emprise is not None:
            from .models import ImpactFoudre
            derniere = ImpactFoudre.objects.order_by("-instant").values_list("instant", flat=True).first()
            if derniere is not None:
                proches = ImpactFoudre.objects.filter(location__within=emprise)
                foudre = {
                    **sources_ouvertes.resume("FOUDRE_MTG"),
                    "eclairs_15min": proches.filter(instant__gte=derniere - datetime.timedelta(minutes=15)).count(),
                    "eclairs_1h": proches.filter(instant__gte=derniere - datetime.timedelta(hours=1)).count(),
                    "dernier_ici": proches.order_by("-instant").values_list("instant", flat=True).first(),
                    "derniere_donnee": derniere,
                }
        return Response({
            "foudre": foudre,
            "cumuls": cumuls,
            **sources_ouvertes.resume("ORAGES_RADAR"),
            "heure_image": image.heure if image else None,
            "radars": len(image.radars) if image else 0,
            "radars_absents": image.radars_absents if image else [],
            "centre": centre, "rayon_km": rayon, "couvert": couvert,
            "cellules": resultats,
        })


class FoudreView(APIView):
    """GET /api/foudre/ : éclairs vus par le satellite MTG (core/foudre.py), en GeoJSON, pour la
    carte. `bbox` (sinon la France entière gardée) et `minutes` (60 par défaut, 360 au plus),
    comptées depuis la donnée la plus récente : les produits arrivent dix à vingt minutes après
    coup, et compter depuis maintenant afficherait une carte vide en permanence."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .models import ImpactFoudre
        try:
            minutes = min(max(int(request.query_params.get("minutes", 60)), 5), 360)
        except (TypeError, ValueError):
            minutes = 60
        derniere = ImpactFoudre.objects.order_by("-instant").values_list("instant", flat=True).first()
        points = []
        if derniere is not None:
            qs = ImpactFoudre.objects.filter(instant__gte=derniere - datetime.timedelta(minutes=minutes))
            if request.query_params.get("bbox"):
                emprise, _centre, _rayon = _emprise(request)
                qs = qs.filter(location__within=emprise)
            for e in qs.order_by("-instant")[:5000]:
                points.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [e.location.x, e.location.y]},
                               "properties": {"instant": e.instant.isoformat(),
                                              "age_min": round((derniere - e.instant).total_seconds() / 60)}})
        return Response({**sources_ouvertes.resume("FOUDRE_MTG"), "derniere_donnee": derniere,
                         "type": "FeatureCollection", "features": points})


class ImageRafalesView(APIView):
    """GET /api/rafales-prevues/image/?echeance=… : l'image d'une échéance (PNG transparent),
    servie comme celle de la pluie."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return _image_d_une_echeance(ImageRafales, request)


class PrecipitationsHiverView(APIView):
    """GET /api/precipitations-hiver/ : les quarts d'heure pour lesquels une image de neige,
    verglas et grêle prévus est disponible, où la poser sur la carte et la légende des teintes.

    Avec `lat` et `lon`, ou `ici=1` pour la commune de l'institution de l'appelant, la réponse
    dit aussi ce qui est prévu À CET ENDROIT pour chaque échéance. C'est lu dans les images déjà
    copiées : aucun appel sortant, la position ne quitte pas ce serveur."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ouest, sud, est, nord = rafales.EMPRISE_IMAGE
        images = list(ImagePrecipitationHiver.objects.order_by("echeance"))
        ici = None
        if request.query_params.get("ici") or request.query_params.get("lat"):
            _emprise_inutile, centre, _rayon = _emprise(request)
            if centre:
                familles = [{"echeance": image.echeance,
                             "famille": precipitations_hiver.famille_au_point(
                                 bytes(image.image), centre["latitude"], centre["longitude"])}
                            for image in images]
                prevues = {f["famille"] for f in familles if f["famille"]}
                couvert = any(f["famille"] is not None for f in familles) or not images
                ici = {**centre, "couvert": couvert, "familles": familles,
                       # La plus dangereuse de ce qui est prévu, ou "" si rien ne l'est.
                       "pire": next((cle for cle in precipitations_hiver.ORDRE_DE_GRAVITE if cle in prevues), "")}
        return Response({
            **sources_ouvertes.resume("PRECIPITATIONS_HIVER"),
            "calcul": max((image.calcul for image in images), default=None),
            "coins": [[ouest, nord], [est, nord], [est, sud], [ouest, sud]],
            "echeances": [image.echeance for image in images],
            "legende": precipitations_hiver.legende(),
            "ici": ici,
        })


class ImagePrecipitationHiverView(APIView):
    """GET /api/precipitations-hiver/image/?echeance=… : l'image d'une échéance (PNG
    transparent), servie comme celle de la pluie."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return _image_d_une_echeance(ImagePrecipitationHiver, request)


class VentPrevuView(APIView):
    """GET /api/vent-prevu/ : les heures pour lesquelles un champ de vent est disponible.
    `?echeance=…` rend en plus ce champ, pour l'animation de la carte : la grille (taille,
    position, pas) et ses valeurs en base 64 -- un octet par point pour la composante vers
    l'est, puis autant pour la composante vers le nord (0 : -40 m/s ; 255 : +40 m/s)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        import base64
        from django.utils.dateparse import parse_datetime

        champs = list(ChampVent.objects.order_by("echeance").defer("donnees"))
        reponse = {
            **sources_ouvertes.resume("VENT"),
            "calcul": max((champ.calcul for champ in champs), default=None),
            "echeances": [champ.echeance for champ in champs],
            "champ": None,
        }
        demande = parse_datetime(request.query_params.get("echeance") or "")
        champ = ChampVent.objects.filter(pk=demande).first() if demande else None
        if champ is not None:
            reponse["champ"] = {
                "echeance": champ.echeance, "largeur": champ.largeur, "hauteur": champ.hauteur,
                "ouest": champ.ouest, "nord": champ.nord, "pas": vent.PAS_DEGRES,
                "vitesse_max_ms": vent.VITESSE_MAX_MS,
                "donnees": base64.b64encode(bytes(champ.donnees)).decode("ascii"),
            }
        return Response(reponse)


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


class HauteursEauView(APIView):
    """GET /api/hauteurs-eau/ : les stations de mesure en rivière d'une emprise (voir `_emprise`),
    celles dont l'eau monte le plus vite d'abord. Hauteur à l'échelle de la station, débit,
    variation sur une et trois heures, et le palier de tendance qui en découle.
    `?en_hausse=1` ne garde que les stations en hausse."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("HAUTEURS_EAU", centre, rayon)
        vide = {palier: 0 for palier in hauteurs_eau.ORDRE_TENDANCES}
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "bilan": vide, "resultats": []})

        maintenant = timezone.now()
        en_hausse_seules = request.query_params.get("en_hausse") in ("1", "true")
        rang = {palier: i for i, palier in enumerate(hauteurs_eau.ORDRE_TENDANCES)}
        bilan, lignes = dict(vide), []
        for station in StationHydrometrique.objects.filter(location__within=emprise).defer("historique"):
            palier = hauteurs_eau.tendance(station, maintenant)
            bilan[palier] += 1
            if en_hausse_seules and palier not in (hauteurs_eau.HAUSSE_RAPIDE, hauteurs_eau.HAUSSE):
                continue
            latitude, longitude = _point(station.location)
            recente = station.hauteur_le is not None and maintenant - station.hauteur_le <= hauteurs_eau.MESURE_VALABLE
            debit_recent = station.debit_le is not None and maintenant - station.debit_le <= hauteurs_eau.MESURE_VALABLE
            lignes.append({
                "code": station.code, "nom": station.nom, "cours_eau": station.cours_eau,
                "tendance": palier,
                "hauteur_m": station.hauteur_m if recente else None,
                "hauteur_le": station.hauteur_le,
                "variation_1h_cm": station.variation_1h_cm if recente else None,
                "variation_3h_cm": station.variation_3h_cm if recente else None,
                "debit_m3s": station.debit_m3s if debit_recent else None,
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"], latitude, longitude), 1)
                                if centre else None),
            })
        # Ce qui monte le plus vite d'abord ; à palier égal, la plus forte hausse, puis la plus proche.
        lignes.sort(key=lambda l: (rang[l["tendance"]], -(l["variation_1h_cm"] or 0),
                                   l["distance_km"] if l["distance_km"] is not None else 0, l["code"]))
        return Response({**entete, "emprise_connue": True, "tronque": len(lignes) > RESULTATS_MAX,
                         "bilan": bilan, "resultats": lignes[:RESULTATS_MAX]})


class NiveauxMerView(APIView):
    """GET /api/niveaux-mer/ : les marégraphes d'une emprise (voir `_emprise`), les plus fortes
    surcotes d'abord. Niveau mesuré, marée calculée par ce serveur, surcote ESTIMÉE avec son
    incertitude, et la prochaine pleine mer telle qu'on la verra si la surcote se maintient."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("NIVEAUX_MER", centre, rayon)
        vide = {palier: 0 for palier in niveaux_mer.ORDRE_ETATS}
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "bilan": vide, "resultats": []})

        maintenant = timezone.now()
        rang = {palier: i for i, palier in enumerate(niveaux_mer.ORDRE_ETATS)}
        bilan, lignes = dict(vide), []
        for station in Maregraphe.objects.filter(location__within=emprise):
            palier = niveaux_mer.etat(station, maintenant)
            bilan[palier] += 1
            latitude, longitude = _point(station.location)
            recente = station.niveau_le is not None and maintenant - station.niveau_le <= niveaux_mer.MESURE_VALABLE
            estimee = recente and bool(station.ajustement) and station.surcote_cm is not None
            a_venir = estimee and station.pleine_mer_le is not None and station.pleine_mer_le > maintenant
            lignes.append({
                "code": station.code, "nom": station.nom, "etat": palier,
                "niveau_m": station.niveau_m if recente else None, "niveau_le": station.niveau_le,
                "maree_attendue_m": station.maree_attendue_m if estimee else None,
                "surcote_cm": station.surcote_cm if estimee else None,
                "incertitude_cm": station.ajustement.get("incertitude_cm") if estimee else None,
                "pleine_mer_le": station.pleine_mer_le if a_venir else None,
                "pleine_mer_niveau_m": station.pleine_mer_niveau_m if a_venir else None,
                # Repère : le niveau le plus haut que ce marégraphe a mesuré sur les mois ajustés.
                "maximum_m": station.ajustement.get("maximum_m") if estimee else None,
                "maximum_le": station.ajustement.get("maximum_le") if estimee else None,
                "jours_ajustes": station.ajustement.get("jours") if estimee else None,
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"], latitude, longitude), 1)
                                if centre else None),
            })
        lignes.sort(key=lambda l: (rang[l["etat"]], -(l["surcote_cm"] or 0),
                                   l["distance_km"] if l["distance_km"] is not None else 0, l["code"]))
        return Response({**entete, "emprise_connue": True, "tronque": len(lignes) > RESULTATS_MAX,
                         "bilan": bilan, "resultats": lignes[:RESULTATS_MAX]})


class QualiteAirView(APIView):
    """GET /api/qualite-air/ : la qualité de l'air ESTIMÉE (modèle OpenWeather, indice de 1 à 5)
    aux points fixes du relevé. Avec une emprise (voir `_emprise`), les points qui s'y trouvent ;
    et dans tous les cas où un centre est connu, `plus_proche` : le point le plus proche de ce
    centre, où qu'il soit, avec sa distance -- la liste ne compte qu'une ville ou deux par
    département."""
    permission_classes = [permissions.AllowAny]

    def _ligne(self, point, centre, maintenant):
        latitude, longitude = _point(point.location)
        recente = maintenant - point.mesure_le <= qualite_air.MESURE_VALABLE
        pire, quand = qualite_air.pire_a_venir(point.prevision, maintenant)
        return {
            "code": point.code, "nom": point.nom, "departement": point.departement,
            "indice": point.indice if recente else None,
            "libelle": qualite_air.LIBELLES.get(point.indice, "") if recente else "",
            "composants": point.composants if recente else {},
            "mesure_le": point.mesure_le,
            "pire_24h": pire, "pire_24h_libelle": qualite_air.LIBELLES.get(pire, ""), "pire_24h_le": quand,
            "latitude": latitude, "longitude": longitude,
            "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"], latitude, longitude), 1)
                            if centre else None),
        }

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("QUALITE_AIR", centre, rayon)
        entete["libelles"] = qualite_air.LIBELLES
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "plus_proche": None, "resultats": []})

        maintenant = timezone.now()
        lignes = [self._ligne(point, centre, maintenant)
                  for point in PointQualiteAir.objects.filter(location__within=emprise)]
        lignes.sort(key=lambda l: (-(l["indice"] or 0), l["distance_km"] if l["distance_km"] is not None else 0, l["code"]))
        plus_proche = None
        if centre:
            tous = [self._ligne(point, centre, maintenant) for point in PointQualiteAir.objects.all()]
            plus_proche = min(tous, key=lambda l: l["distance_km"], default=None)
        return Response({**entete, "emprise_connue": True, "tronque": False,
                         "plus_proche": plus_proche, "resultats": lignes})


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


class FoyersActifsView(APIView):
    """GET /api/foyers-actifs/ : les pixels chauds vus par satellite ces deux derniers jours dans
    une emprise (voir `_emprise`), les plus récents d'abord. Les sources fixes (usines,
    torchères) ne sont rendues qu'avec `?fixes=1`, et toujours marquées comme telles."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("FOYERS_ACTIFS", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "sources_fixes": 0, "resultats": []})
        dans_l_emprise = FoyerActif.objects.filter(location__within=emprise)
        fixes = dans_l_emprise.filter(source_fixe=True).count()
        if request.query_params.get("fixes") not in ("1", "true"):
            dans_l_emprise = dans_l_emprise.filter(source_fixe=False)
        foyers = list(dans_l_emprise.order_by("-date", "reference")[:RESULTATS_MAX + 1])
        resultats = []
        for foyer in foyers[:RESULTATS_MAX]:
            latitude, longitude = _point(foyer.location)
            resultats.append({
                "reference": foyer.reference, "date": foyer.date,
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"],
                                                   latitude, longitude), 1) if centre else None),
                "confiance": foyer.confiance, "puissance_mw": foyer.puissance_mw,
                "satellite": foyer.satellite, "source_fixe": foyer.source_fixe,
            })
        return Response({**entete, "emprise_connue": True, "tronque": len(foyers) > RESULTATS_MAX,
                         "sources_fixes": fixes, "resultats": resultats})


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


class RadioactiviteView(APIView):
    """GET /api/radioactivite/ : la dernière mesure des balises Téléray d'une emprise (voir
    `_emprise`), de la plus proche à la plus lointaine. Un affichage : aucune alerte n'est
    tirée de ces valeurs (voir core/radioactivite.py)."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("RADIOACTIVITE", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "resultats": []})
        balises = list(MesureRadioactivite.objects.filter(location__within=emprise)
                       .order_by("nom", "station")[:RESULTATS_MAX + 1])
        resultats = []
        for balise in balises[:RESULTATS_MAX]:
            latitude, longitude = _point(balise.location)
            fond = balise.bruit_de_fond_nsv_h
            resultats.append({
                "station": balise.station, "nom": balise.nom,
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"],
                                                   latitude, longitude), 1) if centre else None),
                "proche_installation": balise.proche_installation,
                "debit_nsv_h": balise.debit_nsv_h,
                "bruit_de_fond_nsv_h": fond,
                "ecart_nsv_h": None if fond is None else round(balise.debit_nsv_h - fond, 1),
                "valide": balise.valide,
                "mesure_le": balise.mesure_le,
            })
        if centre:
            resultats.sort(key=lambda r: r["distance_km"])
        return Response({**entete, "emprise_connue": True,
                         "tronque": len(balises) > RESULTATS_MAX, "resultats": resultats})


class SeismesView(APIView):
    """GET /api/seismes/ : les événements sismiques des trente derniers jours dans une emprise
    (voir `_emprise`), les plus récents d'abord. `?magnitude_min=2` écarte les plus petits ;
    `?jours=7` raccourcit la période."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("SEISMES", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "resultats": []})
        evenements = Seisme.objects.filter(location__within=emprise)
        magnitude_min = _nombre(request.query_params.get("magnitude_min"))
        if magnitude_min is not None:
            evenements = evenements.filter(magnitude__gte=magnitude_min)
        jours = _nombre(request.query_params.get("jours"))
        if jours is not None and 0 < jours <= 30:
            evenements = evenements.filter(date__gte=timezone.now() - timezone.timedelta(days=jours))
        evenements = list(evenements.order_by("-date")[:RESULTATS_MAX + 1])
        resultats = []
        for evenement in evenements[:RESULTATS_MAX]:
            latitude, longitude = _point(evenement.location)
            resultats.append({
                "reference": evenement.reference, "date": evenement.date,
                "magnitude": evenement.magnitude, "profondeur_km": evenement.profondeur_km,
                "lieu": evenement.lieu, "zone": evenement.zone,
                "nature": evenement.nature,
                "nature_libelle": seismes.NATURES.get(evenement.nature, "Autre événement"),
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"],
                                                   latitude, longitude), 1) if centre else None),
            })
        return Response({**entete, "emprise_connue": True,
                         "tronque": len(evenements) > RESULTATS_MAX, "resultats": resultats})


class VolcansView(APIView):
    """GET /api/volcans/ : la sismicité autour des volcans français, cette semaine et la
    précédente. `a_portee` désigne ceux qui concernent le territoire regardé (voir `_emprise`) :
    l'écran n'affiche ce bloc que pour eux. Aucune donnée ouverte ne dit l'état d'un volcan ni
    son niveau d'alerte : ceci n'est qu'un compte de séismes."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        _emprise_inutile, centre, _rayon = _emprise(request)
        volcans = seismes.activite_volcans()
        for volcan in volcans:
            volcan["distance_km"] = (round(_distance_km(centre["latitude"], centre["longitude"],
                                                        volcan["latitude"], volcan["longitude"]))
                                     if centre else None)
            volcan["a_portee"] = (volcan["distance_km"] is not None
                                  and volcan["distance_km"] <= seismes.PORTEE_VOLCAN_KM)
        return Response({
            **sources_ouvertes.resume("SEISMES"),
            "rayon_km": seismes.RAYON_VOLCAN_KM,
            "volcans": volcans,
        })


class DefibrillateursView(APIView):
    """GET /api/defibrillateurs/ : les défibrillateurs d'une emprise (voir `_emprise`), du plus
    proche au plus lointain quand un centre est connu. Ce sont les appareils que leurs
    exploitants déclarent en service, pas des appareils vérifiés."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("DEFIBRILLATEURS", centre, rayon)
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "total": 0, "resultats": []})
        dans_l_emprise = Defibrillateur.objects.filter(location__within=emprise)
        total = dans_l_emprise.count()
        appareils = list(dans_l_emprise.order_by("reference")[:RESULTATS_MAX])
        resultats = []
        for appareil in appareils:
            latitude, longitude = _point(appareil.location)
            resultats.append({
                "reference": appareil.reference, "nom": appareil.nom, "adresse": appareil.adresse,
                "acces": appareil.acces, "acces_libre": appareil.acces_libre,
                "emplacement": appareil.emplacement, "disponibilite": appareil.disponibilite,
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"],
                                                   latitude, longitude), 2) if centre else None),
            })
        if centre:
            resultats.sort(key=lambda r: r["distance_km"])
        return Response({**entete, "emprise_connue": True, "tronque": total > RESULTATS_MAX,
                         "total": total, "resultats": resultats})


class SanteUrgencesView(APIView):
    """GET /api/sante-urgences/ : pour le département de l'appelant (`?departement=42` pour un
    autre), la part des passages aux urgences attribués à quatre pathologies, cette semaine et
    la précédente. Un taux pour 100 000 passages : une tendance, pas un nombre de malades."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        code = request.query_params.get("departement") or _departement_de_l_appelant(request)
        lignes = {i.pathologie: i for i in IndicateurSante.objects.filter(departement_code=code)} if code else {}
        indicateurs = []
        for pathologie, (libelle, *_reste) in sante_urgences.PATHOLOGIES.items():
            ligne = lignes.get(pathologie)
            if ligne is None:
                continue
            indicateurs.append({
                "pathologie": pathologie, "libelle": libelle,
                "semaine": ligne.semaine, "debut_semaine": ligne.debut_semaine,
                "taux_urgences": ligne.taux_urgences,
                "taux_urgences_precedent": ligne.taux_urgences_precedent,
                "taux_sos": ligne.taux_sos,
                "tendance": sante_urgences.tendance(ligne.taux_urgences, ligne.taux_urgences_precedent),
            })
        return Response({
            **sources_ouvertes.resume("SANTE_URGENCES"),
            "departement_code": code or None,
            "departement_nom": meteo_france.nom_departement(code) if code else None,
            "indicateurs": indicateurs,
        })


class AntennesIndisponiblesView(APIView):
    """GET /api/antennes-indisponibles/ : les antennes mobiles déclarées en panne ou en
    maintenance dans une emprise (voir `_emprise`), les coupures complètes d'abord. Les pannes
    déclarées depuis plus de six mois ne sont pas rendues (déclarations oubliées, sites
    abandonnés) : elles sont seulement comptées, dans `ecartees`. `?operateur=Orange` restreint
    la liste."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("ANTENNES_MOBILES", centre, rayon)
        jour = AntenneIndisponible.objects.order_by("-jour_du_fichier").values_list("jour_du_fichier", flat=True).first()
        entete["jour_du_fichier"] = jour
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False, "ecartees": 0,
                             "ecartees_par_operateur": {}, "par_operateur": {}, "resultats": []})

        maintenant = timezone.now()
        antennes = AntenneIndisponible.objects.filter(location__within=emprise)
        operateur = request.query_params.get("operateur")
        rang = {palier: i for i, palier in enumerate(antennes_mobiles.ORDRE_GRAVITES)}
        par_operateur, lignes, ecartees = {}, [], {}
        for antenne in antennes:
            if antennes_mobiles.trop_ancienne(antenne, maintenant):
                ecartees[antenne.operateur] = ecartees.get(antenne.operateur, 0) + 1
                continue
            par_operateur[antenne.operateur] = par_operateur.get(antenne.operateur, 0) + 1
            if operateur and antenne.operateur != operateur:
                continue
            latitude, longitude = _point(antenne.location)
            lignes.append({
                "cle": antenne.cle, "operateur": antenne.operateur, "commune": antenne.commune,
                "gravite": antennes_mobiles.gravite(antenne),
                "voix_hs": antenne.voix_hs, "donnees_hs": antenne.donnees_hs,
                "technologies": antenne.technologies, "motif": antenne.motif,
                # Début déclaré par l'opérateur ; à défaut, le jour où nous avons vu la panne.
                "depuis": antennes_mobiles.depuis(antenne), "debut_declare": antenne.debut is not None,
                "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"], latitude, longitude), 1)
                                if centre else None),
            })
        lignes.sort(key=lambda l: (rang[l["gravite"]], l["distance_km"] if l["distance_km"] is not None else 0,
                                   l["operateur"], l["cle"]))
        return Response({**entete, "emprise_connue": True, "tronque": len(lignes) > RESULTATS_MAX,
                         "ecartees": sum(ecartees.values()),
                         # Par opérateur, pour pouvoir dire « toutes les déclarations de tel
                         # opérateur sont anciennes » plutôt que « aucune panne chez lui ».
                         "ecartees_par_operateur": dict(sorted(ecartees.items())),
                         "par_operateur": dict(sorted(par_operateur.items())),
                         "resultats": lignes[:RESULTATS_MAX]})


class ArretesCirculationView(APIView):
    """GET /api/arretes-circulation/ : les arrêtés de circulation des collectivités (DiaLog)
    dans une emprise (voir `_emprise`) : circulation interdite d'abord, puis poids lourds, puis
    alternats ; les arrêtés temporaires avant les permanents. `?trace=1` joint leur tracé."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("ARRETES_CIRCULATION", centre, rayon)
        vide = {categorie: 0 for categorie in arretes_circulation.ORDRE_CATEGORIES}
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "bilan": vide, "resultats": []})

        dans_l_emprise = ArreteCirculation.objects.filter(location__within=emprise)
        bilan = {**vide, **{ligne["categorie"]: ligne["nombre"] for ligne in
                            dans_l_emprise.values("categorie").annotate(nombre=Count("pk"))}}
        rang = Case(
            *[When(categorie=categorie, then=Value(i))
              for i, categorie in enumerate(arretes_circulation.ORDRE_CATEGORIES)],
            default=Value(9), output_field=IntegerField(),
        )
        avec_trace = request.query_params.get("trace") in ("1", "true")
        arretes = list(dans_l_emprise.annotate(rang=rang)
                       .order_by("rang", F("fin").asc(nulls_last=True), "reference")[:RESULTATS_MAX + 1])
        resultats = []
        for arrete in arretes[:RESULTATS_MAX]:
            latitude, longitude = _point(arrete.location)
            ligne = {
                "reference": arrete.reference, "categorie": arrete.categorie,
                "categorie_libelle": arrete.get_categorie_display(),
                "description": arrete.description, "autorite": arrete.autorite,
                "voies": arrete.voies, "tonnage_max": arrete.tonnage_max,
                "debut": arrete.debut, "fin": arrete.fin, "url": arrete.url,
                "latitude": latitude, "longitude": longitude,
            }
            if avec_trace:
                ligne["trace"] = json.loads(arrete.geometrie.geojson)
            resultats.append(ligne)
        return Response({**entete, "emprise_connue": True, "tronque": len(arretes) > RESULTATS_MAX,
                         "bilan": bilan, "resultats": resultats})


class CirculationView(APIView):
    """GET /api/circulation/ : les tronçons mesurés du réseau routier national dans une emprise
    (voir `_emprise`), les plus encombrés d'abord. Chaque tronçon porte son état, d'où il vient
    (« OFFICIEL » : l'exploitant ; « ESTIME » : la vitesse comparée à l'habitude apprise par ce
    serveur), sa vitesse et son débit. `?trace=1` joint le trait du tronçon (pour la carte) ;
    `?ralentis=1` ne garde que les tronçons denses, saturés ou bloqués."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        emprise, centre, rayon = _emprise(request)
        entete = _entete("CIRCULATION", centre, rayon)
        vide = {etat: 0 for etat in circulation.ORDRE_ETATS}
        if emprise is None:
            return Response({**entete, "emprise_connue": False, "tronque": False,
                             "bilan": vide, "resultats": []})

        maintenant = timezone.now()
        avec_trace = request.query_params.get("trace") in ("1", "true")
        ralentis_seuls = request.query_params.get("ralentis") in ("1", "true")
        rang = {etat: i for i, etat in enumerate(circulation.ORDRE_ETATS)}
        bilan, lignes = dict(vide), []
        for station in StationCirculation.objects.filter(location__within=emprise):
            etat, origine = circulation.etat_affiche(station, maintenant)
            bilan[etat] += 1
            if ralentis_seuls and etat not in (circulation.BLOQUE, circulation.SATURE, circulation.DENSE):
                continue
            latitude, longitude = _point(station.location)
            recente = station.mesure_le is not None and maintenant - station.mesure_le <= circulation.MESURE_VALABLE
            ligne = {
                "code": station.code, "axe": station.axe, "sens": station.sens,
                "etat": etat, "origine": origine,
                "vitesse_kmh": station.vitesse_kmh if recente else None,
                "debit_veh_h": station.debit_veh_h if recente else None,
                "mesure_le": station.mesure_le,
                # L'habitude n'est donnée qu'une fois apprise : avant, ce n'est qu'une mesure.
                "vitesse_habituelle_kmh": (
                    round(station.vitesse_habituelle_kmh)
                    if station.vitesse_habituelle_kmh is not None
                    and station.mesures_comptees >= circulation.MESURES_POUR_ESTIMER else None),
                "cote": station.cote, "latitude": latitude, "longitude": longitude,
                "distance_km": (round(_distance_km(centre["latitude"], centre["longitude"], latitude, longitude), 1)
                                if centre else None),
            }
            if avec_trace:
                ligne["trace"] = json.loads(station.trace.geojson)
            lignes.append(ligne)
        # Les plus encombrés d'abord ; à état égal, les plus proches, sinon par axe.
        lignes.sort(key=lambda l: (rang[l["etat"]], l["distance_km"] if l["distance_km"] is not None else 0,
                                   l["axe"], l["code"]))
        return Response({**entete, "emprise_connue": True, "tronque": len(lignes) > RESULTATS_MAX,
                         "bilan": bilan, "resultats": lignes[:RESULTATS_MAX]})


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
        # Administrateur placé dans une institution : la sienne seulement (19/11/2026). Pour les
        # autres, leurs rattachements actifs.
        from .perimetre_admin import admin_sans_filtre, institutions_visibles
        if admin_sans_filtre(self.request, self):
            return qs
        return qs.filter(institution_id__in=institutions_visibles(self.request))

    def perform_create(self, serializer):
        institution_id = self.request.data.get('institution')
        institution = Institution.objects.filter(pk=institution_id).first() if institution_id else None
        if institution is None:
            institution = _resolve_institution_or_400(self.request)
        if ConfigurationAlerteVigilance.objects.filter(institution=institution).exists():
            raise ValidationError("Un réglage d'alerte de vigilance existe déjà pour cette institution.")
        serializer.save(institution=institution, environment=get_active_environment(self.request))


class ConfigurationAlerteFeuViewSet(EnvironmentScopedViewSetMixin, viewsets.ModelViewSet):
    """Réglage de l'annonce des foyers détectés par satellite près d'une institution -- même
    patron que ConfigurationAlerteVigilanceViewSet."""

    queryset = ConfigurationAlerteFeu.objects.select_related('institution').all()
    serializer_class = ConfigurationAlerteFeuSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        institution_id = self.request.query_params.get('institution')
        if institution_id:
            qs = qs.filter(institution_id=institution_id)
        # Administrateur placé dans une institution : la sienne seulement (19/11/2026). Pour les
        # autres, leurs rattachements actifs.
        from .perimetre_admin import admin_sans_filtre, institutions_visibles
        if admin_sans_filtre(self.request, self):
            return qs
        return qs.filter(institution_id__in=institutions_visibles(self.request))

    def perform_create(self, serializer):
        institution_id = self.request.data.get('institution')
        institution = Institution.objects.filter(pk=institution_id).first() if institution_id else None
        if institution is None:
            institution = _resolve_institution_or_400(self.request)
        if ConfigurationAlerteFeu.objects.filter(institution=institution).exists():
            raise ValidationError("Un réglage d'alerte de feu existe déjà pour cette institution.")
        serializer.save(institution=institution, environment=get_active_environment(self.request))
