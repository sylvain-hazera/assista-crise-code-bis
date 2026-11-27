"""La mini veille du territoire de l'application de l'intervenant (27/11/2026).

Demande de Sylvain : « à l'échelle de la crise ou de la manifestation en cours ; très léger,
texte, peu de couleurs : vigilance météo ; orage, foudre, pluie intense en approche ; rafales
prévues, neige, verglas, grêle ; inondation, séismes, points chauds détectés ».

**Rien n'est recalculé ici** : le périmètre est fait des communes de la crise (ou de la
manifestation) et les phénomènes sont lus par les détecteurs des alertes automatiques
(`alertes_naturelles`), avec leurs seuils conseillés. Un seul ajout : l'orage EN APPROCHE, que
ces alertes ne disent pas (elles parlent de la pluie déjà là), lu dans les communes que NOS
estimations voient atteintes dans l'heure — une estimation, jamais une prévision.

Les zones : celles de la carte de l'application (`crises_du_perimetre`), puis les
manifestations publiées où la personne tient un poste aujourd'hui.

Les cinq stations-service les plus proches (demande du 27/11/2026) : de la position que
l'application envoie (lue, jamais gardée), sinon du centre de la première zone ; avec ce
qu'elles délivrent encore (flux instantané des prix des carburants).
"""
import datetime
import logging
import math

from django.utils import timezone

from . import alertes_naturelles as an

logger = logging.getLogger(__name__)

APPROCHE = "APPROCHE"
#: Rubriques, dans l'ordre de l'écran, et les phénomènes qu'elles rassemblent.
RUBRIQUES = [
    ("METEO", "Vigilance météo", ["VIGILANCE_METEO"]),
    ("ORAGES", "Orages, foudre, pluie intense", ["ORAGES", APPROCHE, "FOUDRE", "PLUIE"]),
    ("PREVISIONS", "Rafales, neige, verglas, grêle", ["RAFALES", "HIVER"]),
    ("EAU", "Crues et inondation", ["CRUES", "MONTEE_EAU", "SURCOTE"]),
    ("SEISMES", "Séismes", ["SEISME"]),
    ("FEUX", "Feux et points chauds", ["FOYERS", "FEU_SUIVI"]),
]
INFO = "INFO"
GRAVITE = {an.EXCEPTIONNEL: 0, an.ALERTE: 1, INFO: 2}
#: Au-delà, la zone est un département entier ou plus : assez pour la veille d'une équipe.
COMMUNES_MAX = 800
ZONES_MAX = 4


def _communes(qs):
    return [(c.code, c.nom or c.code, c.centre_latitude, c.centre_longitude, c.departement_code or "")
            for c in qs.exclude(centre_latitude=None).exclude(centre_longitude=None)
            .only("code", "nom", "centre_latitude", "centre_longitude", "departement_code")[:COMMUNES_MAX]]


def _autour(latitude, longitude, rayon_km):
    """Les communes dont le centre est à moins de `rayon_km`, sinon la plus proche."""
    from .models import Commune

    marge = max(rayon_km, 5) * 3
    dlat = marge / 111.0
    dlon = marge / (111.0 * max(0.2, math.cos(math.radians(latitude))))
    proches = _communes(Commune.objects.filter(
        centre_latitude__range=(latitude - dlat, latitude + dlat), centre_longitude__range=(longitude - dlon, longitude + dlon)))
    if not proches:
        return []
    dedans = [c for c in proches if an.distance_km(latitude, longitude, c[2], c[3]) <= max(rayon_km, 1)]
    return dedans or [min(proches, key=lambda c: an.distance_km(latitude, longitude, c[2], c[3]))]


def perimetre_de_crise(crise):
    from .accords_communes import communes_de_la_crise
    from .models import Commune

    codes = communes_de_la_crise(crise)
    if codes:
        communes = _communes(Commune.objects.filter(code__in=codes))
    elif crise.zone_departements:
        communes = _communes(Commune.objects.filter(departement_code__in=[d for d in crise.zone_departements if d]))
    elif crise.location:
        communes = _autour(crise.location.y, crise.location.x, crise.radius or 10)
    else:
        communes = []
    return an.Perimetre("crise", str(crise.id), communes) if communes else None


def perimetre_de_manifestation(manifestation):
    from .models import Commune

    codes = [c for c in (manifestation.communes or []) if c] or ([manifestation.commune_code] if manifestation.commune_code else [])
    communes = _communes(Commune.objects.filter(code__in=codes)) if codes else []
    return an.Perimetre("manifestation", str(manifestation.id), communes) if communes else None


def _approche(perimetre, maintenant):
    """Orages que nos estimations voient atteindre la zone dans l'heure, sans y être déjà."""
    from .models import CelluleOrage

    codes = perimetre.codes
    evenements = []
    for cellule in CelluleOrage.objects.filter(heure_image__gte=maintenant - datetime.timedelta(minutes=20)):
        if any(c.get("code") in codes for c in cellule.communes_touchees or []):
            continue                                    # déjà là : c'est la rubrique « orage »
        atteintes = sorted((c for c in cellule.communes_estimees or [] if c.get("code") in codes),
                           key=lambda c: c.get("dans_min") or 0)
        if not atteintes:
            continue
        premiere = atteintes[0]
        violent = bool(cellule.grele_prevue or cellule.doppler_rotation or cellule.doppler_grele)
        dans = f"dans {premiere['dans_min']} min environ" if premiere.get("dans_min") is not None else "dans l'heure"
        evenements.append(an.Evenement(
            cle=f"approche-{cellule.identifiant}", valeur=round(cellule.max_mmh),
            titre=f"Orage en approche de {premiere.get('nom', premiere['code'])}, {dans} ({cellule.max_mmh:.0f} mm/h"
                  f"{', grêle ou rotation' if violent else ''})",
            detail="Notre estimation si la cellule garde sa vitesse et sa direction, pas une prévision. "
                   "Source : radars Météo-France.",
            latitude=cellule.centre.y, longitude=cellule.centre.x, au_moins=an.EXCEPTIONNEL if violent else None))
    return evenements


def _niveau(code, evenement):
    if code == APPROCHE:
        regle = _regle("ORAGES")
        niveau = an.niveau_de(an.PAR_CODE["ORAGES"], regle, evenement)
    else:
        niveau = an.niveau_de(an.PAR_CODE[code], _regle(code), evenement)
    return niveau or INFO


def _regle(code):
    """Une règle jamais enregistrée : les seuils et rayons conseillés du catalogue."""
    from .models import RegleAlerte
    return RegleAlerte(phenomene=code)


def _source(code):
    return an.PAR_CODE["ORAGES" if code == APPROCHE else code].source


def veille_de(perimetre, maintenant=None):
    """Les rubriques d'une zone : [{code, libelle, etat, evenements: [{niveau, titre, detail}]}].
    `etat` : `ok`, `perimee` (toutes ses sources se sont tues) ou `indisponible` (erreur)."""
    from . import sources_ouvertes

    maintenant = maintenant or timezone.now()
    rubriques = []
    for code_rubrique, libelle, phenomenes in RUBRIQUES:
        evenements, en_panne = [], False
        for code in phenomenes:
            try:
                if code == APPROCHE:
                    lus = _approche(perimetre, maintenant)
                    minimum = an.PAR_CODE["ORAGES"].minimum
                else:
                    phenomene = an.PAR_CODE[code]
                    lus = phenomene.detecter(perimetre, _regle(code), maintenant, {})
                    minimum = phenomene.minimum
            except Exception:
                logger.exception("Veille terrain : %s illisible.", code)
                en_panne = True
                continue
            for e in lus:
                # Sous le plus petit seuil réglable : du bruit (micro-séisme, quelques gouttes).
                if e.valeur < minimum:
                    continue
                evenements.append({"phenomene": code, "niveau": _niveau(code, e), "titre": e.titre,
                                   "detail": e.detail, "valeur": e.valeur})
        evenements.sort(key=lambda e: (GRAVITE[e["niveau"]], -e["valeur"]))
        sources = {_source(c) for c in phenomenes}
        perimees = all(s in sources_ouvertes.SOURCES and sources_ouvertes.est_perime(s, maintenant) for s in sources)
        etat = "indisponible" if en_panne and not evenements else ("perimee" if perimees and not evenements else "ok")
        rubriques.append({"code": code_rubrique, "libelle": libelle, "etat": etat,
                          "evenements": [{k: e[k] for k in ("niveau", "titre", "detail")} for e in evenements[:6]]})
    return rubriques


def manifestations_du_jour(utilisateur, environment, maintenant=None):
    from .models import Manifestation, StatutManifestation

    maintenant = maintenant or timezone.now()
    return list(Manifestation.objects.filter(
        environment=environment, statut=StatutManifestation.PUBLIEE, postes__inscriptions__utilisateur=utilisateur,
        debut__lte=maintenant + datetime.timedelta(hours=12), fin__gte=maintenant,
    ).distinct().order_by("debut"))


STATIONS = 5
#: Rayons de recherche successifs : l'index spatial travaille sur un petit carré d'abord.
RAYONS_STATIONS_KM = (15, 50, 150)


def stations_proches(latitude, longitude, nombre=STATIONS):
    """Les `nombre` stations les plus proches, à vol d'oiseau."""
    from django.contrib.gis.geos import Polygon

    from .models import StationCarburant

    for rayon in RAYONS_STATIONS_KM:
        dlat = rayon / 111.0
        dlon = rayon / (111.0 * max(0.2, math.cos(math.radians(latitude))))
        carre = Polygon.from_bbox((longitude - dlon, latitude - dlat, longitude + dlon, latitude + dlat))
        lues = list(StationCarburant.objects.filter(location__within=carre))
        if len(lues) >= nombre or rayon == RAYONS_STATIONS_KM[-1]:
            break
    rangees = sorted(((an.distance_km(latitude, longitude, s.location.y, s.location.x), s) for s in lues), key=lambda x: x[0])
    return [{
        "distance_km": round(d, 1), "adresse": s.adresse, "ville": s.ville,
        "latitude": s.location.y, "longitude": s.location.x,
        "carburants_disponibles": s.carburants_disponibles, "ruptures_temporaires": s.ruptures_temporaires,
        "automate_24_24": s.automate_24_24, "mis_a_jour_le": s.mis_a_jour_le,
    } for d, s in rangees[:nombre]]


def construire(utilisateur, environment, maintenant=None, latitude=None, longitude=None):
    from .views_carte_terrain import crises_du_perimetre

    maintenant = maintenant or timezone.now()
    crises, _raison = crises_du_perimetre(utilisateur, environment)
    zones = []
    for crise in crises:
        zones.append(("crise", crise.id, crise.name, perimetre_de_crise(crise)))
    for m in manifestations_du_jour(utilisateur, environment, maintenant):
        zones.append(("manifestation", m.id, m.titre, perimetre_de_manifestation(m)))
    resultat = []
    for nature, ident, nom, perimetre in zones[:ZONES_MAX]:
        resultat.append({
            "nature": nature, "id": str(ident), "nom": nom,
            "communes": len(perimetre.communes) if perimetre else 0,
            "rubriques": veille_de(perimetre, maintenant) if perimetre else [],
        })
    # Les stations : autour de moi si l'application l'a dit, sinon au centre de la première zone.
    stations, autour = [], None
    if latitude is not None and longitude is not None:
        stations, autour = stations_proches(latitude, longitude), "votre position"
    else:
        premiere = next(((nom, p) for _n, _i, nom, p in zones if p), None)
        if premiere:
            nom, p = premiere
            lat = sum(c[2] for c in p.communes) / len(p.communes)
            lon = sum(c[3] for c in p.communes) / len(p.communes)
            stations, autour = stations_proches(lat, lon), nom
    return {"genere_le": maintenant, "zones": resultat,
            "stations": {"autour_de": autour, "resultats": stations}}
