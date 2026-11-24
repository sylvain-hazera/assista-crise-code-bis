"""Les alertes automatiques d'une collectivité (core/alertes_naturelles.py) : la matrice des
règles, l'historique des alertes, et les deux gestes qui en partent — ouvrir une crise,
demander les disponibilités (24/11/2026)."""
import datetime

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import alertes_naturelles
from .audit import audit_log
from .models import AlerteNaturelle, Institution, RegleAlerte
from .permissions import INSTITUTIONAL_TYPES, get_active_environment, get_effective_role


def _institution(request, institution_id, ecriture=False):
    from .perimetre_admin import institutions_visibles

    if not institution_id:
        institution_id = _par_defaut(request)
    if not institution_id:
        raise ValidationError({"institution": "Précisez la collectivité."})
    institution = get_object_or_404(Institution, pk=institution_id)
    visibles = institutions_visibles(request)
    if visibles is not None and institution.pk not in set(visibles):
        raise PermissionDenied("Cette collectivité n'est pas la vôtre.")
    if ecriture and get_effective_role(request) not in INSTITUTIONAL_TYPES:
        raise PermissionDenied("Régler les alertes est réservé aux responsables de la collectivité.")
    return institution


def _mes_institutions(request):
    """Les collectivités où l'appelant est membre actif (contact principal d'abord), puis la sienne."""
    from .models import ContactInstitution

    contacts = (ContactInstitution.objects.filter(utilisateur=request.user, actif=True)
                .select_related("institution").order_by("-contact_principal"))
    choix = {c.institution_id: c.institution for c in contacts}
    if request.user.institution_id and request.user.institution_id not in choix:
        choix[request.user.institution_id] = request.user.institution
    return list(choix.values())


def _par_defaut(request):
    mes = _mes_institutions(request)
    return mes[0].pk if mes else None


def _regle_en_dict(regle):
    if regle is None:
        return None
    return {"id": str(regle.id), "actif": regle.actif, "seuils": regle._valeurs(), "email": regle.email,
            "radio_si_exceptionnel": regle.radio_si_exceptionnel, "silence_nuit": regle.silence_nuit,
            "destinataires": regle.destinataires, "modifie_le": regle.modifie_le}


def alerte_en_dict(alerte):
    phenomene = alertes_naturelles.PAR_CODE.get(alerte.phenomene)
    return {
        "id": str(alerte.id), "phenomene": alerte.phenomene, "phenomene_libelle": phenomene.libelle if phenomene else alerte.phenomene,
        "famille": phenomene.famille if phenomene else "", "niveau": alerte.niveau, "valeur": alerte.valeur,
        "unite": phenomene.unite if phenomene else "", "titre": alerte.titre, "detail": alerte.detail,
        "latitude": alerte.lieu.y if alerte.lieu else None, "longitude": alerte.lieu.x if alerte.lieu else None,
        "emise_le": alerte.emise_le, "bilan": alerte.bilan or {}, "institution": str(alerte.institution_id),
        "crise": str(alerte.crise_id) if alerte.crise_id else None,
        "crise_nom": alerte.crise.name if alerte.crise_id else None,
        "campagne": str(alerte.campagne_id) if alerte.campagne_id else None,
        "type_crise": phenomene.type_crise if phenomene else "AUTRE",
    }


def matrice(request, institution):
    from . import sources_ouvertes

    environment = get_active_environment(request)
    regles = {r.phenomene: r for r in RegleAlerte.objects.filter(institution=institution, environment=environment)}
    dernieres = {}
    alertes = list(AlerteNaturelle.objects.filter(institution=institution, environment=environment)
                   .select_related("crise")[:60])
    for alerte in alertes:
        dernieres.setdefault(alerte.phenomene, alerte.emise_le)
    perimetre = alertes_naturelles.perimetre_de(institution)
    lignes = []
    for p in alertes_naturelles.CATALOGUE:
        source = sources_ouvertes.resume(p.source) if p.source in sources_ouvertes.SOURCES else {}
        lignes.append({
            "code": p.code, "libelle": p.libelle, "famille": p.famille, "unite": p.unite,
            "conseille": alertes_naturelles.valeurs_conseillees(p), "minimum": p.minimum, "maximum": p.maximum,
            "pas": p.pas, "radio_possible": p.radio,
            "reglages": {nom: {"defaut": d, "minimum": mi, "maximum": ma} for nom, (d, mi, ma) in p.reglages.items()},
            "echelle": {str(k): v for k, v in (p.echelle or {}).items()},
            "source": source, "regle": _regle_en_dict(regles.get(p.code)), "derniere_alerte": dernieres.get(p.code),
        })
    choix = _mes_institutions(request)
    if institution.pk not in {i.pk for i in choix}:
        choix.insert(0, institution)
    return {
        "institution": {"id": str(institution.id), "nom": institution.nom},
        "choix": [{"id": str(i.pk), "nom": i.nom} for i in choix],
        "perimetre": ({"niveau": perimetre.niveau, "code": perimetre.code, "communes": len(perimetre.communes)}
                      if perimetre else None),
        "phenomenes": lignes,
        "alertes": [alerte_en_dict(a) for a in alertes],
    }


class AlertesAutomatiquesView(APIView):
    """GET : la matrice d'une collectivité (catalogue, sa règle par phénomène, l'état de chaque
    source) et ses dernières alertes."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        institution = _institution(request, request.query_params.get("institution"))
        return Response(matrice(request, institution))


class RegleAlerteView(APIView):
    """POST : enregistre une ligne de la matrice (créée au premier réglage)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        institution = _institution(request, request.data.get("institution"), ecriture=True)
        phenomene = alertes_naturelles.PAR_CODE.get(request.data.get("phenomene"))
        if phenomene is None:
            raise ValidationError({"phenomene": "Phénomène inconnu."})
        environment = get_active_environment(request)
        regle = RegleAlerte.objects.filter(institution=institution, phenomene=phenomene.code, environment=environment).first() \
            or RegleAlerte(institution=institution, phenomene=phenomene.code, environment=environment)
        try:
            regle.seuils = alertes_naturelles.valider_seuils(phenomene, request.data.get("seuils", regle.seuils))
        except (TypeError, ValueError) as erreur:
            raise ValidationError({"seuils": str(erreur)})
        for champ in ("actif", "email", "radio_si_exceptionnel", "silence_nuit"):
            if champ in request.data:
                setattr(regle, champ, bool(request.data[champ]))
        if request.data.get("destinataires") in dict(RegleAlerte.DESTINATAIRES):
            regle.destinataires = request.data["destinataires"]
        regle.modifie_par = request.user
        regle.save()
        audit_log(request=request, action_code="MODIFICATION", objet_type="RegleAlerte", objet_id=regle.id,
                  commentaire=f"Alerte automatique « {phenomene.libelle} » {'activée' if regle.actif else 'désactivée'} "
                              f"pour {institution.nom}", institution=institution)
        return Response(_regle_en_dict(regle))


class ToutesReglesAlerteView(APIView):
    """POST {institution, actif} : tout activer avec les valeurs conseillées, ou tout couper."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        institution = _institution(request, request.data.get("institution"), ecriture=True)
        actif = bool(request.data.get("actif"))
        environment = get_active_environment(request)
        for p in alertes_naturelles.CATALOGUE:
            regle = RegleAlerte.objects.filter(institution=institution, phenomene=p.code, environment=environment).first()
            if regle is None:
                if not actif:
                    continue
                regle = RegleAlerte(institution=institution, phenomene=p.code, environment=environment,
                                    seuils=alertes_naturelles.valeurs_conseillees(p))
            regle.actif = actif
            regle.modifie_par = request.user
            regle.save()
        audit_log(request=request, action_code="MODIFICATION", objet_type="RegleAlerte",
                  commentaire=f"Toutes les alertes automatiques {'activées' if actif else 'désactivées'} pour {institution.nom}",
                  institution=institution)
        return Response(matrice(request, institution))


def _alerte(request, alerte_id):
    alerte = get_object_or_404(AlerteNaturelle.objects.select_related("institution", "crise"), pk=alerte_id,
                               environment=get_active_environment(request))
    _institution(request, alerte.institution_id)
    return alerte


class AlerteNaturelleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, alerte_id):
        return Response(alerte_en_dict(_alerte(request, alerte_id)))


class CriseDepuisAlerteView(APIView):
    """GET : ce qui préremplit la déclaration de crise ; POST {crise} : relie la crise créée."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, alerte_id):
        alerte = _alerte(request, alerte_id)
        donnees = alerte_en_dict(alerte)
        return Response({"type": donnees["type_crise"], "titre": alerte.titre[:120],
                         "description": f"{alerte.titre}\n\n{alerte.detail}\n\n(Ouverte depuis une alerte automatique du "
                                        f"{timezone.localtime(alerte.emise_le):%d/%m/%Y à %H h %M}.)",
                         "latitude": donnees["latitude"], "longitude": donnees["longitude"],
                         "institution": str(alerte.institution_id)})

    def post(self, request, alerte_id):
        from .models import Crisis

        alerte = _alerte(request, alerte_id)
        if get_effective_role(request) not in INSTITUTIONAL_TYPES:
            raise PermissionDenied()
        crise = get_object_or_404(Crisis, pk=request.data.get("crise"))
        alerte.crise = crise
        alerte.save(update_fields=["crise"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="AlerteNaturelle", objet_id=alerte.id,
                  crise=crise, commentaire="Crise ouverte depuis une alerte automatique", institution=alerte.institution)
        return Response(alerte_en_dict(alerte))


def _ciblage(institution):
    """Le territoire de la collectivité : sa commune, ou son département ; national sinon."""
    niveau = institution.secteur_niveau_effectif or "commune"
    if niveau == "commune" and institution.commune_code:
        return {"echelon": "COMMUNE", "territoire_code": institution.commune_code}
    if niveau in ("epci", "departement") and institution.departement_code:
        return {"echelon": "DEPARTEMENT", "territoire_code": institution.departement_code}
    if niveau == "region" and institution.region_code:
        return {"echelon": "REGION", "territoire_code": institution.region_code}
    return {}


class DisponibilitesDepuisAlerteView(APIView):
    """POST : prépare une campagne de disponibilités « Crise à venir » en brouillon. Rien ne part :
    la campagne s'ouvre dans son écran pour être relue et envoyée."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, alerte_id):
        from .campagnes_disponibilite import peut_lancer_campagne
        from .canaux_campagne import CANAL_APPLICATION, CANAL_EMAIL
        from .models import CampagneDisponibilite

        alerte = _alerte(request, alerte_id)
        if alerte.campagne_id:
            return Response({**alerte_en_dict(alerte), "campagne_creee": False})
        if not peut_lancer_campagne(request.user, alerte.institution):
            raise PermissionDenied("Demander les disponibilités est réservé aux responsables de la collectivité.")
        aujourd_hui = timezone.localdate()
        campagne = CampagneDisponibilite.objects.create(
            institution=alerte.institution, cree_par=request.user, motif="CRISE_A_VENIR",
            intitule=f"Préparation : {alerte.titre}"[:200],
            texte=f"{alerte.titre}.\n{alerte.detail}\n\nMerci d'indiquer vos disponibilités pour les jours qui viennent.",
            crise=alerte.crise, periode_debut=aujourd_hui, periode_fin=aujourd_hui + datetime.timedelta(days=2),
            canaux=[CANAL_APPLICATION, CANAL_EMAIL], environment=alerte.environment, **_ciblage(alerte.institution))
        alerte.campagne = campagne
        alerte.save(update_fields=["campagne"])
        audit_log(request=request, action_code="CREATION", objet_type="CampagneDisponibilite", objet_id=campagne.id,
                  commentaire="Campagne « Crise à venir » préparée depuis une alerte automatique", institution=alerte.institution)
        return Response({**alerte_en_dict(alerte), "campagne_creee": True}, status=201)
