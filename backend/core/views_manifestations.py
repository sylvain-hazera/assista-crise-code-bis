"""API des manifestations d'association et du bénévolat (26/11/2026) — voir core/manifestations.py
et core/benevolat.py.

Tout est calculé à partir de l'appartenance réelle (ContactInstitution) : un compte ordinaire de
bénévole voit les manifestations de ses associations ; le bureau les organise, pointe, valorise.
"""
import datetime
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import benevolat, manifestations as mf
from .audit import audit_log
from .models import (
    AbandonFrais, InscriptionPoste, Institution, Manifestation, PosteManifestation, StatutInscriptionPoste,
    StatutManifestation, TypeManifestation,
)
from .permissions import get_active_environment


#: Les types de points qu'un poste de manifestation peut prendre (26/11/2026).
TYPES_POINTS_POSTE = ["PC_MANIFESTATION", "SIGNALISATION", "TRANSIT", "SECOURS", "REGROUPEMENT_MOYENS", "AUTRE"]


def _instant(valeur, champ):
    instant = parse_datetime(str(valeur or ""))
    if instant is None:
        raise ValidationError({"detail": f"{champ} : date et heure attendues."})
    return timezone.make_aware(instant) if timezone.is_naive(instant) else instant


def _texte(valeur, maxi):
    return str(valeur or "").strip()[:maxi]


def _nom(u):
    return f"{u.first_name} {u.last_name}".strip() or u.email


def _poste_en_dict(poste, utilisateur, bureau: bool) -> dict:
    inscriptions = list(poste.inscriptions.all())
    occupes = sum(1 for i in inscriptions if i.statut in mf.ACTIVES)
    attente = sorted((i for i in inscriptions if i.statut == StatutInscriptionPoste.LISTE_ATTENTE), key=lambda i: i.inscrit_le)
    moi = next((i for i in inscriptions if i.utilisateur_id == utilisateur.id), None)
    d = {
        "id": str(poste.id), "intitule": poste.intitule, "debut": poste.debut, "fin": poste.fin,
        "places": poste.places, "occupes": occupes, "attente": len(attente), "remarque": poste.remarque,
        "type_point": poste.type_point.code if poste.type_point_id else None,
        "type_point_libelle": poste.type_point.libelle if poste.type_point_id else "",
        "latitude": poste.location.y if poste.location else None,
        "longitude": poste.location.x if poste.location else None,
        "mon_statut": moi.statut if moi else None,
        "mon_rang_attente": (attente.index(moi) + 1) if moi in attente else None,
    }
    if bureau:
        d["inscrits"] = [{"id": str(i.id), "utilisateur": str(i.utilisateur_id), "nom": _nom(i.utilisateur),
                          "statut": i.statut, "inscrit_le": i.inscrit_le, "pointe_le": i.pointe_le}
                         for i in sorted(inscriptions, key=lambda i: i.inscrit_le) if i.statut != StatutInscriptionPoste.DESISTE]
    return d


def _en_dict(m, utilisateur, detail=False) -> dict:
    bureau = mf.organise(utilisateur, m.institution_id)
    postes = list(m.postes.all())
    d = {
        "id": str(m.id), "institution": str(m.institution_id), "institution_nom": m.institution.nom,
        "type": m.type, "type_libelle": m.get_type_display(), "titre": m.titre, "lieu": m.lieu,
        "organisateur": m.organisateur, "debut": m.debut, "fin": m.fin, "statut": m.statut,
        "statut_libelle": m.get_statut_display(), "commune_code": m.commune_code,
        "places": sum(p.places for p in postes),
        "occupes": sum(1 for p in postes for i in p.inscriptions.all() if i.statut in mf.ACTIVES),
        "je_suis_inscrit": any(i.utilisateur_id == utilisateur.id and i.statut in mf.ACTIVES for p in postes for i in p.inscriptions.all()),
        "organise": bureau,
        "communes": list(m.communes or ([m.commune_code] if m.commune_code else [])),
        # Le lieu (27/11/2026) : la carte hors ligne de l'application couvre la manifestation + 15 km.
        "latitude": m.location.y if m.location else None, "longitude": m.location.x if m.location else None,
    }
    if detail:
        from . import partage_manifestation as pm
        # Ce que chaque commune partage : le tableau pour le bureau, ce qui est ouvert pour tous.
        d["partages"] = [dict(pm.tableau(p) if bureau else {"id": str(p.id), "commune_code": p.commune_code,
                                                             "mairie": p.mairie.nom if p.mairie else None},
                              ouvert=pm.ce_qui_est_ouvert(p))
                         for p in m.partages.select_related("mairie").prefetch_related("lignes")]
        d["consignes"] = m.consignes
        d["postes"] = [_poste_en_dict(p, utilisateur, bureau) for p in postes]
        # Où l'application peut poser un marqueur (28/11/2026) : autour de ces points.
        from . import zones_marqueurs
        d["zone_points"] = [[round(la, 5), round(lo, 5)] for la, lo in zones_marqueurs.points_de_manifestation(m)]
        d["zone_rayon_km"] = zones_marqueurs.RAYON_MANIFESTATION_KM
        d["documents"] = [{"id": str(doc.id), "nom": (doc.metadata_publiques or {}).get("nom") or doc.fichier.name.rsplit("/", 1)[-1]}
                          for doc in m.documents.all()]
    return d


def _manifestation(request, pk):
    environment = get_active_environment(request)
    m = mf.visibles_par(request.user, environment).filter(id=pk).select_related("institution").first()
    if m is None:
        raise PermissionDenied("Manifestation introuvable, ou réservée aux membres de l'association.")
    return m


def _exiger_bureau(request, institution_id):
    if not mf.organise(request.user, institution_id):
        raise PermissionDenied("Réservé au bureau de l'association.")


def _champs(m, donnees):
    if "type" in donnees:
        if donnees["type"] not in TypeManifestation.values:
            raise ValidationError({"detail": "Type de manifestation inconnu."})
        m.type = donnees["type"]
    for champ, maxi in (("titre", 200), ("lieu", 300), ("organisateur", 300), ("consignes", 20000)):
        if champ in donnees:
            setattr(m, champ, _texte(donnees[champ], maxi))
    if "commune_code" in donnees:
        m.commune_code = _texte(donnees["commune_code"], 10)
    if "communes" in donnees:
        # Les communes traversées (26/11/2026) : chacune est invitée à la publication.
        m.communes = [_texte(c, 10) for c in (donnees.get("communes") or []) if str(c or "").strip()][:30]
        if m.communes and not m.commune_code:
            m.commune_code = m.communes[0]
    if "debut" in donnees:
        m.debut = _instant(donnees["debut"], "Début")
    if "fin" in donnees:
        m.fin = _instant(donnees["fin"], "Fin")
    if not m.titre:
        raise ValidationError({"detail": "Donnez un titre à la manifestation."})
    if m.fin <= m.debut:
        raise ValidationError({"detail": "La fin doit suivre le début."})


def _poste(m, donnees, poste=None):
    poste = poste or PosteManifestation(manifestation=m, environment=m.environment)
    if "intitule" in donnees:
        poste.intitule = _texte(donnees["intitule"], 200)
    if "remarque" in donnees:
        poste.remarque = _texte(donnees["remarque"], 2000)
    nouveau = poste._state.adding
    poste.debut = _instant(donnees["debut"], "Début du poste") if "debut" in donnees else (m.debut if nouveau else poste.debut)
    poste.fin = _instant(donnees["fin"], "Fin du poste") if "fin" in donnees else (m.fin if nouveau else poste.fin)
    if "places" in donnees:
        try:
            poste.places = max(1, min(500, int(donnees["places"])))
        except (TypeError, ValueError):
            raise ValidationError({"detail": "Nombre de places : un entier est attendu."})
    if "type_point" in donnees:
        from .models import PointType
        code = str(donnees.get("type_point") or "")
        poste.type_point = PointType.objects.filter(code=code, actif=True).first() if code else None
        if code and poste.type_point is None:
            raise ValidationError({"detail": "Type de point inconnu."})
    if "latitude" in donnees or "longitude" in donnees:
        from django.contrib.gis.geos import Point
        try:
            lat, lon = donnees.get("latitude"), donnees.get("longitude")
            poste.location = Point(float(lon), float(lat), srid=4326) if lat not in (None, "") and lon not in (None, "") else None
        except (TypeError, ValueError):
            raise ValidationError({"detail": "Position invalide."})
        if poste.location is not None and not (-90 <= poste.location.y <= 90 and -180 <= poste.location.x <= 180):
            raise ValidationError({"detail": "Position invalide."})
    if not poste.intitule:
        raise ValidationError({"detail": "Donnez un intitulé au poste (« Carrefour D936, signaleur »)."})
    if poste.fin <= poste.debut:
        raise ValidationError({"detail": "La fin du poste doit suivre son début."})
    poste.save()
    return poste


class ManifestationsView(APIView):
    """GET ?du=&au= : les manifestations visibles. POST : en créer une (bureau), brouillon."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        environment = get_active_environment(request)
        du = parse_date(str(request.query_params.get("du") or "")) or timezone.localdate() - datetime.timedelta(days=31)
        au = parse_date(str(request.query_params.get("au") or "")) or du + datetime.timedelta(days=400)
        qs = (mf.visibles_par(request.user, environment)
              .filter(fin__gte=timezone.make_aware(datetime.datetime.combine(du, datetime.time.min)),
                      debut__lte=timezone.make_aware(datetime.datetime.combine(au, datetime.time.max)))
              .select_related("institution").prefetch_related("postes__inscriptions").order_by("debut"))
        organisees = Institution.objects.filter(id__in=mf.associations_organisees_par(request.user)).order_by("nom")
        from .models import PointType
        return Response({
            "manifestations": [_en_dict(m, request.user) for m in qs[:500]],
            # Les types de points proposés pour un poste (catalogue des points de crise).
            "types_points": [{"code": t.code, "libelle": t.libelle} for t in PointType.objects.filter(
                actif=True, code__in=TYPES_POINTS_POSTE).order_by("libelle")],
            "associations_organisees": [{"id": str(i.id), "nom": i.nom} for i in organisees],
            "types": [{"code": c, "libelle": l} for c, l in TypeManifestation.choices],
        })

    def post(self, request):
        environment = get_active_environment(request)
        institution = get_object_or_404(Institution, id=request.data.get("institution"))
        _exiger_bureau(request, institution.id)
        m = Manifestation(institution=institution, environment=environment, cree_par=request.user, titre="")
        _champs(m, request.data)
        m.save()
        for p in request.data.get("postes") or []:
            _poste(m, p)
        from . import partage_manifestation as pm
        demandes = request.data.get("demandes")
        pm.preparer(m, demandes=demandes if isinstance(demandes, list) else None, request=request)
        audit_log(request=request, action_code="CREATION", objet_type="Manifestation", objet_id=m.id,
                  commentaire=f"Manifestation créée pour {institution.nom}")
        return Response(_en_dict(m, request.user, detail=True), status=status.HTTP_201_CREATED)


class ManifestationView(APIView):
    """GET : détail. PATCH : modifier (bureau ; inscrits prévenus si horaires ou lieu changent).
    DELETE : supprimer un brouillon."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        return Response(_en_dict(_manifestation(request, pk), request.user, detail=True))

    def patch(self, request, pk):
        m = _manifestation(request, pk)
        _exiger_bureau(request, m.institution_id)
        avant = (m.debut, m.fin, m.lieu)
        _champs(m, request.data)
        m.save()
        if "communes" in request.data or "demandes" in request.data:
            from . import partage_manifestation as pm
            from .models import LignePartage, OriginePartage
            demandes = request.data.get("demandes")
            if not isinstance(demandes, list):
                demandes = list(LignePartage.objects.filter(partage__manifestation=m, origine=OriginePartage.DEMANDE_ASSOCIATION)
                                .values_list("element", flat=True).distinct())
            pm.preparer(m, demandes=demandes, request=request)
        if (m.debut, m.fin, m.lieu) != avant:
            mf.horaires_changes(m)
        return Response(_en_dict(m, request.user, detail=True))

    def delete(self, request, pk):
        m = _manifestation(request, pk)
        _exiger_bureau(request, m.institution_id)
        if m.statut != StatutManifestation.BROUILLON:
            raise ValidationError({"detail": "Une manifestation publiée ne se supprime pas : annulez-la."})
        m.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManifestationGesteView(APIView):
    """POST {geste: publier | annuler | terminer, motif?} (bureau)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        m = _manifestation(request, pk)
        geste = request.data.get("geste")
        try:
            if geste == "publier":
                mf.publier(m, request.user)
            elif geste == "annuler":
                mf.annuler(m, request.user, str(request.data.get("motif") or ""))
            elif geste == "terminer":
                _exiger_bureau(request, m.institution_id)
                m.statut = StatutManifestation.TERMINEE
                m.save(update_fields=["statut", "date_maj"])
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except mf.ErreurManifestation as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="Manifestation", objet_id=m.id,
                  commentaire=f"Manifestation : {geste}")
        return Response(_en_dict(m, request.user, detail=True))


class PostesView(APIView):
    """POST : ajouter un poste à une manifestation (bureau)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        m = _manifestation(request, pk)
        _exiger_bureau(request, m.institution_id)
        _poste(m, request.data)
        return Response(_en_dict(m, request.user, detail=True), status=status.HTTP_201_CREATED)


class PosteView(APIView):
    """PATCH / DELETE d'un poste (bureau) ; POST {geste: inscrire | desister} (membre)."""
    permission_classes = [IsAuthenticated]

    def _poste(self, request, pid):
        poste = get_object_or_404(PosteManifestation.objects.select_related("manifestation__institution"), id=pid)
        _manifestation(request, poste.manifestation_id)
        return poste

    def patch(self, request, pid):
        poste = self._poste(request, pid)
        _exiger_bureau(request, poste.manifestation.institution_id)
        _poste(poste.manifestation, request.data, poste)
        mf.monter_la_liste(poste)
        return Response(_en_dict(poste.manifestation, request.user, detail=True))

    def delete(self, request, pid):
        poste = self._poste(request, pid)
        m = poste.manifestation
        _exiger_bureau(request, m.institution_id)
        if poste.inscriptions.filter(statut__in=mf.ACTIVES).exists():
            raise ValidationError({"detail": "Des bénévoles sont inscrits sur ce poste : prévenez-les avant de le retirer."})
        poste.delete()
        return Response(_en_dict(m, request.user, detail=True))

    def post(self, request, pid):
        poste = self._poste(request, pid)
        try:
            if request.data.get("geste") == "inscrire":
                mf.inscrire(poste, request.user)
            elif request.data.get("geste") == "desister":
                mf.desister(poste, request.user)
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except mf.ErreurManifestation as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_en_dict(poste.manifestation, request.user, detail=True))


class PointageView(APIView):
    """POST {present: true|false} : pointer une inscription (bureau)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, iid):
        inscription = get_object_or_404(InscriptionPoste.objects.select_related("poste__manifestation__institution"), id=iid)
        _manifestation(request, inscription.poste.manifestation_id)
        try:
            mf.pointer(inscription, bool(request.data.get("present")), request.user)
        except mf.ErreurManifestation as erreur:
            raise ValidationError({"detail": str(erreur)})
        return Response(_en_dict(inscription.poste.manifestation, request.user, detail=True))


class MonCalendrierView(APIView):
    """GET : fichier iCalendar des manifestations où je suis inscrit, à importer dans son agenda."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        environment = get_active_environment(request)
        qs = (Manifestation.objects.filter(
            environment=environment, postes__inscriptions__utilisateur=request.user,
            postes__inscriptions__statut__in=mf.ACTIVES + (StatutInscriptionPoste.LISTE_ATTENTE,),
            fin__gte=timezone.now() - datetime.timedelta(days=30))
            .exclude(statut=StatutManifestation.BROUILLON).distinct().order_by("debut"))
        reponse = HttpResponse(mf.ical(qs), content_type="text/calendar; charset=utf-8")
        reponse["Content-Disposition"] = 'attachment; filename="mes-manifestations.ics"'
        return reponse


# --- Bénévolat (bureau) -------------------------------------------------------------------------

def _association(request, depuis):
    institution = get_object_or_404(Institution, id=depuis.get("institution"))
    _exiger_bureau(request, institution.id)
    return institution


def _annee(valeur):
    try:
        annee = int(valeur or timezone.localdate().year)
    except (TypeError, ValueError):
        raise ValidationError({"detail": "Année invalide."})
    if not 2020 <= annee <= 2100:
        raise ValidationError({"detail": "Année invalide."})
    return annee


def _decimal(valeur, champ):
    if valeur in (None, ""):
        return None
    try:
        d = Decimal(str(valeur).replace(",", "."))
    except InvalidOperation:
        raise ValidationError({"detail": f"{champ} : un nombre est attendu."})
    if d < 0 or d > 1000:
        raise ValidationError({"detail": f"{champ} : valeur hors bornes."})
    return d


def _abandon_en_dict(a) -> dict:
    d = a.detail or {}
    return {"id": str(a.id), "utilisateur": str(a.utilisateur_id), "nom": _nom(a.utilisateur), "annee": a.annee,
            "statut": a.statut, "statut_libelle": a.get_statut_display(), "montant": d.get("montant"),
            "kilometres": d.get("kilometres"), "deplacements": len(d.get("lignes", [])), "numero_recu": a.numero_recu,
            "date_recu": a.date_recu, "motif_refus": a.motif_refus, "date_demande": a.date_demande}


class BenevolatView(APIView):
    """GET ?institution=&annee= : valorisation de l'année, demandes d'abandon (bureau)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        environment = get_active_environment(request)
        organisees = Institution.objects.filter(id__in=mf.associations_organisees_par(request.user)).order_by("nom")
        if not request.query_params.get("institution"):
            return Response({"associations_organisees": [{"id": str(i.id), "nom": i.nom} for i in organisees]})
        institution = _association(request, request.query_params)
        annee = _annee(request.query_params.get("annee"))
        donnees = benevolat.valorisation(institution, environment, annee)
        donnees["abandons"] = [_abandon_en_dict(a) for a in AbandonFrais.objects.filter(
            institution=institution, annee=annee, environment=environment).select_related("utilisateur")]
        donnees["associations_organisees"] = [{"id": str(i.id), "nom": i.nom} for i in organisees]
        donnees["taux_reduction_informatif"] = benevolat.TAUX_REDUCTION_INFORMATIF
        return Response(donnees)


class ReglagesBenevolatView(APIView):
    """PUT {institution, annee, taux_horaire, tarif_km_voiture, tarif_km_deux_roues, recus_fiscaux,
    fondement_recus, signataire_nom, signataire_qualite} (bureau)."""
    permission_classes = [IsAuthenticated]

    def put(self, request):
        environment = get_active_environment(request)
        institution = _association(request, request.data)
        r = benevolat.reglages(institution, _annee(request.data.get("annee")), environment)
        r.taux_horaire = _decimal(request.data.get("taux_horaire"), "Taux horaire")
        r.tarif_km_voiture = _decimal(request.data.get("tarif_km_voiture"), "Tarif voiture")
        r.tarif_km_deux_roues = _decimal(request.data.get("tarif_km_deux_roues"), "Tarif deux-roues")
        if "tarifs_km_puissance" in request.data:
            tarifs = {}
            for tranche, valeur in dict(request.data.get("tarifs_km_puissance") or {}).items():
                if str(tranche) not in ("3", "4", "5", "6", "7"):
                    raise ValidationError({"detail": "Tranches de puissance : 3 (et moins) à 7 (et plus)."})
                d = _decimal(valeur, f"Tarif {tranche} CV")
                if d:
                    tarifs[str(tranche)] = str(d)
            r.tarifs_km_puissance = tarifs
        r.recus_fiscaux = bool(request.data.get("recus_fiscaux"))
        r.fondement_recus = _texte(request.data.get("fondement_recus"), 300)
        r.signataire_nom = _texte(request.data.get("signataire_nom"), 150)
        r.signataire_qualite = _texte(request.data.get("signataire_qualite"), 100)
        r.modifie_par = request.user
        r.save()
        audit_log(request=request, action_code="MODIFICATION", objet_type="ReglagesBenevolat", objet_id=r.id,
                  commentaire=f"Réglages du bénévolat {r.annee} de {institution.nom}")
        return Response(benevolat.reglages_en_dict(r))


class ExportBenevolatView(APIView):
    """GET ?institution=&annee=&fichier=csv|xlsx (« format » est réservé par DRF) : les lignes validées, pour le comptable (bureau)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        environment = get_active_environment(request)
        institution = _association(request, request.query_params)
        annee = _annee(request.query_params.get("annee"))
        contenu, mime, ext = benevolat.export_lignes(
            institution, environment, annee, "xlsx" if request.query_params.get("fichier") == "xlsx" else "csv")
        audit_log(request=request, action_code="EXPORT", objet_type="Institution", objet_id=institution.id,
                  commentaire=f"Export du bénévolat {annee}")
        reponse = HttpResponse(contenu, content_type=mime)
        reponse["Content-Disposition"] = f'attachment; filename="benevolat-{annee}.{ext}"'
        return reponse


class ReleveKmBureauView(APIView):
    """GET ?institution=&utilisateur=&annee= : le relevé kilométrique PDF d'un bénévole, lignes
    validées de l'année seulement (bureau, 28/11/2026)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import User

        environment = get_active_environment(request)
        institution = _association(request, request.query_params)
        annee = _annee(request.query_params.get("annee"))
        benevole = get_object_or_404(User, id=request.query_params.get("utilisateur"))
        if not benevolat.lignes_de(institution, environment, annee, benevole):
            # Pas de relevé pour quelqu'un qui n'a rien de validé chez nous : rien à dire de lui.
            raise ValidationError({"detail": "Aucune ligne validée de ce bénévole sur cette année."})
        pdf = benevolat.releve_km_pdf(benevole, institution, environment, datetime.date(annee, 1, 1),
                                      datetime.date(annee, 12, 31), validees_seulement=True)
        audit_log(request=request, action_code="EXPORT", objet_type="Institution", objet_id=institution.id,
                  commentaire=f"Relevé kilométrique {annee} d'un bénévole")
        reponse = HttpResponse(pdf, content_type="application/pdf")
        reponse["Content-Disposition"] = f'attachment; filename="releve-km-{annee}.pdf"'
        return reponse


class AbandonGesteView(APIView):
    """POST {geste: accepter | refuser, motif?} sur une demande d'abandon de frais (bureau)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, aid):
        abandon = get_object_or_404(AbandonFrais.objects.select_related("institution", "utilisateur"),
                                    id=aid, environment=get_active_environment(request))
        _exiger_bureau(request, abandon.institution_id)
        try:
            if request.data.get("geste") == "accepter":
                benevolat.accepter_abandon(abandon, request.user)
            elif request.data.get("geste") == "refuser":
                benevolat.refuser_abandon(abandon, request.user, request.data.get("motif"))
            else:
                raise ValidationError({"detail": "Geste inconnu."})
        except benevolat.ErreurBenevolat as erreur:
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="AbandonFrais", objet_id=abandon.id,
                  commentaire=f"Abandon de frais : {request.data.get('geste')}")
        from .notifications_application import prevenir
        prevenir(abandon.utilisateur, f"Abandon de frais {abandon.annee} : {abandon.get_statut_display().lower()}",
                 "Votre reçu fiscal est disponible dans « Mon relevé d'heures »." if abandon.numero_recu else abandon.motif_refus,
                 lien="/mon-releve", institution=abandon.institution, environment=abandon.environment)
        return Response(_abandon_en_dict(abandon))


class MonAbandonView(APIView):
    """POST {institution, annee, adresse} : je renonce au remboursement de mes frais validés de
    l'année (le bureau est prévenu)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        environment = get_active_environment(request)
        institution = get_object_or_404(Institution, id=request.data.get("institution"))
        if institution.id not in mf.associations_de(request.user):
            raise PermissionDenied("Vous n'êtes pas membre de cette association.")
        try:
            abandon = benevolat.demander_abandon(institution, environment, _annee(request.data.get("annee")),
                                                 request.user, str(request.data.get("adresse") or ""))
        except benevolat.ErreurBenevolat as erreur:
            raise ValidationError({"detail": str(erreur)})
        from django.contrib.auth import get_user_model

        from .notifications_application import prevenir
        for membre in get_user_model().objects.filter(id__in=[
                u for u in institution.contacts.filter(actif=True, membre_bureau=True).values_list("utilisateur_id", flat=True) if u]):
            if membre.id != request.user.id:
                prevenir(membre, "Demande d'abandon de frais", f"{_nom(request.user)} renonce au remboursement de ses frais {abandon.annee}.",
                         lien="/benevolat", institution=institution, environment=environment)
        return Response(_abandon_en_dict(abandon), status=status.HTTP_201_CREATED)


class RecuFiscalView(APIView):
    """GET : le reçu PDF (le bénévole concerné, ou le bureau)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, aid):
        abandon = get_object_or_404(AbandonFrais.objects.select_related("institution", "utilisateur"),
                                    id=aid, environment=get_active_environment(request))
        if abandon.utilisateur_id != request.user.id:
            _exiger_bureau(request, abandon.institution_id)
        try:
            pdf = benevolat.recu_pdf(abandon)
        except benevolat.ErreurBenevolat as erreur:
            raise ValidationError({"detail": str(erreur)})
        reponse = HttpResponse(pdf, content_type="application/pdf")
        reponse["Content-Disposition"] = f'attachment; filename="recu-{abandon.numero_recu}.pdf"'
        return reponse


class DocumentsManifestationView(APIView):
    """POST (multipart « fichier ») : joindre une image à une manifestation — plan du dispositif,
    carte des postes (bureau). GET <doc> : la télécharger (ceux qui voient la manifestation)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from django.core.exceptions import ValidationError as DjangoValidationError

        from .models import Document
        from .validators import validate_image_file
        m = _manifestation(request, pk)
        _exiger_bureau(request, m.institution_id)
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ValidationError({"detail": "Joignez une image (plan, carte des postes)."})
        try:
            validate_image_file(fichier)
        except DjangoValidationError as erreur:
            raise ValidationError({"detail": " ".join(erreur.messages)})
        fichier.seek(0)
        Document.objects.create(fichier=fichier, auteur=request.user, manifestation=m, environment=m.environment,
                                metadata_publiques={"nom": _texte(fichier.name, 120)})
        return Response(_en_dict(m, request.user, detail=True), status=status.HTTP_201_CREATED)

    def get(self, request, pk, doc):
        from django.http import FileResponse

        m = _manifestation(request, pk)
        document = get_object_or_404(m.documents, id=doc)
        return FileResponse(document.fichier.open("rb"), as_attachment=True,
                            filename=(document.metadata_publiques or {}).get("nom") or "document")



# --- Partage commune-association (26/11/2026, core/partage_manifestation.py) ---------------------

def _partage(pid):
    from .models import PartageManifestation
    return get_object_or_404(PartageManifestation.objects.select_related("manifestation__institution", "mairie"), id=pid)


class PcsPartageView(APIView):
    """GET : le plan communal de sauvegarde de la commune, pour le bureau de l'association, si la
    mairie l'a ouvert et pendant la manifestation. Régénéré à chaque fois, tracé."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pid):
        from . import document_pcs
        from . import partage_manifestation as pm
        from .models import ElementPartage
        partage = _partage(pid)
        _exiger_bureau(request, partage.manifestation.institution_id)
        if partage.mairie is None or not pm.accorde(partage, ElementPartage.PCS_LECTURE):
            raise PermissionDenied("La mairie n'a pas ouvert son plan, ou la manifestation est passée.")
        nom = lambda u: (f"{u.first_name} {u.last_name}".strip() or u.email) if u else ""
        contenu = document_pcs.rassembler(partage.mairie, partage.environment, nom)
        pdf = document_pcs.generer_pdf(contenu, edite_par=f"{nom(request.user)} ({partage.manifestation.institution.nom})")
        audit_log(request=request, action_code="EXPORT", objet_type="PartageManifestation", objet_id=partage.id,
                  commentaire=f"PCS de {partage.mairie.nom} téléchargé par l'association (manifestation)")
        reponse = HttpResponse(pdf, content_type="application/pdf")
        reponse["Content-Disposition"] = f'attachment; filename="plan-communal-de-sauvegarde-{partage.commune_code}.pdf"'
        reponse["Cache-Control"] = "private, no-store"
        return reponse


class ArretePartageView(APIView):
    """GET : l'arrêté joint par la mairie (inscrits et bureau si ouvert ; la mairie toujours).
    POST (multipart « fichier ») : la mairie le joint (PDF ou image)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pid):
        from django.http import FileResponse

        from . import partage_manifestation as pm
        from .models import ElementPartage
        partage = _partage(pid)
        mairie = pm._peut_decider(partage, request.user)
        if not mairie:
            _manifestation(request, partage.manifestation_id)
            if not pm.accorde(partage, ElementPartage.CONSIGNES_ARRETE):
                raise PermissionDenied("La mairie n'a pas partagé son arrêté, ou la manifestation est passée.")
        if not partage.arrete:
            raise ValidationError({"detail": "Aucun arrêté joint."})
        reponse = FileResponse(partage.arrete.open("rb"), content_type=partage.arrete_type or "application/octet-stream",
                               as_attachment=True, filename=partage.arrete_nom or "arrete")
        reponse["Cache-Control"] = "private, no-store"
        return reponse

    def post(self, request, pid):
        from django.core.exceptions import ValidationError as ErreurDeValidation

        from . import partage_manifestation as pm
        from .validators import validate_identity_document_file
        partage = _partage(pid)
        if not pm._peut_decider(partage, request.user):
            raise PermissionDenied("Seule la mairie joint son arrêté.")
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ValidationError({"detail": "Joignez l'arrêté (PDF, ou photo JPEG/PNG)."})
        try:
            validate_identity_document_file(fichier)
        except ErreurDeValidation as erreur:
            raise ValidationError({"detail": " ".join(erreur.messages)})
        fichier.seek(0)
        nom = (getattr(fichier, "name", "") or "arrete")[:200]
        if partage.arrete:
            try:
                partage.arrete.delete(save=False)
            except Exception:  # noqa: BLE001
                pass
        partage.arrete, partage.arrete_nom = fichier, nom
        partage.arrete_type = "application/pdf" if nom.lower().endswith(".pdf") else (getattr(fichier, "content_type", "") or "")[:60]
        partage.save(update_fields=["arrete", "arrete_nom", "arrete_type", "modifie_le"])
        return Response(_partage_pour_mairie(partage), status=status.HTTP_201_CREATED)


def _partage_pour_mairie(partage) -> dict:
    from . import partage_manifestation as pm
    from .models import Crisis
    m = partage.manifestation
    d = pm.tableau(partage, pour_mairie=True)
    d.update({
        "manifestation": {"id": str(m.id), "titre": m.titre, "type_libelle": m.get_type_display(), "lieu": m.lieu,
                          "organisateur": m.organisateur, "debut": m.debut, "fin": m.fin, "statut": m.statut,
                          "statut_libelle": m.get_statut_display(), "association": m.institution.nom},
        "referent_nom": partage.referent_nom, "referent_telephone": partage.referent_telephone,
        "consignes": partage.consignes, "arrete": partage.arrete_nom if partage.arrete else "",
        "en_vigueur": pm.en_vigueur(m),
        "crises_ouvertes": [{"id": str(c.id), "nom": c.name} for c in Crisis.objects.filter(end_date__isnull=True, environment=partage.environment)
                            if partage.commune_code in (c.zone_communes or [])],
        # Les points de la manifestation (PC, signaleurs), pour la carte de la mairie.
        "points": [{"intitule": p.intitule, "type_point_libelle": p.type_point.libelle if p.type_point_id else "",
                    "type_point": p.type_point.code if p.type_point_id else None,
                    "latitude": p.location.y, "longitude": p.location.x}
                   for p in m.postes.select_related("type_point").all() if p.location],
    })
    return d


class ManifestationsCommuneView(APIView):
    """GET : les manifestations sur les communes dont je suis membre de la mairie, avec leur tableau."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import ContactInstitution, PartageManifestation, UserRole
        environment = get_active_environment(request)
        qs = PartageManifestation.objects.filter(environment=environment).exclude(invitation="") \
            .select_related("manifestation__institution", "mairie").prefetch_related("lignes")
        if getattr(request.user, "type", None) != UserRole.ADMINISTRATOR:
            mairies = ContactInstitution.objects.filter(utilisateur=request.user, actif=True).values_list("institution_id", flat=True)
            qs = qs.filter(mairie_id__in=list(mairies))
        partages = sorted(qs[:300], key=lambda p: p.manifestation.debut, reverse=True)
        return Response({"partages": [_partage_pour_mairie(p) for p in partages]})


class PartageCommuneView(APIView):
    """POST {geste: accepter | refuser | retirer | offrir, element, crise?} ; PATCH {referent_nom,
    referent_telephone, consignes} — la mairie."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pid):
        from . import partage_manifestation as pm
        from .models import Crisis, LignePartage
        partage = _partage(pid)
        geste, element = request.data.get("geste"), request.data.get("element")
        try:
            if geste == "offrir":
                crise = Crisis.objects.filter(id=request.data.get("crise")).first() if request.data.get("crise") else None
                pm.offrir(partage, request.user, element, crise)
            else:
                ligne = LignePartage.objects.filter(partage=partage, element=element).first()
                if ligne is None:
                    raise ValidationError({"detail": "Cette ligne n'existe pas pour cette manifestation."})
                pm.decider(ligne, request.user, geste)
        except pm.ErreurPartage as erreur:
            if "Seule la mairie" in str(erreur):
                raise PermissionDenied(str(erreur))
            raise ValidationError({"detail": str(erreur)})
        audit_log(request=request, action_code="MODIFICATION", objet_type="PartageManifestation", objet_id=partage.id,
                  commentaire=f"Partage avec l'association : {geste} {element}")
        partage.refresh_from_db()
        return Response(_partage_pour_mairie(partage))

    def patch(self, request, pid):
        from . import partage_manifestation as pm
        partage = _partage(pid)
        if not pm._peut_decider(partage, request.user):
            raise PermissionDenied("Seule la mairie renseigne ces informations.")
        for champ, maxi in (("referent_nom", 150), ("referent_telephone", 30), ("consignes", 20000)):
            if champ in request.data:
                setattr(partage, champ, _texte(request.data[champ], maxi))
        partage.save()
        return Response(_partage_pour_mairie(partage))
