"""Le dossier du plan communal de sauvegarde : son état, sa partie administrative, son document.

Voir core/document_pcs.py pour ce que le document contient et pourquoi il n'est jamais stocké.
"""
import datetime

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
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
        pdf = document_pcs.generer_pdf(contenu, edite_par=_nommer(request)(request.user))
        dossier = document_pcs.dossier_de(institution, get_active_environment(request))
        audit_log(request=request, action_code="EXPORT", objet_type="DossierPCS", objet_id=dossier.id,
                  commentaire=f"Édition du plan communal de sauvegarde de « {institution.nom} » "
                              f"({len(contenu['manques'])} point(s) restant à compléter)")
        reponse = HttpResponse(pdf, content_type="application/pdf")
        code = institution.commune_code or "collectivite"
        reponse["Content-Disposition"] = f'attachment; filename="plan-communal-de-sauvegarde-{code}.pdf"'
        return reponse


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

from .models import ExercicePCS, FonctionPCS, MoyenAlertePCS, Zone  # noqa: E402
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
