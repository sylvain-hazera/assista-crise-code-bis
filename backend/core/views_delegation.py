"""API de la délégation de gestion mairie → AASC, et export de réversibilité (21/11/2026).

Voir core/delegation_gestion.py pour les règles (qui agit, contexte délégué, export seul).

- `/api/delegations-gestion/` : liste (celles de mes institutions), création (convention signée
  hors plateforme, création de la mairie si elle n'existe pas), `retirer`, `inviter`
  (comptes de la mairie), `personnes` (qui agit pour l'AASC).
- `/api/institutions/<id>/export-donnees/` : archive ZIP de tout ce qui appartient à la
  collectivité. La mairie reste propriétaire de ses données : cet export lui reste ouvert même
  quand la convention est rompue (« elle ne peut plus qu'exporter ses données »).
"""
import io
import json
import zipfile

from django.apps import apps
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import audit_log
from .delegation_gestion import (
    agit_pour, crise_touche, est_en_vigueur, personnes_qui_agissent,
)
from .models import (
    Commune, ContactInstitution, Crisis, DelegationGestion, Institution, InstitutionType, User,
    UserRole,
)
from .permissions import get_active_environment, get_effective_role

CODES_COLLECTIVITE = {"mairie", "epci", "cg"}
CODE_AASC = "aasc"


def _code_type(institution):
    return ((institution.type.code if institution and institution.type_id else "") or "").lower()


def _membre(user, institution, bureau=False):
    q = ContactInstitution.objects.filter(utilisateur=user, institution=institution, actif=True)
    if bureau:
        q = q.filter(membre_bureau=True)
    return q.exists()


class DelegationGestionSerializer(serializers.ModelSerializer):
    collectivite_nom = serializers.CharField(source="collectivite.nom", read_only=True)
    aasc_nom = serializers.SerializerMethodField()
    en_vigueur = serializers.SerializerMethodField()
    a_un_document = serializers.SerializerMethodField()
    commune_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    departement_code = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = DelegationGestion
        fields = [
            "id", "collectivite", "collectivite_nom", "aasc", "aasc_nom", "communes", "statut",
            "en_vigueur", "convention_reference", "convention_signee_le", "convention_signataire",
            "convention_signataire_qualite", "date_fin", "convention_document", "a_un_document",
            "date_creation", "date_retrait", "motif_retrait", "commune_code", "departement_code",
        ]
        read_only_fields = ["statut", "date_creation", "date_retrait", "motif_retrait"]
        # La contrainte « une délégation active par couple » est tenue en base et rattrapée en
        # erreur lisible dans perform_create ; le validateur que DRF en déduirait rendrait
        # `collectivite` obligatoire alors qu'elle peut être créée à partir de la commune.
        validators = []
        extra_kwargs = {
            "collectivite": {"required": False},
            "aasc": {"required": False},
            "convention_document": {"write_only": True, "required": False},
        }

    def get_aasc_nom(self, obj):
        return obj.aasc.nom_affichage or obj.aasc.nom

    def get_en_vigueur(self, obj):
        return est_en_vigueur(obj)

    def get_a_un_document(self, obj):
        return bool(obj.convention_document)


def _mairie_de_la_commune(commune_code, aasc, request):
    """La mairie de la commune : celle qui existe (jamais un doublon), sinon créée depuis le
    référentiel par l'AASC, qui lui fournit alors l'accès (« si elle n'existe pas, la Réserve
    crée l'institution »). Jamais par simple saisie d'un nom (cf. le doublon du 21/11/2026)."""
    existante = (Institution.objects.filter(commune_code=commune_code, type__code__iexact="mairie")
                 .order_by("date_creation").first())
    if existante is not None:
        return existante, False
    commune = Commune.objects.filter(code=commune_code).first()
    if commune is None:
        raise ValidationError({"commune_code": "Commune inconnue du référentiel."})
    type_mairie = (InstitutionType.objects.filter(code__iexact="mairie").first()
                   or InstitutionType.objects.create(code="mairie", libelle="Mairie"))
    mairie = Institution.objects.create(
        nom=f"Mairie de {commune.nom}", type=type_mairie, commune_code=commune.code,
        commune_nom=commune.nom, acces_fourni_par=aasc,
    )
    audit_log(request=request, action_code="CREATION", objet_type="Institution", objet_id=mairie.id,
              commentaire=f"Mairie créée par {aasc.nom} pour la délégation de gestion")
    return mairie, True


def _conseil_departemental(departement_code, aasc, request):
    """Le conseil départemental : celui qui existe, sinon créé par l'AASC (« la Réserve signe
    par défaut avec le département »). Ancré sur la commune la plus peuplée du département,
    faute de chef-lieu au référentiel : seul son secteur (le département) compte."""
    from .geo_reference import DEPARTEMENTS

    existant = (Institution.objects.filter(departement_code=departement_code, type__code__iexact="cg")
                .order_by("date_creation").first())
    if existant is not None:
        return existant, False
    ancre = (Commune.objects.filter(departement_code=departement_code)
             .order_by("-population", "code").first())
    nom_dep = DEPARTEMENTS.get(departement_code)
    if ancre is None or not nom_dep:
        raise ValidationError({"departement_code": "Département inconnu du référentiel."})
    type_cg = (InstitutionType.objects.filter(code__iexact="cg").first()
               or InstitutionType.objects.create(code="cg", libelle="Conseil départemental"))
    cg = Institution.objects.create(
        nom=f"Conseil départemental — {nom_dep}", type=type_cg, commune_code=ancre.code,
        commune_nom=ancre.nom, departement_code=departement_code, secteur_override="departement",
        acces_fourni_par=aasc,
    )
    audit_log(request=request, action_code="CREATION", objet_type="Institution", objet_id=cg.id,
              commentaire=f"Conseil départemental créé par {aasc.nom} pour la délégation de gestion")
    return cg, True


class DelegationGestionViewSet(viewsets.ModelViewSet):
    serializer_class = DelegationGestionSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = DelegationGestion.objects.select_related("collectivite", "aasc").filter(
            environment=get_active_environment(self.request))
        if get_effective_role(self.request) == UserRole.ADMINISTRATOR:
            return qs
        mes = list(ContactInstitution.objects.filter(utilisateur=self.request.user, actif=True)
                   .values_list("institution_id", flat=True))
        return qs.filter(collectivite_id__in=mes) | qs.filter(aasc_id__in=mes)

    # -- qui peut faire quoi ---------------------------------------------------------------

    def _cote_aasc_autorise(self, aasc, collectivite, communes=None):
        """Bureau de l'AASC, ou cadre d'une de ses coordinations couvrant le territoire."""
        user = self.request.user
        if _membre(user, aasc, bureau=True):
            return True
        fictive = DelegationGestion(aasc=aasc, communes=communes or [], collectivite=collectivite,
                                    statut=DelegationGestion.Statut.ACTIVE)
        return agit_pour(user, fictive)

    def _cote_mairie_autorise(self, collectivite):
        return (get_effective_role(self.request) == UserRole.LOCAL_AUTHORITY
                and _membre(self.request.user, collectivite))

    def perform_create(self, serializer):
        from .habitations import _institution_couvre_commune

        d = serializer.validated_data
        request = self.request
        user = request.user
        aasc = d.get("aasc") or getattr(user, "institution", None)
        if aasc is None or _code_type(aasc) != CODE_AASC:
            raise ValidationError({"aasc": "Précisez l'association agréée de sécurité civile qui exploite la plateforme."})
        if not d.get("convention_signee_le"):
            raise ValidationError({"convention_signee_le": "Indiquez la date de signature de la convention."})

        commune_code = (d.pop("commune_code", "") or "").strip()
        departement_code = (d.pop("departement_code", "") or "").strip()
        collectivite = d.get("collectivite")
        cree = False
        if collectivite is None and not commune_code and not departement_code:
            raise ValidationError({"collectivite": "Choisissez la collectivité, le département ou la commune."})
        communes = [c for c in (d.get("communes") or []) if c]
        refus = ("Seuls le bureau de l'association et les cadres des coordinations qui couvrent ce "
                 "territoire peuvent l'engager.")

        if collectivite is None and departement_code:
            apercu = Institution(departement_code=departement_code, secteur_niveau_effectif="departement")
            if not self._cote_aasc_autorise(aasc, apercu):
                raise PermissionDenied(refus)
            with transaction.atomic():
                collectivite, cree = _conseil_departemental(departement_code, aasc, request)
        elif collectivite is None:
            apercu = Institution(commune_code=commune_code, secteur_niveau_effectif="commune")
            if not self._cote_aasc_autorise(aasc, apercu):
                raise PermissionDenied(refus)
            with transaction.atomic():
                collectivite, cree = _mairie_de_la_commune(commune_code, aasc, request)
        else:
            if _code_type(collectivite) not in CODES_COLLECTIVITE:
                raise ValidationError({"collectivite": "Seule une collectivité (mairie, intercommunalité, "
                                                       "département) délègue sa gestion."})
            if not (self._cote_aasc_autorise(aasc, collectivite, communes) or self._cote_mairie_autorise(collectivite)):
                raise PermissionDenied("Il faut être de la collectivité (autorité locale) ou agir pour "
                                       "l'association sur ce territoire.")

        hors = [c for c in communes if not _institution_couvre_commune(collectivite, c)]
        if hors:
            raise ValidationError({"communes": "Hors du territoire de la collectivité : " + ", ".join(hors)})

        # La collectivité reçoit l'accès de l'AASC si elle n'avait personne sur la plateforme :
        # rompre la convention lui laissera alors l'export seul.
        if not cree and collectivite.acces_fourni_par_id is None and not ContactInstitution.objects.filter(
                institution=collectivite, actif=True).exists():
            collectivite.acces_fourni_par = aasc
            collectivite.save(update_fields=["acces_fourni_par"])

        try:
            with transaction.atomic():
                delegation = serializer.save(collectivite=collectivite, aasc=aasc, creee_par=user,
                                             environment=get_active_environment(request))
        except IntegrityError:
            raise ValidationError({"collectivite": "Une délégation est déjà en vigueur entre ces deux institutions."})
        audit_log(request=request, action_code="CREATION", objet_type="DelegationGestion",
                  objet_id=delegation.id,
                  commentaire=(f"Délégation de gestion {collectivite.nom} → {aasc.nom}, convention "
                               f"{delegation.convention_reference or 'sans référence'} signée le "
                               f"{delegation.convention_signee_le}"))

    def perform_update(self, serializer):
        delegation = serializer.instance
        if not self._cote_aasc_autorise(delegation.aasc, delegation.collectivite, delegation.communes):
            raise PermissionDenied("Seuls ceux qui agissent pour l'association mettent la convention à jour.")
        for interdit in ("collectivite", "aasc"):
            serializer.validated_data.pop(interdit, None)
        serializer.validated_data.pop("commune_code", None)
        serializer.validated_data.pop("departement_code", None)
        serializer.save()
        audit_log(request=self.request, action_code="MODIFICATION", objet_type="DelegationGestion",
                  objet_id=delegation.id, commentaire="Convention de délégation mise à jour")

    # -- actions ---------------------------------------------------------------------------

    @action(detail=True, methods=["post"])
    def retirer(self, request, pk=None):
        """La collectivité (ou le bureau de l'AASC) met fin à la délégation. Pendant une crise
        ouverte sur le territoire, rien n'est bloqué d'office (« on traite au cas par cas, dans
        l'intérêt de la population ») : il faut confirmer (`forcer`) et motiver, c'est journalisé."""
        delegation = self.get_object()
        if delegation.statut != DelegationGestion.Statut.ACTIVE:
            return Response({"error": "Cette délégation n'est plus active."}, status=status.HTTP_400_BAD_REQUEST)
        if not (self._cote_mairie_autorise(delegation.collectivite)
                or _membre(request.user, delegation.aasc, bureau=True)
                or get_effective_role(request) == UserRole.ADMINISTRATOR):
            raise PermissionDenied("Seuls la collectivité ou le bureau de l'association mettent fin à la délégation.")
        ouvertes = [c.name for c in Crisis.objects.filter(end_date__isnull=True) if crise_touche(delegation, c)]
        motif = (request.data.get("motif") or "").strip()
        forcer = str(request.data.get("forcer", "")).lower() in ("true", "1", "oui")
        if ouvertes and not (forcer and motif):
            return Response({
                "error": ("Une crise est ouverte sur ce territoire (" + ", ".join(ouvertes) + "). Le retrait "
                          "couperait la gestion en cours : confirmez-le explicitement et indiquez le motif."),
                "crises_ouvertes": ouvertes, "confirmation_requise": True,
            }, status=status.HTTP_400_BAD_REQUEST)
        delegation.statut = DelegationGestion.Statut.RETIREE
        delegation.date_retrait = timezone.now()
        delegation.retiree_par = request.user
        delegation.motif_retrait = motif
        delegation.save(update_fields=["statut", "date_retrait", "retiree_par", "motif_retrait"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="DelegationGestion",
                  objet_id=delegation.id,
                  commentaire=(f"Délégation de gestion retirée ({delegation.collectivite.nom})"
                               + (f" malgré la crise ouverte : {', '.join(ouvertes)}" if ouvertes else "")))
        return Response(self.get_serializer(delegation).data)

    @action(detail=True, methods=["get"])
    def personnes(self, request, pk=None):
        delegation = self.get_object()
        bureau = set(ContactInstitution.objects.filter(institution=delegation.aasc, membre_bureau=True, actif=True)
                     .values_list("utilisateur_id", flat=True))
        return Response([
            {"id": str(u.id), "nom": f"{u.first_name} {u.last_name}".strip() or u.username,
             "titre": "Bureau de l'association" if u.id in bureau else "Encadrement d'une coordination"}
            for u in personnes_qui_agissent(delegation)
        ])

    @action(detail=True, methods=["get"])
    def repertoires(self, request, pk=None):
        """Délégation départementale : les répertoires des intercommunalités du département
        (« chaque division départementale a la vue sur le département, en incluant les
        répertoires des EPCI »). Lecture seule, réservée à ceux qui agissent, journalisée."""
        from .models import InterlocuteurAlertePCS

        delegation = self.get_object()
        if not agit_pour(request.user, delegation) and get_effective_role(request) != UserRole.ADMINISTRATOR:
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        dep = delegation.collectivite.departement_code
        if (delegation.collectivite.secteur_niveau_effectif or "") != "departement" or not dep:
            return Response([])
        epcis = Institution.objects.filter(type__code__iexact="epci", departement_code=dep, actif=True).order_by("nom")
        resultat = []
        for e in epcis:
            contacts = (ContactInstitution.objects.filter(institution=e, actif=True)
                        .select_related("utilisateur"))
            annuaire = InterlocuteurAlertePCS.objects.filter(institutions=e)
            resultat.append({
                "id": str(e.id), "nom": e.nom,
                "contacts": [{"nom": f"{c.utilisateur.first_name} {c.utilisateur.last_name}".strip(),
                              "fonction": c.fonction, "email": c.utilisateur.email,
                              "telephone": c.utilisateur.phone_number} for c in contacts],
                "annuaire": [{"nom": i.nom, "organisme": i.organisme, "categorie": i.categorie,
                              "email": i.email, "telephone": i.telephone} for i in annuaire],
            })
        audit_log(request=request, action_code="LECTURE",
                  objet_type="DelegationGestion", objet_id=delegation.id,
                  commentaire=f"Consultation des répertoires des EPCI du département {dep} ({len(resultat)} EPCI)")
        return Response(resultat)

    @action(detail=True, methods=["post"])
    def inviter(self, request, pk=None):
        """Invite les personnes de la mairie à ouvrir leur compte (autorité locale, rattaché à la
        collectivité) pour compléter et vérifier ce que l'AASC a saisi, et garder la main."""
        from .branding import branding_for_institution, send_branded_mail
        from .crypto_fields import blind_index
        from .institution_attachment import _get_or_create_contact_institution, grant_institution_and_demo_access
        from .views import build_magic_link

        delegation = self.get_object()
        if not agit_pour(request.user, delegation):
            raise PermissionDenied("Seuls ceux qui agissent pour l'association invitent la mairie.")
        emails = [e.strip().lower() for e in (request.data.get("emails") or []) if e and "@" in e]
        if not emails:
            return Response({"error": "Indiquez au moins une adresse."}, status=status.HTTP_400_BAD_REQUEST)
        fonction = (request.data.get("fonction") or "Mairie").strip()[:120]
        mairie, aasc = delegation.collectivite, delegation.aasc
        nom_aasc = branding_for_institution(aasc).nom_affichage
        invites = []
        for email in emails:
            user = User.objects.filter(email_bidx=blind_index(email)).first()
            nouveau = user is None
            if nouveau:
                user = User.objects.create_user(username=email, email=email, password=None,
                                                type=UserRole.LOCAL_AUTHORITY, institution=mairie,
                                                enabled=False, is_active=False)
            _get_or_create_contact_institution(mairie, user, fonction)
            grant_institution_and_demo_access(user, mairie, request)
            lien = build_magic_link(request, user, "activate-account" if nouveau else "magic-login")
            message = (
                "Bonjour,\n\n"
                f"{nom_aasc} exploite pour {mairie.nom} la plateforme de gestion de crise, dans le "
                "cadre de la convention signée avec votre collectivité. Votre espace est prêt : "
                "nous vous invitons à vous y connecter pour vérifier ce qui a été saisi et compléter "
                "les coordonnées de vos cadres et responsables.\n\n"
                f"- {'Activer votre compte' if nouveau else 'Vous connecter'} : {lien}\n\n"
                "Ce lien est valable 7 jours. Vos données restent celles de votre collectivité : "
                "vous pouvez à tout moment les exporter.\n\n{signature}"
            )
            send_branded_mail(request, aasc, subject=f"Votre espace {mairie.nom} est prêt",
                              message=message, recipient_list=[email], fail_silently=True)
            invites.append(email)
        audit_log(request=request, action_code="CREATION", objet_type="DelegationGestion",
                  objet_id=delegation.id, commentaire=f"{len(invites)} invitation(s) envoyée(s) à {mairie.nom}")
        return Response({"invites": len(invites)})


# -- Export de réversibilité ---------------------------------------------------------------

def _valeur(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "geojson"):
        return json.loads(v.geojson)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "name") and hasattr(v, "storage"):  # fichier : le nom seulement
        return v.name or None
    if isinstance(v, (list, dict)):
        return v
    return str(v)


def _ligne(objet):
    ligne = {}
    for champ in objet._meta.concrete_fields:
        if champ.name in ("environment",) or champ.name.endswith("_bidx") or "token" in champ.name:
            continue
        ligne[champ.name] = _valeur(getattr(objet, champ.attname if champ.is_relation else champ.name))
    return ligne


def modeles_de_la_collectivite():
    """Les modèles qui appartiennent à une institution par un champ `institution` (ou
    `collectivite`) : plan, zones, risques, équipes, annuaire, main courante… Calculé, pour qu'un
    modèle ajouté demain soit exporté sans qu'on pense à l'ajouter ici. Le registre des
    personnes vulnérables n'en fait pas partie (champ `institution_declarante`) : il a sa propre
    procédure, réservée aux personnes habilitées."""
    for modele in apps.get_app_config("core").get_models():
        for nom in ("institution", "collectivite"):
            try:
                champ = modele._meta.get_field(nom)
            except Exception:
                continue
            if getattr(champ, "related_model", None) is Institution and not champ.many_to_many:
                yield modele, nom
                break


class ExportDonneesInstitutionView(APIView):
    """GET : archive ZIP (un JSON par type d'objet) de tout ce qui appartient à la collectivité.

    Ouvert à ses membres — même en mode export seul, c'est précisément ce qui leur reste — et à
    ceux qui agissent pour elle par délégation. Journalisé."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        from .delegation_gestion import est_delegue

        institution = Institution.objects.filter(pk=pk).first()
        if institution is None:
            return Response({"error": "Institution inconnue."}, status=status.HTTP_404_NOT_FOUND)
        if not (_membre(request.user, institution) or est_delegue(request.user, institution)):
            raise PermissionDenied("Seuls les membres de la collectivité exportent ses données.")
        tampon = io.BytesIO()
        compte = {}
        with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("institution.json", json.dumps(_ligne(institution), ensure_ascii=False, indent=1))
            for modele, champ in modeles_de_la_collectivite():
                lignes = [_ligne(o) for o in modele.objects.filter(**{champ: institution}).iterator()]
                if lignes:
                    nom = modele.__name__
                    compte[nom] = len(lignes)
                    archive.writestr(f"{nom}.json", json.dumps(lignes, ensure_ascii=False, indent=1))
            archive.writestr("LISEZMOI.txt", (
                f"Export des données de {institution.nom}, le {timezone.now():%d/%m/%Y %H:%M}.\n"
                "Un fichier JSON par type d'objet ; les identifiants relient les fichiers entre eux.\n"
                "Ces données appartiennent à la collectivité.\n\n"
                + "\n".join(f"- {n} : {c}" for n, c in sorted(compte.items()))
            ))
        audit_log(request=request, action_code="EXPORT",
                  objet_type="Institution", objet_id=institution.id,
                  commentaire=f"Export de toutes les données de {institution.nom}")
        reponse = HttpResponse(tampon.getvalue(), content_type="application/zip")
        reponse["Content-Disposition"] = f'attachment; filename="donnees-{institution.pk}.zip"'
        return reponse

