"""Feux en cours suivis par le satellite géostationnaire MTG : puissance toutes les dix minutes.

SOURCE
Produit « FRP-PIXEL » (LSA-509) du LSA SAF d'EUMETSAT, calculé par l'IPMA sur les images de
l'imageur FCI de MTG : une liste des pixels en feu du disque entier toutes les dix minutes, avec
leur puissance rayonnée (FRP, MW), son incertitude et une confiance. Service de données
https://datalsasaf.lsasvcs.ipma.pt, compte gratuit (secret « lsasaf_identifiants », sous la
forme « identifiant:mot de passe »). Licence CC BY 4.0 : « EUMETSAT LSA SAF [FRP-PIXEL, LSA-509] ».

CE QUE C'EST : UN SUIVI, PAS UNE DÉTECTION PRÉCOCE
Mesuré sur le feu de Saumos (Gironde, 22/07/2026, départ à 10 h 06 TU) : le satellite ne l'a vu
qu'à 10 h 48 (8 MW), le fichier a paru à 10 h 56, la détection s'est confirmée à 11 h 07. Les
pixels font 3 à 4 km sur la France : un départ de feu n'est vu qu'une fois assez puissant, bien
après les premiers appels. En revanche, une fois vu, le feu est suivi toutes les dix minutes, de
jour comme de nuit : 0,1 GW à 11 h, 1,4 GW à 13 h 10, 3,3 GW à 14 h 20 ce jour-là.

CE QUE CE N'EST PAS
- Pas une alerte : rien n'est annoncé, l'écran dit « détection satellite, à confirmer ».
- Pas tous les feux : sous les nuages, un feu n'est pas vu. Le 24/07/2026, la puissance mesurée a
  chuté de moitié quand le nuage d'orage s'est formé au-dessus du feu, puis est tombée à zéro :
  le feu brûlait toujours. D'où le contexte joint à chaque feu (orage radar au-dessus, foudre).
- Pas seulement des feux de forêt : torchères, hauts-fourneaux et sites industriels brûlent jour
  et nuit. Un feu est marqué « source fixe » s'il coïncide avec une source fixe repérée par NASA
  FIRMS (core/foyers_actifs.py) ou s'il revient cinq jours sur sept sans jamais dépasser
  150 MW. Les sources fixes sont gardées mais pas montrées par défaut.

Chaque feu est rapproché du potentiel d'orage de feu de son endroit (core/orages_de_feu.py) :
la puissance qui alimente le panache vaut à peu près 5 à 10 fois la puissance rayonnée (ordre de
grandeur, NOS ESTIMATIONS), à comparer au seuil calculé.
"""
import csv
import datetime
import gzip
import io
import logging
import math
import os
import re
from pathlib import Path

import requests
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

SERVEUR = "https://datalsasaf.lsasvcs.ipma.pt"
DOSSIER = "/PRODUCTS/MTG/MTFRPPixel/NATIVE/{jour:%Y/%m/%d}/"
_FICHIER = re.compile(r'href="(/PRODUCTS/MTG/MTFRPPixel/NATIVE/\d{4}/\d{2}/\d{2}/'
                      r'LSA-509_MTG_MTFRPPIXEL-ListProduct_MTG-FD_(\d{12})\.csv\.gz)"')
DELAI_REPONSE_S = 60
FRAICHEUR_MAX = datetime.timedelta(minutes=40)
ATTRIBUTION = "EUMETSAT LSA SAF [FRP-PIXEL, LSA-509]"

# Métropole et Corse, avec les communes frontalières (ouest, sud, est, nord).
EMPRISE = (-5.5, 41.0, 10.0, 51.5)
# Fichiers lus au plus par relevé (deux heures de retard rattrapées), et profondeur au premier relevé.
FICHIERS_PAR_RELEVE = 12
RATTRAPAGE_INITIAL = datetime.timedelta(hours=1)
# Détections gardées : une semaine, pour reconnaître les sources fixes.
GARDER = datetime.timedelta(days=7)
# Feux montrés : vus dans les 48 dernières heures ; leur courbe de puissance : 24 heures.
FENETRE_FEUX = datetime.timedelta(hours=48)
FENETRE_COURBE = datetime.timedelta(hours=24)
# Un feu non revu depuis 20 minutes (deux images) est dit « plus vu » : éteint, ou masqué.
ACTIF_SI_VU_DEPUIS = datetime.timedelta(minutes=20)
# Maille de regroupement (≈ 5 km) : deux mailles voisines appartiennent au même feu.
MAILLE = 0.05
# Sources fixes.
RAYON_SOURCE_FIXE_KM = 3.0
JOURS_SOURCE_FIXE = 5
PUISSANCE_MAX_SOURCE_FIXE_MW = 150.0
# Contexte.
RAYON_ORAGE_KM = 15.0
RAYON_ECLAIRS_KM = 15.0
FENETRE_ECLAIRS = datetime.timedelta(minutes=30)
FACTEUR_PANACHE = (5, 10)


class IdentifiantsAbsents(Exception):
    """Le secret du LSA SAF n'est pas monté sur cette machine."""


def _chemin_identifiants():
    return Path(os.environ.get("LSASAF_IDENTIFIANTS_FILE", "/run/secrets/lsasaf_identifiants"))


def lire_identifiants():
    """(identifiant, mot de passe) du service de données du LSA SAF. Jamais journalisés."""
    try:
        texte = _chemin_identifiants().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        raise IdentifiantsAbsents()
    identifiant, _, mot_de_passe = texte.partition(":")
    if not identifiant or not mot_de_passe:
        raise IdentifiantsAbsents()
    return identifiant.strip(), mot_de_passe


def _creneau(texte):
    return datetime.datetime.strptime(texte, "%Y%m%d%H%M").replace(tzinfo=datetime.timezone.utc)


def lister(page):
    """[(créneau, chemin)] des listes de feux d'une page de dossier du serveur."""
    return sorted({(_creneau(m.group(2)), m.group(1)) for m in _FICHIER.finditer(page)})


def fichiers_disponibles(session, maintenant):
    """Les fichiers d'aujourd'hui, et d'hier dans la première heure du jour (TU)."""
    jour = maintenant.astimezone(datetime.timezone.utc)
    jours = [jour - datetime.timedelta(days=1), jour] if jour.hour < 1 else [jour]
    trouves = []
    for j in jours:
        r = session.get(SERVEUR + DOSSIER.format(jour=j), timeout=DELAI_REPONSE_S)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        trouves += lister(r.text)
    return trouves


def lire(octets):
    """Pixels en feu d'une liste (CSV compressé) tombés dans l'emprise :
    [{instant, latitude, longitude, puissance_mw, incertitude_mw, confiance}]."""
    if octets[:2] != b"\x1f\x8b":
        # Le serveur rend une page HTML « Invalid Credentials » au lieu du fichier.
        raise ValueError("le service du LSA SAF n'a pas rendu de fichier (identifiants refusés ?)")
    ouest, sud, est, nord = EMPRISE
    pixels = []
    for ligne in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(octets)), encoding="ascii")):
        try:
            latitude, longitude = float(ligne["LATITUDE"]), float(ligne["LONGITUDE"])
            if not (ouest <= longitude <= est and sud <= latitude <= nord):
                continue
            pixels.append({
                "instant": datetime.datetime.strptime(ligne["ACQTIME"], "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc),
                "latitude": latitude, "longitude": longitude,
                "puissance_mw": float(ligne["FRP"]),
                "incertitude_mw": float(ligne.get("FRP_UNCERTAINTY") or 0),
                "confiance": float(ligne.get("FIRE_CONFIDENCE") or 0),
            })
        except (KeyError, ValueError):
            continue
    return pixels


# ── Regroupement en feux ──

def _maille(latitude, longitude):
    return (round(latitude / MAILLE), round(longitude / MAILLE))


def _km(lat1, lon1, lat2, lon2):
    return math.hypot((lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)), (lat2 - lat1) * 111.32)


def regrouper(detections):
    """Groupes de détections dont les mailles se touchent (huit voisines) : [[détection…]].
    `detections` : objets ou dictionnaires portant latitude, longitude."""
    par_maille = {}
    for d in detections:
        par_maille.setdefault(_maille(d["latitude"], d["longitude"]), []).append(d)
    parent = {m: m for m in par_maille}

    def racine(m):
        while parent[m] != m:
            parent[m] = parent[parent[m]]
            m = parent[m]
        return m

    for (i, j) in par_maille:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                voisine = (i + di, j + dj)
                if voisine in parent:
                    parent[racine(voisine)] = racine((i, j))
    groupes = {}
    for m, liste in par_maille.items():
        groupes.setdefault(racine(m), []).extend(liste)
    return list(groupes.values())


def decrire(groupe, maintenant):
    """Un feu à partir de ses détections : position, puissance, courbe."""
    groupe = sorted(groupe, key=lambda d: d["instant"])
    premier, dernier = groupe[0], groupe[-1]
    par_creneau = {}
    for d in groupe:
        cle = d["creneau"]
        somme, nombre, plat, plon = par_creneau.get(cle, (0.0, 0, 0.0, 0.0))
        poids = max(d["puissance_mw"], 0.1)
        par_creneau[cle] = (somme + d["puissance_mw"], nombre + 1, plat + d["latitude"] * poids, plon + d["longitude"] * poids)
    creneaux = sorted(par_creneau)
    dernier_creneau = creneaux[-1]
    somme, nombre, plat, plon = par_creneau[dernier_creneau]
    poids_total = sum(max(d["puissance_mw"], 0.1) for d in groupe if d["creneau"] == dernier_creneau)
    maximum = max(creneaux, key=lambda c: par_creneau[c][0])
    lat0, lon0 = _maille(premier["latitude"], premier["longitude"])
    return {
        "identifiant": f"{premier['creneau']:%Y%m%d%H%M}-{lat0 * MAILLE:.2f}_{lon0 * MAILLE:.2f}",
        "premier_vu": premier["instant"], "dernier_vu": dernier["instant"],
        "latitude": plat / poids_total, "longitude": plon / poids_total,
        "puissance_mw": round(somme, 1), "pixels": nombre,
        "puissance_max_mw": round(par_creneau[maximum][0], 1), "instant_max": maximum,
        "confirme": len(creneaux) >= 2,
        "courbe": [[c.isoformat(), round(par_creneau[c][0], 1), par_creneau[c][1]]
                   for c in creneaux if c >= maintenant - FENETRE_COURBE],
        "mailles": sorted({_maille(d["latitude"], d["longitude"]) for d in groupe}),
    }


def est_source_fixe(feu, foyers_fixes, historique_mailles):
    """Vrai pour une usine ou une torchère plutôt qu'un incendie (voir l'en-tête).
    `foyers_fixes` : [(lat, lon)] des sources fixes de FIRMS ; `historique_mailles` : {maille:
    (jours distincts, puissance maximale)} sur sept jours."""
    for lat, lon in foyers_fixes:
        if _km(feu["latitude"], feu["longitude"], lat, lon) <= RAYON_SOURCE_FIXE_KM:
            return True
    jours, maximum = set(), 0.0
    for m in feu["mailles"]:
        j, p = historique_mailles.get(m, (set(), 0.0))
        jours |= j
        maximum = max(maximum, p)
    return len(jours) >= JOURS_SOURCE_FIXE and maximum < PUISSANCE_MAX_SOURCE_FIXE_MW


def contexte(feu, cellules, eclairs, potentiel, maintenant):
    """Ce qui entoure un feu : orage radar au-dessus, foudre, potentiel d'orage de feu.
    `cellules` : CelluleOrage ; `eclairs` : [(lat, lon)] des trente dernières minutes ;
    `potentiel` : (échéance, valeurs au point) ou None."""
    from django.contrib.gis.geos import Point

    point = Point(feu["longitude"], feu["latitude"], srid=4326)
    orage = None
    for c in cellules:
        distance = c.contour.distance(point) * 111.32 * math.cos(math.radians(feu["latitude"]))
        if distance <= RAYON_ORAGE_KM and (orage is None or distance < orage["distance_km"]):
            orage = {"identifiant": c.identifiant, "distance_km": round(distance, 1),
                     "au_dessus": distance == 0, "intensite_max_mmh": round(c.max_mmh),
                     "eclairs": c.eclairs, "rafale_descendante": bool(c.doppler_divergence),
                     "rotation": bool(c.doppler_rotation), "grele": bool(c.doppler_grele)}
    proches = sum(1 for lat, lon in eclairs if _km(feu["latitude"], feu["longitude"], lat, lon) <= RAYON_ECLAIRS_KM)
    # Une puissance qui s'effondre sous un orage : le nuage cache sans doute le feu.
    courbe = [(datetime.datetime.fromisoformat(c), p) for c, p, _n in feu["courbe"]]
    heure_avant = [p for c, p in courbe[:-1] if c >= maintenant - datetime.timedelta(minutes=70)]
    recent_max = max(heure_avant, default=0.0)
    masque = bool(orage) and (feu["statut"] == "plus vu" or (recent_max > 0 and feu["puissance_mw"] < 0.5 * recent_max))
    au_point = None
    if potentiel:
        echeance, valeurs = potentiel
        if valeurs:
            bas, haut = (feu["puissance_mw"] / 1000 * f for f in FACTEUR_PANACHE)
            au_point = {**valeurs, "echeance": echeance.isoformat(),
                        "puissance_estimee_gw": [round(bas), round(haut)],
                        "atteint_le_seuil": bool(valeurs["pft_gw"] is not None and haut >= valeurs["pft_gw"])}
    return {"orage": orage, "eclairs_30_min": proches, "masque_par_nuage": masque, "potentiel": au_point}


# ── Relevé ──

def relever(maintenant=None):
    """Lit les listes de feux parues depuis le dernier relevé, puis recalcule les feux suivis.
    Rend le nombre de feux suivis (sources fixes comprises)."""
    from django.contrib.gis.geos import Point
    from .models import DetectionFeuMTG, ProduitFeuMTG

    maintenant = maintenant or timezone.now()
    session = requests.Session()
    session.auth = lire_identifiants()
    session.headers["User-Agent"] = "assista-crise-veille"
    dernier = ProduitFeuMTG.objects.order_by("-creneau").first()
    depuis = dernier.creneau if dernier else maintenant - RATTRAPAGE_INITIAL
    deja = set(ProduitFeuMTG.objects.filter(creneau__gte=depuis - datetime.timedelta(hours=1))
               .values_list("creneau", flat=True))
    nouveaux = [(c, chemin) for c, chemin in fichiers_disponibles(session, maintenant)
                if c >= depuis and c not in deja][:FICHIERS_PAR_RELEVE]
    for creneau, chemin in nouveaux:
        r = session.get(SERVEUR + chemin, timeout=DELAI_REPONSE_S)
        r.raise_for_status()
        pixels = lire(r.content)
        with transaction.atomic():
            ProduitFeuMTG.objects.create(creneau=creneau, detections=len(pixels), releve_le=timezone.now())
            DetectionFeuMTG.objects.bulk_create([DetectionFeuMTG(
                creneau=creneau, instant=p["instant"], location=Point(p["longitude"], p["latitude"], srid=4326),
                puissance_mw=p["puissance_mw"], incertitude_mw=p["incertitude_mw"], confiance=p["confiance"],
            ) for p in pixels])
    limite = maintenant - GARDER
    DetectionFeuMTG.objects.filter(creneau__lt=limite).delete()
    ProduitFeuMTG.objects.filter(creneau__lt=limite).delete()
    return suivre(maintenant)


def suivre(maintenant=None):
    """Recalcule les feux suivis à partir des détections gardées. Rend leur nombre."""
    from django.contrib.gis.geos import Point
    from .models import CelluleOrage, DetectionFeuMTG, FeuSuivi, FoyerActif, ImpactFoudre, ProduitFeuMTG

    maintenant = maintenant or timezone.now()
    dernier = ProduitFeuMTG.objects.order_by("-creneau").first()
    reference = dernier.creneau if dernier else maintenant
    detections = [{"creneau": d.creneau, "instant": d.instant, "latitude": d.location.y, "longitude": d.location.x,
                   "puissance_mw": d.puissance_mw}
                  for d in DetectionFeuMTG.objects.filter(creneau__gte=maintenant - FENETRE_FEUX)]
    historique = {}
    for creneau, location, puissance in DetectionFeuMTG.objects.values_list("creneau", "location", "puissance_mw"):
        jours, maximum = historique.get(_maille(location.y, location.x), (set(), 0.0))
        jours.add(creneau.date())
        historique[_maille(location.y, location.x)] = (jours, max(maximum, puissance))
    foyers_fixes = [(f.location.y, f.location.x) for f in FoyerActif.objects.filter(source_fixe=True)]
    cellules = list(CelluleOrage.objects.all())
    eclairs = [(e.location.y, e.location.x) for e in ImpactFoudre.objects.filter(instant__gte=maintenant - FENETRE_ECLAIRS)]
    potentiel = _potentiel_le_plus_proche(maintenant)

    feux = []
    for groupe in regrouper(detections):
        feu = decrire(groupe, maintenant)
        feu["statut"] = "actif" if feu["dernier_vu"] >= reference - ACTIF_SI_VU_DEPUIS else "plus vu"
        feu["source_fixe"] = est_source_fixe(feu, foyers_fixes, historique)
        feu["contexte"] = ({} if feu["source_fixe"] else
                           contexte(feu, cellules, eclairs,
                                    potentiel and (potentiel.echeance, _valeur(potentiel, feu)), maintenant))
        feux.append(feu)
    with transaction.atomic():
        FeuSuivi.objects.all().delete()
        FeuSuivi.objects.bulk_create([FeuSuivi(
            identifiant=f["identifiant"], premier_vu=f["premier_vu"], dernier_vu=f["dernier_vu"],
            centre=Point(f["longitude"], f["latitude"], srid=4326), statut=f["statut"],
            puissance_mw=f["puissance_mw"], puissance_max_mw=f["puissance_max_mw"], instant_max=f["instant_max"],
            pixels=f["pixels"], confirme=f["confirme"], source_fixe=f["source_fixe"],
            courbe=f["courbe"], contexte=f["contexte"], calcule_le=maintenant,
        ) for f in feux])
    return len(feux)


def _potentiel_le_plus_proche(maintenant):
    from .models import PotentielOrageFeu

    proches = [p for p in PotentielOrageFeu.objects.all() if abs(p.echeance - maintenant) <= datetime.timedelta(hours=3)]
    return min(proches, key=lambda p: abs(p.echeance - maintenant), default=None)


def _valeur(potentiel, feu):
    from . import orages_de_feu

    return orages_de_feu.valeur_au_point(potentiel, feu["latitude"], feu["longitude"])
