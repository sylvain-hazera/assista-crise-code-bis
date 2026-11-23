"""Organisation (arbre des institutions et de leurs filles) et revue des droits (23/11/2026).
Voir core/organisation.py et core/revue_droits.py."""
import csv

from django.http import HttpResponse
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import organisation, revue_droits
from .models import AffectationRoleOperationnel, ContactInstitution, Institution, RevueDroits, UserRole
from .permissions import INSTITUTIONAL_TYPES, get_effective_role


class OrganisationView(APIView):
    """GET /api/organisation/?q= : les arbres institution → filles → équipes du périmètre."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if get_effective_role(request) not in INSTITUTIONAL_TYPES and not getattr(request.user, "institution_id", None):
            raise PermissionDenied("Réservé aux comptes d'une institution.")
        return Response({"arbres": organisation.arbre(request, request.query_params.get("q", ""))})


def _institution_demandee(request):
    """L'institution dont on fait la revue : celle demandée, sinon celle qu'on regarde."""
    from .perimetre_admin import est_administrateur, institution_regardee

    ident = request.query_params.get("institution")
    if ident:
        institution = Institution.objects.filter(pk=ident).select_related("type").first()
        if institution is None:
            raise ValidationError({"error": "Institution inconnue."})
    else:
        institution = (institution_regardee(request) if est_administrateur(request) else None) or getattr(request.user, "institution", None)
        if institution is not None and not revue_droits.peut_revoir(request.user, institution):
            revisables = revue_droits.institutions_revisables(request.user)
            institution = Institution.objects.filter(id__in=revisables, institution_parente__isnull=True).first() \
                or Institution.objects.filter(id__in=revisables).first()
    if institution is None:
        raise PermissionDenied("Aucune institution dont vous puissiez faire la revue des droits.")
    if not revue_droits.peut_revoir(request.user, institution):
        raise PermissionDenied("La revue des droits de cette institution revient à son bureau, son contact principal "
                               "ou ses responsables (ou à ceux de l'institution dont elle dépend).")
    return institution


def _choix(request, courante):
    """Les institutions proposées dans le sélecteur de la page."""
    if request.user.type == UserRole.ADMINISTRATOR:
        ids = set(Institution.objects.filter(institution_parente=None, actif=True, institutions_filles__isnull=False)
                  .values_list("id", flat=True)[:300])
    else:
        ids = revue_droits.institutions_revisables(request.user)
    ids.add(courante.id)
    return [{"id": str(i.id), "nom": i.nom_affichage or i.nom}
            for i in Institution.objects.filter(id__in=ids).order_by("nom")]


class RevueDroitsView(APIView):
    """GET /api/revue-droits/?institution= : la matrice de l'institution et de ses filles."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        institution = _institution_demandee(request)
        donnees = revue_droits.matrice(request, institution)
        donnees["choix"] = _choix(request, institution)
        return Response(donnees)


class RevueDroitsDecisionView(APIView):
    """POST /api/revue-droits/decision/ {contact, decision, commentaire?, affectation?}."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        contact = ContactInstitution.objects.filter(pk=request.data.get("contact")).select_related(
            "institution", "utilisateur").first()
        if contact is None:
            raise ValidationError({"error": "Fiche de contact inconnue."})
        if not revue_droits.peut_revoir(request.user, contact.institution):
            raise PermissionDenied("Vous ne pouvez pas revoir les droits de cette institution.")
        decision = request.data.get("decision")
        if decision not in RevueDroits.Decision.values:
            raise ValidationError({"error": "Décision inconnue."})
        if contact.utilisateur_id == request.user.id and decision != RevueDroits.Decision.CONFIRME:
            raise ValidationError({"error": "On ne retire pas ses propres droits depuis la revue : demandez-le à un autre responsable."})
        affectation = None
        if decision == RevueDroits.Decision.ROLE_RETIRE:
            affectation = AffectationRoleOperationnel.objects.filter(
                pk=request.data.get("affectation"), utilisateur=contact.utilisateur,
                institution=contact.institution, actif=True).select_related("role").first()
            if affectation is None:
                raise ValidationError({"error": "Rôle introuvable pour cette personne dans cette institution."})
        revue = revue_droits.decider(request, contact, decision, request.data.get("commentaire", ""), affectation)
        return Response({"id": str(revue.id), "decision": revue.get_decision_display()}, status=status.HTTP_201_CREATED)


class RevueDroitsExportView(APIView):
    """GET /api/revue-droits/export/?institution= : la matrice en CSV (contrôle de conformité)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .audit import audit_log

        institution = _institution_demandee(request)
        donnees = revue_droits.matrice(request, institution)
        reponse = HttpResponse(content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = 'attachment; filename="revue-des-droits.csv"'
        reponse.write("﻿")   # Excel reconnaît l'UTF-8
        w = csv.writer(reponse, delimiter=";")
        w.writerow(["Institution", "Nom", "Email", "Fonction", "Fiche active", "Contact principal", "Bureau",
                    "Type de compte", "Institution de travail", "Rôles", "Équipes", "Encadre", "Habilité registre",
                    "Engagement signé", "Accès formation", "Compte actif", "Dernière connexion", "Dernière revue",
                    "Anomalies"])
        for l in donnees["lignes"]:
            w.writerow([
                l["institution_nom"], l["nom"], l["email"], l["fonction"], _oui(l["actif"]), _oui(l["contact_principal"]),
                _oui(l["membre_bureau"]), l["type_compte_libelle"], l["institution_travail"],
                ", ".join(r["libelle"] for r in l["roles"]), ", ".join(l["equipes"]), ", ".join(l["encadre"]),
                _oui(l["habilite_registre"]), _oui(l["engagement_signe"]), _oui(l["acces_formation"]),
                _oui(l["compte_actif"]), (l["derniere_connexion"] or "")[:10],
                (f'{l["derniere_revue"]["le"][:10]} {l["derniere_revue"]["par"]} ({l["derniere_revue"]["decision"]})'
                 if l["derniere_revue"] else ""),
                " ; ".join(a["libelle"] for a in l["anomalies"]),
            ])
        audit_log(request=request, action_code="EXPORT", objet_type="RevueDroits", objet_id=institution.id,
                  commentaire=f"Export de la revue des droits — {institution.nom} ({len(donnees['lignes'])} fiches)")
        return reponse


def _oui(v):
    return "oui" if v else "non"


class TableauRadioMeshCoreView(APIView):
    """GET /api/tableau-radio-meshcore/?fenetre=6h|24h|7j : trafic, liaisons, relais publics et
    observateurs MeshCore (23/11/2026, core/tableau_meshcore.py)."""

    def get_permissions(self):
        from .permissions import PeutAccederRadio
        return [permissions.IsAuthenticated(), PeutAccederRadio()]

    def get(self, request):
        from . import tableau_meshcore
        from .permissions import get_active_environment
        return Response(tableau_meshcore.construire(get_active_environment(request), request.query_params.get("fenetre", "24h")))
