"""L'évaluation des dégâts à pied, depuis l'application (lot C, 20/11/2026).

Voir DOSSIER-ADRESSES-ET-DEGATS.md, § 5. Une personne seule, téléphone à la main :
- la TOURNÉE : les adresses du référentiel et les biens déjà référencés les plus proches d'elle ;
- le CONSTAT : sur une adresse (le point est-il bien placé ? sinon replacé), ou sur un point
  nouveau (une voiture, un pont, un arbre), avec l'état, la cause, les dangers, une personne sur
  place ou à reloger ;
- le RAPPROCHEMENT : un point nouveau à moins de 50 m d'un bien du même type de la même crise
  est PROPOSÉ comme le même bien, jamais fusionné d'office ; un rapprochement se fait aussi à la
  main, et deux biens rapprochés par erreur se séparent (décisions du 20/11/2026).

Qui évalue sur le téléphone : le personnel municipal et les élus (décision du 20/11/2026), soit
l'autorité locale sur sa propre commune, module de dégâts activé sur la crise. Le pointage du
site, ouvert aux intervenants avec validation par la commune, ne change pas.
"""
import datetime
import logging
import math

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

RAYON_TOURNEE_M = 150
RAYON_TOURNEE_MAX_M = 1000
RAPPROCHEMENT_M = 50
DANGERS = ("STRUCTURE", "ELECTRICITE", "GAZ", "EAU", "AUTRE")
#: Un constat daté de plus loin que cela n'est pas cru : l'heure du téléphone est fausse.
ANCIENNETE_MAX = datetime.timedelta(days=30)


def motif_de_refus(request, commune_code, crise):
    """Pourquoi l'évaluation sur le terrain est refusée ici, en clair -- ou None si elle est
    permise. Le personnel municipal et les élus de la commune (autorité locale), le module de
    dégâts activé par leur institution sur cette crise ; un administrateur pour dépanner.

    23/11/2026 : un seul message (« réservé aux élus ») couvrait tous les cas, et un membre de
    réserve communale, pourtant rattaché à sa mairie, ne pouvait pas savoir que le seul manque
    était l'activation du module par sa mairie."""
    from .models import ModuleDegatsCrise, UserRole
    from .permissions import get_effective_role

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return "Connectez-vous pour évaluer les dégâts."
    role = get_effective_role(request)
    if role == UserRole.ADMINISTRATOR:
        return None
    if role != UserRole.LOCAL_AUTHORITY:
        return "L'évaluation des dégâts sur le terrain est réservée aux comptes d'une mairie (personnel, élus, réserve communale)."
    institution = getattr(user, "institution", None)
    if institution is None:
        return "Votre compte n'est rattaché à aucune mairie : demandez à votre mairie de vous y rattacher."
    if not commune_code or institution.commune_code != commune_code:
        return "Vous êtes hors du territoire de votre commune : l'évaluation se fait sur la commune de votre mairie."
    if not ModuleDegatsCrise.objects.filter(crise=crise, institution=institution, actif=True).exists():
        return ("Votre mairie n'a pas activé l'évaluation des dégâts pour cette crise. Elle s'active sur le site, "
                "page « Référencement des dégâts », bouton « Activation du module ».")
    return None


def peut_evaluer(request, commune_code, crise):
    return motif_de_refus(request, commune_code, crise) is None


def type_de_bien(valeur, libre, user):
    """Le type choisi (identifiant), ou celui que nomme le texte libre -- créé s'il n'existe pas,
    et proposé ensuite à tous. None si rien n'est donné (un logement)."""
    from .models import TypeBien

    if valeur:
        trouve = TypeBien.objects.filter(pk=valeur, actif=True).first()
        if trouve is None:
            raise ValueError("type de bien inconnu")
        return trouve
    nom = " ".join((libre or "").split())[:80]
    if not nom:
        return None
    existant = TypeBien.objects.filter(cle=TypeBien.cle_de(nom)).first()
    if existant is not None:
        return existant
    return TypeBien.objects.create(nom=nom, a_une_adresse=False, cree_par=user if user.is_authenticated else None)


def _distance_m(a, b):
    est = (a.x - b.x) * 111_320 * math.cos(math.radians((a.y + b.y) / 2))
    return math.hypot(est, (a.y - b.y) * 111_320)


def tournee(crise, environment, latitude, longitude, rayon_m=RAYON_TOURNEE_M):
    """Les points à évaluer autour de moi, du plus proche au plus lointain : les adresses du
    référentiel (avec l'état du bien de cette adresse s'il est déjà référencé pour la crise) et
    les biens sans adresse de la crise."""
    from django.contrib.gis.geos import Point, Polygon

    from .models import Habitation
    from .referentiel_adresses import proches

    rayon_m = max(20, min(RAYON_TOURNEE_MAX_M, rayon_m))
    ici = Point(longitude, latitude, srid=4326)
    adresses = proches(latitude, longitude, rayon_m=rayon_m, nombre=200)
    ecart_lat = rayon_m / 111_320
    ecart_lon = rayon_m / (111_320 * max(0.1, math.cos(math.radians(latitude))))
    emprise = Polygon.from_bbox((longitude - ecart_lon, latitude - ecart_lat, longitude + ecart_lon, latitude + ecart_lat))
    biens = list(Habitation.objects.filter(crise=crise, environment=environment, fusionne_dans__isnull=True)
                 .filter(location__within=emprise).select_related("type_bien"))
    par_ban = {b.ban_id: b for b in biens if b.ban_id}
    points = []
    for adresse in adresses:
        bien = par_ban.get(adresse.ban_id)
        points.append(_point(adresse.libelle, adresse.location, ici, ban_id=adresse.ban_id, bien=bien))
    for bien in biens:
        if not bien.ban_id or bien.ban_id not in {a.ban_id for a in adresses}:
            if bien.location is not None and _distance_m(bien.location, ici) <= rayon_m:
                points.append(_point(bien.adresse, bien.location, ici, ban_id=bien.ban_id, bien=bien))
    return sorted(points, key=lambda p: p["distance_m"])


def _point(libelle, position, ici, ban_id=None, bien=None):
    lieu = bien.location if bien is not None and bien.location is not None else position
    return {
        "ban_id": ban_id, "habitation": str(bien.id) if bien else None, "libelle": libelle,
        "latitude": round(lieu.y, 6), "longitude": round(lieu.x, 6),
        "distance_m": round(_distance_m(lieu, ici), 1),
        "statut_evaluation": bien.statut_evaluation if bien else None,
        "type_bien": bien.type_bien.nom if bien and bien.type_bien else None,
        "position_corrigee": bool(bien and bien.position_corrigee),
    }


def heure_du_constat(texte):
    """L'heure du constat sur le téléphone, si elle est crédible ; sinon maintenant."""
    from django.utils.dateparse import parse_datetime

    maintenant = timezone.now()
    valeur = parse_datetime(texte) if texte else None
    if valeur is None:
        return maintenant
    if valeur.tzinfo is None:
        valeur = valeur.replace(tzinfo=datetime.timezone.utc)
    return valeur if maintenant - ANCIENNETE_MAX <= valeur <= maintenant + datetime.timedelta(minutes=5) else maintenant


# ── Rapprochements ──

def proposer_rapprochements(bien):
    """Propose comme le même bien les fiches de la même crise, du même type, à moins de 50 m.
    Jamais une paire déjà proposée, refusée ou séparée. Rend les propositions créées."""
    from django.contrib.gis.geos import Polygon

    from .models import Habitation, RapprochementBien

    if bien.location is None or bien.crise_id is None:
        return []
    ecart_lat = RAPPROCHEMENT_M / 111_320
    ecart_lon = RAPPROCHEMENT_M / (111_320 * max(0.1, math.cos(math.radians(bien.location.y))))
    x, y = bien.location.x, bien.location.y
    emprise = Polygon.from_bbox((x - ecart_lon, y - ecart_lat, x + ecart_lon, y + ecart_lat))
    voisins = (Habitation.objects.filter(crise=bien.crise, environment=bien.environment, type_bien=bien.type_bien,
                                         fusionne_dans__isnull=True, location__within=emprise)
               .exclude(pk=bien.pk))
    creees = []
    for voisin in voisins:
        distance = _distance_m(voisin.location, bien.location)
        if distance > RAPPROCHEMENT_M:
            continue
        deja = RapprochementBien.objects.filter(bien__in=(bien, voisin), autre__in=(bien, voisin)).exists()
        if deja:
            continue
        # Le bien déjà référencé est gardé ; le nouveau lui serait rattaché.
        creees.append(RapprochementBien.objects.create(
            crise=bien.crise, bien=voisin, autre=bien, distance_m=round(distance, 1), environment=bien.environment))
    return creees


@transaction.atomic
def confirmer(rapprochement, user):
    """« Même bien » : `autre` est rattaché à `bien`, sans rien effacer."""
    from .models import HabitationHistorique, StatutRapprochementBien

    if rapprochement.statut not in (StatutRapprochementBien.PROPOSE, StatutRapprochementBien.SEPARE):
        raise ValueError("ce rapprochement est déjà tranché")
    garde, rattache = rapprochement.bien, rapprochement.autre
    if garde.fusionne_dans_id or garde.pk == rattache.pk:
        raise ValueError("le bien gardé est lui-même rattaché à un autre")
    rattache.fusionne_dans = garde
    rattache.save(update_fields=["fusionne_dans", "modifie_le"])
    rapprochement.statut = StatutRapprochementBien.CONFIRME
    rapprochement.decide_par, rapprochement.decide_le = user, timezone.now()
    rapprochement.save(update_fields=["statut", "decide_par", "decide_le"])
    for fiche, texte in ((garde, f"Rapproché : « {rattache.adresse} » est le même bien"),
                         (rattache, f"Rattaché à « {garde.adresse} » (même bien)")):
        HabitationHistorique.objects.create(habitation=fiche, auteur=user, evenement=texte[:255], environment=fiche.environment)
    return rapprochement


def refuser(rapprochement, user):
    from .models import StatutRapprochementBien

    if rapprochement.statut != StatutRapprochementBien.PROPOSE:
        raise ValueError("ce rapprochement est déjà tranché")
    rapprochement.statut = StatutRapprochementBien.REFUSE
    rapprochement.decide_par, rapprochement.decide_le = user, timezone.now()
    rapprochement.save(update_fields=["statut", "decide_par", "decide_le"])
    return rapprochement


@transaction.atomic
def rapprocher_a_la_main(garde, rattache, user):
    """Rapprochement fait par une personne : créé et confirmé d'un coup."""
    from .models import RapprochementBien

    if garde.crise_id != rattache.crise_id:
        raise ValueError("les deux biens ne sont pas de la même crise")
    distance = _distance_m(garde.location, rattache.location) if garde.location and rattache.location else None
    rapprochement = RapprochementBien.objects.create(
        crise=garde.crise, bien=garde, autre=rattache, manuel=True, environment=garde.environment,
        distance_m=round(distance, 1) if distance is not None else None)
    return confirmer(rapprochement, user)


@transaction.atomic
def separer(rattache, user):
    """Deux biens rapprochés par erreur : le bien rattaché redevient une fiche à part entière."""
    from .models import HabitationHistorique, RapprochementBien, StatutRapprochementBien

    garde = rattache.fusionne_dans
    if garde is None:
        raise ValueError("ce bien n'est rattaché à aucun autre")
    rattache.fusionne_dans = None
    rattache.save(update_fields=["fusionne_dans", "modifie_le"])
    RapprochementBien.objects.filter(bien=garde, autre=rattache, statut=StatutRapprochementBien.CONFIRME).update(
        statut=StatutRapprochementBien.SEPARE, decide_par=user, decide_le=timezone.now())
    for fiche, texte in ((garde, f"Séparé de « {rattache.adresse} » : ce n'était pas le même bien"),
                         (rattache, f"Séparé de « {garde.adresse} » : ce n'était pas le même bien")):
        HabitationHistorique.objects.create(habitation=fiche, auteur=user, evenement=texte[:255], environment=fiche.environment)
    return rattache
