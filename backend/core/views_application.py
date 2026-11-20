"""Ce que l'application mobile demande au serveur, et rien que cela.

À part de `views.py` : ces vues ne servent qu'à un client, le téléphone, et tiennent sur une
page. Les y noyer ferait chercher « comment l'application sait-elle qu'un message est lu »
dans vingt-quatre mille lignes.

Toutes exigent un compte, et aucune ne lit ni n'écrit pour quelqu'un d'autre que l'appelant :
il n'y a pas d'identifiant de personne dans leurs paramètres, donc rien à deviner.
"""
import datetime
import uuid

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import notifications_application as moteur
from .models import (
    CampagneDisponibilite, CibleCampagne, DemandeMobilisation, NotificationApplication,
    StatutCampagne,
)
from .permissions import get_active_environment
from .serializers import NotificationApplicationSerializer


def _uuids(valeurs):
    """Les identifiants bien formés, les autres ignorés : un accusé mal écrit ne doit pas
    faire échouer ceux qui l'accompagnent."""
    bons = []
    for valeur in valeurs if isinstance(valeurs, (list, tuple)) else []:
        try:
            bons.append(uuid.UUID(str(valeur)))
        except (TypeError, ValueError):
            continue
    return bons


class MonAppareilView(APIView):
    """Le téléphone se présente (POST) ou prend congé (DELETE).

    Appelé à chaque ouverture : c'est ce qui tient à jour « l'application peut joindre cette
    personne », sur quoi repose la portée annoncée du canal Application."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        installation = str(request.data.get("installation") or "").strip()
        if len(installation) < 16:
            return Response({"error": "Identifiant d'installation manquant."},
                            status=status.HTTP_400_BAD_REQUEST)
        from .web_push import AbonnementRefuse
        try:
            appareil = moteur.enregistrer_appareil(
                request.user, installation,
                plateforme=str(request.data.get("plateforme") or ""),
                version=str(request.data.get("version") or ""),
                notifications_autorisees=request.data.get("notifications_autorisees", True),
                # Application web : l'abonnement aux notifications poussées (absent ailleurs).
                abonnement_push=request.data.get("abonnement_push"),
            )
        except AbonnementRefuse as refus:
            return Response({"error": str(refus)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": appareil.id, "dernier_contact": appareil.dernier_contact})

    def delete(self, request):
        installation = str(request.data.get("installation")
                           or request.query_params.get("installation") or "")
        moteur.oublier_appareil(request.user, installation)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MesNotificationsView(APIView):
    """Mes notifications récentes, la plus neuve d'abord.

    Lire cette liste n'accuse RIEN : c'est le téléphone qui dit ensuite ce qu'il en a fait
    (`AccuserNotificationsView`). Déduire « remise » d'un simple appel ferait compter comme
    prévenue une personne dont l'application a planté avant d'afficher quoi que ce soit."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        depuis = timezone.now() - datetime.timedelta(days=moteur.FENETRE_JOURS)
        notifications = list(
            NotificationApplication.objects.filter(
                utilisateur=request.user, date_creation__gte=depuis,
            ).select_related("institution", "campagne")[:100]
        )
        campagnes = {n.campagne_id for n in notifications if n.campagne_id}
        cibles = {
            c.campagne_id: c
            for c in CibleCampagne.objects.filter(
                utilisateur=request.user, campagne_id__in=campagnes)
        }
        return Response(NotificationApplicationSerializer(
            notifications, many=True, context={"request": request, "cibles": cibles},
        ).data)


class AccuserNotificationsView(APIView):
    """Le téléphone dit où en sont des notifications : REMISE, VUE ou LUE."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        etape = str(request.data.get("etape") or "").upper()
        if etape not in (moteur.ETAPE_REMISE, moteur.ETAPE_VUE, moteur.ETAPE_LUE):
            return Response({"error": "Étape attendue : REMISE, VUE ou LUE."},
                            status=status.HTTP_400_BAD_REQUEST)
        avancees = moteur.accuser(request.user, _uuids(request.data.get("ids")), etape)
        return Response({"avancees": avancees})


class RepondreIndisponibleView(APIView):
    """« Je ne suis pas disponible sur cette période » — pour l'application ET pour le site.

    Le « oui » n'a pas de vue : il se dit en cochant des créneaux (`MesDisponibilitesView`),
    parce qu'un oui sans dates n'arme aucune garde."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from .campagnes_disponibilite import repondre_indisponible

        identifiants = _uuids([request.data.get("campagne")])
        campagne = CampagneDisponibilite.objects.filter(
            pk__in=identifiants, cibles__utilisateur=request.user,
        ).select_related("institution").first()
        # Même réponse que la campagne n'existe pas ou qu'on n'en soit pas la cible : ne pas
        # confirmer à qui devine un identifiant qu'il a deviné juste.
        if campagne is None:
            return Response({"error": "Cette demande ne vous est pas adressée."},
                            status=status.HTTP_404_NOT_FOUND)
        if campagne.statut == StatutCampagne.CLOTUREE:
            return Response({"error": "Cette demande est close : il n'y a plus à y répondre."},
                            status=status.HTTP_400_BAD_REQUEST)
        cible = repondre_indisponible(campagne, request.user)
        return Response({"etat": cible.etat, "creneaux_declares": cible.creneaux_declares,
                         "date_reponse": cible.date_reponse})


class MesMobilisationsView(APIView):
    """Les demandes de mobilisation adressées à l'appelant, pour qu'il présente son QR code.

    `DemandeMobilisationViewSet` est réservé aux acteurs institutionnels : un bénévole mobilisé
    n'y lit pas la demande qui le concerne, alors que c'est lui qui doit la montrer au bord de
    la route. Ici, rien que les siennes (`cible_utilisateur`), et rien que ce qu'il sait déjà :
    c'est le contenu de l'attestation qu'il a reçue.

    Le jeton est rendu : c'est ce que porte le QR code de son attestation. Le rendre à son
    titulaire ne donne rien de plus que le PDF — et le verdict d'un jeton ne révèle le nom et le
    lieu qu'à un compte connecté (`verdict_mobilisation`)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        demandes = DemandeMobilisation.objects.filter(
            cible_utilisateur=request.user, environment=get_active_environment(request),
            jeton_verification__isnull=False,
        ).select_related("crise", "institution_emettrice", "point_operationnel").order_by(
            "-date_creation")[:50]
        import base64

        from django.conf import settings

        from .attestation_mobilisation import generer_qr_image, url_verification

        def qr(demande):
            # La MÊME adresse et le MÊME dessin que sur l'attestation PDF : un QR code affiché
            # à l'écran doit se lire exactement comme celui du papier.
            adresse = url_verification(demande, settings.SERVER_URL)
            return adresse, base64.b64encode(generer_qr_image(adresse).getvalue()).decode("ascii")

        return Response([
            {
                **dict(zip(("adresse_verification", "qr_png"), qr(d))),
                "id": d.id,
                "crise_nom": d.crise.name,
                "institution_emettrice_nom": d.institution_emettrice.nom,
                "type_demande_libelle": d.get_type_demande_display(),
                "point_operationnel_nom": d.point_operationnel.nom if d.point_operationnel_id else None,
                "lieu_texte": d.lieu_texte,
                "statut": d.statut,
                "cible_utilisateur": request.user.id,
                "date_creation": d.date_creation,
                "jeton_verification": d.jeton_verification,
            }
            for d in demandes
        ])
