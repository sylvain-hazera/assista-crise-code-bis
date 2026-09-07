"""Filtrage par zone de compétence (commune/EPCI/département/région/national).

Extrait de views.py lors de l'audit sécurité qui a montré que la quasi-totalité des vues
(demandes d'aide, offres d'aide, signalements, équipes, points opérationnels, dossiers, "je
suis en sécurité") n'appliquait aucun filtrage par institution/zone — seul le filtre
environnement PROD/DEMO existait. `SECTEUR_CHAMP_PAR_NIVEAU`/`_institution_secteur_or_400`
existaient déjà (RequestViewSet.vue_secteur/OfferViewSet.vue_secteur) mais n'étaient utilisés
que sur ces deux actions dédiées, jamais sur les vues "liste" par défaut. Ce module généralise
le même mécanisme : `viewer_zone_code`/`object_in_viewer_zone` pour les serializers (prédicat
par objet, jamais bloquant), `filter_queryset_to_viewer_zone` pour les querysets (get_queryset).

UserRole.ADMINISTRATOR (rôle applicatif, pas un rôle institutionnel) contourne toujours ce
filtrage — c'est le seul rôle qui voit vraiment tout, sans notion de zone.
"""
from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response

from .models import UserRole
from .permissions import effective_role_or_none

# Colonne correspondante par niveau de secteur — mêmes noms de champ dénormalisés sur Offer et
# Request (voir OfferViewSet.perform_create/RequestViewSet.perform_create) — "national" n'en a
# pas (aucun filtre géographique, voir vue_secteur).
SECTEUR_CHAMP_PAR_NIVEAU = {
    "commune": "commune_code",
    "epci": "epci_code",
    "departement": "departement_code",
    "region": "region_code",
}


def _institution_commune_or_400(request):
    """Code commune de l'institution de l'utilisateur appelant, pour les actions "vue mairie"
    partagées par RequestViewSet/InformationViewSet. Retourne soit le code (str), soit une
    Response 400 prête à renvoyer si l'utilisateur n'a pas d'institution ou que celle-ci n'a
    pas de commune renseignée (ex: institution non-AUT_LOCALE, ou AUT_LOCALE non encore
    rattachée via l'annuaire) — jamais une liste vide silencieuse qui masquerait la vraie
    cause."""
    institution = getattr(request.user, 'institution', None)
    if institution is None or not institution.commune_code:
        return Response(
            {"error": "Aucune commune associée à votre institution : contactez un administrateur."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return institution.commune_code


def _institution_secteur_or_400(request):
    """(niveau, code) du secteur consultable par l'institution de l'utilisateur appelant.
    `institution.secteur_override` (posé manuellement, usage test uniquement — voir le champ)
    prend le pas sur le niveau déduit du type. Le code lui-même est lu directement sur
    l'institution (epci_code/departement_code/region_code, dénormalisés par Institution.save()
    depuis commune_code) — jamais recalculé ici. "national" ne renvoie aucun code (pas de
    filtre géographique). Retourne une Response 400 prête à renvoyer si l'institution n'a pas
    de commune, ou si le secteur demandé (override compris) n'est pas renseigné."""
    commune_code = _institution_commune_or_400(request)
    if isinstance(commune_code, Response):
        return commune_code

    institution = request.user.institution
    # Déjà calculé et stocké par Institution.save() (secteur_override en priorité, sinon
    # déduit du type via SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION) — jamais recalculé ici.
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
    """Variante douce de `_institution_secteur_or_400` : jamais de 400, `None` si la zone de
    l'utilisateur courant n'est pas résolvable (anonyme, sans institution, institution sans
    commune/secteur renseigné) — pour les prédicats de visibilité "best effort" (serializers),
    qui ne doivent jamais faire échouer toute une réponse pour un champ optionnel."""
    user = getattr(request, 'user', None) if request is not None else None
    if not (user and user.is_authenticated):
        return None
    result = _institution_secteur_or_400(request)
    if isinstance(result, Response):
        return None
    return result


def object_in_viewer_zone(request, obj, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Prédicat par objet : True si `obj` est dans la zone de compétence de l'utilisateur
    courant de `request`. UserRole.ADMINISTRATOR (rôle applicatif) et le niveau "national"
    (aucun filtre géographique pour cette institution) court-circuitent toujours vers True ;
    une zone non résolvable (anonyme, pas d'institution...) donne toujours False."""
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


def filter_queryset_to_viewer_zone(request, queryset, resolver=None, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Version dure (querysets) du même filtrage, pour les `get_queryset`/actions `list` :
    réduit `queryset` à la zone de compétence de l'utilisateur courant. UserRole.ADMINISTRATOR
    voit tout, sans filtre. `resolver(niveau, code) -> Q` permet de filtrer une ressource sans
    code géographique dénormalisé directement dessus (ex: Team via
    `Q(institution__commune_code=code)`, PointOperationnel via
    `Q(equipe__institution__commune_code=code)`) ; par défaut, filtre directement sur
    `champ_par_niveau[niveau]`. Retourne un queryset vide (`.none()`) si la zone de
    l'utilisateur n'est pas résolvable — jamais tout ouvrir par défaut faute de zone connue."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return queryset
    zone = viewer_zone_code(request)
    if zone is None:
        return queryset.none()
    niveau, code = zone
    if niveau == "national":
        return queryset
    if resolver is not None:
        return queryset.filter(resolver(niveau, code))
    champ = champ_par_niveau.get(niveau)
    if not champ:
        return queryset.none()
    return queryset.filter(**{champ: code})
