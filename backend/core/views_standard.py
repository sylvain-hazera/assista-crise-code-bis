"""Accès au standard de crise et au point de situation — voir core/standard_crise.py et
core/point_situation.py pour le pourquoi."""
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import point_situation, standard_crise
from .audit import audit_log
from .models import AppelStandard, Crisis, Dossier, NatureAppelStandard, SuiteAppelStandard
from .permissions import IsInstitutionalActor, get_active_environment
from .views_stocks import _du_perimetre, _institution_ou_refus


class AppelStandardSerializer(serializers.ModelSerializer):
    nature_libelle = serializers.CharField(source="get_nature_display", read_only=True)
    suite_libelle = serializers.CharField(source="get_suite_display", read_only=True)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    recu_par_nom = serializers.SerializerMethodField()
    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True, default=None)
    fiches = serializers.SerializerMethodField()

    class Meta:
        model = AppelStandard
        exclude = ["environment", "demandes", "offres", "informations", "recherches"]
        read_only_fields = ["institution", "numero", "recu_par", "date_appel", "dossier",
                            "suite", "suite_donnee", "traite_par", "traite_le", "identifiant_saisie"]

    def get_fiches(self, obj):
        """Les vraies fiches créées pendant cet appel : c'est là que se lit et se traite le fond."""
        return ([{"type": "demande", "id": str(d.id), "titre": d.title} for d in obj.demandes.all()]
                + [{"type": "offre", "id": str(o.id), "titre": o.title} for o in obj.offres.all()]
                + [{"type": "information", "id": str(i.id), "titre": i.title} for i in obj.informations.all()]
                + [{"type": "recherche", "id": str(r.id), "titre": "Recherche de personne"} for r in obj.recherches.all()])

    def get_recu_par_nom(self, obj):
        from .views import _nommer_pour
        return _nommer_pour(self.context.get("request"))(obj.recu_par) if obj.recu_par_id else ""

    def validate_objet(self, valeur):
        if not (valeur or "").strip():
            raise serializers.ValidationError("Notez en une phrase l'objet de l'appel.")
        return valeur.strip()


class AppelStandardViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """Fiches d'appel du standard de crise. On crée et on donne une suite ; une fiche ne se
    modifie ni ne se supprime — c'est une trace."""
    queryset = AppelStandard.objects.select_related("crise", "recu_par", "dossier").prefetch_related(
        "demandes", "offres", "informations", "recherches")
    serializer_class = AppelStandardSerializer
    permission_classes = [IsInstitutionalActor]
    filterset_fields = ["crise", "nature", "suite"]

    def get_queryset(self):
        return _du_perimetre(self.request, super().get_queryset())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        appel = standard_crise.enregistrer(
            _institution_ou_refus(request), get_active_environment(request), request.user,
            nature=donnees["nature"], objet=donnees["objet"], crise=donnees.get("crise"),
            appelant_nom=donnees.get("appelant_nom", ""), appelant_telephone=donnees.get("appelant_telephone", ""),
            lieu=donnees.get("lieu", ""),
        )
        return Response(self.get_serializer(appel).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def clore(self, request, pk=None):
        """Donne sa suite à l'appel : traité, ou sans suite, avec ce qui a été fait."""
        appel = self.get_object()
        suite = request.data.get("suite")
        if suite not in (SuiteAppelStandard.TRAITE, SuiteAppelStandard.SANS_SUITE, SuiteAppelStandard.A_TRAITER):
            raise ValidationError({"suite": "Suite inconnue."})
        standard_crise.clore(appel, request.user, suite, str(request.data.get("suite_donnee") or "").strip())
        return Response(self.get_serializer(appel).data)

    @action(detail=True, methods=["post"], url_path="ouvrir-dossier")
    def ouvrir_dossier(self, request, pk=None):
        """Ouvre le dossier que les équipes traiteront. Une fiche n'en ouvre qu'un."""
        appel = self.get_object()
        priorite = request.data.get("priorite") or Dossier.Priorite.NORMALE
        if priorite not in Dossier.Priorite.values:
            raise ValidationError({"priorite": "Priorité invalide."})
        try:
            dossier = standard_crise.ouvrir_un_dossier(appel, request.user, priorite)
        except ValueError as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="CREATION", objet_type="Dossier", objet_id=dossier.id,
                  crise=appel.crise, commentaire=f"Dossier ouvert depuis la fiche d'appel n° {appel.numero} du standard.")
        return Response(self.get_serializer(appel).data)

    @action(detail=False, methods=["get"])
    def synthese(self, request):
        crise = Crisis.objects.filter(id=request.query_params.get("crise")).first() \
            if request.query_params.get("crise") else None
        return Response({
            "natures": [{"code": c, "libelle": l} for c, l in NatureAppelStandard.choices],
            **standard_crise.synthese(_institution_ou_refus(request), get_active_environment(request), crise),
        })


class EngagementPersonnelView(APIView):
    """« Je pars », « je rentre » pour le personnel et les membres d'association — voir
    core/engagements_personnels.py.

    GET : où j'en suis, et sur quelles crises et avec quelles équipes je peux partir.
    POST {geste: "partir", crise, equipe?} ou {geste: "rentrer"}.

    Ouvert à tout compte connecté : c'est l'appartenance à une équipe ou à une institution
    engagée sur la crise qui autorise le départ, pas le rôle sur la plateforme — un bénévole
    d'association est un compte ordinaire."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def _etat(self, request):
        from . import engagements_personnels as ep
        from . import manifestations as mf

        environment = get_active_environment(request)
        ouvert = ep.en_cours(request.user, environment)
        return {
            "en_cours": None if ouvert is None else {
                "crise": str(ouvert.crise_id) if ouvert.crise_id else None, "crise_nom": ouvert.objet_nom,
                "manifestation": str(ouvert.manifestation_id) if ouvert.manifestation_id else None,
                "equipe_nom": ouvert.equipe.name if ouvert.equipe_id else None,
                "parti_le": ouvert.parti_le, "depart_de": ouvert.depart_de,
                "hebergement": ouvert.hebergement,
                "vehicule_personnel": str(ouvert.vehicule_personnel_id) if ouvert.vehicule_personnel_id else None,
                "compteur_depart": ouvert.compteur_depart,
                # Ce qui sera proposé au retour (relevé kilométrique, 28/11/2026).
                "motif_propose": ouvert.motif or ouvert.objet_nom,
                "arrivee_proposee": ouvert.lieu_arrivee or ep.lieu_de(ouvert),
            },
            "vehicules": [_vehicule_en_dict(v) for v in ep.vehicules_de(request.user)],
            # `hebergement` : le logement de la personne sur cette crise si elle y est « en
            # déplacement sur site » — c'est alors de là qu'elle part et là qu'elle rentre.
            "crises": [{"id": str(c.id), "nom": c.name, "hebergement": ep.hebergement_de(request.user, c)}
                       for c in ep.crises_ouvertes_pour(request.user, environment)],
            "equipes": [{"id": str(e.id), "nom": e.name} for e in ep.equipes_de(request.user).order_by("name")],
            # Les manifestations du jour où je suis inscrit (26/11/2026) : on part aussi pour elles.
            "manifestations": [{"id": str(m.id), "nom": m.titre, "debut": m.debut, "fin": m.fin}
                               for m in mf.du_jour_pour(request.user, environment)],
        }

    def get(self, request):
        return Response(self._etat(request))

    def post(self, request):
        from . import engagements_personnels as ep
        from .models import Team

        environment = get_active_environment(request)
        geste = request.data.get("geste")
        try:
            if geste == "partir" and request.data.get("manifestation"):
                from .models import Manifestation
                manifestation = Manifestation.objects.filter(id=request.data.get("manifestation"), environment=environment).first()
                if manifestation is None:
                    raise ValidationError({"detail": "Manifestation introuvable."})
                ep.partir(request.user, environment, manifestation=manifestation, depart_de=request.data.get("depart_de"),
                          deplacement=_deplacement(request.data))
            elif geste == "partir":
                crise = Crisis.objects.filter(id=request.data.get("crise"), environment=environment).first() \
                    if request.data.get("crise") else None
                if crise is None:
                    raise ValidationError({"detail": "Indiquez la crise sur laquelle vous partez."})
                equipe = Team.objects.filter(id=request.data.get("equipe")).first() if request.data.get("equipe") else None
                ep.partir(request.user, environment, crise, equipe, depart_de=request.data.get("depart_de"),
                          deplacement=_deplacement(request.data))
            elif geste == "rentrer":
                rentree = ep.rentrer(request.user, environment, retour_a=request.data.get("retour_a"),
                                     deplacement=_deplacement(request.data),
                                     peage=request.data.get("peage"), stationnement=request.data.get("stationnement"))
                # La ligne close, pour y joindre ensuite la photo d'un ticket (application, 28/11/2026).
                return Response(dict(self._etat(request), ligne_rentree=str(rentree.id)))
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(self._etat(request))


def _vehicule_en_dict(v) -> dict:
    return {"id": str(v.id), "genre": v.genre, "libelle": v.libelle, "immatriculation": v.immatriculation,
            "puissance_cv": v.puissance(), "designation": v.designation, "actif": v.actif}


def _deplacement(donnees) -> dict:
    """Les champs du déplacement présents dans la requête (relevé kilométrique, 28/11/2026)."""
    from .engagements_personnels import CHAMPS_DEPLACEMENT
    return {k: donnees.get(k) for k in CHAMPS_DEPLACEMENT if k in donnees}


def _frais_en_dict(f) -> dict:
    return {"id": str(f.id), "nature": f.nature, "nature_libelle": f.get_nature_display(), "montant": f.montant,
            "justificatif": bool(f.justificatif), "justificatif_nom": f.justificatif_nom if f.justificatif else ""}


def _ligne_de_releve(engagement) -> dict:
    duree = engagement.duree
    vp = engagement.vehicule_personnel
    return {
        "vehicule_personnel": str(vp.id) if vp is not None else None,
        "vehicule_designation": vp.designation if vp is not None else "",
        "lieu_depart": engagement.lieu_depart, "lieu_arrivee": engagement.lieu_arrivee, "motif": engagement.motif,
        "aller_retour": engagement.aller_retour,
        "compteur_depart": engagement.compteur_depart, "compteur_arrivee": engagement.compteur_arrivee,
        "frais": [_frais_en_dict(f) for f in engagement.frais.all()],
        "id": str(engagement.id), "crise": str(engagement.crise_id) if engagement.crise_id else None,
        # `crise_nom` garde son nom pour les écrans existants : c'est le nom de l'activité.
        "crise_nom": engagement.objet_nom,
        "manifestation": str(engagement.manifestation_id) if engagement.manifestation_id else None,
        "kilometres": engagement.kilometres, "vehicule": engagement.vehicule, "source": engagement.source,
        "equipe": str(engagement.equipe_id) if engagement.equipe_id else None,
        "equipe_nom": engagement.equipe.name if engagement.equipe_id else "",
        "parti_le": engagement.parti_le, "rentre_le": engagement.rentre_le,
        "depart_de": engagement.depart_de, "retour_a": engagement.retour_a,
        "hebergement": engagement.hebergement, "saisie_manuelle": engagement.saisie_manuelle,
        "heures": round(duree.total_seconds() / 3600, 2) if duree is not None else None,
        "validee": engagement.valide_le is not None, "validee_le": engagement.valide_le,
        "remarque_chef": engagement.remarque_chef,
    }


def _instant(valeur, champ):
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    instant = parse_datetime(str(valeur or ""))
    if instant is None:
        raise ValidationError({"detail": f"{champ} : date et heure attendues."})
    return timezone.make_aware(instant) if timezone.is_naive(instant) else instant


class MonReleveView(APIView):
    """Le relevé d'heures de la personne, en forme de tableau, avec en regard son activité et
    celle de ses équipes pour l'aider à retrouver ce qu'elle a oublié de déclarer.

    GET ?du=AAAA-MM-JJ&au=AAAA-MM-JJ (30 derniers jours par défaut).
    POST : ajoute une sortie oubliée (départ ET retour)."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime

        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from . import engagements_personnels as ep
        from .models import EngagementPersonnel, LieuDeDepart

        environment = get_active_environment(request)
        aujourdhui = timezone.localdate()
        au = parse_date(str(request.query_params.get("au") or "")) or aujourdhui
        du = parse_date(str(request.query_params.get("du") or "")) or au - datetime.timedelta(days=30)
        if du > au or (au - du).days > 366:
            raise ValidationError({"detail": "Période invalide (un an au plus)."})
        debut = timezone.make_aware(datetime.datetime.combine(du, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(au, datetime.time.max))
        objets = list(EngagementPersonnel.objects.filter(
            utilisateur=request.user, environment=environment, parti_le__gte=debut, parti_le__lte=fin)
            .select_related("crise", "equipe", "manifestation", "vehicule_personnel").prefetch_related("frais")
            .order_by("-parti_le"))
        lignes = [_ligne_de_releve(l) for l in objets]
        from . import benevolat, manifestations as mf
        from .models import AbandonFrais, Institution, VehiculeBenevole
        # Frais de l'année et renonciation possible, par association (26/11/2026).
        annee = au.year
        frais = []
        for institution in Institution.objects.filter(id__in=mf.associations_de(request.user)).order_by("nom"):
            r = benevolat.reglages(institution, annee, environment)
            dispo = benevolat.frais_abandonnables(institution, environment, annee, request.user)
            abandon = AbandonFrais.objects.filter(institution=institution, utilisateur=request.user, annee=annee,
                                                  environment=environment).first()
            frais.append({
                "institution": str(institution.id), "nom": institution.nom, "annee": annee,
                "recus_fiscaux": r.recus_fiscaux, "kilometres": dispo["kilometres"], "montant": dispo["montant"],
                "abandon": None if abandon is None else {
                    "id": str(abandon.id), "statut": abandon.statut, "statut_libelle": abandon.get_statut_display(),
                    "numero_recu": abandon.numero_recu, "motif_refus": abandon.motif_refus,
                    "montant": (abandon.detail or {}).get("montant")},
            })
        return Response({
            "du": du, "au": au,
            "lignes": lignes,
            "total_heures": round(sum(l["heures"] or 0 for l in lignes), 2),
            "total_kilometres": round(sum(o.kilometres_nombre() for o in objets), 1),
            "manifestations": [{"id": str(m.id), "nom": m.titre, "debut": m.debut}
                               for m in ep.manifestations_declarables(request.user, environment)[:100]],
            "vehicules": [{"code": c, "libelle": l} for c, l in VehiculeBenevole.choices],
            "mes_vehicules": [_vehicule_en_dict(v) for v in ep.vehicules_de(request.user)],
            "frais": frais,
            "activite": ep.activite(request.user, environment, debut, fin),
            "crises": [{"id": str(c.id), "nom": c.name} for c in ep.crises_declarables(request.user, environment)],
            "equipes": [{"id": str(e.id), "nom": e.name} for e in ep.equipes_de(request.user).order_by("name")],
            "lieux": [{"code": c, "libelle": l} for c, l in LieuDeDepart.choices],
            # Vrai si la personne encadre au moins une équipe : elle a alors un second onglet.
            "encadre": (ep.equipes_encadrees(request.user).exists()
                        or bool(ep.institutions_relues_par(request.user, _collectivite_de_l_agent(request)))),
        })

    def post(self, request):
        from . import engagements_personnels as ep
        from .models import Team

        from .models import Manifestation
        environment = get_active_environment(request)
        crise = Crisis.objects.filter(id=request.data.get("crise"), environment=environment).first() \
            if request.data.get("crise") else None
        manifestation = Manifestation.objects.filter(id=request.data.get("manifestation"), environment=environment).first() \
            if request.data.get("manifestation") else None
        if crise is None and manifestation is None:
            raise ValidationError({"detail": "Indiquez la crise ou la manifestation."})
        equipe = Team.objects.filter(id=request.data.get("equipe")).first() if request.data.get("equipe") else None
        try:
            ligne = ep.completer(
                request.user, environment, crise=crise, equipe=equipe, manifestation=manifestation,
                parti_le=_instant(request.data.get("parti_le"), "Départ"),
                rentre_le=_instant(request.data.get("rentre_le"), "Retour"),
                depart_de=request.data.get("depart_de"), retour_a=request.data.get("retour_a"),
                kilometres=request.data.get("kilometres"), vehicule=request.data.get("vehicule"),
                deplacement=_deplacement(request.data),
            )
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_ligne_de_releve(ligne), status=status.HTTP_201_CREATED)


class MonReleveLigneView(APIView):
    """PATCH : corrige une de SES lignes (le retour oublié, une heure fausse). DELETE : retire
    une ligne qu'on a soi-même ajoutée à la main — une déclaration faite sur le moment se
    corrige, elle ne s'efface pas."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def _ligne(self, request, ligne_id):
        from django.shortcuts import get_object_or_404

        from .models import EngagementPersonnel
        return get_object_or_404(
            EngagementPersonnel.objects.select_related("crise", "equipe", "manifestation", "vehicule_personnel"),
            id=ligne_id, utilisateur=request.user, environment=get_active_environment(request))

    def patch(self, request, ligne_id):
        from . import engagements_personnels as ep

        ligne = self._ligne(request, ligne_id)
        donnees = request.data
        try:
            ep.corriger(
                ligne,
                parti_le=_instant(donnees["parti_le"], "Départ") if donnees.get("parti_le") else None,
                rentre_le=_instant(donnees["rentre_le"], "Retour") if donnees.get("rentre_le") else None,
                depart_de=donnees.get("depart_de"), retour_a=donnees.get("retour_a"),
                kilometres=donnees.get("kilometres"), vehicule=donnees.get("vehicule"),
                deplacement=_deplacement(donnees),
            )
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_ligne_de_releve(ligne))

    def delete(self, request, ligne_id):
        ligne = self._ligne(request, ligne_id)
        if ligne.valide_le is not None:
            raise ValidationError({"detail": "Cette ligne a été validée par votre encadrement."})
        if not ligne.saisie_manuelle:
            raise ValidationError({"detail": (
                "Cette ligne a été déclarée sur le moment : corrigez-la, elle ne se supprime pas."
            )})
        ligne.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MesVehiculesView(APIView):
    """GET : mes véhicules actifs. POST {genre, libelle, immatriculation, puissance_cv}."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import engagements_personnels as ep
        return Response([_vehicule_en_dict(v) for v in ep.vehicules_de(request.user)])

    def post(self, request):
        from .models import VehiculePersonnel
        v = VehiculePersonnel(utilisateur=request.user)
        _champs_vehicule(v, request.data)
        if VehiculePersonnel.objects.filter(utilisateur=request.user, actif=True).count() >= 10:
            raise ValidationError({"detail": "Dix véhicules au plus : retirez-en un."})
        v.save()
        return Response(_vehicule_en_dict(v), status=status.HTTP_201_CREATED)


def _champs_vehicule(v, donnees):
    from .models import VehiculeBenevole
    if "genre" in donnees:
        if donnees.get("genre") not in (VehiculeBenevole.VOITURE, VehiculeBenevole.DEUX_ROUES):
            raise ValidationError({"detail": "Voiture, ou moto et scooter."})
        v.genre = donnees["genre"]
    if "libelle" in donnees:
        v.libelle = str(donnees.get("libelle") or "").strip()[:80]
    if "immatriculation" in donnees:
        v.immatriculation = str(donnees.get("immatriculation") or "").strip().upper()[:20]
    if "puissance_cv" in donnees:
        texte = str(donnees.get("puissance_cv") or "").strip()
        if texte and (not texte.isdigit() or not 1 <= int(texte) <= 99):
            raise ValidationError({"detail": "Puissance fiscale : un nombre de chevaux (CV), de 1 à 99."})
        v.puissance_cv = str(int(texte)) if texte else ""
    if not (v.libelle or v.immatriculation):
        raise ValidationError({"detail": "Donnez au moins un nom ou l'immatriculation du véhicule."})


class MonVehiculeView(APIView):
    """PATCH : modifier un de mes véhicules. DELETE : le retirer (il reste sur les lignes passées)."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def _vehicule(self, request, vid):
        from django.shortcuts import get_object_or_404

        from .models import VehiculePersonnel
        return get_object_or_404(VehiculePersonnel, id=vid, utilisateur=request.user, actif=True)

    def patch(self, request, vid):
        v = self._vehicule(request, vid)
        _champs_vehicule(v, request.data)
        v.save()
        return Response(_vehicule_en_dict(v))

    def delete(self, request, vid):
        v = self._vehicule(request, vid)
        if v.engagements.exists():
            v.actif = False
            v.save(update_fields=["actif"])
        else:
            v.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FraisLigneView(APIView):
    """POST (multipart : nature, montant, fichier?) : un péage ou un stationnement sur une de
    MES lignes. DELETE <fid> : le retirer. Refusé sur une ligne validée."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def post(self, request, ligne_id):
        from . import engagements_personnels as ep
        ligne = MonReleveLigneView()._ligne(request, ligne_id)
        try:
            frais = ep.ajouter_frais(ligne, request.data.get("nature"), request.data.get("montant"),
                                     request.FILES.get("fichier"))
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_frais_en_dict(frais), status=status.HTTP_201_CREATED)

    def delete(self, request, ligne_id, fid):
        from django.shortcuts import get_object_or_404

        from . import engagements_personnels as ep
        ligne = MonReleveLigneView()._ligne(request, ligne_id)
        frais = get_object_or_404(ligne.frais, id=fid)
        try:
            ep.retirer_frais(frais)
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(status=status.HTTP_204_NO_CONTENT)


class JustificatifFraisView(APIView):
    """GET : le ticket d'un péage ou d'un stationnement — pour son auteur, pour qui relit la
    ligne (encadrement, bureau, mairie), ou pour le bureau de l'association de la ligne. 404
    pour tout autre : on ne dit pas qu'il existe."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def get(self, request, fid):
        from django.http import FileResponse, Http404
        from django.shortcuts import get_object_or_404

        from . import engagements_personnels as ep
        from . import manifestations as mf
        from .models import FraisDeplacement

        environment = get_active_environment(request)
        frais = get_object_or_404(FraisDeplacement.objects.select_related("engagement__manifestation", "engagement__equipe"),
                                  id=fid, engagement__environment=environment)
        ligne = frais.engagement
        permis = ligne.utilisateur_id == request.user.id or ep.a_relire_par(
            request.user, environment, _collectivite_de_l_agent(request)).filter(id=ligne.id).exists()
        if not permis:
            institutions = {i for i in (ligne.institution_id, ligne.equipe.institution_id if ligne.equipe_id else None,
                                        ligne.manifestation.institution_id if ligne.manifestation_id else None) if i}
            permis = any(mf.organise(request.user, i) for i in institutions)
        if not permis or not frais.justificatif:
            raise Http404
        return FileResponse(frais.justificatif.open("rb"), as_attachment=True, filename=frais.justificatif_nom or "ticket")


class MonReleveKmView(APIView):
    """GET ?institution=&du=&au= : mon relevé kilométrique PDF pour une de mes associations,
    lignes validées et en attente (marquées comme telles)."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime

        from django.http import HttpResponse
        from django.shortcuts import get_object_or_404
        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from . import benevolat
        from . import engagements_personnels as ep
        from .models import Institution

        environment = get_active_environment(request)
        institution = get_object_or_404(Institution, id=request.query_params.get("institution"))
        if institution.id not in ep.institutions_de(request.user):
            from . import manifestations as mf
            if institution.id not in set(mf.associations_de(request.user)):
                raise ValidationError({"detail": "Ce n'est pas l'une de vos associations."})
        au = parse_date(str(request.query_params.get("au") or "")) or timezone.localdate()
        du = parse_date(str(request.query_params.get("du") or "")) or datetime.date(au.year, 1, 1)
        if du > au or (au - du).days > 366:
            raise ValidationError({"detail": "Période invalide (un an au plus)."})
        pdf = benevolat.releve_km_pdf(request.user, institution, environment, du, au, validees_seulement=False)
        reponse = HttpResponse(pdf, content_type="application/pdf")
        reponse["Content-Disposition"] = f'attachment; filename="releve-km-{du:%Y%m%d}-{au:%Y%m%d}.pdf"'
        return reponse


def _collectivite_de_l_agent(request):
    """L'institution dont l'appelant est AGENT (compte institutionnel rattaché) : il en relit
    les relevés au même titre que le bureau d'une association. None pour un compte ordinaire —
    être membre d'une équipe de la mairie ne fait pas de quelqu'un son relecteur."""
    from .models import UserRole
    from .perimetre_admin import institution_regardee
    from .permissions import effective_role_or_none

    if effective_role_or_none(request) not in (UserRole.LOCAL_AUTHORITY, UserRole.ADMINISTRATOR):
        return None
    return institution_regardee(request)


class RelevesEquipeView(APIView):
    """Les relevés des équipes que l'appelant encadre : il les lit et les valide, il ne les
    corrige pas (décision du 17/11/2026 : seule la personne complète son relevé).

    GET ?du=&au= : les lignes, personne par personne.
    POST {ligne, geste: "valider" | "renvoyer", remarque?}."""
    from rest_framework.permissions import IsAuthenticated
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime

        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from . import engagements_personnels as ep
        from .views import _nommer_pour

        environment = get_active_environment(request)
        au = parse_date(str(request.query_params.get("au") or "")) or timezone.localdate()
        du = parse_date(str(request.query_params.get("du") or "")) or au - datetime.timedelta(days=30)
        debut = timezone.make_aware(datetime.datetime.combine(du, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(au, datetime.time.max))
        nommer = _nommer_pour(request)
        personnes = {}
        a_relire = (ep.a_relire_par(request.user, environment, _collectivite_de_l_agent(request))
                    .filter(parti_le__gte=debut, parti_le__lte=fin).select_related("vehicule_personnel", "manifestation")
                    .prefetch_related("frais").order_by("utilisateur_id", "-parti_le"))
        for ligne in a_relire:
            fiche = personnes.setdefault(ligne.utilisateur_id, {
                "personne": nommer(ligne.utilisateur) or "Membre d'équipe", "lignes": [],
                "total_heures": 0, "heures_validees": 0, "a_valider": 0,
            })
            donnees = _ligne_de_releve(ligne)
            fiche["lignes"].append(donnees)
            heures = donnees["heures"] or 0
            fiche["total_heures"] = round(fiche["total_heures"] + heures, 2)
            if donnees["validee"]:
                fiche["heures_validees"] = round(fiche["heures_validees"] + heures, 2)
            elif donnees["heures"] is not None and not donnees["remarque_chef"]:
                fiche["a_valider"] += 1
        return Response({
            "du": du, "au": au,
            "fiches": sorted(personnes.values(), key=lambda f: f["personne"].casefold()),
        })

    def post(self, request):
        from django.shortcuts import get_object_or_404

        from . import engagements_personnels as ep
        from .models import EngagementPersonnel

        environment = get_active_environment(request)
        ligne = get_object_or_404(
            EngagementPersonnel.objects.select_related("crise", "equipe", "manifestation"),
            id=request.data.get("ligne"), environment=environment)
        try:
            agent_de = _collectivite_de_l_agent(request)
            if request.data.get("geste") == "valider":
                ep.valider(ligne, request.user, environment, agent_de)
            elif request.data.get("geste") == "renvoyer":
                ep.renvoyer(ligne, request.user, environment, request.data.get("remarque"), agent_de)
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except ep.ErreurEngagement as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_ligne_de_releve(ligne))


class PointDeSituationView(APIView):
    """GET /api/point-de-situation/?crise=<id> — les chiffres de la crise pour la collectivité
    de l'appelant, rassemblés et en texte prêt à coller."""
    permission_classes = [IsInstitutionalActor]

    def get(self, request):
        crise = Crisis.objects.filter(
            id=request.query_params.get("crise"), environment=get_active_environment(request)).first() \
            if request.query_params.get("crise") else None
        if crise is None:
            raise ValidationError({"crise": "Indiquez la crise."})
        from .views import _nommer_pour
        return Response(point_situation.construire(
            crise, _institution_ou_refus(request), get_active_environment(request),
            nommer=_nommer_pour(request)))
