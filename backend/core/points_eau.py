"""Points d'eau incendie (PEI) : carte, signalements terrain, validation par la commune,
remise au SDIS (24/11/2026). Voir le plan du 24/11/2026 et DOSSIER-APPLICATION-INTERVENANTS.md.

Il n'existe pas de base nationale des PEI : chaque SDIS tient la sienne. Trois sources, qui ne
se mélangent jamais (`PointEauIncendie.source`) :
- OSM : relevé département par département (core/points_eau_osm.py), indicatif, licence ODbL ;
- SDIS : fichier au schéma national importé par l'administrateur (core/points_eau_sdis.py) ;
- TERRAIN : un « nouveau point d'eau » signalé et validé par la commune.

Le circuit (décisions de Sylvain) : la réserve et les intervenants SIGNALENT ; la COMMUNE valide
(le maire porte la défense extérieure contre l'incendie) ; elle transmet ensuite au SDIS
(export CSV au schéma national, où ne figure jamais une ligne OSM). Un compte SDIS pourra
valider plus tard. Tout est réservé aux comptes connectés : une borne hors service est une
information sensible en pleine crise.
"""
import csv
import io
import logging

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

RAYON_DOUBLON_M = 50
COLONNES_SCHEMA = (
    "insee", "id_sdis", "id_gestion", "nom_gest", "ref_terr", "type_pei", "type_rd", "diam_pei", "diam_cana",
    "source_pei", "statut", "nom_etab", "situation", "press_dyn", "press_stat", "debit", "volume", "disponible",
    "date_dispo", "date_mes", "date_maj", "date_ct", "date_ro", "prec", "x", "y", "lon", "lat",
)
ETATS_TERRAIN = {"INDISPONIBLE": "INDISPONIBLE", "REMIS_EN_SERVICE": "DISPONIBLE", "DEFAUT": "DEFAUT"}


# ── Droits ───────────────────────────────────────────────────────────────────

def peut_signaler(request):
    """Comptes d'une mairie (personnel, élus, réserve communale), secours, régulation,
    administrateur, et tout intervenant membre d'une équipe."""
    from .models import UserRole
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return False
    if get_effective_role(request) in (UserRole.ADMINISTRATOR, UserRole.LOCAL_AUTHORITY,
                                       UserRole.ORGANIZED_RESCUE, UserRole.REGULATEUR):
        return True
    return user.teams.exists()


def motif_refus_decision(request, commune_code):
    """Pourquoi ce compte ne peut pas valider un signalement de cette commune (None : il peut)."""
    from .models import UserRole
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return "Connectez-vous."
    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return None
    if role != UserRole.LOCAL_AUTHORITY:
        return "La validation des points d'eau revient à la commune (compte d'une mairie)."
    institution = getattr(user, "institution", None)
    if institution is None or not institution.commune_code:
        return "Votre compte n'est rattaché à aucune mairie."
    if not commune_code or institution.commune_code != commune_code:
        return "Ce point d'eau est sur une autre commune que la vôtre."
    return None


def ma_commune(request):
    institution = getattr(getattr(request, "user", None), "institution", None)
    return getattr(institution, "commune_code", "") or ""


# ── Lecture ──────────────────────────────────────────────────────────────────

def etat(point):
    """DISPONIBLE, INDISPONIBLE, DEFAUT ou INCONNU : le terrain validé prime sur la source."""
    if point.etat_terrain:
        return point.etat_terrain
    if point.disponible is True:
        return "DISPONIBLE"
    if point.disponible is False:
        return "INDISPONIBLE"
    return "INCONNU"


def departements_avec_sdis():
    from .models import ReleveDepartementPEI

    return set(ReleveDepartementPEI.objects.filter(sdis_importe_le__isnull=False).values_list("departement_code", flat=True))


def visibles(environment, avec_osm_partout=False):
    """Points visibles dans un environnement : OSM et SDIS communs, TERRAIN du seul
    environnement. Dans un département dont la base SDIS est importée, l'OSM s'efface."""
    from django.db.models import Q

    from .models import PointEauIncendie, SourcePEI

    qs = PointEauIncendie.objects.filter(Q(environment__isnull=True) | Q(environment=environment))
    if not avec_osm_partout:
        masques = departements_avec_sdis()
        if masques:
            qs = qs.exclude(source=SourcePEI.OSM, departement_code__in=masques)
    return qs


def en_dict(point, distance_km=None):
    from .models import SourcePEI, TypePEI
    from .points_eau_osm import ATTRIBUTION

    return {
        "id": point.pk, "source": point.source, "ref": point.ref_source,
        "type_pei": point.type_pei, "type_libelle": dict(TypePEI.choices).get(point.type_pei, "Point d'eau"),
        "source_eau": point.source_eau, "diametre": point.diametre, "debit": point.debit, "volume": point.volume,
        "ref_terrain": point.ref_terrain, "gestionnaire": point.gestionnaire, "statut": point.statut,
        "etat": etat(point), "etat_terrain_le": point.etat_terrain_le.isoformat() if point.etat_terrain_le else None,
        "date_controle": point.date_controle.isoformat() if point.date_controle else None,
        "releve_le": point.releve_le.isoformat(), "insee": point.insee,
        "latitude": point.location.y, "longitude": point.location.x,
        "attribution": ATTRIBUTION if point.source == SourcePEI.OSM else None,
        "distance_km": distance_km,
    }


def proches(environment, latitude, longitude, rayon_m=RAYON_DOUBLON_M):
    centre = Point(longitude, latitude, srid=4326)
    # Un carré en degrés pour l'index spatial (0,001° ≈ 110 m en latitude), puis la vraie
    # distance en mètres.
    ecart = rayon_m / 50000
    return list(visibles(environment, avec_osm_partout=True)
                .filter(location__dwithin=(centre, ecart), location__distance_lte=(centre, D(m=rayon_m))))


# ── Signalements ─────────────────────────────────────────────────────────────

def commune_du_point(latitude, longitude):
    """Code INSEE de la commune d'un point, par le géocodage déjà employé ailleurs ; à défaut,
    la commune dont le centre est le plus proche (hors réseau du géocodeur)."""
    from .geo_lookup import commune_code_from_point
    from .models import Commune
    from .points_eau_osm import _Grille

    point = Point(longitude, latitude, srid=4326)
    try:
        code = commune_code_from_point(point)
        if code:
            return code
    except Exception:   # noqa: BLE001 - géocodeur injoignable : on se rabat sur les centres
        logger.info("Géocodage indisponible pour un signalement de point d'eau.")
    marge = 0.2
    communes = list(Commune.objects.filter(
        centre_latitude__gte=latitude - marge, centre_latitude__lte=latitude + marge,
        centre_longitude__gte=longitude - marge, centre_longitude__lte=longitude + marge,
    ).values_list("code", "departement_code", "centre_latitude", "centre_longitude"))
    trouvee = _Grille(communes).plus_proche(latitude, longitude) if communes else None
    return trouvee[0] if trouvee else ""


def notifier_commune(signalement, request):
    """Prévient les contacts de la mairie de la commune qu'un signalement l'attend."""
    from .models import ContactInstitution, Institution, Notification

    institutions = Institution.objects.filter(commune_code=signalement.commune_code) if signalement.commune_code else []
    titre = "Point d'eau incendie : un signalement à valider"
    message = f"{signalement.get_genre_display()} — à valider dans « Points d'eau incendie »."
    for contact in ContactInstitution.objects.filter(institution__in=institutions, actif=True).select_related("utilisateur"):
        if contact.utilisateur_id == getattr(request.user, "id", None):
            continue
        Notification.objects.create(utilisateur=contact.utilisateur, titre=titre, message=message,
                                    environment=signalement.environment)


def notifier_auteur(signalement):
    from .models import GenreNotification, Notification
    from .notifications_application import notifier

    if signalement.auteur is None:
        return
    titre = f"Point d'eau : signalement {signalement.get_statut_display().lower()}"
    corps = signalement.get_genre_display() + (f" — {signalement.motif_decision}" if signalement.motif_decision else "")
    Notification.objects.create(utilisateur=signalement.auteur, titre=titre, message=corps,
                                environment=signalement.environment)
    try:
        notifier(signalement.auteur, GenreNotification.INFORMATION, titre, corps, environment=signalement.environment)
    except Exception:   # noqa: BLE001 - la notification du site suffit
        logger.exception("Notification d'application d'un signalement de point d'eau")


@transaction.atomic
def decider(signalement, geste, motif, request, maintenant=None):
    """Valider ou rejeter. Valider un état le pose sur le point visé ; valider un nouveau
    point le crée (source TERRAIN, dans l'environnement du signalement)."""
    from .models import PointEauIncendie, SourcePEI, StatutSignalementPEI

    maintenant = maintenant or timezone.now()
    if signalement.statut != StatutSignalementPEI.A_VALIDER:
        raise ValueError("Ce signalement a déjà été traité.")
    if geste == "rejeter":
        signalement.statut = StatutSignalementPEI.REJETE
    elif geste == "valider":
        signalement.statut = StatutSignalementPEI.VALIDE
        if signalement.genre == "NOUVEAU":
            point = PointEauIncendie.objects.create(
                source=SourcePEI.TERRAIN, ref_source=str(signalement.id), environment=signalement.environment,
                departement_code=_departement(signalement.commune_code), insee=signalement.commune_code,
                type_pei=signalement.type_pei, source_eau=signalement.source_eau, debit=signalement.debit_estime,
                volume=signalement.volume_estime, disponible=True, location=signalement.location, releve_le=maintenant,
            )
            signalement.pei = point
        elif signalement.pei is not None:
            signalement.pei.etat_terrain = ETATS_TERRAIN[signalement.genre]
            signalement.pei.etat_terrain_le = signalement.observe_le
            signalement.pei.save(update_fields=["etat_terrain", "etat_terrain_le"])
    else:
        raise ValueError("Geste inconnu : valider ou rejeter.")
    signalement.motif_decision = " ".join(str(motif or "").split())[:500]
    signalement.traite_par, signalement.traite_le = request.user, maintenant
    signalement.save()
    notifier_auteur(signalement)
    return signalement


def _departement(insee):
    from .models import Commune

    commune = Commune.objects.filter(code=insee).first() if insee else None
    if commune and commune.departement_code:
        return commune.departement_code
    if insee.startswith("97"):
        return insee[:3]
    return insee[:2]


def signalement_en_dict(s, request=None):
    photos = [{"id": str(d.id), "commentaire": d.commentaire} for d in s.documents.all()] if s.pk else []
    return {
        "id": str(s.id), "genre": s.genre, "genre_libelle": s.get_genre_display(), "statut": s.statut,
        "statut_libelle": s.get_statut_display(), "pei": s.pei_id, "pei_source": s.pei_source, "pei_ref": s.pei_ref,
        "latitude": s.location.y, "longitude": s.location.x, "precision_m": s.precision_m,
        "type_pei": s.type_pei, "source_eau": s.source_eau, "debit_estime": s.debit_estime,
        "volume_estime": s.volume_estime, "commentaire": s.commentaire, "commune_code": s.commune_code,
        "auteur": _nom(s.auteur, request), "observe_le": s.observe_le.isoformat(),
        "traite_le": s.traite_le.isoformat() if s.traite_le else None, "traite_par": _nom(s.traite_par, request),
        "motif_decision": s.motif_decision, "numero_sdis": s.numero_sdis,
        "transmis_le": s.transmis_le.isoformat() if s.transmis_le else None, "photos": photos,
    }


def _nom(user, request):
    if user is None:
        return None
    from .permissions import nom_affichable

    return nom_affichable(user, request) or user.username


# ── Remise au SDIS ───────────────────────────────────────────────────────────

def _lambert(point):
    copie = point.clone()
    copie.transform(2154)
    return round(copie.x, 2), round(copie.y, 2)


def export_csv(commune_code, environment):
    """CSV au schéma national pour la commune : ses points TERRAIN et ses signalements validés
    ou transmis. Jamais une ligne ni un attribut OSM (licence ODbL) : un signalement sur un
    point OSM n'exporte que ce que l'équipe a constaté elle-même (sa position, l'état)."""
    from .models import PointEauIncendie, SignalementPEI, SourcePEI, StatutSignalementPEI

    sortie = io.StringIO()
    ecrivain = csv.DictWriter(sortie, fieldnames=COLONNES_SCHEMA, delimiter=";")
    ecrivain.writeheader()

    def ligne(point, champs):
        x, y = _lambert(point)
        ecrivain.writerow({colonne: "" for colonne in COLONNES_SCHEMA} | champs | {
            "insee": commune_code, "x": x, "y": y, "lon": round(point.x, 8), "lat": round(point.y, 8), "prec": "10"})

    for point in PointEauIncendie.objects.filter(source=SourcePEI.TERRAIN, insee=commune_code, environment=environment):
        ligne(point.location, {"id_gestion": point.ref_source, "type_pei": point.type_pei, "source_pei": point.source_eau,
                               "debit": point.debit or "", "volume": point.volume or "",
                               "disponible": "" if etat(point) == "INCONNU" else int(etat(point) == "DISPONIBLE"),
                               "date_maj": point.releve_le.date().isoformat()})
    for s in (SignalementPEI.objects.filter(commune_code=commune_code, environment=environment, genre__in=list(ETATS_TERRAIN),
                                            statut__in=[StatutSignalementPEI.VALIDE, StatutSignalementPEI.TRANSMIS_SDIS])
              .select_related("pei")):
        cible_sdis = s.pei is not None and s.pei.source == SourcePEI.SDIS
        ligne(s.location, {
            "id_sdis": s.pei.ref_source if cible_sdis else "",
            "type_pei": s.pei.type_pei if cible_sdis else s.type_pei,
            "disponible": int(s.genre == "REMIS_EN_SERVICE"),
            "date_dispo": s.observe_le.date().isoformat(), "date_maj": (s.traite_le or s.observe_le).date().isoformat(),
        })
    return sortie.getvalue()
