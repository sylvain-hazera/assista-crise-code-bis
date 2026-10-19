"""Accès à Grafana depuis le site (page admin « Monitoring », demande utilisateur du 19/10),
réservé aux administrateurs de la plateforme.

Grafana est servi sous /grafana/ par ac_proxy, derrière le WAF, en mode « auth proxy » : il
fait confiance à l'en-tête X-WEBAUTH-USER posé par nginx, qui le tient de la réponse de
`GrafanaVerifierView` (directive auth_request, appelée à CHAQUE requête vers /grafana/).

Le site s'authentifie par JWT en en-tête (pas de cookie) : une iframe ne peut pas le
transmettre. D'où un cookie dédié, signé et de courte durée, posé par `GrafanaSessionView`
quand la page Monitoring s'ouvre, et limité au chemin /grafana/ -- jamais envoyé à /api/.
"""
from django.conf import settings
from django.core import signing
from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User, UserRole
from .permissions import IsAdministrator

COOKIE = "ac_grafana"
DUREE_SECONDES = 8 * 3600
_SEL = "core.grafana_acces"


class GrafanaSessionView(APIView):
    """POST : pose le cookie d'accès à Grafana pour l'administrateur connecté."""

    permission_classes = [IsAdministrator]

    def post(self, request):
        response = Response({"url": "/grafana/", "expire_dans": DUREE_SECONDES})
        response.set_cookie(
            COOKIE, signing.dumps(str(request.user.pk), salt=_SEL),
            max_age=DUREE_SECONDES, path="/grafana/", httponly=True,
            secure=settings.SESSION_COOKIE_SECURE, samesite="Strict",
        )
        return response


def utilisateur_grafana(valeur_cookie):
    """Administrateur actif correspondant au cookie, ou None (absent, falsifié, expiré, compte
    désactivé ou qui n'est plus administrateur depuis la pose du cookie)."""
    if not valeur_cookie:
        return None
    try:
        pk = signing.loads(valeur_cookie, salt=_SEL, max_age=DUREE_SECONDES)
    except signing.BadSignature:
        return None
    return User.objects.filter(pk=pk, is_active=True, type=UserRole.ADMINISTRATOR).first()


def grafana_verifier(request):
    """Sous-requête auth_request de nginx (voir proxy/nginx.conf, location /grafana/) : 200 +
    identité dans X-Grafana-User, sinon 401. Vue Django brute plutôt qu'APIView : aucune
    authentification DRF à tenter (pas de JWT dans une requête d'iframe)."""
    user = utilisateur_grafana(request.COOKIES.get(COOKIE))
    if user is None:
        return HttpResponse(status=401)
    response = HttpResponse(status=200)
    response["X-Grafana-User"] = user.email
    return response
