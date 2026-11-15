"""Foyers d'incendie actifs vus par satellite : relevé de NASA FIRMS, copie en base, et
annonce aux institutions qui l'ont demandée.

SOURCE
FIRMS (Fire Information for Resource Management System, NASA), fichiers publics des détections
des sept derniers jours en Europe, sans clé : https://firms.modaps.eosdis.nasa.gov. Quatre
capteurs -- VIIRS sur trois satellites (375 m) et MODIS (1 km) --, soit environ six passages par
jour, publiés trois heures après. Données libres, à citer (« NASA FIRMS »). Ce n'est pas un
service de l'État français : il n'en existe pas d'équivalent.

CE QUE C'EST
Un « foyer » est un pixel plus chaud que ses voisins. C'est le complément des surfaces brûlées
d'EFFIS (core/feux_satellite.py) : celles-ci disent ce qui A brûlé, avec un jour de retard ;
les foyers disent ce qui brûle, avec trois heures de retard.

CE QUE CE N'EST PAS, ET C'EST L'ESSENTIEL
Un pixel chaud n'est pas forcément un feu de forêt. Relevé du 15/11/2026 : sur 109 détections
en 24 heures dans l'emprise de la France, presque toutes étaient des hauts-fourneaux et des
torchères (Dunkerque, Fos-sur-Mer, la Sarre). D'où deux règles :

1. Une maille de 2 km où l'on détecte de la chaleur QUATRE JOURS sur sept -- en comptant ses
   voisines immédiates, un grand site débordant d'une maille -- est marquée « source fixe » :
   un feu de forêt avance ou s'éteint, une usine reste. Les sources fixes sont gardées
   -- les effacer ferait croire que le satellite ne les voit pas -- mais affichées à part, et
   jamais annoncées.
2. Tout le reste est dit « à vérifier » : écobuage, feu de chaume, brûlage de déchets verts
   donnent le même signal qu'un départ de feu.

Et l'inverse est vrai : sous les nuages ou la fumée épaisse, entre deux passages, un feu réel
n'est pas vu. L'absence de foyer ne dit pas qu'il n'y a pas de feu.

Même règle que le reste de la veille : seul le serveur appelle, pour toute l'emprise.
"""
import csv
import datetime
import io
import logging
import math

import requests
from django.contrib.gis.geos import Point, Polygon
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire"
FICHIERS = (
    "noaa-20-viirs-c2/csv/J1_VIIRS_C2_Europe_7d.csv",
    "noaa-21-viirs-c2/csv/J2_VIIRS_C2_Europe_7d.csv",
    "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Europe_7d.csv",
    "modis-c6.1/csv/MODIS_C6_1_Europe_7d.csv",
)
DELAI_REPONSE_S = 60
# Métropole et Corse : (ouest, sud, est, nord). Le rectangle déborde sur les pays voisins, ce
# qui sert les communes frontalières.
EMPRISE = (-5.5, 41.0, 10.0, 51.5)
# Ce qui est gardé en base et montré : les deux derniers jours.
PROFONDEUR = datetime.timedelta(hours=48)
# Maille de repérage des sources fixes (environ 2 km) et seuil en jours distincts sur sept.
MAILLE_FIXE = 0.02
JOURS_POUR_SOURCE_FIXE = 4

# ── Annonce ──
# Maille de regroupement d'un même feu pour l'annonce (environ 5 km).
MAILLE_ANNONCE = 0.05
# Une détection isolée de confiance ordinaire ne suffit pas : il en faut deux dans la maille,
# ou une de confiance élevée.
DETECTIONS_POUR_ANNONCER = 2
# On n'annonce que du récent, et pas deux fois le même feu en trois jours.
FRAICHEUR_ANNONCE = datetime.timedelta(hours=8)
SILENCE_APRES_ANNONCE = datetime.timedelta(days=3)


def telecharger():
    """Les fichiers des quatre capteurs. Un capteur muet ou en panne n'empêche pas les autres ;
    si aucun ne répond, l'erreur remonte."""
    textes, derniere_erreur = [], None
    for fichier in FICHIERS:
        try:
            reponse = requests.get(f"{BASE}/{fichier}", timeout=DELAI_REPONSE_S)
            reponse.raise_for_status()
            textes.append(reponse.text)
        except requests.RequestException as exc:
            derniere_erreur = exc
            logger.warning("Foyers : %s non relevé (%s).", fichier.rsplit("/", 1)[-1], type(exc).__name__)
    if not textes:
        raise derniere_erreur or ValueError("aucun fichier FIRMS")
    return textes


def _confiance(valeur):
    """« élevée », « nominale », ou None pour une détection à écarter. VIIRS donne un mot, MODIS
    un pourcentage."""
    valeur = (valeur or "").strip().lower()
    if valeur in ("h", "high"):
        return "élevée"
    if valeur in ("n", "nominal"):
        return "nominale"
    try:
        pourcentage = float(valeur)
    except ValueError:
        return None
    if pourcentage >= 80:
        return "élevée"
    return "nominale" if pourcentage >= 30 else None


def _maille(latitude, longitude, pas):
    return (round(math.floor(latitude / pas) * pas, 4), round(math.floor(longitude / pas) * pas, 4))


def analyser(textes, maintenant=None):
    """Fichiers FIRMS -> dictionnaires prêts pour FoyerActif : les détections des deux derniers
    jours dans l'emprise, de confiance au moins nominale, chacune marquée « source fixe » ou non
    d'après les sept jours du fichier."""
    maintenant = maintenant or timezone.now()
    ouest, sud, est, nord = EMPRISE
    detections = []
    for texte in textes:
        for ligne in csv.DictReader(io.StringIO(texte)):
            try:
                latitude, longitude = float(ligne["latitude"]), float(ligne["longitude"])
                instant = datetime.datetime.strptime(
                    f"{ligne['acq_date']} {ligne['acq_time'].zfill(4)}", "%Y-%m-%d %H%M",
                ).replace(tzinfo=datetime.timezone.utc)
            except (KeyError, ValueError, TypeError):
                continue
            if not (sud <= latitude <= nord and ouest <= longitude <= est):
                continue
            confiance = _confiance(ligne.get("confidence"))
            if confiance is None:
                continue
            try:
                puissance = round(float(ligne.get("frp") or ""), 1)
            except ValueError:
                puissance = None
            satellite = (ligne.get("satellite") or "").strip()[:8]
            detections.append({
                "reference": f"{satellite}-{instant:%Y%m%d-%H%M}-{latitude:.5f}-{longitude:.5f}"[:60],
                "date": instant,
                "location": Point(longitude, latitude, srid=4326),
                "satellite": satellite,
                "confiance": confiance,
                "puissance_mw": puissance,
                "de_jour": (ligne.get("daynight") or "").strip().upper() == "D",
            })

    jours_par_maille = {}
    for detection in detections:
        maille = _maille(detection["location"].y, detection["location"].x, MAILLE_FIXE)
        jours_par_maille.setdefault(maille, set()).add(detection["date"].date())
    # Un grand site industriel déborde d'une maille : on compte les jours sur la maille ET ses
    # huit voisines. Constaté le 15/11/2026 autour de Fos-sur-Mer et de Gand : maille par
    # maille, la moitié des pixels d'une même aciérie passaient pour des foyers nouveaux.
    def jours_alentour(maille):
        jours = set()
        for pas_lat in (-1, 0, 1):
            for pas_lon in (-1, 0, 1):
                voisine = (round(maille[0] + pas_lat * MAILLE_FIXE, 4), round(maille[1] + pas_lon * MAILLE_FIXE, 4))
                jours |= jours_par_maille.get(voisine, set())
        return jours

    fixes = {maille for maille in jours_par_maille if len(jours_alentour(maille)) >= JOURS_POUR_SOURCE_FIXE}

    recents, vus = [], set()
    for detection in detections:
        if detection["date"] < maintenant - PROFONDEUR or detection["reference"] in vus:
            continue
        vus.add(detection["reference"])
        detection["source_fixe"] = _maille(detection["location"].y, detection["location"].x, MAILLE_FIXE) in fixes
        recents.append(detection)
    return recents


def enregistrer(foyers, maintenant=None):
    """Remplace la copie. Une liste vide est une réponse normale (rien ne brûle) : elle vide la
    table."""
    from .models import FoyerActif

    maintenant = maintenant or timezone.now()
    lignes = [FoyerActif(releve_le=maintenant, **foyer) for foyer in foyers]
    with transaction.atomic():
        if lignes:
            FoyerActif.objects.bulk_create(
                lignes, batch_size=1000, update_conflicts=True, unique_fields=["reference"],
                update_fields=["date", "location", "satellite", "confiance", "puissance_mw",
                               "de_jour", "source_fixe", "releve_le"])
        FoyerActif.objects.exclude(reference__in=[l.reference for l in lignes]).delete()
    return len(lignes)


def relever(maintenant=None):
    return enregistrer(analyser(telecharger(), maintenant), maintenant)


# ── L'annonce aux institutions ──────────────────────────────────────────────────────────────

_DIRECTIONS = ("au nord", "au nord-est", "a l'est", "au sud-est", "au sud", "au sud-ouest", "a l'ouest", "au nord-ouest")


def _distance_et_direction(latitude1, longitude1, latitude2, longitude2):
    phi1, phi2 = math.radians(latitude1), math.radians(latitude2)
    ecart = math.radians(longitude2 - longitude1)
    a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(ecart / 2) ** 2
    distance = 2 * 6371.0 * math.asin(math.sqrt(a))
    cap = math.degrees(math.atan2(math.sin(ecart) * math.cos(phi2),
                                  math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(ecart)))
    return distance, _DIRECTIONS[round((cap % 360) / 45) % 8]


def texte_annonce(commune_nom, distance_km, direction, nombre, instant):
    """Phrase d'annonce, sans accent (elle part telle quelle sur la radio). Elle dit ce qu'on
    sait -- un satellite a vu de la chaleur -- et pas davantage."""
    from .meteo_france import FUSEAU, _sans_accent

    heure = instant.astimezone(FUSEAU).strftime("%Hh%M")
    return (f"Chaleur detectee par satellite a ~{distance_km:.0f} km {direction} de "
            f"{_sans_accent(commune_nom)} ({nombre} detection(s), {heure}). A VERIFIER : peut etre "
            f"un feu, un ecobuage ou un site industriel. Source NASA FIRMS.")


def diffuser_alertes(maintenant=None):
    """Annonce à chaque institution abonnée les foyers récents apparus dans son rayon.

    Un foyer est annoncé quand une maille de 5 km compte au moins deux détections récentes (ou
    une de confiance élevée), n'est pas une source fixe, et n'a pas déjà été annoncée à cette
    institution depuis trois jours. Renvoie la liste des annonces faites."""
    from .meteo_france import _annoncer, _prevenir_administrateurs
    from .models import Commune, ConfigurationAlerteFeu, FoyerActif, FoyerSignale

    maintenant = maintenant or timezone.now()
    annonces = []
    configurations = ConfigurationAlerteFeu.objects.filter(actif=True).select_related("institution")
    for configuration in configurations:
        institution = configuration.institution
        commune = (Commune.objects.filter(code=institution.commune_code).first()
                   if institution.commune_code else None)
        if commune is None or commune.centre_latitude is None or commune.centre_longitude is None:
            continue
        latitude, longitude = commune.centre_latitude, commune.centre_longitude
        ecart_lat = configuration.rayon_km / 111.0
        ecart_lon = configuration.rayon_km / (111.0 * max(0.1, math.cos(math.radians(latitude))))
        emprise = Polygon.from_bbox((longitude - ecart_lon, latitude - ecart_lat,
                                     longitude + ecart_lon, latitude + ecart_lat))

        par_maille = {}
        for foyer in FoyerActif.objects.filter(location__within=emprise, source_fixe=False,
                                               date__gte=maintenant - FRAICHEUR_ANNONCE):
            distance, direction = _distance_et_direction(latitude, longitude, foyer.location.y, foyer.location.x)
            if distance > configuration.rayon_km:
                continue
            maille = _maille(foyer.location.y, foyer.location.x, MAILLE_ANNONCE)
            par_maille.setdefault(maille, []).append((foyer, distance, direction))

        FoyerSignale.objects.filter(institution=institution,
                                    date_signalement__lt=maintenant - SILENCE_APRES_ANNONCE).delete()
        deja = set(FoyerSignale.objects.filter(institution=institution).values_list("maille", flat=True))
        for maille, vus in sorted(par_maille.items()):
            cle = f"{maille[0]:.2f},{maille[1]:.2f}"
            assez = len(vus) >= DETECTIONS_POUR_ANNONCER or any(f.confiance == "élevée" for f, _d, _c in vus)
            if cle in deja or not assez:
                continue
            _foyer, distance, direction = min(vus, key=lambda v: v[1])
            texte = texte_annonce(commune.nom or institution.nom, distance, direction, len(vus),
                                  max(f.date for f, _d, _c in vus))
            _annoncer(institution, texte)
            FoyerSignale.objects.create(institution=institution, maille=cle,
                                        environment=configuration.environment)
            annonces.append(f"{institution.nom} : {texte}")
            logger.info("Foyer annoncé à %s : %s", institution.nom, texte)

    if annonces:
        _prevenir_administrateurs(annonces)
    return annonces
