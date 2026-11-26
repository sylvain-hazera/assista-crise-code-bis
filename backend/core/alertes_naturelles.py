"""Alertes automatiques réglables sur les phénomènes naturels (demande de Sylvain du 24/11/2026).

« Chaque collectivité pour son périmètre ; l'application et l'email toujours, la radio pour les
phénomènes vraiment exceptionnels ; tous les phénomènes, en tableau. »

**Le catalogue.** Une entrée par phénomène : sa source (déjà relevée par `sources_ouvertes`), deux
seuils — *alerte* et *exceptionnel* — avec des valeurs conseillées et des bornes, et un
détecteur qui lit la base et rend les événements du périmètre, chacun avec une **valeur** sur
la même échelle que les seuils. Le moteur compare, une seule fois par événement : de nouveau
seulement s'il devient exceptionnel, ou passé le délai de mémoire du phénomène.

**Le périmètre** est celui de la collectivité : sa commune, ses communes d'interco, son
département (`Institution.secteur_niveau_effectif`). Une distance se mesure au centre de commune
le plus proche.

**Les échelles** (couleurs, indices, paliers) sont celles des modules sources, jamais refaites
ici : les couleurs de vigilance de `meteo_france`, les niveaux de `meteo_forets`, d'`avalanche`,
de `qualite_air`, de `restrictions_eau`, les paliers de `rafales` et d'`orages_de_feu`.

**Prévenir** : `notifications_application.prevenir` (site et application) à chaque fois, urgent
si exceptionnel ; un courriel si la règle le demande ; la radio seulement si
l'événement est exceptionnel, que la règle le permet et que le phénomène s'y prête — en message
DIRECT à la radio de chaque personne prévenue, jamais sur un canal partagé (Fr_EMCOM…). La nuit
(22 h – 7 h), seul l'exceptionnel réveille, si la règle le demande.
"""
import datetime
import logging
import math
import unicodedata
from collections import namedtuple
from dataclasses import dataclass, field

from django.utils import timezone

logger = logging.getLogger(__name__)

ALERTE, EXCEPTIONNEL = "ALERTE", "EXCEPTIONNEL"
NUIT_DEBUT, NUIT_FIN = 22, 7
LONGUEUR_RADIO = 180
#: Au-delà, une collectivité n'a pas de « périmètre » qu'une alerte locale ait du sens à couvrir.
NIVEAUX_LOCAUX = ("commune", "epci", "departement", "region")


@dataclass
class Evenement:
    cle: str
    valeur: float
    titre: str
    detail: str = ""
    latitude: float | None = None
    longitude: float | None = None
    #: Pour un événement qu'une seule valeur ne dit pas (grêle sous un orage, feu tout près) :
    #: le niveau est au moins celui-ci.
    au_moins: str | None = None


@dataclass
class Perimetre:
    niveau: str
    code: str
    communes: list = field(default_factory=list)      # [(code, nom, latitude, longitude, departement)]

    @property
    def codes(self):
        return {c[0] for c in self.communes}

    @property
    def departements(self):
        return sorted({c[4] for c in self.communes if c[4]})

    def emprise(self, marge_km=0.0):
        """(ouest, sud, est, nord) en degrés, élargie de `marge_km`."""
        lats = [c[2] for c in self.communes]
        lons = [c[3] for c in self.communes]
        dlat = marge_km / 111.0
        dlon = marge_km / (111.0 * max(0.2, math.cos(math.radians(sum(lats) / len(lats)))))
        return (min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)

    def polygone(self, marge_km=0.0):
        from django.contrib.gis.geos import Polygon
        return Polygon.from_bbox(self.emprise(marge_km))

    def distance_km(self, latitude, longitude):
        return min(distance_km(latitude, longitude, c[2], c[3]) for c in self.communes)

    def plus_proche(self, latitude, longitude):
        return min(self.communes, key=lambda c: distance_km(latitude, longitude, c[2], c[3]))


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def perimetre_de(institution):
    """Le périmètre de la collectivité, ou None si elle n'en a pas (ni commune, ni secteur)."""
    from .geo_lookup import communes_de_secteur
    from .models import Commune

    niveau = institution.secteur_niveau_effectif or "commune"
    if niveau not in NIVEAUX_LOCAUX:
        niveau = "commune"
    code = {"commune": institution.commune_code, "epci": institution.epci_code,
            "departement": institution.departement_code, "region": institution.region_code}.get(niveau)
    if not code:
        niveau, code = "commune", institution.commune_code
    if not code:
        return None
    codes = [code] if niveau == "commune" else (communes_de_secteur(niveau, code) or [])
    communes = [(c.code, c.nom or c.code, c.centre_latitude, c.centre_longitude, c.departement_code or "")
                for c in Commune.objects.filter(code__in=codes).exclude(centre_latitude=None)
                .exclude(centre_longitude=None).only("code", "nom", "centre_latitude", "centre_longitude", "departement_code")]
    return Perimetre(niveau, code, communes) if communes else None


def _recent(instant, maintenant, duree):
    return instant is not None and maintenant - instant <= duree


def _lieu(perimetre, latitude, longitude):
    commune = perimetre.plus_proche(latitude, longitude)
    d = distance_km(latitude, longitude, commune[2], commune[3])
    return f"à {d:.0f} km de {commune[1]}" if d >= 1 else f"à {commune[1]}"


# ── Les détecteurs ────────────────────────────────────────────────────────────
# Chacun : (perimetre, regle, maintenant, contexte) -> [Evenement]. `regle.seuils` porte aussi
# les réglages propres au phénomène (rayon…). Aucun ne lève pour une donnée manquante : il rend
# une liste vide.

def _seismes(perimetre, regle, maintenant, contexte):
    from .models import Seisme

    rayon = regle.reglage("rayon_km")
    if contexte.get("seismes") is not None:
        lus = contexte["seismes"]
    else:
        lus = [{"event_id": s.reference, "magnitude": s.magnitude, "latitude": s.location.y,
                "longitude": s.location.x, "lieu": s.lieu}
               for s in Seisme.objects.filter(date__gte=maintenant - datetime.timedelta(hours=6), nature="earthquake",
                                              location__within=perimetre.polygone(rayon))]
    evenements = []
    for s in lus:
        d = perimetre.distance_km(s["latitude"], s["longitude"])
        if d > rayon:
            continue
        evenements.append(Evenement(
            cle=f"seisme-{s['event_id']}", valeur=round(float(s["magnitude"]), 1),
            titre=f"Séisme de magnitude {float(s['magnitude']):.1f} {_lieu(perimetre, s['latitude'], s['longitude'])}",
            detail="Source : BCSF-Rénass / EMSC.", latitude=s["latitude"], longitude=s["longitude"],
            # Fort et tout proche : exceptionnel même un demi-degré sous le seuil.
            au_moins=EXCEPTIONNEL if d <= 30 and s["magnitude"] >= regle.seuil(EXCEPTIONNEL) - 0.5 else None))
    return evenements


def _volcans(perimetre, regle, maintenant, contexte):
    from . import seismes

    evenements = []
    for volcan in seismes.activite_volcans(maintenant):
        if perimetre.distance_km(volcan["latitude"], volcan["longitude"]) > regle.reglage("rayon_km"):
            continue
        recents, avant = volcan["seismes_7_jours"], volcan["seismes_7_jours_precedents"]
        if recents < 5:
            continue
        rapport = round(recents / max(1, avant), 1)
        semaine = maintenant.isocalendar()
        evenements.append(Evenement(
            cle=f"volcan-{volcan['code']}-{semaine[0]}-{semaine[1]}", valeur=rapport,
            titre=f"{volcan['nom']} : sismicité en hausse ({recents} séismes en 7 jours, ×{rapport})",
            detail=f"Le niveau d'alerte est fixé par le préfet ; voir {volcan['observatoire']}.",
            latitude=volcan["latitude"], longitude=volcan["longitude"]))
    return evenements


def _vigilance_meteo(perimetre, regle, maintenant, contexte):
    from . import meteo_france
    from .models import VigilanceMeteo

    evenements = []
    for ligne in VigilanceMeteo.objects.filter(pk__in=perimetre.departements):
        if not _recent(ligne.releve_le, maintenant, meteo_france.FRAICHEUR_MAX):
            continue
        for phenomene, niveau in meteo_france.niveaux_en_cours(ligne.detail, maintenant).items():
            debut = niveau.get("debut")
            texte = meteo_france.texte_alerte(ligne.departement_code, phenomene, niveau, maintenant)
            evenements.append(Evenement(
                cle=f"vigilance-{ligne.departement_code}-{phenomene}-{debut.date() if debut else maintenant.date()}",
                valeur=niveau["couleur"], titre=texte.split(" - ", 1)[0],
                detail=texte))
    return evenements


def _crues(perimetre, regle, maintenant, contexte):
    from . import vigilance_crues
    from .models import TronconVigilanceCrues

    evenements = []
    for troncon in TronconVigilanceCrues.objects.filter(geometrie__intersects=perimetre.polygone(regle.reglage("rayon_km"))):
        if not _recent(troncon.releve_le, maintenant, datetime.timedelta(hours=12)):
            continue
        couleur = vigilance_crues.COULEURS.get(troncon.niveau, "")
        evenements.append(Evenement(
            cle=f"crue-{troncon.code}-{troncon.niveau}", valeur=troncon.niveau or 0,
            titre=f"Vigilance crues {couleur} : {troncon.nom}", detail="Source : Vigicrues."))
    return evenements


def _montee_eau(perimetre, regle, maintenant, contexte):
    from .models import StationHydrometrique

    rayon = regle.reglage("rayon_km")
    evenements = []
    for station in StationHydrometrique.objects.filter(location__within=perimetre.polygone(rayon)).exclude(variation_3h_cm=None):
        if not _recent(station.hauteur_le, maintenant, datetime.timedelta(hours=3)):
            continue
        if perimetre.distance_km(station.location.y, station.location.x) > rayon:
            continue
        evenements.append(Evenement(
            cle=f"montee-{station.code}", valeur=round(station.variation_3h_cm),
            titre=f"{station.cours_eau or 'Cours d’eau'} à {station.nom} : +{station.variation_3h_cm:.0f} cm en 3 h",
            detail=f"Hauteur mesurée : {station.hauteur_m:.2f} m. Source : Hub'Eau." if station.hauteur_m is not None else "Source : Hub'Eau.",
            latitude=station.location.y, longitude=station.location.x))
    return evenements


def _surcote(perimetre, regle, maintenant, contexte):
    from .models import Maregraphe

    rayon = regle.reglage("rayon_km")
    evenements = []
    for maregraphe in Maregraphe.objects.filter(location__within=perimetre.polygone(rayon)).exclude(surcote_cm=None):
        if not _recent(maregraphe.niveau_le, maintenant, datetime.timedelta(hours=3)):
            continue
        if perimetre.distance_km(maregraphe.location.y, maregraphe.location.x) > rayon:
            continue
        evenements.append(Evenement(
            cle=f"surcote-{maregraphe.code}", valeur=maregraphe.surcote_cm,
            titre=f"Mer au-dessus de la marée prévue à {maregraphe.nom} : +{maregraphe.surcote_cm} cm",
            detail="Source : Shom, réseau REFMAR.", latitude=maregraphe.location.y, longitude=maregraphe.location.x))
    return evenements


def _restrictions_eau(perimetre, regle, maintenant, contexte):
    from . import restrictions_eau
    from .models import RestrictionEau

    evenements = []
    for ligne in RestrictionEau.objects.filter(departement_code__in=perimetre.departements):
        if ligne.niveau not in restrictions_eau.NIVEAUX:
            continue
        rang = restrictions_eau.NIVEAUX.index(ligne.niveau) + 1
        evenements.append(Evenement(
            cle=f"restriction-{ligne.departement_code}-{ligne.niveau}", valeur=rang,
            titre=f"Restrictions d'eau : {restrictions_eau.LIBELLES.get(ligne.niveau, ligne.niveau)} ({ligne.departement_code})",
            detail="Source : VigiEau."))
    return evenements


def _orages(perimetre, regle, maintenant, contexte):
    from .models import CelluleOrage

    codes = perimetre.codes
    evenements = []
    for cellule in CelluleOrage.objects.filter(heure_image__gte=maintenant - datetime.timedelta(minutes=20)):
        touchees = [c for c in cellule.communes_touchees or [] if c.get("code") in codes]
        if not touchees:
            continue
        violent = bool(cellule.grele_prevue or cellule.doppler_rotation or cellule.doppler_grele)
        noms = ", ".join(c.get("nom", c["code"]) for c in touchees[:4])
        evenements.append(Evenement(
            cle=f"orage-{cellule.identifiant}", valeur=round(cellule.max_mmh),
            titre=f"Orage intense sur {noms} ({cellule.max_mmh:.0f} mm/h{', grêle ou rotation' if violent else ''})",
            detail=(f"Se déplace vers {cellule.cap_deg}° à {cellule.vitesse_kmh} km/h. " if cellule.cap_deg is not None and cellule.vitesse_kmh else "")
            + "Source : radars Météo-France.",
            latitude=cellule.centre.y, longitude=cellule.centre.x, au_moins=EXCEPTIONNEL if violent else None))
    return evenements


def _foudre(perimetre, regle, maintenant, contexte):
    from .models import ImpactFoudre

    rayon = regle.reglage("rayon_km")
    impacts = [i for i in ImpactFoudre.objects.filter(instant__gte=maintenant - datetime.timedelta(minutes=15),
                                                      location__within=perimetre.polygone(rayon)).only("location")
               if perimetre.distance_km(i.location.y, i.location.x) <= rayon]
    if not impacts:
        return []
    heure = maintenant.replace(minute=0, second=0, microsecond=0)
    return [Evenement(cle=f"foudre-{heure:%Y%m%d%H}", valeur=len(impacts),
                      titre=f"Foudre : {len(impacts)} impact(s) à moins de {rayon:.0f} km en 15 minutes",
                      detail="Source : EUMETSAT (MTG).",
                      latitude=impacts[0].location.y, longitude=impacts[0].location.x)]


def _rangs(png, points):
    """Rang de palette aux points d'une image de `rafales.peindre_rangs`, image ouverte une fois."""
    import io

    from PIL import Image

    from . import pluie, rafales

    image = Image.open(io.BytesIO(png))
    ouest, sud, est, nord = rafales.EMPRISE_IMAGE
    haut, bas = pluie._mercator(nord), pluie._mercator(sud)
    rangs = []
    for latitude, longitude in points:
        if not (ouest <= longitude <= est and sud <= latitude <= nord):
            rangs.append(None)
            continue
        colonne = min(image.width - 1, int((longitude - ouest) / (est - ouest) * image.width))
        ligne = min(image.height - 1, int((haut - pluie._mercator(latitude)) / (haut - bas) * image.height))
        rangs.append(image.getpixel((colonne, ligne)))
    return rangs


def _images_a_venir(modele, maintenant, heures):
    return list(modele.objects.filter(echeance__gte=maintenant - datetime.timedelta(minutes=30),
                                      echeance__lte=maintenant + datetime.timedelta(hours=heures)).order_by("echeance"))


def _rafales(perimetre, regle, maintenant, contexte):
    from . import rafales
    from .models import ImageRafales

    points = [(c[2], c[3]) for c in perimetre.communes]
    pire, ou, quand = 0, None, None
    for image in _images_a_venir(ImageRafales, maintenant, 6):
        for rang, commune in zip(_rangs(bytes(image.image), points), perimetre.communes):
            palier = rafales.SEUILS_KMH[rang - 1] if rang else 0
            if palier > pire:
                pire, ou, quand = palier, commune, image.echeance
    if not pire:
        return []
    return [Evenement(cle=f"rafales-{maintenant:%Y%m%d}", valeur=pire,
                      titre=f"Rafales de {pire} km/h ou plus prévues à {ou[1]}",
                      detail=f"Vers {timezone.localtime(quand):%H h %M}. Source : Météo-France (prévision immédiate).",
                      latitude=ou[2], longitude=ou[3])]


#: Gravité des précipitations d'hiver, du plus bénin au plus dangereux (échelle des seuils).
GRAVITE_HIVER = {"GRESIL": 1, "NEIGE_HUMIDE": 1, "NEIGE": 2, "VERGLAS": 3, "GRELE": 4}


def _precipitations_hiver(perimetre, regle, maintenant, contexte):
    from . import precipitations_hiver
    from .models import ImagePrecipitationHiver

    libelles = {cle: libelle for cle, libelle, _t, _c in precipitations_hiver.FAMILLES}
    points = [(c[2], c[3]) for c in perimetre.communes]
    pire, famille, ou = 0, None, None
    for image in _images_a_venir(ImagePrecipitationHiver, maintenant, 6):
        for rang, commune in zip(_rangs(bytes(image.image), points), perimetre.communes):
            cle = precipitations_hiver.FAMILLES[rang - 1][0] if rang else ""
            if GRAVITE_HIVER.get(cle, 0) > pire:
                pire, famille, ou = GRAVITE_HIVER[cle], cle, commune
    if not pire:
        return []
    return [Evenement(cle=f"hiver-{famille}-{maintenant:%Y%m%d}", valeur=pire,
                      titre=f"{libelles[famille]} prévue à {ou[1]}",
                      detail="Dans les six heures. Source : Météo-France (prévision immédiate).",
                      latitude=ou[2], longitude=ou[3])]


def _pluie(perimetre, regle, maintenant, contexte):
    from .models import CumulPluieCommune

    from .orages import derniere_image_pluie

    # Cumuls périmés (radar muet depuis 40 min) : pas d'alerte. La table n'est réécrite que pour
    # les communes qui changent (orages.ecrire_cumuls) : la fraîcheur se lit sur la dernière image.
    derniere = derniere_image_pluie()
    if derniere is None or derniere < maintenant - datetime.timedelta(minutes=40):
        return []
    noms = {c[0]: c for c in perimetre.communes}
    pire = CumulPluieCommune.objects.filter(commune_code__in=list(noms)).order_by("-mm_1h").first()
    if pire is None or not pire.mm_1h:
        return []
    commune = noms[pire.commune_code]
    return [Evenement(cle=f"pluie-{pire.commune_code}-{maintenant:%Y%m%d%H}", valeur=round(pire.mm_1h),
                      titre=f"Pluie intense à {commune[1]} : {pire.mm_1h:.0f} mm en 1 h",
                      detail=f"{pire.mm_3h:.0f} mm en 3 h, {pire.mm_24h:.0f} mm en 24 h. Source : radars Météo-France.",
                      latitude=commune[2], longitude=commune[3])]


def _foyers(perimetre, regle, maintenant, contexte):
    from .models import FoyerActif

    rayon = regle.reglage("rayon_km")
    foyers = [f for f in FoyerActif.objects.filter(date__gte=maintenant - datetime.timedelta(hours=24), source_fixe=False,
                                                   location__within=perimetre.polygone(rayon))
              if perimetre.distance_km(f.location.y, f.location.x) <= rayon]
    if not foyers:
        return []
    proche = min(foyers, key=lambda f: perimetre.distance_km(f.location.y, f.location.x))
    maille = f"{round(proche.location.y * 20)}-{round(proche.location.x * 20)}"
    return [Evenement(cle=f"foyers-{maille}-{maintenant:%Y%m%d}", valeur=len(foyers),
                      titre=f"Feu possible : {len(foyers)} détection(s) satellite {_lieu(perimetre, proche.location.y, proche.location.x)}",
                      detail="Écobuages et brûlages donnent aussi des détections : à vérifier. Source : NASA FIRMS.",
                      latitude=proche.location.y, longitude=proche.location.x)]


def _feu_suivi(perimetre, regle, maintenant, contexte):
    from .models import FeuSuivi

    rayon = regle.reglage("rayon_km")
    evenements = []
    for feu in FeuSuivi.objects.filter(statut="actif", source_fixe=False, centre__within=perimetre.polygone(rayon)):
        d = perimetre.distance_km(feu.centre.y, feu.centre.x)
        if d > rayon:
            continue
        evenements.append(Evenement(
            cle=f"feu-mtg-{feu.identifiant}", valeur=round(feu.puissance_max_mw),
            titre=f"Feu suivi par satellite {_lieu(perimetre, feu.centre.y, feu.centre.x)} ({feu.puissance_max_mw:.0f} MW)",
            detail="Source : EUMETSAT LSA SAF (MTG), toutes les dix minutes.",
            latitude=feu.centre.y, longitude=feu.centre.x, au_moins=EXCEPTIONNEL if d <= 5 else None))
    return evenements


def _danger_feu(perimetre, regle, maintenant, contexte):
    from . import meteo_forets
    from .models import DangerFeuForet

    evenements = []
    for ligne in DangerFeuForet.objects.filter(pk__in=perimetre.departements).exclude(niveau_demain=None):
        if not _recent(ligne.releve_le, maintenant, datetime.timedelta(hours=36)):
            continue
        evenements.append(Evenement(
            cle=f"danger-feu-{ligne.departement_code}-{ligne.niveau_demain}-{maintenant:%Y%m%d}", valeur=ligne.niveau_demain,
            titre=f"Danger de feu de forêt {meteo_forets.NIVEAUX.get(ligne.niveau_demain, '')} demain ({ligne.departement_code})",
            detail="Source : Météo-France, météo des forêts."))
    return evenements


def _orage_feu(perimetre, regle, maintenant, contexte):
    from . import orages_de_feu
    from .models import PotentielOrageFeu

    pire, ou, quand = 0, None, None
    for grille in _images_a_venir(PotentielOrageFeu, maintenant, 24):
        rangs = orages_de_feu.decoder(grille.grilles, grille.largeur, grille.hauteur)["rang"]
        for commune in perimetre.communes:
            colonne = min(grille.largeur - 1, max(0, round((commune[3] - grille.ouest) / orages_de_feu.PAS_DEGRES)))
            ligne = min(grille.hauteur - 1, max(0, round((grille.nord - commune[2]) / orages_de_feu.PAS_DEGRES)))
            palier = int(rangs[ligne, colonne])
            if palier > pire:
                pire, ou, quand = palier, commune, grille.echeance
    if not pire:
        return []
    return [Evenement(cle=f"orage-feu-{maintenant:%Y%m%d}", valeur=pire,
                      titre=f"Potentiel d'orage de feu {orages_de_feu.LIBELLES.get(pire)} vers {ou[1]}",
                      detail=f"Échéance {timezone.localtime(quand):%d/%m %H h}. Estimation Assista-Crise (modèle ARPEGE).",
                      latitude=ou[2], longitude=ou[3])]


def _zones_brulees(perimetre, regle, maintenant, contexte):
    from .models import ZoneBrulee

    rayon = regle.reglage("rayon_km")
    evenements = []
    for zone in ZoneBrulee.objects.filter(date_feu__gte=maintenant - datetime.timedelta(days=3),
                                          location__within=perimetre.polygone(rayon)):
        if perimetre.distance_km(zone.location.y, zone.location.x) > rayon:
            continue
        evenements.append(Evenement(
            cle=f"brulee-{zone.reference}", valeur=round(zone.surface_ha),
            titre=f"Surface brûlée de {zone.surface_ha:.0f} ha {_lieu(perimetre, zone.location.y, zone.location.x)}",
            detail="© Union européenne, Copernicus EFFIS.", latitude=zone.location.y, longitude=zone.location.x))
    return evenements


def _avalanche(perimetre, regle, maintenant, contexte):
    from . import avalanche
    from .models import RisqueAvalanche

    evenements = []
    for massif in RisqueAvalanche.objects.filter(geometrie__intersects=perimetre.polygone()):
        risque = max(massif.risque or 0, massif.risque_demain or 0)
        if not risque:
            continue
        evenements.append(Evenement(
            cle=f"avalanche-{massif.massif_code}-{risque}-{(massif.publie_le or maintenant):%Y%m%d}", valeur=risque,
            titre=f"Risque d'avalanche {avalanche.NIVEAUX.get(risque, risque)} ({risque}/5) : massif {massif.nom}",
            detail=(massif.commentaire or "") + " Source : Météo-France, bulletin d'estimation du risque d'avalanche."))
    return evenements


def _qualite_air(perimetre, regle, maintenant, contexte):
    from . import qualite_air
    from .models import PointQualiteAir

    rayon = regle.reglage("rayon_km")
    evenements = []
    for point in PointQualiteAir.objects.filter(location__within=perimetre.polygone(rayon)):
        if not _recent(point.mesure_le, maintenant, datetime.timedelta(hours=4)):
            continue
        if perimetre.distance_km(point.location.y, point.location.x) > rayon:
            continue
        evenements.append(Evenement(
            cle=f"air-{point.code}-{maintenant:%Y%m%d}", valeur=point.indice,
            titre=f"Qualité de l'air {qualite_air.LIBELLES.get(point.indice, '')} à {point.nom}",
            detail=f"Source : {qualite_air.ATTRIBUTION}.",
            latitude=point.location.y, longitude=point.location.x))
    return evenements


def _radioactivite(perimetre, regle, maintenant, contexte):
    from .models import MesureRadioactivite

    rayon = regle.reglage("rayon_km")
    evenements = []
    for balise in MesureRadioactivite.objects.filter(valide=True, location__within=perimetre.polygone(rayon)):
        if not balise.bruit_de_fond_nsv_h or not _recent(balise.mesure_le, maintenant, datetime.timedelta(hours=6)):
            continue
        if perimetre.distance_km(balise.location.y, balise.location.x) > rayon:
            continue
        rapport = round(balise.debit_nsv_h / balise.bruit_de_fond_nsv_h, 1)
        evenements.append(Evenement(
            cle=f"radio-{balise.station}-{maintenant:%Y%m%d}", valeur=rapport,
            titre=f"Radioactivité ambiante ×{rapport} à la balise {balise.nom}",
            detail=f"{balise.debit_nsv_h:.0f} nSv/h pour un bruit de fond de {balise.bruit_de_fond_nsv_h:.0f}. Source : IRSN, Téléray.",
            latitude=balise.location.y, longitude=balise.location.x))
    return evenements


# ── Le catalogue ──────────────────────────────────────────────────────────────

Phenomene = namedtuple(
    "Phenomene",
    "code libelle famille source unite alerte exceptionnel minimum maximum pas radio memoire_h reglages detecter "
    "type_crise rapide echelle",
)

H = datetime.timedelta(hours=1)


def _p(code, libelle, famille, source, unite, alerte, exceptionnel, minimum, maximum, detecter, pas=1, radio=True,
       memoire_h=24, reglages=None, type_crise="AUTRE", rapide=False, echelle=None):
    return Phenomene(code, libelle, famille, source, unite, alerte, exceptionnel, minimum, maximum, pas, radio,
                     memoire_h, reglages or {}, detecter, type_crise, rapide, echelle)


COULEURS_VIGILANCE = {2: "jaune", 3: "orange", 4: "rouge", 5: "violet"}

CATALOGUE = [
    _p("SEISME", "Séisme", "Terre", "SEISMES", "magnitude", 3.5, 4.5, 2.0, 7.0, _seismes, pas=0.1,
       reglages={"rayon_km": (100, 10, 300)}, type_crise="CATASTROPHE_NATURELLE", rapide=True, memoire_h=24 * 7),
    _p("VOLCAN", "Activité volcanique (outre-mer)", "Terre", "SEISMES", "× semaine passée", 3, 10, 2, 50, _volcans,
       reglages={"rayon_km": (250, 20, 500)}, memoire_h=24 * 7, type_crise="CATASTROPHE_NATURELLE"),
    _p("VIGILANCE_METEO", "Vigilance Météo-France", "Météo", "VIGILANCE_METEO", "couleur", 3, 4, 2, 5, _vigilance_meteo,
       echelle=COULEURS_VIGILANCE, type_crise="CATASTROPHE_NATURELLE", memoire_h=48),
    _p("ORAGES", "Orages intenses (radar)", "Météo", "ORAGES_RADAR", "mm/h", 30, 60, 10, 150, _orages,
       type_crise="CATASTROPHE_NATURELLE", rapide=True, memoire_h=3),
    _p("FOUDRE", "Foudre", "Météo", "FOUDRE_MTG", "impacts en 15 min", 5, 20, 1, 500, _foudre,
       reglages={"rayon_km": (10, 2, 50)}, rapide=True, memoire_h=2),
    _p("RAFALES", "Rafales prévues", "Météo", "RAFALES_PREVISION", "km/h", 80, 120, 40, 140, _rafales, pas=20,
       type_crise="CATASTROPHE_NATURELLE", memoire_h=12),
    _p("PLUIE", "Pluie intense (cumul radar)", "Météo", "ORAGES_RADAR", "mm en 1 h", 30, 50, 10, 150, _pluie,
       type_crise="INONDATION", rapide=True, memoire_h=3),
    _p("HIVER", "Neige, verglas, grêle prévus", "Météo", "PRECIPITATIONS_HIVER", "gravité", 2, 4, 1, 4,
       _precipitations_hiver, echelle={1: "grésil, neige humide", 2: "neige", 3: "verglas", 4: "grêle"},
       type_crise="CATASTROPHE_NATURELLE", memoire_h=12),
    _p("CRUES", "Vigilance crues", "Eau", "VIGILANCE_CRUES", "couleur", 3, 4, 2, 4, _crues,
       echelle={2: "jaune", 3: "orange", 4: "rouge"}, reglages={"rayon_km": (5, 0, 30)}, type_crise="INONDATION"),
    _p("MONTEE_EAU", "Montée rapide d'un cours d'eau", "Eau", "HAUTEURS_EAU", "cm en 3 h", 50, 100, 10, 500, _montee_eau,
       pas=10, reglages={"rayon_km": (10, 0, 50)}, type_crise="INONDATION", memoire_h=6),
    _p("SURCOTE", "Niveau de la mer au-dessus de la marée", "Eau", "NIVEAUX_MER", "cm", 40, 80, 10, 300, _surcote,
       pas=10, reglages={"rayon_km": (30, 5, 100)}, type_crise="INONDATION", memoire_h=12),
    _p("RESTRICTIONS_EAU", "Restrictions d'eau", "Eau", "RESTRICTIONS_EAU", "niveau", 3, 4, 1, 4, _restrictions_eau,
       echelle={1: "vigilance", 2: "alerte", 3: "alerte renforcée", 4: "crise"}, radio=False, memoire_h=24 * 7,
       type_crise="AUTRE"),
    _p("FOYERS", "Foyers détectés par satellite", "Feu", "FOYERS_ACTIFS", "détections en 24 h", 2, 5, 1, 50, _foyers,
       reglages={"rayon_km": (15, 2, 60)}, type_crise="INCENDIE", memoire_h=24),
    _p("FEU_SUIVI", "Feu suivi par satellite (MTG)", "Feu", "FEUX_MTG", "MW", 10, 50, 1, 1000, _feu_suivi,
       reglages={"rayon_km": (15, 2, 60)}, type_crise="INCENDIE", rapide=True, memoire_h=24),
    _p("DANGER_FEU", "Danger de feu de forêt", "Feu", "METEO_FORETS", "niveau", 3, 4, 2, 4, _danger_feu,
       echelle={2: "modéré", 3: "élevé", 4: "très élevé"}, type_crise="INCENDIE", memoire_h=20),
    _p("ORAGE_FEU", "Potentiel d'orage de feu", "Feu", "POTENTIEL_ORAGE_FEU", "niveau", 2, 3, 1, 3, _orage_feu,
       echelle={1: "modéré", 2: "élevé", 3: "très élevé"}, type_crise="INCENDIE", memoire_h=20),
    _p("ZONES_BRULEES", "Surfaces brûlées", "Feu", "FEUX_SATELLITE", "ha", 10, 500, 1, 10000, _zones_brulees,
       reglages={"rayon_km": (20, 2, 100)}, radio=False, type_crise="INCENDIE", memoire_h=24 * 7),
    _p("AVALANCHE", "Risque d'avalanche", "Montagne", "AVALANCHE", "niveau sur 5", 3, 4, 2, 5, _avalanche,
       echelle={2: "limité", 3: "marqué", 4: "fort", 5: "très fort"}, type_crise="CATASTROPHE_NATURELLE", memoire_h=20),
    _p("QUALITE_AIR", "Qualité de l'air", "Air et radioactivité", "QUALITE_AIR", "indice sur 5", 4, 5, 3, 5, _qualite_air,
       echelle={3: "moyen", 4: "mauvais", 5: "très mauvais"}, reglages={"rayon_km": (30, 5, 100)}, memoire_h=20,
       type_crise="AUTRE"),
    _p("RADIOACTIVITE", "Radioactivité ambiante", "Air et radioactivité", "RADIOACTIVITE", "× bruit de fond", 2, 10, 1.5, 100,
       _radioactivite, pas=0.5, reglages={"rayon_km": (50, 10, 200)}, type_crise="AUTRE", memoire_h=24),
]
PAR_CODE = {p.code: p for p in CATALOGUE}


def valeurs_conseillees(phenomene):
    return {"alerte": phenomene.alerte, "exceptionnel": phenomene.exceptionnel,
            **{nom: defaut for nom, (defaut, _mini, _maxi) in phenomene.reglages.items()}}


def valider_seuils(phenomene, seuils):
    """Les seuils d'une règle, ramenés dans les bornes du catalogue. Lève ValueError si incohérents."""
    propres = valeurs_conseillees(phenomene)
    for cle in ("alerte", "exceptionnel"):
        if cle in (seuils or {}):
            valeur = float(seuils[cle])
            if not phenomene.minimum <= valeur <= phenomene.maximum:
                raise ValueError(f"{phenomene.libelle} : le seuil doit rester entre {phenomene.minimum} et {phenomene.maximum}.")
            propres[cle] = valeur
    if propres["exceptionnel"] < propres["alerte"]:
        raise ValueError(f"{phenomene.libelle} : le seuil exceptionnel ne peut pas être sous le seuil d'alerte.")
    for nom, (_defaut, mini, maxi) in phenomene.reglages.items():
        if nom in (seuils or {}):
            valeur = float(seuils[nom])
            if not mini <= valeur <= maxi:
                raise ValueError(f"{phenomene.libelle} : {nom} doit rester entre {mini} et {maxi}.")
            propres[nom] = valeur
    return propres


# ── Le moteur ─────────────────────────────────────────────────────────────────

def niveau_de(phenomene, regle, evenement):
    niveau = None
    if evenement.valeur >= regle.seuil(EXCEPTIONNEL):
        niveau = EXCEPTIONNEL
    elif evenement.valeur >= regle.seuil(ALERTE):
        niveau = ALERTE
    if evenement.au_moins == EXCEPTIONNEL and niveau == ALERTE:
        niveau = EXCEPTIONNEL
    return niveau


def de_nuit(maintenant):
    heure = timezone.localtime(maintenant).hour
    return heure >= NUIT_DEBUT or heure < NUIT_FIN


def _deja_dit(regle, phenomene, evenement, niveau, maintenant):
    from .models import AlerteNaturelle

    connues = AlerteNaturelle.objects.filter(institution_id=regle.institution_id, phenomene=phenomene.code,
                                             cle=evenement.cle,
                                             emise_le__gte=maintenant - datetime.timedelta(hours=phenomene.memoire_h))
    if niveau == ALERTE:
        return connues.exists()
    return connues.filter(niveau=EXCEPTIONNEL).exists()


def destinataires(regle):
    from .models import ContactInstitution, User
    from .permissions import INSTITUTIONAL_TYPES

    contacts = list(ContactInstitution.objects.filter(institution_id=regle.institution_id, actif=True,
                                                      utilisateur__is_active=True).select_related("utilisateur"))
    if regle.destinataires == "PRINCIPAUX":
        contacts = [c for c in contacts if c.contact_principal] or contacts
    personnes = {c.utilisateur.pk: c.utilisateur for c in contacts}
    if not personnes:
        personnes = {u.pk: u for u in User.objects.filter(institution_id=regle.institution_id, is_active=True,
                                                          type__in=INSTITUTIONAL_TYPES)}
    return list(personnes.values())


def _ascii(texte):
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c) and ord(c) < 128)


def _compagnon(modele, institution):
    """La radio qui émet : celle de la collectivité d'abord (à portée de ses membres), puis la
    radio principale, puis n'importe laquelle — jamais une radio de navigateur sans relais vivant
    (même règle que l'envoi des clés de canal, views._compagnon_pour_equipe)."""
    from .relais_navigateur import emetteurs

    actifs = emetteurs(modele.objects.filter(actif=True))
    return (actifs.filter(institution=institution).order_by("-principal").first()
            or actifs.filter(principal=True).first() or actifs.first())


def _radio(regle, alerte, personnes):
    """Message radio DIRECT à la radio personnelle de chaque personne prévenue (décision de
    Sylvain du 24/11/2026 : « on passe en message direct pour ne pas inonder Fr_EMCOM ») —
    jamais sur un canal partagé. Rend le nombre de messages déposés."""
    from .models import (
        CompagnonMeshCore, CompagnonMeshtastic, DirectionMessageMesh, MessageMeshLog, MessageMeshtasticLog,
        NoeudMeshUtilisateur, NoeudUtilisateurMeshtastic, StatutMessageMesh,
    )

    texte = _ascii(f"ALERTE {alerte.titre}")[:LONGUEUR_RADIO]
    ids = [p.pk for p in personnes]
    deposes = 0
    meshcore = _compagnon(CompagnonMeshCore, regle.institution)
    if meshcore is not None:
        for noeud in NoeudMeshUtilisateur.objects.filter(utilisateur_id__in=ids, actif=True):
            MessageMeshLog.objects.create(compagnon=meshcore, direction=DirectionMessageMesh.SORTANT,
                                          contact_pubkey_hex=noeud.pubkey_hex, contenu=texte,
                                          statut=StatutMessageMesh.EN_ATTENTE, environment=regle.environment)
            deposes += 1
    meshtastic = _compagnon(CompagnonMeshtastic, regle.institution)
    if meshtastic is not None:
        for noeud in NoeudUtilisateurMeshtastic.objects.filter(utilisateur_id__in=ids, actif=True):
            MessageMeshtasticLog.objects.create(compagnon=meshtastic, canal=None, direction=DirectionMessageMesh.SORTANT,
                                                contact_node_num=noeud.node_num, contenu=texte,
                                                statut=StatutMessageMesh.EN_ATTENTE, environment=regle.environment)
            deposes += 1
    return deposes


def _courriel(regle, alerte, personnes):
    from django.conf import settings

    from .branding import send_branded_mail

    lien = f"{settings.SERVER_URL.rstrip('/')}/admin/alertes-automatiques?alerte={alerte.id}"
    sujet = f"{'ALERTE EXCEPTIONNELLE' if alerte.niveau == EXCEPTIONNEL else 'Alerte'} — {alerte.titre}"
    corps = (f"{alerte.titre}\n\n{alerte.detail}\n\nVoir l'alerte, ouvrir une crise ou demander les disponibilités : "
             f"{lien}\n\n{{signature}}")
    adresses = sorted({p.email for p in personnes if p.email and "@" in p.email})
    envoyes = 0
    for adresse in adresses:
        try:
            send_branded_mail(None, regle.institution, sujet, corps, [adresse], fail_silently=False)
            envoyes += 1
        except Exception:
            logger.exception("Alerte naturelle : courriel non parti (alerte %s).", alerte.id)
    return envoyes


def _prevenir(regle, alerte, maintenant):
    from .notifications_application import prevenir

    personnes = destinataires(regle)
    # Les associations qui ont obtenu « alertes de la commune » pour une manifestation en cours
    # (26/11/2026, core/partage_manifestation.py) : bureau et inscrits.
    try:
        from .partage_manifestation import personnes_alertees
        deja = {p.pk for p in personnes}
        personnes = personnes + [p for p in personnes_alertees(regle.institution, maintenant) if p.pk not in deja]
    except Exception:
        logger.exception("Alerte naturelle : associations des manifestations non ajoutées (alerte %s).", alerte.id)
    urgent = alerte.niveau == EXCEPTIONNEL
    for personne in personnes:
        prevenir(personne, alerte.titre, alerte.detail, urgent=urgent,
                 lien=f"/admin/alertes-automatiques?alerte={alerte.id}", institution=regle.institution,
                 environment=regle.environment)
    bilan = {"personnes": len(personnes), "courriels": 0, "radio": 0}
    if regle.email:
        bilan["courriels"] = _courriel(regle, alerte, personnes)
    phenomene = PAR_CODE[regle.phenomene]
    if urgent and regle.radio_si_exceptionnel and phenomene.radio:
        try:
            bilan["radio"] = _radio(regle, alerte, personnes)
        except Exception:
            logger.exception("Alerte naturelle : radio non déposée (alerte %s).", alerte.id)
    return bilan


def evaluer(phenomenes=None, maintenant=None, contexte=None):
    """Passe les règles actives (des phénomènes donnés, ou toutes) ; rend les alertes émises.

    Jamais d'exception vers l'appelant : un détecteur en panne ne bloque ni les autres, ni le
    relevé qui l'a appelé."""
    from . import sources_ouvertes
    from .models import AlerteNaturelle, RegleAlerte

    maintenant = maintenant or timezone.now()
    contexte = contexte or {}
    regles = RegleAlerte.objects.filter(actif=True).select_related("institution")
    if phenomenes is not None:
        regles = regles.filter(phenomene__in=list(phenomenes))
    perimetres, perimees, emises = {}, {}, []
    for regle in regles:
        phenomene = PAR_CODE.get(regle.phenomene)
        if phenomene is None:
            continue
        if phenomene.source not in perimees:
            perimees[phenomene.source] = (phenomene.source in sources_ouvertes.SOURCES
                                          and sources_ouvertes.est_perime(phenomene.source, maintenant))
        if perimees[phenomene.source] and not contexte.get("seismes"):
            continue
        if regle.institution_id not in perimetres:
            try:
                perimetres[regle.institution_id] = perimetre_de(regle.institution)
            except Exception:
                logger.exception("Alerte naturelle : périmètre illisible (institution %s).", regle.institution_id)
                perimetres[regle.institution_id] = None
        perimetre = perimetres[regle.institution_id]
        if perimetre is None:
            continue
        try:
            evenements = phenomene.detecter(perimetre, regle, maintenant, contexte)
        except Exception:
            logger.exception("Alerte naturelle : détecteur %s en échec.", phenomene.code)
            continue
        for evenement in evenements:
            niveau = niveau_de(phenomene, regle, evenement)
            if niveau is None or _deja_dit(regle, phenomene, evenement, niveau, maintenant):
                continue
            if niveau == ALERTE and regle.silence_nuit and de_nuit(maintenant):
                continue
            point = None
            if evenement.latitude is not None and evenement.longitude is not None:
                from django.contrib.gis.geos import Point
                point = Point(evenement.longitude, evenement.latitude, srid=4326)
            alerte = AlerteNaturelle.objects.create(
                institution=regle.institution, phenomene=phenomene.code, cle=evenement.cle[:120], niveau=niveau,
                valeur=evenement.valeur, titre=evenement.titre[:200], detail=evenement.detail, lieu=point,
                emise_le=maintenant, environment=regle.environment)
            try:
                alerte.bilan = _prevenir(regle, alerte, maintenant)
                alerte.save(update_fields=["bilan"])
            except Exception:
                logger.exception("Alerte naturelle : prévenance en échec (alerte %s).", alerte.id)
            emises.append(alerte)
    if emises:
        _resume_administrateurs(emises)
    return emises


def _resume_administrateurs(emises):
    from .notifications_application import prevenir_administrateurs

    lignes = [f"{a.institution.nom} : {a.titre}" for a in emises[:20]]
    if len(emises) > 20:
        lignes.append(f"… et {len(emises) - 20} autres.")
    prevenir_administrateurs(f"Alertes automatiques ({len(emises)})", "\n".join(lignes),
                             urgent=any(a.niveau == EXCEPTIONNEL for a in emises), lien="/admin/alertes-automatiques")


PHENOMENES_RAPIDES = [p.code for p in CATALOGUE if p.rapide]
PHENOMENES_LENTS = [p.code for p in CATALOGUE if not p.rapide]


#: Les sources relevées sous un autre code que celui du catalogue.
SOURCES_EQUIVALENTES = {"VIGILANCE_OUTRE_MER": "VIGILANCE_METEO"}


def phenomenes_de_source(code_source):
    """Les phénomènes lents à passer après le relevé de cette source."""
    code_source = SOURCES_EQUIVALENTES.get(code_source, code_source)
    return [p.code for p in CATALOGUE if p.source == code_source and not p.rapide]
