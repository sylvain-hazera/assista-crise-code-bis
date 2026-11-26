"""Ce que le menu latéral affiche en plus des liens (revue du menu, 19/11/2026) :
- les compteurs : signalements non traités, messages à relire, demandes de mobilisation actives ;
- si une crise est ouverte pour l'institution, pour mettre « Crise en cours » devant
  « Préparer » (et l'inverse hors crise).

Chaque nombre est compté avec le queryset de la LISTE correspondante : on ne compte que ce que
la page montrerait à cet utilisateur, jamais plus (périmètre, institution, zone).
"""
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Status, StatutDemandeMobilisation


def _queryset_de(classe_vue, request):
    vue = classe_vue()
    vue.request, vue.args, vue.kwargs, vue.format_kwarg, vue.action = request, (), {}, None, "list"
    vue.headers = {}
    for permission in vue.get_permissions():
        if not permission.has_permission(request, vue):
            return None
    return vue.get_queryset()


def _compter(classe_vue, request, **filtres):
    try:
        qs = _queryset_de(classe_vue, request)
    except Exception:  # noqa: BLE001 -- un compteur en moins ne casse pas le menu
        return None
    return None if qs is None else qs.filter(**filtres).order_by().count()


class CompteursMenuView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .views import (
            BrouillonEnvoiViewSet, DemandeMobilisationViewSet, ImplicationInstitutionViewSet,
            InformationViewSet, OfferViewSet, RequestViewSet,
        )
        signalements = [_compter(v, request, status=Status.UNPROCESSED)
                        for v in (RequestViewSet, OfferViewSet, InformationViewSet)]
        signalements = [n for n in signalements if n is not None]
        implications = None
        try:
            qs = _queryset_de(ImplicationInstitutionViewSet, request)
            institution = getattr(request.user, "institution_id", None)
            if qs is not None and institution:
                implications = qs.filter(institution_id=institution, actif=True,
                                         crise__end_date__isnull=True).exists()
        except Exception:  # noqa: BLE001
            implications = None
        return Response({
            "signalements": sum(signalements) if signalements else None,
            "messages_a_relire": _compter(BrouillonEnvoiViewSet, request, statut="A_RELIRE"),
            "demandes_mobilisation": _compter(DemandeMobilisationViewSet, request,
                                              statut=StatutDemandeMobilisation.ACTIVE),
            "crise_ouverte": bool(implications),
            # Une association (AASC ou non) : hors crise, ses écrans de crise sont masqués du menu
            # (26/11/2026). La réserve communale reste côté mairie.
            "association": _est_association(request.user),
        })


def _est_association(user) -> bool:
    institution = getattr(user, "institution", None)
    code = (getattr(getattr(institution, "type", None), "code", "") or "").lower()
    return code in ("aasc", "association")
