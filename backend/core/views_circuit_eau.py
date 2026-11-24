"""API du circuit réflexe points d'eau (24/11/2026) — voir core/circuit_eau.py."""
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import circuit_eau
from .audit import audit_log

logger = logging.getLogger(__name__)


def _crise(request, valeur):
    from .models import Crisis

    crise = Crisis.objects.filter(pk=valeur).first() if valeur else None
    if crise is None:
        raise ValidationError({"crise": "Crise introuvable."})
    return crise


class CircuitEauView(APIView):
    """GET /api/circuit-eau/?crise= : l'état du circuit ; pour la cellule, les points candidats
    autour de la crise et les équipes mobilisables."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .conversations import dans_la_crise

        crise = _crise(request, request.query_params.get("crise"))
        if not dans_la_crise(request.user, crise):
            raise PermissionDenied("Vous n'êtes pas engagé sur cette crise.")
        donnees = circuit_eau.etat(crise, request.user)
        if donnees["peut_piloter"] and request.query_params.get("candidats") != "non":
            donnees["candidats"] = circuit_eau.candidats(crise)
            donnees["equipes"] = circuit_eau.equipes_mobilisables(crise, request.user)
        return Response(donnees)


class ActiverCircuitEauView(APIView):
    """POST /api/circuit-eau/activer/ {crise, affectations: [{pei, equipe}]} : la cellule ouvre
    les points choisis et y envoie une équipe."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        crise = _crise(request, request.data.get("crise"))
        if not circuit_eau.peut_piloter(request.user, crise):
            raise PermissionDenied("L'activation des points d'eau revient à la cellule de crise.")
        if crise.end_date is not None:
            raise ValidationError({"crise": "Cette crise est close."})
        affectations = request.data.get("affectations") or []
        if not isinstance(affectations, list) or not affectations:
            raise ValidationError({"affectations": "Choisissez au moins un point d'eau et son équipe."})
        try:
            activations = circuit_eau.activer(crise, affectations, request)
        except ValueError as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="ACTIVATION", objet_type="ActivationPointEau", crise=crise,
                  commentaire=f"Activation de {len(activations)} point(s) d'eau sur la crise {crise.name}")
        return Response({"activations": [circuit_eau.activation_en_dict(a) for a in activations]}, status=status.HTTP_201_CREATED)


class EtatActivationPointEauView(APIView):
    """POST /api/circuit-eau/<id>/etat/ {etat, observe_le} : le binôme (ou la cellule) déclare
    en route, actif, fermé ; la cellule peut aussi annuler. Rejouable sans double effet."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, ident):
        from .models import ActivationPointEau
        from .permissions import get_active_environment

        activation = get_object_or_404(ActivationPointEau.objects.select_related("crise", "equipe", "mission"),
                                       pk=ident, environment=get_active_environment(request))
        etat = str(request.data.get("etat") or "")
        if etat == "ANNULE":
            if not circuit_eau.peut_piloter(request.user, activation.crise):
                raise PermissionDenied("Seule la cellule annule un point d'eau.")
        elif not circuit_eau.peut_declarer(request.user, activation):
            raise PermissionDenied("Seuls l'équipe envoyée sur ce point et la cellule en déclarent l'état.")
        observe_le = parse_datetime(str(request.data.get("observe_le") or ""))
        if observe_le is not None and timezone.is_naive(observe_le):
            observe_le = timezone.make_aware(observe_le)
        try:
            change = circuit_eau.changer_etat(activation, etat, request, observe_le)
        except ValueError as erreur:
            raise ValidationError({"detail": str(erreur)})
        if change:
            audit_log(request=request, action_code="MODIFICATION", objet_type="ActivationPointEau", objet_id=activation.id,
                      crise=activation.crise, commentaire=f"Point d'eau {activation.nom} : {activation.get_statut_display()}")
        return Response(circuit_eau.activation_en_dict(activation))


class LienCodisView(APIView):
    """POST /api/circuit-eau/lien-codis/ {crise, geste: creer|renouveler|revoquer}."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        crise = _crise(request, request.data.get("crise"))
        if not circuit_eau.peut_piloter(request.user, crise):
            raise PermissionDenied("Le lien du CODIS se gère par la cellule de crise.")
        geste = str(request.data.get("geste") or "creer")
        if geste == "revoquer":
            crise.liens_codis.filter(revoque_le__isnull=True).update(revoque_le=timezone.now())
            lien = None
        elif geste == "renouveler" or circuit_eau.lien_actif(crise) is None:
            lien = circuit_eau.creer_lien(crise, request.user)
        else:
            lien = circuit_eau.lien_actif(crise)
        audit_log(request=request, action_code="MODIFICATION", objet_type="LienCodis", crise=crise,
                  commentaire=f"Lien CODIS : {geste}")
        return Response({"lien_codis": circuit_eau.url_codis(lien) if lien else None})


class CarteCodisPublicView(APIView):
    """GET /api/public/codis/<jeton>/ : la carte des points d'eau de la crise, sans compte."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, jeton):
        carte = circuit_eau.carte_codis(jeton)
        if carte is None:
            return Response({"detail": "Lien inconnu, révoqué, ou crise close."}, status=status.HTTP_404_NOT_FOUND)
        return Response(carte)
