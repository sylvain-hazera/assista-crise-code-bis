"""Connexion à Grafana sans second mot de passe (DOCUMENTATION.md, « Monitoring »).

Le frontend demande ici un jeton signé RS256 et le passe à l'iframe Grafana (`?auth_token=`).
Grafana le vérifie avec la clé publique ([auth.jwt], `url_login`). Il ne crée pas de session :
son interface renvoie ce jeton à chaque requête, d'où une durée de vie égale à celle du jeton
d'accès (1 h), renouvelé par le frontend avant expiration. Le jeton passe dans une URL : il ne
contient aucune donnée personnelle et le proxy le masque dans ses journaux.
"""
import datetime

import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserRole

GRAFANA_JWT_TTL = 3600


class IsAdministrator(permissions.BasePermission):
    """Rôle réel (pas le rôle effectif de la zone DEMO) : la supervision n'existe qu'en prod."""

    message = "La supervision technique est réservée aux administrateurs."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.type == UserRole.ADMINISTRATOR)


class GrafanaTokenView(APIView):
    permission_classes = [IsAdministrator]

    def post(self, request):
        if not settings.GRAFANA_JWT_PRIVATE_KEY:
            return Response({"detail": "Supervision non configurée."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        now = timezone.now()
        token = jwt.encode(
            {
                "iss": "assista-crise",
                "aud": "grafana",
                "sub": f"assista-{request.user.id}",
                "role": "Viewer",   # rôle Grafana, lu par role_attribute_path
                "iat": now,
                "exp": now + datetime.timedelta(seconds=GRAFANA_JWT_TTL),
            },
            settings.GRAFANA_JWT_PRIVATE_KEY,
            algorithm="RS256",
        )
        return Response({"token": token, "expires_in": GRAFANA_JWT_TTL})
