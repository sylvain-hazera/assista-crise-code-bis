"""Les centres d'une crise, pour le poste de pilotage (23/11/2026). Demande de Sylvain : « dans
la PWA pilotage il faut un bloc dédié à la gestion du centre d'accueil ou de regroupement ».

Trois types de points : centre d'accueil (CARE, `HEBERGEMENT`), point de transit (`TRANSIT`),
regroupement des moyens (`REGROUPEMENT_MOYENS`). Pour chacun : occupation (registre de
présence), manques de stock, équipe et responsables, état (ouvert, fermé, prévu). En tête,
l'orientation de la crise : personnes qui cherchent un centre, familles à reloger.

Rien n'est saisi ici : les gestes passent par les API existantes (registre de présence, stocks
d'un point), sauf ouvrir / fermer / capacité (`changer_etat`), réservé à qui peut gérer le
centre. Les noms du registre (chiffrés en base) ne sont rendus qu'à qui peut le gérer.
"""
import datetime

from django.db.models import Count, Q, Sum
from django.utils import timezone

TYPES_CENTRES = ("HEBERGEMENT", "TRANSIT", "REGROUPEMENT_MOYENS")
PRESQUE_PLEIN = 0.9
CRENEAUX = (("NUIT", 0, 6), ("MATIN", 6, 12), ("MIDI", 12, 18), ("SOIR", 18, 24))


def creneau_courant(maintenant):
    heure = timezone.localtime(maintenant).hour
    return next(nom for nom, debut, fin in CRENEAUX if debut <= heure < fin)


def institutions_du_point(point):
    """Les institutions qui tiennent le centre : celle de son équipe (ou de ses équipes de
    gestion) et celle de son responsable."""
    ids = set()
    if point.equipe_id and point.equipe.institution_id:
        ids.add(point.equipe.institution_id)
    if point.responsable_id and getattr(point.responsable, "institution_id", None):
        ids.add(point.responsable.institution_id)
    ids |= {i for i in point.equipes_gestion.values_list("institution_id", flat=True) if i}
    return ids


def orientation(crise, environment):
    """Personnes en sécurité qui cherchent un centre, familles à reloger par statut."""
    from .models import DeclarationSecurite, DossierRelogement

    cherchent = DeclarationSecurite.objects.filter(crise=crise, environment=environment, situation="BESOIN_CENTRE")
    personnes = cherchent.aggregate(a=Sum("nombre_adultes"), e=Sum("nombre_enfants"))
    relogement = dict(DossierRelogement.objects.filter(crise=crise, environment=environment)
                      .values_list("statut").annotate(n=Count("id")).values_list("statut", "n"))
    return {
        "cherchent_un_centre": {"declarations": cherchent.count(), "personnes": (personnes["a"] or 0) + (personnes["e"] or 0)},
        "relogement": {"en_recherche": relogement.get("EN_RECHERCHE", 0), "heberges": relogement.get("HEBERGE", 0),
                       "reloges": relogement.get("RELOGEE", 0) + relogement.get("RETOUR_DOMICILE", 0)},
    }


def etat(point):
    if point.date_fermeture is not None or not point.actif:
        return "FERME"
    if point.date_ouverture is not None:
        return "OUVERT"
    return "PREVU"


def resume(point, request, maintenant=None):
    """Une carte de centre : occupation, manques, équipe, état."""
    from .models import DisponibilitePointEquipe, MaterielPoint, TypePersonneAccueillie
    from .permissions import _peut_gerer_stock_point, nom_affichable

    maintenant = maintenant or timezone.now()
    presents = point.registre_presences.filter(date_depart__isnull=True)
    par_type = dict(presents.values_list("type_personne").annotate(n=Sum("nombre")).values_list("type_personne", "n"))
    total = sum(n or 0 for n in par_type.values())
    capacite = point.capacite_accueil or None
    taux = round(total / capacite, 2) if capacite else None
    il_y_a_24h = maintenant - datetime.timedelta(hours=24)
    arrivees = point.registre_presences.filter(date_arrivee__gte=il_y_a_24h).aggregate(n=Sum("nombre"))["n"] or 0
    departs = point.registre_presences.filter(date_depart__gte=il_y_a_24h).aggregate(n=Sum("nombre"))["n"] or 0
    manques = list(MaterielPoint.objects.filter(point=point, niveau_stock__in=["NUL", "FAIBLE"])
                   .select_related("item").values_list("item__nom", "nom", "niveau_stock")[:20])
    equipes = list(point.equipes_gestion.all())
    if point.equipe_id and point.equipe not in equipes:
        equipes.insert(0, point.equipe)
    peut = _peut_gerer_stock_point(request, point)
    responsables = [point.responsable] if point.responsable_id else []
    responsables += [r for r in point.responsables.all() if r not in responsables]
    sur_place = DisponibilitePointEquipe.objects.filter(point=point, date=timezone.localdate(maintenant),
                                                        creneau=creneau_courant(maintenant)).count()
    libelles = dict(TypePersonneAccueillie.choices)
    return {
        "id": str(point.id), "nom": point.nom, "type": point.type.code if point.type_id else None,
        "type_libelle": point.type.libelle if point.type_id else "", "etat": etat(point),
        "ouvert_le": point.date_ouverture.isoformat() if point.date_ouverture else None,
        "ferme_le": point.date_fermeture.isoformat() if point.date_fermeture else None,
        "occupation": {
            "presents": total, "capacite": capacite, "taux": taux,
            "presque_plein": bool(taux is not None and taux >= PRESQUE_PLEIN), "plein": bool(capacite and total >= capacite),
            "par_type": [{"type": t, "libelle": libelles.get(t, t), "nombre": n or 0}
                         for t, n in sorted(par_type.items(), key=lambda x: -(x[1] or 0))],
            "arrivees_24h": arrivees, "departs_24h": departs,
        },
        "manques": [{"article": nom_item or nom or "Article", "niveau": niveau} for nom_item, nom, niveau in manques],
        "equipes": [{"id": str(e.id), "nom": e.name, "effectif": e.members.count()} for e in equipes],
        "sur_place_creneau": sur_place,
        "responsables": [{
            "nom": nom_affichable(r, request) or r.username,
            "telephone": (r.phone_number or None) if peut else None,
        } for r in responsables],
        "peut_gerer": peut,
        "accepte_animaux": point.accepte_animaux,
    }


def liste(crise, request, environment, maintenant=None):
    from .models import PointOperationnel

    points = (PointOperationnel.objects.filter(crise=crise, environment=environment, type__code__in=TYPES_CENTRES)
              .select_related("type", "equipe", "responsable").prefetch_related("equipes_gestion", "responsables"))
    centres = [resume(p, request, maintenant) for p in points]
    rang = {"OUVERT": 0, "PREVU": 1, "FERME": 2}
    centres.sort(key=lambda c: (rang[c["etat"]], TYPES_CENTRES.index(c["type"]) if c["type"] in TYPES_CENTRES else 9, c["nom"]))
    return {
        "crise": str(crise.id), "orientation": orientation(crise, environment), "centres": centres,
        "alertes": sum(1 for c in centres if c["etat"] == "OUVERT" and (c["occupation"]["presque_plein"] or c["manques"])),
    }


def detail(point, request, maintenant=None):
    """La carte, plus le registre des présents (noms seulement pour qui gère), les derniers
    mouvements, le stock et le planning du jour."""
    from . import stocks_points
    from .models import DisponibilitePointEquipe, MaterielCatalogue, MaterielPoint, TypePersonneAccueillie
    from .permissions import nom_affichable

    maintenant = maintenant or timezone.now()
    carte = resume(point, request, maintenant)
    peut = carte["peut_gerer"]
    libelles = dict(TypePersonneAccueillie.choices)
    presents = point.registre_presences.filter(date_depart__isnull=True).order_by("-date_arrivee")[:300]
    mouvements = point.registre_presences.filter(
        Q(date_arrivee__gte=maintenant - datetime.timedelta(hours=48)) | Q(date_depart__gte=maintenant - datetime.timedelta(hours=48))
    ).order_by("-date_arrivee")[:60]
    quantites = stocks_points.quantites(point)
    lignes = {l.item_id: l for l in MaterielPoint.objects.filter(point=point).select_related("item")}
    items = {i.id: i for i in MaterielCatalogue.objects.filter(pk__in=set(quantites) | {k for k in lignes if k})}
    stock = []
    for item_id in set(quantites) | {k for k in lignes if k}:
        item, ligne = items.get(item_id), lignes.get(item_id)
        stock.append({"item": str(item_id), "article": item.nom if item else (ligne.nom if ligne else "Article"),
                      "quantite": float(quantites.get(item_id, 0) or 0), "niveau": ligne.niveau_stock if ligne else None,
                      "unite": (ligne.unite if ligne else None) or "unité"})
    stock.sort(key=lambda s: ({"NUL": 0, "FAIBLE": 1}.get(s["niveau"], 2), s["article"]))
    planning = [{"membre": nom_affichable(d.membre, request) or d.membre.username, "creneau": d.creneau}
                for d in DisponibilitePointEquipe.objects.filter(point=point, date=timezone.localdate(maintenant))
                .select_related("membre").order_by("creneau")]
    return {
        **carte,
        "adresse": point.adresse or None,
        "registre": [{
            "id": str(r.id), "type": r.type_personne, "libelle": libelles.get(r.type_personne, r.type_personne),
            "nombre": r.nombre, "arrivee": r.date_arrivee.isoformat() if r.date_arrivee else None,
            "nom": (r.nom or None) if peut else None, "commentaire": (r.commentaire or None) if peut else None,
        } for r in presents],
        "mouvements": [{
            "type": r.type_personne, "libelle": libelles.get(r.type_personne, r.type_personne), "nombre": r.nombre,
            "arrivee": r.date_arrivee.isoformat() if r.date_arrivee else None,
            "depart": r.date_depart.isoformat() if r.date_depart else None,
        } for r in mouvements],
        "stock": stock,
        "planning": planning,
        "categories": [{"type": t, "libelle": l} for t, l in TypePersonneAccueillie.choices],
    }


def changer_etat(point, geste, capacite=None, maintenant=None):
    """Ouvrir, fermer, rouvrir un centre ; ajuster sa capacité. Rend les champs modifiés."""
    maintenant = maintenant or timezone.now()
    champs = []
    if geste == "ouvrir":
        point.actif, point.date_fermeture = True, None
        if point.date_ouverture is None:
            point.date_ouverture = maintenant
        champs += ["actif", "date_fermeture", "date_ouverture"]
    elif geste == "fermer":
        point.date_fermeture = maintenant
        champs.append("date_fermeture")
    if capacite is not None:
        point.capacite_accueil = capacite
        champs.append("capacite_accueil")
    if champs:
        point.save(update_fields=champs)
    return champs
