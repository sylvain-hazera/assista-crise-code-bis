"""Le dossier du plan communal de sauvegarde : son état, sa partie administrative, son document.

Voir core/document_pcs.py pour ce que le document contient et pourquoi il n'est jamais stocké.
"""
import datetime

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from . import document_pcs
from .audit import audit_log
from .models import RevisionPCS
from .perimetre_admin import institution_regardee
from .permissions import IsInstitutionalActor, get_active_environment, nom_affichable

CHAMPS_MODIFIABLES = ("arrete_numero", "arrete_date", "lieu_pcc", "lieu_pcc_repli", "modalites_activation")


def _institution(request):
    """L'institution dont on tient le plan : celle de la personne, ou celle que regarde
    l'administrateur. Un compte institutionnel sans rattachement n'a pas de plan à ouvrir."""
    institution = institution_regardee(request)
    if institution is None:
        raise PermissionDenied("Aucune collectivité n'est rattachée à votre compte : il n'y a pas de plan à ouvrir.")
    return institution


def _nommer(request):
    return lambda utilisateur: (nom_affichable(utilisateur, request) or utilisateur.username) if utilisateur else ""


def _equipes_par_point_nommees(institution, environment) -> dict:
    from .models import Team

    par_point = document_pcs.equipes_par_point(institution, environment)
    noms = dict(Team.objects.filter(pk__in=par_point.values()).values_list("id", "name"))
    return {code: {"id": identifiant, "nom": noms.get(__import__("uuid").UUID(identifiant), "")}
            for code, identifiant in par_point.items()}


def _etat(request, institution) -> dict:
    contenu = document_pcs.rassembler(institution, get_active_environment(request), _nommer(request))
    dossier = contenu["dossier"]
    compte = {
        "risques": len(contenu["risques"]),
        "sites_sensibles": sum(len(f) for f in contenu["enjeux"].values()) + sum(len(f) for f in contenu["ressources"].values()),
        "administratif": int(bool(dossier["arrete_numero"] and dossier["lieu_pcc"] and dossier["modalites_activation"])),
        "zones": len(contenu["zones"]),
        "dispositifs": len(contenu["dispositifs"]),
        "interlocuteurs": sum(len(f) for f in contenu["annuaire"].values()),
        "points": len(contenu["points"]),
        "equipes": len(contenu["equipes"]),
        "materiels": contenu["nombre_materiels"],
        "fonctions": len(contenu["fonctions"]),
        "moyens_alerte": len(contenu["moyens_alerte"]),
        "exercices": len(contenu["exercices"]),
        # « Renseigné » dès que la simulation existe pour la commune : c'est elle qui manque, pas une saisie.
        "enjeux_exposes": int(contenu["exposition"]["simulation_disponible"]),
    }
    return {
        # L'équipe permanente que l'organigramme désigne pour chaque point proposé au démarrage
        # d'une crise, avec son nom : l'assistant s'en sert pour proposer l'équipe de la crise,
        # qui en reprendra les membres.
        "equipes_par_point": _equipes_par_point_nommees(institution, get_active_environment(request)),
        "paragraphes": document_pcs.paragraphes(compte),
        "institution": str(institution.id),
        "institution_nom": institution.nom,
        "commune": contenu["commune"],
        **{champ: dossier[champ] for champ in CHAMPS_MODIFIABLES},
        "revisions": contenu["revisions"],
        "manques": contenu["manques"],
        # Ce que le document reprendra, pour que l'écran le dise avant qu'on l'édite.
        "contenu": {
            "risques": len(contenu["risques"]),
            "sites_sensibles": sum(len(f) for f in contenu["enjeux"].values()),
            "dispositifs": len(contenu["dispositifs"]),
            "missions_types": sum(len(d["missions"]) for d in contenu["dispositifs"]),
            "interlocuteurs": sum(len(f) for f in contenu["annuaire"].values()),
            "membres": len(contenu["organisation"]),
            "equipes": len(contenu["equipes"]),
            "points": len(contenu["points"]),
        },
    }


class DossierPCSView(APIView):
    """GET /api/dossier-pcs/ -- l'état du plan (partie administrative, révisions, ce qui manque).
    PATCH -- l'arrêté, le lieu du poste de commandement, les modalités d'activation."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        return Response(_etat(request, _institution(request)))

    def patch(self, request):
        institution = _institution(request)
        dossier = document_pcs.dossier_de(institution, get_active_environment(request))
        modifies = []
        for champ in CHAMPS_MODIFIABLES:
            if champ not in request.data:
                continue
            valeur = request.data[champ]
            if champ == "arrete_date":
                if valeur in (None, ""):
                    valeur = None
                else:
                    try:
                        valeur = datetime.date.fromisoformat(str(valeur))
                    except ValueError:
                        raise ValidationError({"arrete_date": "Date attendue au format AAAA-MM-JJ."})
            else:
                valeur = str(valeur or "").strip()
                limite = dossier._meta.get_field(champ).max_length
                if limite and len(valeur) > limite:
                    raise ValidationError({champ: f"{limite} caractères au plus."})
            setattr(dossier, champ, valeur)
            modifies.append(champ)
        if modifies:
            dossier.save(update_fields=modifies + ["date_maj"])
            audit_log(request=request, action_code="MODIFICATION", objet_type="DossierPCS", objet_id=dossier.id,
                      commentaire="Plan communal de sauvegarde : " + ", ".join(modifies))
        return Response(_etat(request, institution))


class RevisionPCSView(APIView):
    """POST /api/dossier-pcs/revisions/ -- ajoute une ligne au tableau des mises à jour du plan.
    Une ligne ne se modifie ni ne se supprime : c'est l'historique du plan."""
    permission_classes = [IsInstitutionalActor]

    def post(self, request):
        institution = _institution(request)
        objet = str(request.data.get("objet") or "").strip()
        if not objet:
            raise ValidationError({"objet": "Dites ce qui a été mis à jour."})
        if len(objet) > 500:
            raise ValidationError({"objet": "500 caractères au plus."})
        try:
            date = datetime.date.fromisoformat(str(request.data.get("date") or timezone.localdate().isoformat()))
        except ValueError:
            raise ValidationError({"date": "Date attendue au format AAAA-MM-JJ."})
        if date > timezone.localdate():
            raise ValidationError({"date": "Une mise à jour ne peut pas être datée dans le futur."})
        environment = get_active_environment(request)
        dossier = document_pcs.dossier_de(institution, environment)
        revision = RevisionPCS.objects.create(
            dossier=dossier, environment=environment, date=date, objet=objet, auteur=request.user)
        audit_log(request=request, action_code="CREATION", objet_type="RevisionPCS", objet_id=revision.id,
                  commentaire=f"Mise à jour du plan communal de sauvegarde : {objet[:120]}")
        return Response(_etat(request, institution), status=201)


class DocumentPCSView(APIView):
    """GET /api/dossier-pcs/document/ -- le plan en PDF, construit à l'instant.

    Diffusion restreinte : il porte l'annuaire de crise et les coordonnées des membres. Chaque
    édition est inscrite à la main courante, et le nom de qui l'a sortie est au pied de chaque
    page. La liste des personnes vulnérables n'y est pas (voir core/registre_vulnerables_pdf.py)."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        institution = _institution(request)
        contenu = document_pcs.rassembler(institution, get_active_environment(request), _nommer(request))
        from . import cartes_pcs
        # `?fond=ign` : les planches sur le Plan IGN plutôt qu'en schéma (case de l'écran du plan).
        fond = cartes_pcs.fond_ign if request.query_params.get("fond") == "ign" else None
        contenu["cartes"] = cartes_pcs.planches(institution, get_active_environment(request), fond=fond)
        pdf = document_pcs.generer_pdf(contenu, edite_par=_nommer(request)(request.user))
        dossier = document_pcs.dossier_de(institution, get_active_environment(request))
        audit_log(request=request, action_code="EXPORT", objet_type="DossierPCS", objet_id=dossier.id,
                  commentaire=f"Édition du plan communal de sauvegarde de « {institution.nom} » "
                              f"({len(contenu['manques'])} point(s) restant à compléter)")
        reponse = HttpResponse(pdf, content_type="application/pdf")
        code = institution.commune_code or "collectivite"
        reponse["Content-Disposition"] = f'attachment; filename="plan-communal-de-sauvegarde-{code}.pdf"'
        return reponse


class EnjeuxExposesView(APIView):
    """GET /api/dossier-pcs/enjeux-exposes/ -- les sites sensibles retenus et les lieux d'accueil
    du plan, avec le niveau d'eau qui les atteint d'après la simulation d'inondation
    (core/enjeux_exposes.py). Des hypothèses, à vérifier sur place."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        from .enjeux_exposes import exposes

        return Response(exposes(_institution(request), get_active_environment(request)))


class ZonagesOfficielsView(APIView):
    """POST /api/dossier-pcs/zonages-officiels/ -- demande le relevé des zones inondables
    officielles de la commune auprès de Géorisques. Le relevé se fait en tâche de fond, une
    requête par scénario, espacées ; un relevé récent n'est pas refait (`forcer` pour passer
    outre). La réponse dit où l'on en est ; l'écran relit ensuite les enjeux exposés."""
    permission_classes = [IsInstitutionalActor]

    def post(self, request):
        from . import zonages_officiels
        from .tasks import relever_zonages_officiels_task

        institution = _institution(request)
        commune_code = institution.commune_code or ""
        if not commune_code:
            raise ValidationError({"commune": "Cette collectivité n'a pas de commune de rattachement : rien à relever."})
        environment = get_active_environment(request)
        relever_zonages_officiels_task.delay(commune_code, environment, bool(request.data.get("forcer")))
        audit_log(request=request, action_code="MODIFICATION", objet_type="ZonageOfficiel", objet_id=None,
                  commentaire=f"Relevé des zones inondables officielles demandé pour la commune {commune_code} (Géorisques).")
        return Response({"demande": True, "pause_s": zonages_officiels.PAUSE_S,
                         **zonages_officiels.etat(commune_code, environment)}, status=202)


class CouchesCartoView(APIView):
    """GET /api/couches-carto/ -- ce que la commune peut sortir vers un logiciel de cartographie,
    couche par couche (core/couches_carto.py). Le registre des personnes vulnérables n'y est pas."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        from . import couches_carto

        return Response(couches_carto.inventaire(_institution(request), get_active_environment(request)))


class CoucheCartoView(APIView):
    """GET /api/couches-carto/<couche>/ -- la couche en GeoJSON (WGS 84), à ouvrir dans QGIS.
    Chaque sortie est inscrite à la main courante : un fichier de carte se copie."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request, couche):
        import json

        from . import couches_carto

        if couche not in couches_carto.COUCHES:
            raise ValidationError({"couche": "Couche inconnue."})
        institution = _institution(request)
        contenu = couches_carto.exporter(couche, institution, get_active_environment(request))
        audit_log(request=request, action_code="EXPORT", objet_type="CoucheCarto", objet_id=None,
                  commentaire=f"Couche « {couches_carto.COUCHES[couche]} » exportée en GeoJSON "
                              f"({len(contenu['features'])} objet(s), {institution.nom}).")
        reponse = HttpResponse(json.dumps(contenu, ensure_ascii=False), content_type="application/geo+json")
        reponse["Content-Disposition"] = f'attachment; filename="{couche}.geojson"'
        return reponse


class ImportQuartiersView(APIView):
    """POST /api/couches-carto/quartiers/importer/ -- fait entrer les quartiers d'un fichier
    GeoJSON (champ `fichier`). Sans `enregistrer`, ne crée rien et dit ce qui se passerait :
    l'écran montre toujours cet aperçu d'abord. `remplacer` autorise à redessiner un quartier
    du même nom, qui est sinon laissé tel quel."""
    permission_classes = [IsInstitutionalActor]

    def post(self, request):
        from . import couches_carto

        institution = _institution(request)
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ValidationError({"fichier": "Joignez le fichier GeoJSON de vos quartiers."})
        if fichier.size > couches_carto.MAX_OCTETS:
            raise ValidationError({"fichier": "Ce fichier dépasse 5 Mo : simplifiez les contours avant de l'importer."})
        vrai = ("1", "true", "oui", "on")
        enregistrer = str(request.data.get("enregistrer", "")).lower() in vrai
        remplacer = str(request.data.get("remplacer", "")).lower() in vrai
        try:
            quartiers = couches_carto.lire_quartiers(fichier.read())
        except couches_carto.FichierIllisible as exc:
            raise ValidationError({"fichier": str(exc)}) from exc
        bilan = couches_carto.importer_quartiers(
            quartiers, institution, get_active_environment(request), remplacer=remplacer, enregistrer=enregistrer)
        if enregistrer and (bilan["crees"] or bilan["remplaces"]):
            audit_log(request=request, action_code="CREATION", objet_type="Zone", objet_id=None,
                      commentaire=f"Import de quartiers depuis un fichier ({institution.nom}) : "
                                  f"{bilan['crees']} créé(s), {bilan['remplaces']} redessiné(s).")
        return Response(bilan)


class DebitRemiseRapport(SimpleRateThrottle):
    """Trente par heure et par adresse IP : large pour une personne qui suit son lien, court
    pour qui essaierait des jetons au hasard (ils font 43 caractères tirés au sort)."""
    scope = "remise_rapport"
    rate = "30/hour"

    def get_cache_key(self, request, view):
        from .audit import get_client_ip
        return self.cache_format % {"scope": self.scope, "ident": get_client_ip(request) or "inconnu"}


class RecevoirRapportView(APIView):
    """GET puis POST /api/rapports/recevoir/<jeton>/ -- la page du lien personnel envoyé quand
    la clôture d'une crise est proposée (core/cloture_crise.py). Sans compte : le jeton désigne
    UNE personne et UN rapport. GET dit de quel rapport il s'agit et à quelle adresse (masquée)
    il partira ; POST l'envoie, à cette adresse et à aucune autre. Le PDF n'est jamais rendu ici."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [DebitRemiseRapport]

    def get(self, request, jeton):
        from . import cloture_crise
        try:
            return Response(cloture_crise.decrire(jeton))
        except cloture_crise.ClotureImpossible as exc:
            return Response({"error": str(exc)}, status=410)

    def post(self, request, jeton):
        from . import cloture_crise
        try:
            return Response(cloture_crise.remettre(jeton, request))
        except cloture_crise.ClotureImpossible as exc:
            return Response({"error": str(exc)}, status=410)


class DicrimView(APIView):
    """GET /api/dossier-pcs/dicrim/ -- le document d'information des habitants sur les risques.

    Public par nature, il ne porte aucune donnée personnelle (voir document_pcs.generer_dicrim).
    C'est la collectivité qui l'édite et le diffuse ; l'édition est inscrite à la main courante."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        institution = _institution(request)
        contenu = document_pcs.rassembler(institution, get_active_environment(request), _nommer(request))
        pdf = document_pcs.generer_dicrim(contenu)
        dossier = document_pcs.dossier_de(institution, get_active_environment(request))
        audit_log(request=request, action_code="EXPORT", objet_type="DossierPCS", objet_id=dossier.id,
                  commentaire=f"Édition du DICRIM de « {institution.nom} »")
        reponse = HttpResponse(pdf, content_type="application/pdf")
        reponse["Content-Disposition"] = f'attachment; filename="dicrim-{institution.commune_code or "collectivite"}.pdf"'
        return reponse


# ───────────── Les paragraphes tenus en liste : organigramme, alerte, exercices ─────────────
#
# Trois paragraphes du plan ont la même forme -- une liste de lignes propres à la collectivité --
# et donc la même API : lecture, ajout, modification, retrait, toujours bornés au dossier de la
# collectivité de l'appelant. Chaque écriture est inscrite à la main courante, sans le contenu.

from rest_framework import serializers, viewsets  # noqa: E402

from rest_framework.decorators import action  # noqa: E402

from .models import ExercicePCS, FonctionPCS, MoyenAlertePCS, PieceJointePCS, Zone  # noqa: E402
from .pcs_fiches import fiche_type  # noqa: E402


class FonctionPCSSerializer(serializers.ModelSerializer):
    fonction_libelle = serializers.CharField(source="get_fonction_display", read_only=True)
    #: La fiche de la trame de l'État, montrée tant que la commune n'a pas écrit la sienne.
    fiche_type = serializers.SerializerMethodField()

    equipe_nom = serializers.CharField(source="equipe.name", read_only=True, default=None)
    #: Qui tient la fonction, tel que le document le dira : ce qui est saisi, sinon ce que dit
    #: l'équipe reliée. L'écran affiche ceci, et ne propose de saisir que ce qui manque.
    personnes = serializers.SerializerMethodField()

    class Meta:
        model = FonctionPCS
        fields = ["id", "fonction", "fonction_libelle", "libelle", "equipe", "equipe_nom", "titulaire",
                  "titulaire_telephone", "suppleant", "suppleant_telephone", "personnes", "consignes",
                  "fiche_type", "date_maj"]
        read_only_fields = ["id", "date_maj"]

    def get_fiche_type(self, obj):
        return fiche_type(obj.fonction)

    def get_personnes(self, obj):
        request = self.context.get("request")
        zone_reelle = request is None or get_active_environment(request) == "PROD"
        return document_pcs.personnes_de_la_fonction(obj, _nommer(request), zone_reelle)


class MoyenAlertePCSSerializer(serializers.ModelSerializer):
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)
    zone_nom = serializers.CharField(source="zone.nom", read_only=True, default=None)

    class Meta:
        model = MoyenAlertePCS
        fields = ["id", "type", "type_libelle", "description", "zone", "zone_nom", "personne",
                  "personne_telephone", "date_maj"]
        read_only_fields = ["id", "date_maj"]


class ExercicePCSSerializer(serializers.ModelSerializer):
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)

    class Meta:
        model = ExercicePCS
        fields = ["id", "date", "theme", "deroulement", "enseignements", "actions", "crise", "crise_nom"]
        read_only_fields = ["id"]

    def validate_date(self, valeur):
        if valeur > timezone.localdate():
            raise serializers.ValidationError("Un exercice se consigne une fois joué, pas à l'avance.")
        return valeur


class _ListeDuDossierPCS(viewsets.ModelViewSet):
    """Une liste du plan de la collectivité de l'appelant. Rien n'y est visible ni modifiable
    d'une autre collectivité : le dossier vient de la requête, jamais du corps."""
    permission_classes = [IsInstitutionalActor]
    pagination_class = None
    #: Ce qu'on inscrit à la main courante : le nom de l'objet, jamais son contenu.
    objet = ""

    def _dossier(self):
        return document_pcs.dossier_de(_institution(self.request), get_active_environment(self.request))

    def get_queryset(self):
        return self.queryset.filter(dossier=self._dossier())

    def _verifier_zone(self, serializer):
        """Un quartier ou une équipe rattachés à une ligne du plan sont ceux de la collectivité."""
        institution_id = self._dossier().institution_id
        zone = serializer.validated_data.get("zone")
        if zone is not None and zone.institution_id != institution_id:
            raise ValidationError({"zone": "Ce quartier n'appartient pas à votre collectivité."})
        equipe = serializer.validated_data.get("equipe")
        if equipe is not None and equipe.institution_id != institution_id:
            raise ValidationError({"equipe": "Cette équipe n'appartient pas à votre collectivité."})

    def perform_create(self, serializer):
        self._verifier_zone(serializer)
        dossier = self._dossier()
        ligne = serializer.save(dossier=dossier, environment=dossier.environment)
        audit_log(request=self.request, action_code="CREATION", objet_type=self.objet, objet_id=ligne.id,
                  commentaire=f"Plan communal de sauvegarde : {self.queryset.model._meta.verbose_name} ajouté(e)")

    def perform_update(self, serializer):
        self._verifier_zone(serializer)
        ligne = serializer.save()
        audit_log(request=self.request, action_code="MODIFICATION", objet_type=self.objet, objet_id=ligne.id,
                  commentaire=f"Plan communal de sauvegarde : {self.queryset.model._meta.verbose_name} modifié(e)")

    def perform_destroy(self, instance):
        identifiant = instance.id
        instance.delete()
        audit_log(request=self.request, action_code="SUPPRESSION", objet_type=self.objet, objet_id=identifiant,
                  commentaire=f"Plan communal de sauvegarde : {self.queryset.model._meta.verbose_name} retiré(e)")


class FonctionPCSViewSet(_ListeDuDossierPCS):
    """/api/pcs-fonctions/ -- l'organigramme du poste de commandement communal et ses fiches réflexes."""
    queryset = FonctionPCS.objects.select_related("equipe__leader").prefetch_related("equipe__membres_encadrement")
    serializer_class = FonctionPCSSerializer
    objet = "FonctionPCS"


class MoyenAlertePCSViewSet(_ListeDuDossierPCS):
    """/api/pcs-moyens-alerte/ -- les moyens d'alerter la population, par quartier s'il y a lieu."""
    queryset = MoyenAlertePCS.objects.select_related("zone")
    serializer_class = MoyenAlertePCSSerializer
    objet = "MoyenAlertePCS"


class ExercicePCSViewSet(_ListeDuDossierPCS):
    """/api/pcs-exercices/ -- les exercices du plan et ce qu'on en a tiré."""
    queryset = ExercicePCS.objects.select_related("crise")
    serializer_class = ExercicePCSSerializer
    objet = "ExercicePCS"


class PieceJointePCSSerializer(serializers.ModelSerializer):
    depose_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = PieceJointePCS
        fields = ["id", "titre", "fonction", "moyen_alerte", "nom_fichier", "type_mime", "taille", "depose_par_nom", "date_depot"]
        read_only_fields = ["nom_fichier", "type_mime", "taille", "date_depot"]

    def get_depose_par_nom(self, obj):
        return _nommer(self.context.get("request"))(obj.depose_par) if obj.depose_par_id else ""


class PieceJointePCSViewSet(_ListeDuDossierPCS):
    """/api/pcs-pieces/ -- les fichiers que la commune joint à son plan, à une fiche réflexe ou à
    un moyen d'alerte. On dépose, on lit, on retire ; un fichier ne se remplace pas, il se
    redépose. Le fichier lui-même ne sort que par `fichier/`, jamais par une adresse directe."""
    queryset = PieceJointePCS.objects.select_related("depose_par")
    serializer_class = PieceJointePCSSerializer
    objet = "PieceJointePCS"
    http_method_names = ["get", "post", "delete", "head", "options"]
    MAX_PAR_DOSSIER = 200

    def get_queryset(self):
        pieces = super().get_queryset()
        for champ in ("fonction", "moyen_alerte"):
            valeur = self.request.query_params.get(champ)
            if valeur:
                pieces = pieces.filter(**{f"{champ}_id": valeur})
        return pieces

    def create(self, request, *args, **kwargs):
        from django.core.exceptions import ValidationError as ErreurDeValidation

        from .validators import validate_identity_document_file

        dossier = self._dossier()
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ValidationError({"fichier": "Joignez un fichier (PDF, ou photo JPEG/PNG)."})
        try:
            validate_identity_document_file(fichier)
        except ErreurDeValidation as erreur:
            raise ValidationError({"fichier": erreur.messages})
        if dossier.pieces.count() >= self.MAX_PAR_DOSSIER:
            raise ValidationError({"fichier": f"Pas plus de {self.MAX_PAR_DOSSIER} fichiers par plan."})
        # La fiche ou le moyen désignés sont ceux de CE plan : on ne rattache rien chez le voisin.
        fonction = FonctionPCS.objects.filter(pk=request.data.get("fonction") or None, dossier=dossier).first() \
            if request.data.get("fonction") else None
        moyen = MoyenAlertePCS.objects.filter(pk=request.data.get("moyen_alerte") or None, dossier=dossier).first() \
            if request.data.get("moyen_alerte") else None
        if (request.data.get("fonction") and fonction is None) or (request.data.get("moyen_alerte") and moyen is None):
            raise ValidationError({"detail": "Cette fiche n'appartient pas à votre plan."})
        nom = (getattr(fichier, "name", "") or "fichier")[:200]
        titre = (str(request.data.get("titre") or "").strip() or nom)[:200]
        piece = PieceJointePCS.objects.create(
            dossier=dossier, environment=dossier.environment, fonction=fonction, moyen_alerte=moyen, titre=titre,
            fichier=fichier, nom_fichier=nom, taille=fichier.size, depose_par=request.user,
            type_mime="application/pdf" if nom.lower().endswith(".pdf") else (getattr(fichier, "content_type", "") or "")[:60],
        )
        audit_log(request=request, action_code="CREATION", objet_type=self.objet, objet_id=piece.id,
                  commentaire="Plan communal de sauvegarde : fichier joint")
        return Response(self.get_serializer(piece).data, status=201)

    def perform_destroy(self, instance):
        fichier = instance.fichier
        super().perform_destroy(instance)
        try:
            fichier.delete(save=False)          # le fichier chiffré quitte le disque avec sa ligne
        except Exception:  # noqa: BLE001
            pass

    @action(detail=True, methods=["get"])
    def fichier(self, request, pk=None):
        """Le fichier, déchiffré à la volée pour qui tient ce plan. Chaque lecture est tracée."""
        from django.http import FileResponse

        piece = self.get_object()
        audit_log(request=request, action_code="TELECHARGEMENT", objet_type=self.objet, objet_id=piece.id,
                  commentaire="Plan communal de sauvegarde : fichier joint téléchargé")
        reponse = FileResponse(piece.fichier.open("rb"), content_type=piece.type_mime or "application/octet-stream",
                               as_attachment=request.query_params.get("voir") != "1",
                               filename=piece.nom_fichier or "fichier")
        reponse["Cache-Control"] = "private, no-store"
        reponse["X-Content-Type-Options"] = "nosniff"
        return reponse


# ───────────────────────────── L'alerte aux habitants ─────────────────────────────

from rest_framework.permissions import IsAuthenticated  # noqa: E402

from . import alerte_population  # noqa: E402
from .models import AbonnementAlerte, AlertePopulation, Crisis, Institution  # noqa: E402


def _alerte_en_clair(alerte, request) -> dict:
    return {
        "id": str(alerte.id), "titre": alerte.titre, "message": alerte.message, "urgent": alerte.urgent,
        "crise": str(alerte.crise_id) if alerte.crise_id else None,
        "crise_nom": alerte.crise.name if alerte.crise_id else None,
        "canaux": alerte.canaux, "bilan": alerte.bilan, "destinataires": alerte.destinataires,
        "terrain": alerte.terrain or [],
        "auteur": _nommer(request)(alerte.auteur) if alerte.auteur_id else "", "date": alerte.date_creation,
    }


def _crise_demandee(request, valeur):
    if not valeur:
        return None
    crise = Crisis.objects.filter(pk=valeur, end_date__isnull=True, environment=get_active_environment(request)).first()
    if crise is None:
        raise ValidationError({"crise": "Cette crise n'existe pas ou est clôturée."})
    return crise


class AlertesPopulationView(APIView):
    """GET /api/alertes-population/ -- les alertes déjà envoyées par la collectivité, et l'aperçu
    de la prochaine (`?crise=` : qui serait touché, canal par canal).
    POST -- envoie une alerte aux habitants. Voir core/alerte_population.py."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        institution = _institution(request)
        environment = get_active_environment(request)
        crise = _crise_demandee(request, request.query_params.get("crise"))
        alertes = AlertePopulation.objects.filter(institution=institution, environment=environment).select_related("crise", "auteur")[:50]
        return Response({
            "apercu": alerte_population.apercu(institution, crise, environment),
            "par_defaut": alerte_population.PAR_DEFAUT,
            "alertes": [_alerte_en_clair(a, request) for a in alertes],
        })

    def post(self, request):
        institution = _institution(request)
        titre = str(request.data.get("titre") or "").strip()
        message = str(request.data.get("message") or "").strip()
        if not titre or not message:
            raise ValidationError({"message": "Une alerte a un titre et un message."})
        if len(titre) > 150:
            raise ValidationError({"titre": "150 caractères au plus."})
        canaux = request.data.get("canaux") or []
        terrain = request.data.get("terrain") or []
        relayer = request.data.get("relayer") or []
        if not isinstance(canaux, list) or not isinstance(terrain, list) or not isinstance(relayer, list):
            raise ValidationError({"canaux": "Choisissez au moins un canal ou un moyen de terrain."})
        # Une alerte peut ne passer QUE par le terrain : la sirène n'a pas besoin d'Internet.
        if not [c for c in canaux if c in alerte_population.CODES] and not terrain:
            raise ValidationError({"canaux": "Choisissez au moins un canal ou un moyen de terrain."})
        crise = _crise_demandee(request, request.data.get("crise"))
        alerte = alerte_population.envoyer(request, institution, crise, titre, message, canaux,
                                           urgent=bool(request.data.get("urgent", True)), terrain=terrain, relayer=relayer)
        return Response(_alerte_en_clair(alerte, request), status=201)


class CollectivitesAlerteView(APIView):
    """GET /api/alertes-population/collectivites/?q=saint -- les communes et intercommunalités
    dont on peut recevoir les alertes, cherchées par leur nom. Nom et identifiant seulement :
    rien ici n'est privé, et c'est ce dont l'habitant a besoin pour s'abonner."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response([])
        collectivites = (Institution.objects
                         .filter(environment=get_active_environment(request), type__code__in=("MAIRIE", "EPCI"),
                                 nom__icontains=q, actif=True).order_by("nom")[:15])
        return Response([{"id": str(i.id), "nom": i.nom} for i in collectivites])


class AbonnementAlerteView(APIView):
    """GET /api/alertes-population/abonnement/ -- les collectivités dont je reçois les alertes.
    POST {institution} -- je m'abonne. DELETE {institution} -- je me désabonne.

    Ouvert à tout compte connecté : c'est l'habitant qui décide, pour lui-même."""
    permission_classes = [IsAuthenticated]

    def _institution(self, request):
        institution = Institution.objects.filter(pk=request.data.get("institution") or request.query_params.get("institution")).first()
        if institution is None:
            raise ValidationError({"institution": "Collectivité inconnue."})
        return institution

    def get(self, request):
        abonnements = AbonnementAlerte.objects.filter(
            utilisateur=request.user, actif=True, environment=get_active_environment(request)).select_related("institution")
        return Response([{"institution": str(a.institution_id), "institution_nom": a.institution.nom} for a in abonnements])

    def post(self, request):
        institution = self._institution(request)
        abonnement, _cree = AbonnementAlerte.objects.update_or_create(
            utilisateur=request.user, institution=institution, environment=get_active_environment(request),
            defaults={"actif": True})
        return Response({"institution": str(institution.id), "institution_nom": institution.nom, "actif": True}, status=201)

    def delete(self, request):
        institution = self._institution(request)
        AbonnementAlerte.objects.filter(utilisateur=request.user, institution=institution,
                                        environment=get_active_environment(request)).update(actif=False)
        return Response(status=204)
