"""La carte du terrain de l'application (27/11/2026) : le périmètre en cours d'une personne.

Décision de Sylvain : la carte (et sa liste de points) ne montre que la crise ou la
manifestation en cours ; sans crise en cours, les crises de sa commune.

`GET carte-terrain/perimetre/` rend les crises, dans cet ordre :
1. celles des missions en cours de ses équipes (membre, chef, régulateur) — « engagement » ;
2. sinon, les crises ouvertes de sa commune — « commune » : son institution ou l'une de ses
   associations y est impliquée (implication validée), ou la commune de cette institution est
   dans la zone de la crise ;
3. sinon, rien.
Les manifestations du jour, l'application les a déjà (`manifestations/`).
"""
import json

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ContactInstitution, Crisis, ImplicationInstitution, Institution, Mission, StatutImplication
from .permissions import get_active_environment


def _en_dict(c):
    return {
        "id": str(c.id), "nom": c.name,
        "latitude": c.location.y if c.location else None, "longitude": c.location.x if c.location else None,
        "zone": json.loads(c.zone.geojson) if getattr(c, "zone", None) else None,
    }


def crises_du_perimetre(utilisateur, environment):
    """(crises, raison) : voir le module."""
    ouvertes = Crisis.objects.filter(environment=environment, end_date__isnull=True)
    engagees = ouvertes.filter(id__in=Mission.objects.filter(
        Q(equipes__members=utilisateur) | Q(equipes__leader=utilisateur) | Q(equipes__regulateur=utilisateur),
        statut=Mission.Statut.EN_COURS, crise__isnull=False).values("crise_id")).distinct()
    if engagees.exists():
        return list(engagees.order_by("-start_date")), "engagement"
    institutions = set(ContactInstitution.objects.filter(utilisateur=utilisateur, actif=True).values_list("institution_id", flat=True))
    if getattr(utilisateur, "institution_id", None):
        institutions.add(utilisateur.institution_id)
    if not institutions:
        return [], "aucune"
    communes = [c for c in Institution.objects.filter(id__in=institutions).values_list("commune_code", flat=True) if c]
    filtre = Q(id__in=ImplicationInstitution.objects.filter(
        institution_id__in=institutions, actif=True, statut=StatutImplication.VALIDEE).values("crise_id"))
    for code in communes:
        filtre |= Q(zone_communes__contains=[code])
    crises = list(ouvertes.filter(filtre).distinct().order_by("-start_date"))
    return crises, ("commune" if crises else "aucune")


class PerimetreCarteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        crises, raison = crises_du_perimetre(request.user, get_active_environment(request))
        return Response({"raison": raison, "crises": [_en_dict(c) for c in crises]})


class VeilleTerrainView(APIView):
    """GET carte-terrain/veille/ : la mini veille du territoire de l'application (27/11/2026),
    pour chaque crise du périmètre et chaque manifestation du jour (voir core/veille_terrain.py)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import veille_terrain

        def nombre(cle, borne):
            try:
                v = float(request.query_params.get(cle))
            except (TypeError, ValueError):
                return None
            return v if -borne <= v <= borne else None
        latitude, longitude = nombre("lat", 90), nombre("lon", 180)
        if latitude is None or longitude is None:
            latitude = longitude = None
        return Response(veille_terrain.construire(request.user, get_active_environment(request),
                                                  latitude=latitude, longitude=longitude))
