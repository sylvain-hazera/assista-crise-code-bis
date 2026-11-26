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
    }
    if detail:
        d["consignes"] = m.consignes
        d["postes"] = [_poste_en_dict(p, utilisateur, bureau) for p in postes]
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
        return Response({
            "manifestations": [_en_dict(m, request.user) for m in qs[:500]],
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
