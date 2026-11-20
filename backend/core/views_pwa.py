"""Le site installable comme une application (PWA), pour l'iPhone et l'iPad (20/11/2026).

Voir DOSSIER-PWA-INTERVENANTS.md. Deux applications sur le même site, chacune avec son
manifeste :
- « Terrain » (intervenants), qui s'ouvre sur `/terrain` ;
- « Pilotage » (poste de commandement, directeur des opérations sur iPad), sur `/admin`.

Nom, couleur et icône suivent la marque du domaine visité, comme le reste du site
(core/branding.py : le Host seul fait foi, jamais un paramètre du client). Rien de personnel :
public, mis en cache par domaine.
"""
import functools
import io
from pathlib import Path

from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from .branding import branding_for_institution, branding_satellite, resolve_institution_branding

#: L'emblème Assista-Crise, celui de l'application Android (640 × 640).
ICONE_DEFAUT = Path(__file__).parent / "pwa" / "icone-defaut.png"

#: Les tailles servies : 180 (iPhone et iPad, `apple-touch-icon`), 192 et 512 (manifeste).
TAILLES = {180, 192, 512}

ESPACES = {
    "terrain": {"suffixe": "Terrain", "depart": "/terrain", "court": None},
    "pilotage": {"suffixe": "Pilotage", "depart": "/admin", "court": "Pilotage"},
}


def _institution_de_la_marque(request):
    institution = resolve_institution_branding(request)
    if institution is None:
        satellite = branding_satellite()
        if satellite and satellite.institution_id:
            from .models import Institution
            institution = Institution.objects.filter(id=satellite.institution_id).first()
    return institution


def _logo(institution):
    """(clé de cache, octets) du logo de la marque ; l'emblème Assista-Crise à défaut."""
    if institution is not None and institution.logo:
        try:
            with institution.logo.open("rb") as fichier:
                return f"{institution.id}:{institution.logo.name}", fichier.read()
        except (OSError, ValueError):
            pass
    return "defaut", ICONE_DEFAUT.read_bytes()


@functools.lru_cache(maxsize=64)
def _icone(cle, octets, taille, masquable):
    """Une icône carrée sur fond blanc : iOS remplit de noir la transparence, et rogne les
    coins. Le logo occupe 80 % du carré (64 % pour une icône « masquable », dont Android peut
    découper un cercle)."""
    from PIL import Image

    logo = Image.open(io.BytesIO(octets)).convert("RGBA")
    place = int(taille * (0.64 if masquable else 0.8))
    logo.thumbnail((place, place), Image.LANCZOS)
    fond = Image.new("RGBA", (taille, taille), (255, 255, 255, 255))
    fond.alpha_composite(logo, ((taille - logo.width) // 2, (taille - logo.height) // 2))
    tampon = io.BytesIO()
    fond.convert("RGB").save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()


class IconePwaView(APIView):
    """GET /api/pwa/icone/?taille=180|192|512[&masquable=1] : PNG carré de la marque."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            taille = int(request.query_params.get("taille", "192"))
        except ValueError:
            return HttpResponseNotFound()
        if taille not in TAILLES:
            return HttpResponseNotFound()
        cle, octets = _logo(_institution_de_la_marque(request))
        try:
            png = _icone(cle, octets, taille, request.query_params.get("masquable") == "1")
        except Exception:
            # Un logo illisible ne doit pas priver l'application d'icône.
            png = _icone("defaut", ICONE_DEFAUT.read_bytes(), taille, False)
        reponse = HttpResponse(png, content_type="image/png")
        reponse["Cache-Control"] = "public, max-age=86400"
        reponse.cache_public = True
        return reponse


class ManifestePwaView(APIView):
    """GET /api/pwa/manifeste/?espace=terrain|pilotage : le manifeste de l'application."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        espace = ESPACES.get(request.query_params.get("espace", "terrain"))
        if espace is None:
            return HttpResponseNotFound()
        institution = _institution_de_la_marque(request)
        branding = branding_for_institution(institution)
        nom = branding.nom_affichage
        manifeste = {
            # Deux applications sur le même site : c'est `id` qui les distingue.
            "id": espace["depart"],
            "name": f"{nom} — {espace['suffixe']}",
            "short_name": espace["court"] or nom[:12],
            "start_url": espace["depart"],
            "scope": "/",
            "display": "standalone",
            "orientation": "any",
            "lang": "fr",
            "dir": "ltr",
            "background_color": "#ffffff",
            "theme_color": branding.couleur_primaire,
            "icons": [
                {"src": "/api/pwa/icone/?taille=192", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/api/pwa/icone/?taille=512", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/api/pwa/icone/?taille=512&masquable=1", "sizes": "512x512", "type": "image/png",
                 "purpose": "maskable"},
            ],
        }
        reponse = JsonResponse(manifeste, content_type="application/manifest+json",
                               json_dumps_params={"ensure_ascii": False})
        reponse["Cache-Control"] = "public, max-age=300"
        reponse.cache_public = True
        return reponse


class ClePushView(APIView):
    """GET /api/pwa/cle-push/ : la clé publique VAPID que le navigateur donne au service de
    notification en s'abonnant. 404 si les notifications poussées ne sont pas configurées."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from .web_push import cle_publique_b64url
        cle = cle_publique_b64url()
        if cle is None:
            return HttpResponseNotFound()
        reponse = JsonResponse({"cle": cle})
        reponse["Cache-Control"] = "public, max-age=3600"
        reponse.cache_public = True
        return reponse

