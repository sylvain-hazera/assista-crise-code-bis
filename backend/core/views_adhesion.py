"""API : une association existante rejoint le réseau, et son étendue d'intervention (26/11/2026) —
voir core/adhesion_association.py."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import adhesion_association as aa
from .audit import audit_log
from .models import DemandeAdhesionAssociation, EchelonIntervention, Institution, UserRole
from .permissions import get_active_environment


def _echelons(commune_code):
    noms = aa.libelles(commune_code) if commune_code else {}
    return [{"code": c, "libelle": l, "territoire": noms.get(c, "")} for c, l in EchelonIntervention.choices]


def _demande_en_dict(d, admin=False) -> dict:
    noms = aa.libelles(d.commune_code)
    r = {"id": str(d.id), "nom": d.nom, "activite": d.activite, "commune_code": d.commune_code,
         "commune_nom": noms.get(EchelonIntervention.COMMUNE, d.commune_code), "echelon": d.echelon,
         "echelon_libelle": d.get_echelon_display(), "territoire": noms.get(d.echelon, ""), "agrement": d.agrement,
         "statut": d.statut, "statut_libelle": d.get_statut_display(), "motif_refus": d.motif_refus,
         "date_demande": d.date_demande, "institution": str(d.institution_id) if d.institution_id else None}
    if admin:
        u = d.demandeur
        r.update({"demandeur": f"{u.first_name} {u.last_name}".strip() or u.email, "demandeur_email": u.email,
                  "fonction": d.fonction, "telephone": d.telephone,
                  "doublons": [{"id": str(i.id), "nom": i.nom, "commune_nom": i.commune_nom or ""} for i in aa.doublons_possibles(d.nom)]})
    return r


def _exiger_admin(request):
    if getattr(request.user, "type", None) != UserRole.ADMINISTRATOR:
        raise PermissionDenied("Réservé à l'administrateur de la plateforme.")


class EtendueView(APIView):
    """GET ?commune=<code INSEE> : les six échelons et ce qu'ils veulent dire depuis cette commune
    (« Gironde », « zone Sud-Ouest »…). Public : c'est de la géographie."""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"echelons": _echelons(str(request.query_params.get("commune") or ""))})


class DemandesAdhesionView(APIView):
    """POST : déposer la demande de son association (compte connecté). GET : la mienne, ou toutes
    (administrateur, ?toutes=1)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.query_params.get("toutes"):
            _exiger_admin(request)
            qs = DemandeAdhesionAssociation.objects.filter(environment=get_active_environment(request)).select_related("demandeur")
            statut = request.query_params.get("statut")
            if statut:
                qs = qs.filter(statut=statut)
            return Response({"demandes": [_demande_en_dict(d, admin=True) for d in qs[:200]]})
        mienne = DemandeAdhesionAssociation.objects.filter(demandeur=request.user).first()
        return Response({"demande": _demande_en_dict(mienne) if mienne else None})

    def post(self, request):
        d = request.data
        try:
            demande = aa.deposer(request.user, get_active_environment(request), nom=d.get("nom"), activite=d.get("activite"),
                                 commune_code=str(d.get("commune_code") or ""), echelon=d.get("echelon"),
                                 agrement=d.get("agrement", ""), fonction=d.get("fonction", ""), telephone=d.get("telephone", ""))
        except aa.ErreurAdhesion as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="CREATION", objet_type="DemandeAdhesionAssociation", objet_id=demande.id,
                  commentaire="Demande d'adhésion d'une association au réseau")
        return Response(_demande_en_dict(demande), status=status.HTTP_201_CREATED)


class DemandeAdhesionGesteView(APIView):
    """POST {geste: accepter | refuser, motif?} (administrateur)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        _exiger_admin(request)
        demande = get_object_or_404(DemandeAdhesionAssociation.objects.select_related("demandeur"), id=pk)
        try:
            if request.data.get("geste") == "accepter":
                aa.accepter(demande, request.user, request)
            elif request.data.get("geste") == "refuser":
                aa.refuser(demande, request.user, request.data.get("motif"))
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except aa.ErreurAdhesion as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="DemandeAdhesionAssociation", objet_id=demande.id,
                  commentaire=f"Demande d'adhésion : {request.data.get('geste')}")
        return Response(_demande_en_dict(demande, admin=True))


class EchelonAssociationView(APIView):
    """GET : l'étendue d'intervention d'une association (ses membres). PUT {echelon} : la changer
    (son bureau, librement)."""
    permission_classes = [IsAuthenticated]

    def _institution(self, request, pk):
        from . import manifestations as mf
        institution = get_object_or_404(Institution, id=pk)
        if not (mf.est_admin(request.user) or institution.id in mf.associations_de(request.user)):
            raise PermissionDenied("Réservé aux membres de l'association.")
        return institution

    def _reponse(self, request, institution):
        from . import manifestations as mf
        return {"institution": str(institution.id), "nom": institution.nom, "echelon": institution.echelon_intervention,
                "echelons": _echelons(institution.commune_code), "modifiable": mf.organise(request.user, institution.id),
                "concernee": aa.soumise_a_l_etendue(institution)}

    def get(self, request, pk):
        return Response(self._reponse(request, self._institution(request, pk)))

    def put(self, request, pk):
        institution = self._institution(request, pk)
        try:
            aa.changer_echelon(institution, request.user, request.data.get("echelon"))
        except aa.ErreurAdhesion as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="Institution", objet_id=institution.id,
                  commentaire=f"Étendue d'intervention : {institution.get_echelon_intervention_display()}")
        return Response(self._reponse(request, institution))
