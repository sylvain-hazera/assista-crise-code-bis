"""Recherche d'adresse et géocodage inverse, relayés par le serveur.

POURQUOI (15/11/2026)
Le site appelait la Base adresse nationale directement depuis le navigateur. Chaque frappe dans
un champ d'adresse, et chaque « utiliser ma position », envoyait donc à un service extérieur --
certes de l'État -- l'adresse IP de la personne, son navigateur, la page d'où elle venait, et
ce qu'elle cherchait ou l'endroit où elle se trouvait. Pour une application qu'on ouvre quand
on a besoin d'aide, c'est un flux de trop.

Désormais le navigateur ne parle qu'à ce serveur, et c'est le serveur qui interroge le service
de géocodage. Celui-ci voit une question (« 8 bd du port amiens ») venant d'Assista-Crise, sans
rien qui la rattache à quelqu'un.

CE QUI SORT ENCORE, ET CE QUI NE SORT PAS
- Le texte cherché et, pour le géocodage inverse, la position : il faut bien poser la question.
- La position qui sert seulement à CLASSER les résultats d'une recherche (les adresses proches
  d'abord) est arrondie au centième de degré, environ un kilomètre : c'est assez pour trier,
  et cela ne situe plus personne.
- Jamais l'adresse IP, l'identité, ni aucun en-tête du navigateur.

Rien n'est conservé ici : ni journal des recherches, ni cache. Une adresse tapée par quelqu'un
n'a pas à dormir sur le serveur.

SERVICE APPELÉ
Le géocodage de la Géoplateforme de l'IGN (https://data.geopf.fr/geocodage), successeur
officiel d'api-adresse.data.gouv.fr : mêmes paramètres, même réponse GeoJSON, aucune clé.

Les deux vues sont publiques -- les formulaires de demande d'aide le sont -- donc bornées :
paramètres en liste fermée, taille de la question plafonnée, et un débit par adresse IP pour
que ce relais ne serve pas à moissonner le service de l'État à notre nom.
"""
import logging

import requests
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from .audit import get_client_ip

logger = logging.getLogger(__name__)

URL_GEOCODAGE = "https://data.geopf.fr/geocodage"
DELAI_REPONSE_S = 6
LONGUEUR_MIN, LONGUEUR_MAX = 3, 200
RESULTATS_MAX = 10
TYPES = {"housenumber", "street", "locality", "municipality"}

_VIDE = {"type": "FeatureCollection", "features": []}


class DebitGeocodage(SimpleRateThrottle):
    """Trois requêtes par seconde en moyenne : large pour quelqu'un qui tape une adresse (une
    requête par frappe, déjà temporisée par la page), très court pour une moisson."""
    scope = "geocodage"
    rate = "180/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": get_client_ip(request) or "inconnu"}


def _flottant(valeur, minimum, maximum):
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return None
    return nombre if minimum <= nombre <= maximum else None


def _interroger(chemin, parametres):
    """Appelle le service de géocodage. Rend sa réponse, ou une collection vide en cas de panne :
    un champ d'adresse qui ne propose rien est gênant, une page qui casse l'est davantage."""
    try:
        reponse = requests.get(f"{URL_GEOCODAGE}/{chemin}", params=parametres, timeout=DELAI_REPONSE_S)
        reponse.raise_for_status()
        donnees = reponse.json()
    except (requests.RequestException, ValueError) as exc:
        # Le texte de l'exception contient l'adresse appelée, donc la question posée : on ne
        # journalise que sa nature.
        logger.warning("Géocodage indisponible (%s).", type(exc).__name__)
        return None
    return donnees if isinstance(donnees, dict) else None


class RechercheAdresseView(APIView):
    """GET /api/adresses/recherche/?q=…[&limit=][&lat=&lon=][&type=][&citycode=][&postcode=]"""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [DebitGeocodage]

    def get(self, request):
        question = " ".join((request.query_params.get("q") or "").split())[:LONGUEUR_MAX]
        if len(question) < LONGUEUR_MIN:
            return Response(_VIDE)

        try:
            limite = max(1, min(RESULTATS_MAX, int(request.query_params.get("limit", 5))))
        except ValueError:
            limite = 5
        parametres = {"q": question, "limit": limite, "index": "address"}

        latitude = _flottant(request.query_params.get("lat"), -90, 90)
        longitude = _flottant(request.query_params.get("lon"), -180, 180)
        if latitude is not None and longitude is not None:
            # Arrondi au centième de degré : voir l'en-tête du module.
            parametres["lat"], parametres["lon"] = round(latitude, 2), round(longitude, 2)

        genre = request.query_params.get("type")
        if genre in TYPES:
            parametres["type"] = genre
        for cle in ("citycode", "postcode"):
            valeur = (request.query_params.get(cle) or "").strip()
            if valeur.isalnum() and len(valeur) == 5:
                parametres[cle] = valeur

        return Response(_interroger("search", parametres) or _VIDE)


class GeocodageInverseView(APIView):
    """GET /api/adresses/inverse/?lat=…&lon=… : l'adresse la plus proche d'un point."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [DebitGeocodage]

    def get(self, request):
        latitude = _flottant(request.query_params.get("lat"), -90, 90)
        longitude = _flottant(request.query_params.get("lon"), -180, 180)
        if latitude is None or longitude is None:
            return Response({"detail": "Latitude et longitude attendues."}, status=400)
        # Quatre décimales, une dizaine de mètres : la précision d'un numéro de rue, pas plus.
        parametres = {"lat": round(latitude, 4), "lon": round(longitude, 4), "limit": 1,
                      "index": "address"}
        return Response(_interroger("reverse", parametres) or _VIDE)


# ── Zone atteignable depuis un point (isochrone) ────────────────────────────────────────────
#
# « Jusqu'où va-t-on en dix minutes depuis la caserne, le centre d'accueil, le point de
# rassemblement ? » Le calcul est fait par le service d'itinéraires de la Géoplateforme de
# l'IGN (https://data.geopf.fr/navigation), ouvert et sans clé. Comme pour les adresses, c'est
# le serveur qui pose la question : le service reçoit un point et une durée venant
# d'Assista-Crise, sans adresse IP ni en-tête de navigateur. Le point est arrondi à une dizaine
# de mètres ; rien n'est conservé.

URL_ISOCHRONE = "https://data.geopf.fr/navigation/isochrone"
MINUTES_MIN, MINUTES_MAX = 1, 60
MODES = {"voiture": "car", "pied": "pedestrian"}


class ZoneAtteignableView(APIView):
    """GET /api/zone-atteignable/?lat=…&lon=…[&minutes=10][&mode=voiture|pied] : le contour de
    ce qu'on atteint depuis ce point en ce temps, par la route ou à pied."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [DebitGeocodage]

    def get(self, request):
        latitude = _flottant(request.query_params.get("lat"), -90, 90)
        longitude = _flottant(request.query_params.get("lon"), -180, 180)
        if latitude is None or longitude is None:
            return Response({"detail": "Latitude et longitude attendues."}, status=400)
        try:
            minutes = int(request.query_params.get("minutes", 10))
        except ValueError:
            minutes = 10
        minutes = max(MINUTES_MIN, min(MINUTES_MAX, minutes))
        mode = request.query_params.get("mode")
        mode = mode if mode in MODES else "voiture"

        donnees = None
        try:
            reponse = requests.get(URL_ISOCHRONE, timeout=DELAI_REPONSE_S * 2, params={
                "point": f"{round(longitude, 4)},{round(latitude, 4)}",
                "resource": "bdtopo-valhalla", "costType": "time", "costValue": minutes * 60,
                "profile": MODES[mode], "direction": "departure", "geometryFormat": "geojson",
            })
            reponse.raise_for_status()
            donnees = reponse.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Calcul de zone atteignable indisponible (%s).", type(exc).__name__)
        contour = donnees.get("geometry") if isinstance(donnees, dict) else None
        if not isinstance(contour, dict) or contour.get("type") not in ("Polygon", "MultiPolygon"):
            return Response({"detail": "Le calcul n'a pas abouti : réessayez, ou choisissez un "
                                       "point plus proche d'une route."}, status=503)
        return Response({"minutes": minutes, "mode": mode, "contour": contour,
                         "source": "Géoplateforme IGN (BD TOPO)"})
