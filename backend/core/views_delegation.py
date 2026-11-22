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
import uuid
import zipfile

from django.apps import apps
from django.db import IntegrityError, transaction
from django.db.models import Q
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


def _dans_le_departement(inst, dep) -> bool:
    """Mairie ou intercommunalité du département délégué."""
    code = inst.commune_code or ""
    departement = inst.departement_code or (code[:3] if code[:2] in ("97", "98") else code[:2])
    return _code_type(inst) in ("mairie", "epci") and bool(dep) and departement == dep


def _cellule(valeur) -> str:
    """Une cellule de tableur sans formule déguisée (=, +, -, @ en tête)."""
    texte = "" if valeur is None else str(valeur)
    return "'" + texte if texte[:1] in ("=", "+", "-", "@") else texte


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
    departementale = serializers.SerializerMethodField()
    commune_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    departement_code = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = DelegationGestion
        fields = [
            "id", "collectivite", "collectivite_nom", "aasc", "aasc_nom", "communes", "statut",
            "en_vigueur", "convention_reference", "convention_signee_le", "convention_signataire",
            "convention_signataire_qualite", "date_fin", "convention_document", "a_un_document",
            "date_creation", "date_retrait", "motif_retrait", "commune_code", "departement_code", "departementale",
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

    def get_departementale(self, obj):
        """Convention avec un conseil départemental : son suivi a sa page (communes, invitations,
        amorçage, historique)."""
        return (obj.collectivite.secteur_niveau_effectif or "") == "departement"

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


def _aasc_du_contexte(request):
    """L'AASC pour laquelle on engage, quand l'écran ne la précise pas (22/11/2026 : un
    administrateur qui regardait la Réserve par le sélecteur du haut se voyait répondre
    « précisez l'association », son institution courante n'étant pas elle). Dans l'ordre :
    l'institution regardée par l'administrateur, l'institution courante, sinon la seule AASC
    dont on est membre."""
    from .perimetre_admin import institution_regardee

    for candidate in (institution_regardee(request), getattr(request.user, "institution", None)):
        if candidate is not None and _code_type(candidate) == CODE_AASC:
            return candidate
    mes_aasc = list(Institution.objects.filter(
        contacts__utilisateur=request.user, contacts__actif=True, type__code__iexact=CODE_AASC).distinct()[:2])
    return mes_aasc[0] if len(mes_aasc) == 1 else None


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
        """Bureau de l'AASC, ou cadre d'une de ses coordinations couvrant le territoire (ou
        l'administrateur de la plateforme)."""
        user = self.request.user
        if get_effective_role(self.request) == UserRole.ADMINISTRATOR or _membre(user, aasc, bureau=True):
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
        aasc = d.get("aasc") or _aasc_du_contexte(request)
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
        # Délégation départementale : l'amorçage part aussitôt (« ça devrait lancer l'amorçage
        # aussitôt », 21/11/2026) — répertoires, adresses, risques, sites sensibles.
        if (collectivite.secteur_niveau_effectif or "") == "departement" and collectivite.departement_code:
            self._lancer_amorcage(delegation, None)

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
    def amorcer(self, request, pk=None):
        """Délégation départementale : lance l'amorçage du département (répertoires officiels,
        adresses, risques, sites sensibles), toutes les étapes ou celles demandées."""
        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        cg = delegation.collectivite
        if (cg.secteur_niveau_effectif or "") != "departement" or not cg.departement_code:
            return Response({"error": "L'amorçage concerne une délégation départementale."},
                            status=status.HTTP_400_BAD_REQUEST)
        from .amorcage_departement import est_interrompu
        en_cours = next((a for a in delegation.amorcages.filter(fin__isnull=True) if not est_interrompu(a)), None)
        if en_cours is not None:
            return Response({"error": "Un amorçage est déjà en cours pour ce département."},
                            status=status.HTTP_409_CONFLICT)
        amorcage = self._lancer_amorcage(delegation, request.data.get("etapes"))
        return Response(self._etat_amorcage(amorcage), status=status.HTTP_202_ACCEPTED)

    def _lancer_amorcage(self, delegation, etapes):
        from .amorcage_departement import ETAPES
        from .models import AmorcageDepartement
        from .tasks import amorcer_departement_task

        etapes = [e for e in (etapes or ETAPES) if e in ETAPES] or list(ETAPES)
        amorcage = AmorcageDepartement.objects.create(
            delegation=delegation, lance_par=self.request.user, environment=delegation.environment,
            etapes={e: {"statut": "EN_ATTENTE"} for e in etapes})
        transaction.on_commit(lambda: amorcer_departement_task.delay(str(amorcage.id), etapes))
        audit_log(request=self.request, action_code="IMPORT_LISTE", objet_type="DelegationGestion",
                  objet_id=delegation.id,
                  commentaire=(f"Amorçage du département {delegation.collectivite.departement_code} "
                               f"lancé ({', '.join(etapes)})"))
        return amorcage

    @action(detail=True, methods=["post"], url_path="inviter-collectivites")
    def inviter_collectivites(self, request, pk=None):
        """Invite les mairies et intercommunalités choisies dans l'arborescence à rejoindre la
        plateforme (« Rejoindre votre collectivité »). Seulement dans le territoire délégué."""
        from .delegation_gestion import zones_de
        from .invitation_collectivite import inviter

        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        dep = next((code for niveau, code in zones_de(delegation) if niveau == "departement"), None)
        ids = [i for i in (request.data.get("institutions") or []) if i][:1000]
        cibles = Institution.objects.filter(id__in=ids, actif=True)
        resultat = {"envoyees": 0, "sans_email": [], "deja_membres": 0, "hors_territoire": 0}
        for inst in cibles:
            if not _dans_le_departement(inst, dep):
                resultat["hors_territoire"] += 1
                continue
            etat = inviter(inst, delegation, request)
            if etat == "envoyee":
                resultat["envoyees"] += 1
            elif etat == "sans_email":
                resultat["sans_email"].append(inst.nom)
            else:
                resultat["deja_membres"] += 1
        audit_log(request=request, action_code="ENVOI_MASSE", objet_type="DelegationGestion", objet_id=delegation.id,
                  commentaire=(f"Invitations « Rejoindre votre collectivité » : {resultat['envoyees']} envoyée(s), "
                               f"{len(resultat['sans_email'])} sans adresse officielle"))
        return Response(resultat)

    def _cibles_du_departement(self, request, delegation, limite=2000):
        from .delegation_gestion import zones_de
        dep = next((code for niveau, code in zones_de(delegation) if niveau == "departement"), None)
        ids = [str(i) for i in (request.data.get("institutions") or []) if i][:limite]
        rang = {ident: n for n, ident in enumerate(ids)}
        cibles = [i for i in Institution.objects.filter(id__in=ids, actif=True).select_related("type")
                  if _dans_le_departement(i, dep)]
        return sorted(cibles, key=lambda i: rang.get(str(i.id), 0))  # l'ordre de la sélection

    @action(detail=True, methods=["post"], url_path="preparer-invitation")
    def preparer_invitation(self, request, pk=None):
        """Ce que la fenêtre « Préparer l'invitation » affiche (22/11/2026) : où ira chaque
        courriel (référent, adresse officielle, aucune adresse), le texte proposé à champs, et
        les connecteurs d'envoi utilisables avec leur adresse."""
        from . import invitation_collectivite as ic
        from .envoi_connecteurs import connecteurs_pour

        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        cibles = self._cibles_du_departement(request, delegation)
        resume = {"vers_referent": 0, "vers_officielle": 0, "sans_adresse": [], "deja_membres": 0}
        pretes = []
        for inst in cibles:
            p = ic.preparer(inst)
            if p["etat"] == "deja_membre":
                resume["deja_membres"] += 1
            elif p["etat"] == "sans_email":
                resume["sans_adresse"].append(inst.nom)
            else:
                resume["vers_referent" if p["vers_referent"] else "vers_officielle"] += 1
                pretes.append({"id": str(inst.id), "nom": inst.nom})
        sujet, corps = ic.modele(delegation.aasc)
        return Response({"resume": resume, "pretes": pretes, "sujet": sujet, "corps": corps, "champs": list(ic.CHAMPS),
                         "connecteurs": connecteurs_pour([delegation.aasc, delegation.collectivite])})

    @action(detail=True, methods=["post"], url_path="campagne-invitation")
    def campagne_invitation(self, request, pk=None):
        """Avec `apercu` (une collectivité) : le courriel tel qu'elle le recevra, lien masqué,
        rien n'est envoyé ni créé. Sans : crée la campagne et la lance en tâche de fond (file
        des travaux lourds), par le connecteur choisi."""
        from . import invitation_collectivite as ic
        from .envoi_connecteurs import connecteurs_pour, libelle
        from .models import CampagneInvitation
        from .tasks import envoyer_campagne_invitation_task

        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        sujet = (request.data.get("sujet") or "").strip()
        corps = (request.data.get("corps") or "").strip()
        if not sujet or not corps:
            return Response({"error": "L'objet et le texte sont obligatoires."}, status=status.HTTP_400_BAD_REQUEST)
        if "[LIEN]" not in corps:
            return Response({"error": "Le texte doit contenir [LIEN] : c'est le lien qui permet à la collectivité de "
                                      "créer ses comptes."}, status=status.HTTP_400_BAD_REQUEST)
        permises = [delegation.aasc, delegation.collectivite]
        cle = request.data.get("connecteur") or ""
        if cle not in {c["cle"] for c in connecteurs_pour(permises)}:
            return Response({"error": "Connecteur d'envoi inconnu ou indisponible."}, status=status.HTTP_400_BAD_REQUEST)

        apercu = request.data.get("apercu")
        if apercu:
            inst = Institution.objects.filter(pk=apercu, actif=True).first()
            if inst is None:
                return Response({"error": "Collectivité introuvable."}, status=status.HTTP_400_BAD_REQUEST)
            p = ic.preparer(inst)
            if p["etat"] != "prete":
                return Response({"etat": p["etat"]})
            champs = ic.valeurs(inst, delegation, p, ic.LIEN_MASQUE)
            return Response({"etat": "prete", "destinataire": p["destinataire"], "vers_referent": p["vers_referent"],
                             "sujet": ic.rendre(sujet, champs), "corps": ic.rendre(corps, champs)})

        cibles = self._cibles_du_departement(request, delegation)
        if not cibles:
            return Response({"error": "Aucune collectivité du territoire dans la sélection."}, status=status.HTTP_400_BAD_REQUEST)
        campagne = CampagneInvitation.objects.create(
            delegation=delegation, connecteur=cle, connecteur_libelle=libelle(cle, permises)[:255], sujet=sujet,
            corps=corps, cree_par=request.user, prevues=len(cibles), environment=get_active_environment(request))
        ids = [str(i.id) for i in cibles]
        transaction.on_commit(lambda: envoyer_campagne_invitation_task.delay(str(campagne.id), ids))
        audit_log(request=request, action_code="ENVOI_MASSE", objet_type="DelegationGestion", objet_id=delegation.id,
                  commentaire=f"Campagne « Rejoindre votre collectivité » lancée : {len(cibles)} collectivité(s), "
                              f"par {campagne.connecteur_libelle}")
        return Response(self._etat_campagne(campagne), status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _etat_campagne(c):
        return {"id": str(c.id), "date": c.date_creation, "date_fin": c.date_fin, "statut": c.statut,
                "connecteur": c.connecteur_libelle, "prevues": c.prevues, "envoyees": c.envoyees, "echecs": c.echecs,
                "sans_adresse": c.sans_adresse, "deja_membres": c.deja_membres, "erreurs": c.erreurs or []}

    @action(detail=True, methods=["get"])
    def campagnes(self, request, pk=None):
        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        return Response([self._etat_campagne(c) for c in delegation.campagnes_invitation.all()[:20]])

    @action(detail=True, methods=["post"], url_path="export-coordonnees")
    def export_coordonnees(self, request, pk=None):
        """Les coordonnées des collectivités cochées, en tableur (CSV, point-virgule, lisible par
        Excel) : pour une campagne de contact hors plateforme (publipostage, téléphone). Officiel
        et référent ; journalisé, puisqu'il sort des coordonnées de personnes."""
        import csv
        from .delegation_gestion import zones_de
        from .models import Commune, ContactInstitution, InvitationCollectivite, ReferentCollectivite

        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        dep = next((code for niveau, code in zones_de(delegation) if niveau == "departement"), None)
        ids = [i for i in (request.data.get("institutions") or []) if i][:2000]
        cibles = [i for i in Institution.objects.filter(id__in=ids, actif=True).select_related("type")
                  if _dans_le_departement(i, dep)]
        cibles.sort(key=lambda i: (_code_type(i) != "epci", i.commune_code or "", i.nom))
        noms_communes = dict(Commune.objects.filter(departement_code=dep).values_list("code", "nom")) if dep else {}
        epci_par_commune = dict(Commune.objects.filter(departement_code=dep).values_list("code", "epci_code")) if dep else {}
        noms_epci = {e.epci_code: e.nom for e in Institution.objects.filter(type__code__iexact="epci",
                                                                             epci_code__in=set(epci_par_commune.values()))}
        referents = {r.institution_id: r for r in ReferentCollectivite.objects.filter(institution__in=cibles)}
        comptes = {}
        for inst_id in ContactInstitution.objects.filter(institution__in=cibles, actif=True).values_list("institution_id", flat=True):
            comptes[inst_id] = comptes.get(inst_id, 0) + 1
        invitees = {}
        for inv in InvitationCollectivite.objects.filter(institution__in=cibles).order_by("date_envoi"):
            invitees[inv.institution_id] = inv.date_relance or inv.date_envoi

        tampon = io.StringIO()
        ecrire = csv.writer(tampon, delimiter=";")
        ecrire.writerow(["Collectivité", "Type", "Code commune", "Commune", "Intercommunalité", "Courriel officiel",
                         "Téléphone officiel", "Adresse", "Personne référente", "Fonction", "Courriel du référent",
                         "Téléphone du référent", "Comptes sur la plateforme", "Invitée le"])
        for inst in cibles:
            r = referents.get(inst.id)
            commune = inst.commune_code or ""
            ecrire.writerow([_cellule(v) for v in (
                inst.nom, "Intercommunalité" if _code_type(inst) == "epci" else "Mairie", commune,
                noms_communes.get(commune, ""),
                "" if _code_type(inst) == "epci" else noms_epci.get(epci_par_commune.get(commune), ""),
                inst.email, inst.telephone, inst.adresse,
                r.nom if r else "", r.fonction if r else "", r.email if r else "", r.telephone if r else "",
                comptes.get(inst.id, 0),
                timezone.localtime(invitees[inst.id]).strftime("%d/%m/%Y") if inst.id in invitees else "")])
        audit_log(request=request, action_code="EXPORT", objet_type="DelegationGestion", objet_id=delegation.id,
                  commentaire=f"Export des coordonnées de {len(cibles)} collectivité(s) (délégation de gestion)")
        reponse = HttpResponse("\ufeff" + tampon.getvalue(), content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = f'attachment; filename="coordonnees-collectivites-{dep or "territoire"}.csv"'
        return reponse

    @action(detail=True, methods=["post"])
    def coordonnees(self, request, pk=None):
        """Corrige les coordonnées d'une collectivité du territoire délégué, et indique la
        personne à joindre (« tel salarié ciblé, dont le conseil départemental donnerait
        l'adresse »). Référent vide : il est retiré, l'invitation repart à l'adresse officielle."""
        from .delegation_gestion import zones_de
        from .models import ReferentCollectivite

        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        inst = Institution.objects.filter(pk=request.data.get("institution"), actif=True).first()
        dep = next((code for niveau, code in zones_de(delegation) if niveau == "departement"), None)
        departement = (inst.departement_code or (inst.commune_code or "")[:2]) if inst else None
        if inst is None or _code_type(inst) not in ("mairie", "epci") or not dep or departement != dep:
            return Response({"error": "Collectivité hors du territoire délégué."}, status=status.HTTP_400_BAD_REQUEST)

        officiel = request.data.get("officiel") or {}
        modifies = []
        for champ in ("email", "telephone", "adresse"):
            if champ in officiel:
                setattr(inst, champ, (officiel.get(champ) or "").strip() or None)
                modifies.append(champ)
        if modifies:
            inst.save(update_fields=modifies)

        r = request.data.get("referent")
        if r is not None:
            nom, email = (r.get("nom") or "").strip(), (r.get("email") or "").strip().lower()
            if email and "@" not in email:
                return Response({"error": "Adresse du référent invalide."}, status=status.HTTP_400_BAD_REQUEST)
            if not nom and not email and not (r.get("telephone") or "").strip():
                ReferentCollectivite.objects.filter(institution=inst).delete()
            else:
                ReferentCollectivite.objects.update_or_create(institution=inst, defaults={
                    "nom": nom[:200], "fonction": (r.get("fonction") or "").strip()[:120], "email": email or None,
                    "telephone": (r.get("telephone") or "").strip()[:40] or None, "indique_par": request.user,
                    "environment": inst.environment})
        # Les copies de ces coordonnées dans les répertoires des autres collectivités suivent.
        from .repertoires_departement import resynchroniser
        resynchroniser(inst)
        audit_log(request=request, action_code="MODIFICATION", objet_type="Institution", objet_id=inst.id,
                  commentaire=f"Coordonnées de {inst.nom} mises à jour (délégation de gestion)")
        return Response({"ok": True})

    @action(detail=True, methods=["get"])
    def historique(self, request, pk=None):
        """Ce qui s'est passé sur la délégation, du plus récent au plus ancien : main courante de
        la délégation (amorçages, invitations, exports) et des collectivités de son territoire
        (coordonnées corrigées), puis les amorçages et les invitations envoyées (22/11/2026)."""
        from .delegation_gestion import zones_de
        from .models import AmorcageDepartement, AuditLog, InvitationCollectivite

        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
            raise PermissionDenied("Réservé à ceux qui agissent pour l'association sur ce territoire.")
        dep = next((code for niveau, code in zones_de(delegation) if niveau == "departement"), None)
        territoire = [i.id for i in Institution.objects.filter(actif=True).only("id", "commune_code", "departement_code", "type")
                      .select_related("type") if _dans_le_departement(i, dep)] if dep else [delegation.collectivite_id]
        evenements = []
        lignes = (AuditLog.objects.select_related("action", "utilisateur")
                  .filter(Q(objet_type="DelegationGestion", objet_id=delegation.id)
                          | Q(objet_type="Institution", objet_id__in=territoire, date_action__gte=delegation.date_creation))
                  .order_by("-date_action")[:300])
        for l in lignes:
            u = l.utilisateur
            evenements.append({"date": l.date_action, "type": "journal",
                               "action": l.action.libelle if l.action_id else "",
                               "par": (f"{u.first_name} {u.last_name}".strip() or u.username) if u else "",
                               "texte": l.commentaire or ""})
        for a in AmorcageDepartement.objects.filter(delegation=delegation).order_by("-debut")[:20]:
            evenements.append({"date": a.debut, "type": "amorcage", "action": "Amorçage", "par": "",
                               "texte": "Terminé le " + timezone.localtime(a.fin).strftime("%d/%m/%Y %H:%M") if a.fin
                               else "En cours"})
        for c in delegation.campagnes_invitation.all()[:50]:
            evenements.append({"date": c.date_creation, "type": "campagne", "action": "Campagne d'invitation",
                               "par": (f"{c.cree_par.first_name} {c.cree_par.last_name}".strip() or c.cree_par.username)
                               if c.cree_par else "",
                               "texte": (f"{c.connecteur_libelle} : {c.envoyees}/{c.prevues} envoyée(s), {c.echecs} échec(s), "
                                         f"{c.sans_adresse} sans adresse, {c.deja_membres} déjà présente(s)"
                                         + (" — en cours" if c.statut == c.Statut.EN_COURS else ""))})
        noms = dict(Institution.objects.filter(id__in=territoire).values_list("id", "nom"))
        for inv in InvitationCollectivite.objects.filter(delegation=delegation).order_by("-date_envoi")[:500]:
            evenements.append({"date": inv.date_relance or inv.date_envoi, "type": "invitation",
                               "action": "Relance" if inv.date_relance else "Invitation",
                               "par": "", "texte": f"{noms.get(inv.institution_id, 'Collectivité')} — "
                                                  f"{inv.comptes_crees} compte(s) créé(s)"})
        evenements.sort(key=lambda e: e["date"], reverse=True)
        return Response(evenements[:500])

    @action(detail=True, methods=["get"])
    def suivi(self, request, pk=None):
        """Suivi départemental. Sans paramètre : chaque intercommunalité avec ses comptes
        d'enrôlement. `?epci=<code>` : ses communes, l'enrôlement et l'avancement du PCS de
        chacune, et le PICS de l'intercommunalité (calculé à la demande, branche par branche)."""
        from .suivi_departement import avancement, enrolement

        reponse = self.arborescence(request, pk)
        arbre = reponse.data
        if not arbre:
            return reponse
        code = request.query_params.get("epci")
        if code is None:
            branches = []
            for b in arbre["epcis"]:
                etats = [enrolement(c["mairie"]) for c in b["communes"]]
                branches.append({
                    "code": b["code"], "nom": b["nom"], "institution": b["institution"],
                    "enrolement": enrolement(b["institution"]) if b["code"] else None,
                    "communes": len(etats), "ont_rejoint": etats.count("a_rejoint"),
                    "invitees": etats.count("invitee"), "sans_adresse": etats.count("pas_d_adresse"),
                })
            tous = [enrolement(c["mairie"]) for b in arbre["epcis"] for c in b["communes"]]
            return Response({"departement": arbre["departement"], "epcis": branches, "totaux": {
                **arbre["totaux"], "ont_rejoint": tous.count("a_rejoint"), "invitees": tous.count("invitee"),
                "sans_adresse": tous.count("pas_d_adresse")}})

        branche = next((b for b in arbre["epcis"] if b["code"] == code), None)
        if branche is None:
            return Response({"error": "Intercommunalité inconnue dans ce département."}, status=status.HTTP_404_NOT_FOUND)
        env = self.get_object().environment
        par_id = {i.id: i for i in Institution.objects.filter(
            id__in=[c["mairie"]["id"] for c in branche["communes"] if c["mairie"]]
            + ([branche["institution"]["id"]] if branche["institution"] else []))}
        communes = []
        for c in branche["communes"]:
            m = c["mairie"]
            inst = par_id.get(uuid.UUID(m["id"])) if m else None
            communes.append({**c, "enrolement": enrolement(m), "pcs": avancement(inst, env) if inst else None})
        epci = branche["institution"]
        epci_inst = par_id.get(uuid.UUID(epci["id"])) if epci else None
        return Response({
            "code": branche["code"], "nom": branche["nom"], "institution": epci,
            "enrolement": enrolement(epci) if epci else None,
            "pics": avancement(epci_inst, env) if epci_inst else None,
            "communes": communes,
        })

    @action(detail=True, methods=["get"])
    def arborescence(self, request, pk=None):
        """Le département, ses intercommunalités et leurs communes, avec pour chacune sa mairie
        (ses coordonnées officielles, ses membres sur la plateforme, une délégation communale
        éventuelle). Construit depuis le référentiel des communes : l'arbre est complet avant
        même l'amorçage, qui le remplit ensuite de coordonnées."""
        from .delegation_gestion import est_en_vigueur
        from .geo_reference import DEPARTEMENTS

        delegation = self.get_object()
        if not agit_pour(request.user, delegation) and get_effective_role(request) != UserRole.ADMINISTRATOR \
                and not _membre(request.user, delegation.collectivite):
            raise PermissionDenied("Réservé à ceux qui agissent pour ce territoire.")
        cg = delegation.collectivite
        dep = cg.departement_code
        if (cg.secteur_niveau_effectif or "") != "departement" or not dep:
            return Response(None)

        communes = list(Commune.objects.filter(departement_code=dep).order_by("nom")
                        .values("code", "nom", "population", "epci_code"))
        codes = [c["code"] for c in communes]
        mairies = {}
        for m in Institution.objects.filter(commune_code__in=codes, type__code__iexact="mairie").order_by("date_creation"):
            mairies.setdefault(m.commune_code, m)
        epci_codes = sorted({c["epci_code"] for c in communes if c["epci_code"]})
        epcis = {e.epci_code: e for e in Institution.objects.filter(type__code__iexact="epci", epci_code__in=epci_codes)}
        ids = [i.id for i in list(mairies.values()) + list(epcis.values())]
        membres = {}
        for inst_id in ContactInstitution.objects.filter(institution_id__in=ids, actif=True).values_list("institution_id", flat=True):
            membres[inst_id] = membres.get(inst_id, 0) + 1
        deleguees = {d.collectivite_id for d in DelegationGestion.objects.filter(collectivite_id__in=ids) if est_en_vigueur(d)}
        from .models import InvitationCollectivite, ReferentCollectivite
        referents = {r.institution_id: r for r in ReferentCollectivite.objects.filter(institution_id__in=ids)}
        invitees = {}
        for inv in InvitationCollectivite.objects.filter(institution_id__in=ids, actif=True).order_by("date_envoi"):
            invitees[inv.institution_id] = inv.date_relance or inv.date_envoi

        def fiche(inst):
            if inst is None:
                return None
            return {"id": str(inst.id), "nom": inst.nom, "email": inst.email, "telephone": inst.telephone,
                    "adresse": inst.adresse, "membres": membres.get(inst.id, 0), "delegation": inst.id in deleguees,
                    "invitee_le": invitees.get(inst.id),
                    "referent": ({"nom": r.nom, "fonction": r.fonction, "email": r.email, "telephone": r.telephone}
                                 if (r := referents.get(inst.id)) else None)}

        par_epci = {}
        for c in communes:
            par_epci.setdefault(c["epci_code"] or "", []).append({
                "code": c["code"], "nom": c["nom"], "population": c["population"], "mairie": fiche(mairies.get(c["code"])),
            })
        branches = []
        for code in epci_codes + ([""] if "" in par_epci else []):
            inst = epcis.get(code)
            branches.append({
                "code": code, "nom": (inst.nom if inst else (f"Intercommunalité {code}" if code else "Sans intercommunalité")),
                "institution": fiche(inst), "communes": par_epci.get(code, []),
            })
        return Response({
            "departement": {"code": dep, "nom": DEPARTEMENTS.get(dep, dep), "institution": fiche(cg)},
            "epcis": branches,
            "totaux": {"communes": len(communes), "mairies_sur_la_plateforme": len(mairies),
                       "epcis": len(epci_codes)},
        })

    @action(detail=True, methods=["get"])
    def amorcage(self, request, pk=None):
        """Où en est le dernier amorçage, et les imports de sites sensibles du département."""
        delegation = self.get_object()
        dernier = delegation.amorcages.first()
        return Response(self._etat_amorcage(dernier) if dernier else None)

    @staticmethod
    def _peut_agir(request, delegation) -> bool:
        """Ceux qui agissent pour l'AASC sur ce territoire, et l'administrateur de la plateforme
        (22/11/2026 : il pouvait engager une délégation, mais pas relancer son amorçage)."""
        return get_effective_role(request) == UserRole.ADMINISTRATOR or agit_pour(request.user, delegation)

    def _etat_amorcage(self, amorcage):
        from .amorcage_departement import avancement_risques, est_interrompu
        from .models import ImportOpenData
        imports = ImportOpenData.objects.filter(institution=amorcage.delegation.collectivite)
        return {
            "id": str(amorcage.id), "debut": amorcage.debut, "fin": amorcage.fin, "etapes": amorcage.etapes,
            "interrompu": est_interrompu(amorcage), "risques": avancement_risques(amorcage),
            # `incomplet` et `erreur` : un import tronqué ou en échec doit se voir (22/11/2026).
            "sites": [{"source": i.source, "statut": i.statut, "date_fin": i.date_fin,
                       "crees": (i.resultat or {}).get("crees"), "total": (i.resultat or {}).get("total"),
                       "incomplet": (i.resultat or {}).get("incomplet") or [], "erreur": i.erreur or None}
                      for i in imports],
        }

    @action(detail=True, methods=["post"])
    def inviter(self, request, pk=None):
        """Invite les personnes de la mairie à ouvrir leur compte (autorité locale, rattaché à la
        collectivité) pour compléter et vérifier ce que l'AASC a saisi, et garder la main."""
        from .branding import branding_for_institution, send_branded_mail
        from .crypto_fields import blind_index
        from .institution_attachment import _get_or_create_contact_institution, grant_institution_and_demo_access
        from .views import build_magic_link

        delegation = self.get_object()
        if not self._peut_agir(request, delegation):
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



class RejoindreCollectiviteView(APIView):
    """`/api/rejoindre-collectivite/<jeton>/` : GET dit à quoi invite le lien ; POST crée le compte.
    Public (la personne n'a pas encore de compte), borné par l'invitation elle-même : jeton
    chiffré retrouvé par empreinte, 30 jours, cinq comptes au plus, chacun signalé à l'adresse
    officielle et inactif jusqu'à l'activation par courriel."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, jeton=None):
        from .convention_sous_traitance import institution_necessite_convention
        from .invitation_collectivite import trouver

        invitation = trouver(jeton)
        if invitation is None:
            return Response({"error": "Lien expiré ou invalide."}, status=status.HTTP_404_NOT_FOUND)
        aasc = invitation.delegation.aasc if invitation.delegation else None
        return Response({
            "institution": invitation.institution.nom, "type": _code_type(invitation.institution),
            "invite_par": (aasc.nom_affichage or aasc.nom) if aasc else "La plateforme",
            "convention_requise": institution_necessite_convention(invitation.institution),
        })

    def post(self, request, jeton=None):
        from .invitation_collectivite import rejoindre, trouver

        invitation = trouver(jeton)
        if invitation is None:
            return Response({"error": "Lien expiré ou invalide."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            user = rejoindre(invitation, request.data, request)
        audit_log(request=request, action_code="CREATION", objet_type="User", objet_id=user.id,
                  institution=invitation.institution,
                  commentaire=f"Compte ouvert pour {invitation.institution.nom} par invitation")
        return Response({"ok": True}, status=status.HTTP_201_CREATED)
