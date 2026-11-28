"""Points d'accès sans connexion de la partie « pour les copains » (28/11/2026) — voir
core/carte_ouverte.py pour ce qui est montré, et surtout ce qui ne l'est pas."""
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from . import carte_ouverte, propagation, sources_ouvertes
from .permissions import get_active_environment

#: Distance maximale du bilan de liaison public (l'outil de l'accès radio va à 120 km).
LIAISON_MAX_M = 60_000


class _Public(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


def _en_cache(cle, duree_s, calcul):
    valeur = cache.get(cle)
    if valeur is None:
        valeur = calcul()
        cache.set(cle, valeur, duree_s)
    return valeur


class ResumeOuvertView(_Public):
    """GET carte-ouverte/ : une ligne d'état par bouton de l'accueil."""

    def get(self, request):
        env = get_active_environment(request)
        return Response(_en_cache(f"carte-ouverte:resume:{env}", 120, lambda: carte_ouverte.resume(env)))


class RadioOuverteView(_Public):
    """GET carte-ouverte/radio/ : répéteurs et rooms MeshCore (GeoJSON)."""

    def get(self, request):
        env = get_active_environment(request)
        return Response(_en_cache(f"carte-ouverte:radio:{env}", 600, lambda: carte_ouverte.radio_publique(env)))


class CouverturesOuvertesView(_Public):
    """GET carte-ouverte/radio/couvertures/ : les couvertures publiées."""

    def get(self, request):
        return Response([carte_ouverte.couverture_en_dict(c)
                         for c in carte_ouverte.couvertures_publiques(get_active_environment(request))])


class CouvertureOuverteGeojsonView(_Public):
    """GET carte-ouverte/radio/couvertures/<id>/geojson/ : points atteints d'une couverture
    publiée ; 404 pour une couverture qui ne l'est pas."""

    def get(self, request, pk):
        c = get_object_or_404(carte_ouverte.couvertures_publiques(get_active_environment(request)), pk=pk)
        return Response({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
             "properties": {"marge_db": marge}}
            for lat, lon, marge, _distance in (c.points or [])],
            "proprietes": carte_ouverte.couverture_en_dict(c)})


class SanteReseauView(_Public):
    """GET carte-ouverte/radio/sante/ : séries agrégées des dernières 24 heures."""

    def get(self, request):
        env = get_active_environment(request)
        return Response(_en_cache(f"carte-ouverte:sante:{env}", 300, lambda: carte_ouverte.sante_reseau(env)))


class PropagationOuverteView(_Public):
    """GET carte-ouverte/propagation/ : ondes courtes (NOAA) et conduits troposphériques (nos
    estimations sur ARPEGE)."""

    def get(self, request):
        from . import orages_de_feu, tropo
        from .models import PropagationTropo

        ouest, sud, est, nord = orages_de_feu.EMPRISE_IMAGE
        grilles = list(PropagationTropo.objects.order_by("echeance"))
        echeances = []
        for g in grilles:
            rang = tropo.decoder(g.grilles, g.largeur, g.hauteur)["rang"]
            echeances.append({"echeance": g.echeance, "classe_max": int(rang.max()),
                              "part_conduit_pct": round(float((rang == 2).mean()) * 100, 1)})
        return Response({
            "hf": propagation.dernier(),
            "hf_source": sources_ouvertes.resume("PROPAGATION_HF"),
            "tropo": {
                "nos_estimations": True,
                "source": "Météo-France (ARPEGE), nos estimations",
                "calcul": max((g.calcul for g in grilles), default=None),
                "coins": [[ouest, nord], [est, nord], [est, sud], [ouest, sud]],
                "legende": tropo.legende(),
                "limite": "Maille ARPEGE : les couches proches du sol sont mal résolues ; la portée réelle peut être meilleure.",
                "echeances": echeances,
            },
        })


class ImageTropoView(_Public):
    """GET carte-ouverte/propagation/tropo/image/?echeance=… : PNG transparent."""

    def get(self, request):
        from django.utils.dateparse import parse_datetime

        from .models import PropagationTropo

        echeance = parse_datetime(request.query_params.get("echeance") or "")
        image = PropagationTropo.objects.filter(pk=echeance).first() if echeance else None
        if image is None:
            return HttpResponseNotFound()
        reponse = HttpResponse(bytes(image.image), content_type="image/png")
        reponse["Cache-Control"] = "public, max-age=600"
        return reponse


class LiaisonMinuteThrottle(AnonRateThrottle):
    scope = "liaison_ouverte_minute"
    rate = "10/min"

    def get_rate(self):
        return self.rate


class LiaisonJourThrottle(AnonRateThrottle):
    scope = "liaison_ouverte_jour"
    rate = "100/day"

    def get_rate(self):
        return self.rate


class LiaisonOuverteView(_Public):
    """POST carte-ouverte/radio/liaison/ {lat_a, lon_a, lat_b, lon_b, preset?, hauteur_a_m?,
    hauteur_b_m?, puissance_dbm?} : « est-ce que ça passe ? », sur le relief IGN. Mêmes bornes
    que l'outil de l'accès radio, 60 km au plus, et un nombre de calculs limité par adresse
    (l'altimétrie IGN est limitée à 2,5 requêtes par seconde)."""
    throttle_classes = [LiaisonMinuteThrottle, LiaisonJourThrottle]

    def post(self, request):
        from .relief_radio import (
            PRESETS_LORA, altitude_point, altitudes_points, analyser_liaison, distance_m, parametres_calibres,
            points_profil,
        )

        try:
            a = (float(request.data["lat_a"]), float(request.data["lon_a"]))
            b = (float(request.data["lat_b"]), float(request.data["lon_b"]))
            hauteur_a = float(request.data.get("hauteur_a_m", 6.0))
            hauteur_b = float(request.data.get("hauteur_b_m", 2.0))
            puissance = float(request.data.get("puissance_dbm", 27.0))
        except (KeyError, TypeError, ValueError):
            return Response({"detail": "Deux points (lat_a, lon_a, lat_b, lon_b) et des nombres sont attendus."},
                            status=status.HTTP_400_BAD_REQUEST)
        preset = request.data.get("preset") or "LONG_FAST"
        if preset not in PRESETS_LORA:
            return Response({"detail": "Preset inconnu."}, status=status.HTTP_400_BAD_REQUEST)
        if not (0 <= hauteur_a <= 200 and 0 <= hauteur_b <= 200 and 1 <= puissance <= 30):
            return Response({"detail": "Hauteurs de 0 à 200 m, puissance de 1 à 30 dBm."}, status=status.HTTP_400_BAD_REQUEST)
        if distance_m(a, b) > LIAISON_MAX_M:
            return Response({"detail": "Au plus 60 km entre les deux points."}, status=status.HTTP_400_BAD_REQUEST)
        params = parametres_calibres(get_active_environment(request), preset=preset, puissance_dbm=puissance)
        resultat = analyser_liaison(a, b, altitude_point(a), altitude_point(b), altitudes_points(points_profil(a, b)), params,
                                    hauteur_a=hauteur_a, hauteur_b=hauteur_b)
        if resultat is None:
            return Response({"detail": "Altitude indisponible : le service de l'IGN n'a pas répondu, ou le point est hors de France."},
                            status=status.HTTP_502_BAD_GATEWAY)
        marge = resultat["marge_db"]
        # Mêmes seuils que l'outil de l'accès radio : 6 dB, c'est la marge d'évanouissement.
        resultat["verdict"] = "ne passe pas" if marge < 0 else ("passe de justesse" if marge < 6 else "passe")
        return Response(resultat)
