"""Filtrage par zone de compétence (commune, EPCI, département, région, national).

Fonctionnement et règles : DOCUMENTATION.md, § 5.5.
"""
from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response

from .models import UserRole
from .permissions import effective_role_or_none

# colonnes dénormalisées sur Offer et Request ; "national" n'a pas de filtre
SECTEUR_CHAMP_PAR_NIVEAU = {
    "commune": "commune_code",
    "epci": "epci_code",
    "departement": "departement_code",
    "region": "region_code",
}


def _institution_commune_or_400(request):
    """Code commune de l'institution de l'appelant, ou une Response 400 explicite (plutôt
    qu'une liste vide qui masquerait la cause)."""
    institution = getattr(request.user, 'institution', None)
    if institution is None or not institution.commune_code:
        return Response(
            {"error": "Aucune commune associée à votre institution : contactez un administrateur."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return institution.commune_code


def _sdis_en_demo(request):
    from .models import Environment
    from .permissions import get_active_environment

    institution = getattr(request.user, 'institution', None)
    if institution is None or not institution.type_id:
        return False
    if (institution.type.code or '').upper() != 'SDIS':
        return False
    return get_active_environment(request) == Environment.DEMO


def _institution_secteur_or_400(request):
    """(niveau, code) du secteur de l'institution de l'appelant, ou une Response 400.
    "national" renvoie un code None. En zone DEMO, un SDIS a une portée nationale (les jeux de
    démonstration couvrent plusieurs départements, POC SDIS 40 du 20/10/2026)."""
    if _sdis_en_demo(request):
        return "national", None

    commune_code = _institution_commune_or_400(request)
    if isinstance(commune_code, Response):
        return commune_code

    institution = request.user.institution
    # calculé par Institution.save()
    niveau = institution.secteur_niveau_effectif or "commune"

    if niveau == "national":
        return "national", None
    if niveau == "commune":
        return "commune", commune_code

    code = getattr(institution, f"{niveau}_code", None)
    if not code:
        return Response(
            {"error": f"Secteur ({niveau}) introuvable pour votre institution."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return niveau, code


def viewer_zone_code(request):
    """Comme _institution_secteur_or_400, mais None au lieu d'une 400 (pour les serializers)."""
    user = getattr(request, 'user', None) if request is not None else None
    if not (user and user.is_authenticated):
        return None
    result = _institution_secteur_or_400(request)
    if isinstance(result, Response):
        return None
    return result


ECHELLE_ORDER = ["commune", "epci", "departement", "region", "national"]


def widen_zone_from_request(request):
    """Zone de l'appelant, élargie par ?echelle= (jamais rétrécie). None si non résolvable :
    l'appelant choisit le repli."""
    natural = viewer_zone_code(request)
    if natural is None:
        return None
    echelle = request.query_params.get('echelle')
    if not echelle or echelle not in ECHELLE_ORDER:
        return natural
    if ECHELLE_ORDER.index(echelle) <= ECHELLE_ORDER.index(natural[0]):
        return natural
    if echelle == "national":
        return ("national", None)
    institution = request.user.institution
    code = getattr(institution, f"{echelle}_code", None)
    return (echelle, code) if code else natural


def object_in_viewer_zone(request, obj, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """True si obj est dans la zone de l'appelant (toujours pour un administrateur ou le
    niveau national, jamais si la zone n'est pas résolvable)."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return True
    zone = viewer_zone_code(request)
    if zone is None:
        return False
    niveau, code = zone
    if niveau == "national":
        return True
    champ = champ_par_niveau.get(niveau)
    if not champ:
        return False
    return getattr(obj, champ, None) == code


def object_in_viewer_zone_via_commune(request, obj, commune_field="commune_code"):
    """object_in_viewer_zone pour un modèle qui n'a que commune_code (Information) : les
    niveaux supérieurs sont résolus via le référentiel Commune."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return True
    zone = viewer_zone_code(request)
    if zone is None:
        return False
    niveau, code = zone
    if niveau == "national":
        return True
    commune_code = getattr(obj, commune_field, None)
    if not commune_code:
        return False
    if niveau == "commune":
        return commune_code == code
    champ_commune = SECTEUR_CHAMP_PAR_NIVEAU.get(niveau)
    if not champ_commune:
        return False
    from .models import Commune
    return Commune.objects.filter(code=commune_code, **{champ_commune: code}).exists()


def apply_zone(queryset, zone, resolver=None, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Filtre queryset sur une zone (niveau, code) déjà résolue."""
    niveau, code = zone
    if niveau == "national":
        return queryset
    if resolver is not None:
        return queryset.filter(resolver(niveau, code))
    champ = champ_par_niveau.get(niveau)
    if not champ:
        return queryset.none()
    return queryset.filter(**{champ: code})


def filter_queryset_to_viewer_zone(request, queryset, resolver=None, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Réduit queryset à la zone de l'appelant ; vide si elle n'est pas résolvable.
    resolver(niveau, code) -> Q pour une ressource sans code géographique propre (ex : Team)."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return queryset
    zone = viewer_zone_code(request)
    if zone is None:
        return queryset.none()
    return apply_zone(queryset, zone, resolver=resolver, champ_par_niveau=champ_par_niveau)
