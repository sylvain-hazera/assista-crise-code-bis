"""Orages et pluies intenses, selon les relevés radar de Météo-France (19/11/2026).

SOURCE
API « DPRadar » du portail public de Météo-France (même clé que la vigilance), mosaïque
« LAME_D_EAU » de la métropole à 500 m : la pluie tombée en cinq minutes, en millimètres, au
format HDF5 ODIM (le format européen des données radar). Une image toutes les cinq minutes,
disponible environ cinq minutes après son heure ; seule la plus récente est servie, rien n'est
archivé chez Météo-France. Grille de 3472 × 3472 points, projection stéréographique polaire
décrite dans le fichier lui-même (`where/projdef`), avec un indice de qualité par point et la
liste des radars présents ou absents.

Vérifié sur une image réelle le 19/11/2026 : les coins recalculés à partir de la projection
retombent à 0,002° près sur ceux que le fichier annonce.

Pourquoi la lame d'eau et pas la réflectivité : la réflectivité (en dBZ) n'est servie qu'en
BUFR, codé avec des descripteurs propres à Météo-France que les tables publiques ne décrivent
pas — elle ne se décode pas aujourd'hui. Le Doppler (vitesse radiale) et la double polarisation,
qui permettraient de reconnaître une rotation ou la grêle elle-même, sont dans le même cas.

CE QUE CE MODULE FAIT, ET CE QU'IL NE FAIT PAS
À chaque image :
1. délimite les cellules de pluie intense (au moins SEUIL_MMH mm/h sur au moins SURFACE_MIN_KM2) ;
2. estime leur déplacement en comparant cette image à la précédente (corrélation de phase,
   autour de chaque cellule) et les suit d'une image à l'autre ;
3. en déduit, pour chaque cellule, les communes sous la pluie MAINTENANT, et celles que la cellule
   atteindrait dans l'heure SI elle gardait sa vitesse et sa direction ;
4. y joint ce que Météo-France PRÉVOIT au même endroit (grêle et rafales, modèle AROME-PI, déjà
   copiés par la veille) et les rafales MESURÉES par les stations sous la cellule.

Les communes « atteintes » sont des ESTIMATIONS, pas des prévisions : une simple translation,
sans croissance ni dissipation de l'orage. Elles sont présentées comme telles. Aucune annonce
ne part d'ici (décision du 19/11/2026) : la veille du territoire les affiche, c'est tout.

Une commune est « sous la pluie » quand son centre l'est : une grande commune peut être touchée
sans que son centre le soit.
"""
import datetime
import io
import logging
import math
import uuid
import zlib

import requests
from django.utils import timezone

from . import meteo_france

logger = logging.getLogger(__name__)

URL_MOSAIQUES = "https://public-api.meteofrance.fr/public/DPRadar/v1/mosaiques"
URL = f"{URL_MOSAIQUES}/METROPOLE/observations/LAME_D_EAU"
#: Les mosaïques analysées (20/11/2026). Même produit, même format HDF5 ODIM à 500 m ; seules la
#: grille et la projection changent, et le fichier les décrit lui-même. La Réunion : deux radars
#: (Colorado et Piton Villers), Mercator, 2300 × 2000 points de 51° E à 62° E — vérifié sur une
#: image réelle le 20/11/2026. Ce que Météo-France PRÉVOIT sous une cellule (AROME-PI) n'existe
#: qu'en métropole, de même que le Doppler et la trace d'analyse gardée trente jours.
ZONES = {
    "METROPOLE": {"source": "ORAGES_RADAR", "libelle": "Métropole", "arome_pi": True},
    "REUNION": {"source": "ORAGES_RADAR_REUNION", "libelle": "La Réunion", "arome_pi": False},
}
ZONE_PAR_DEFAUT = "METROPOLE"


def url_zone(zone):
    return f"{URL_MOSAIQUES}/{zone}/observations/LAME_D_EAU"
DELAI_REPONSE_S = 60

#: Pluie à partir de laquelle on parle de cellule de pluie intense (mm/h). 30 mm/h est le seuil
#: usuel d'une averse forte, typique d'un orage.
SEUIL_MMH = 30
#: Paliers d'intensité annoncés.
PALIERS_MMH = (30, 50, 100)
#: Surface minimale d'une cellule : en dessous, c'est un écho isolé, souvent un artefact.
SURFACE_MIN_KM2 = 4
#: L'analyse se fait à 1 km (2 × 2 points de 500 m, valeur la plus forte) : quatre fois moins de
#: calcul, et une résolution qui reste bien plus fine que la taille d'un orage.
PAS_M = 1000
#: Horizon des estimations, en minutes, par pas de cinq.
HORIZON_MIN = 60
#: Une cellule est la « même » que celle de l'image précédente si sa position estimée tombe à
#: moins de cette distance.
DISTANCE_SUIVI_KM = 10
#: Vitesse au-delà de laquelle un déplacement estimé n'est pas plausible (km/h).
VITESSE_MAX_KMH = 150
#: Ligne de grain : longue, étroite, rapide.
LIGNE_LONGUEUR_MIN_KM = 80
LIGNE_ALLONGEMENT_MIN = 3
LIGNE_VITESSE_MIN_KMH = 40
#: Une image plus vieille que cela n'est plus présentée comme actuelle.
FRAICHEUR_MAX = datetime.timedelta(minutes=20)
#: Images gardées (pour le déplacement) et analyses gardées (pour régler les seuils).
IMAGES_GARDEES = 13     # une heure : le suivi par tobac (core/suivi_tobac.py) la parcourt ; ~60 Ko l'image
ANALYSES_GARDEES = datetime.timedelta(days=30)

NODATA = 255   # valeur de la grille compacte (mm/h, plafonné à 254) là où le radar ne voit pas


class GrilleRadar:
    """Une image radar ramenée à 1 km : intensité en mm/h (float32, NaN là où rien n'est vu),
    et de quoi passer d'un point de la grille à des coordonnées géographiques."""

    def __init__(self, taux, projdef, x0, y0, heure, radars, absents, taux_moyen=None):
        self.taux = taux
        # Moyenne des quatre points de 500 m : pour les CUMULS, où la valeur la plus forte
        # surestimerait la pluie tombée. `taux` (la plus forte) sert aux cellules.
        self.taux_moyen = taux_moyen if taux_moyen is not None else taux
        self.projdef = projdef
        self.x0, self.y0 = x0, y0          # coin haut gauche, mètres dans la projection
        self.heure = heure
        self.radars, self.absents = radars, absents

    @property
    def forme(self):
        return self.taux.shape

    def _transformation(self, vers_geo):
        from django.contrib.gis.gdal import CoordTransform, SpatialReference
        projection, geo = SpatialReference(self.projdef), SpatialReference(4326)
        return CoordTransform(projection, geo) if vers_geo else CoordTransform(geo, projection)

    def vers_geo(self, lignes, colonnes):
        """Points de grille (centres) -> [(lon, lat)]."""
        from django.contrib.gis.geos import MultiPoint, Point
        points = MultiPoint([Point(self.x0 + (c + 0.5) * PAS_M, self.y0 - (r + 0.5) * PAS_M)
                             for r, c in zip(lignes, colonnes)])
        points.transform(self._transformation(True))
        return [p.coords for p in points]

    def depuis_geo(self, lons, lats):
        """[(lon, lat)] -> (lignes, colonnes) flottantes dans la grille."""
        import numpy
        from django.contrib.gis.geos import MultiPoint, Point
        if not len(lons):
            return numpy.array([]), numpy.array([])
        points = MultiPoint([Point(lon, lat, srid=4326) for lon, lat in zip(lons, lats)])
        points.transform(self._transformation(False))
        xy = numpy.array([p.coords for p in points])
        return (self.y0 - xy[:, 1]) / PAS_M - 0.5, (xy[:, 0] - self.x0) / PAS_M - 0.5

    def compacte(self):
        """Grille en octets (mm/h plafonné à 254, NODATA ailleurs), compressée."""
        import numpy
        octets = numpy.where(numpy.isnan(self.taux), NODATA,
                             numpy.clip(numpy.nan_to_num(self.taux), 0, 254)).astype(numpy.uint8)
        return zlib.compress(octets.tobytes(), 6)

    @staticmethod
    def depuis_compacte(donnees, largeur, hauteur):
        import numpy
        octets = numpy.frombuffer(zlib.decompress(bytes(donnees)), dtype=numpy.uint8).reshape(hauteur, largeur)
        return numpy.where(octets == NODATA, numpy.nan, octets.astype(numpy.float32))


# ── Lecture ──────────────────────────────────────────────────────────────────

def heure_disponible(zone=ZONE_PAR_DEFAUT):
    """Heure (UTC) de la dernière image publiée, lue dans la fiche — sans la télécharger."""
    cle = meteo_france.lire_cle()
    r = requests.get(url_zone(zone), headers={"apikey": cle, "accept": "application/json"}, timeout=DELAI_REPONSE_S)
    r.raise_for_status()
    for lien in r.json().get("links", []):
        if lien.get("type") == "application/x-hdf" and lien.get("validity_time"):
            return datetime.datetime.fromisoformat(lien["validity_time"].replace("Z", "+00:00"))
    raise ValueError("Fiche radar sans heure de validité pour la maille de 500 m.")


def telecharger(zone=ZONE_PAR_DEFAUT):
    cle = meteo_france.lire_cle()
    r = requests.get(f"{url_zone(zone)}/produit", params={"maille": "500"},
                     headers={"apikey": cle, "accept": "*/*"}, timeout=DELAI_REPONSE_S)
    r.raise_for_status()
    return r.content


def _texte(valeur):
    """Attribut HDF5 en texte : octets ou chaîne selon la façon dont il a été écrit."""
    if isinstance(valeur, bytes):
        return valeur.decode()
    if hasattr(valeur, "tobytes") and getattr(valeur, "dtype", None) is not None and valeur.dtype.kind == "S":
        return valeur.tobytes().decode()
    return str(valeur)


def lire(octets):
    """HDF5 ODIM de la lame d'eau -> GrilleRadar à 1 km (mm/h)."""
    import h5py
    import numpy

    with h5py.File(io.BytesIO(octets), "r") as h:
        donnees = h["dataset1/data1/data"]
        what = donnees.parent["what"].attrs
        gain, offset = float(what["gain"]), float(what["offset"])
        nodata, undetect = float(what["nodata"]), float(what["undetect"])
        brut = donnees[:].astype(numpy.float32)
        where, what_racine, how = h["where"].attrs, h["what"].attrs, h["how"].attrs
        projdef = _texte(where["projdef"])
        pas = float(where["xscale"])
        if abs(pas - 500) > 1 or abs(float(where["yscale"]) - 500) > 1:
            raise ValueError(f"Maille inattendue : {pas} m.")
        coin_lon, coin_lat = float(where["UL_lon"]), float(where["UL_lat"])
        heure = datetime.datetime.strptime(
            _texte(what_racine["date"]) + _texte(what_racine["time"]), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
        def liste(cle):
            valeur = _texte(how.get(cle, b""))
            return [n.strip() for n in valeur.split(",") if n.strip()]
        radars, absents = liste("nodes"), liste("missing_nodes")

    # mm en 5 minutes -> mm/h ; « non détecté » = pas de pluie ; « pas de donnée » = NaN.
    taux = numpy.where(brut == nodata, numpy.nan,
                       numpy.where(brut == undetect, 0.0, (brut * gain + offset) * 12)).astype(numpy.float32)
    # 500 m -> 1 km : la plus forte des quatre valeurs (une pointe d'intensité ne doit pas être
    # moyennée avec ses voisines), NaN seulement si les quatre le sont.
    h2, w2 = taux.shape[0] // 2, taux.shape[1] // 2
    blocs = taux[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # « All-NaN slice » : voulu, donne NaN
        taux_1km = numpy.nanmax(blocs, axis=(1, 3))
        taux_moyen_1km = numpy.nanmean(blocs, axis=(1, 3))

    # Coin haut gauche dans la projection, à partir du coin géographique donné par le fichier.
    from django.contrib.gis.gdal import CoordTransform, SpatialReference
    from django.contrib.gis.geos import Point
    coin = Point(coin_lon, coin_lat, srid=4326)
    coin.transform(CoordTransform(SpatialReference(4326), SpatialReference(projdef)))
    return GrilleRadar(taux_1km, projdef, coin.x, coin.y, heure, radars, absents, taux_moyen_1km)


# ── Cellules ─────────────────────────────────────────────────────────────────

def cellules(grille):
    """Les cellules de pluie intense : [{etiquette, lignes, colonnes, surface_km2, max_mmh,
    moyenne_mmh, centre (ligne, colonne)}], plus la grille des étiquettes."""
    import numpy
    from scipy import ndimage

    masque = numpy.nan_to_num(grille.taux) >= SEUIL_MMH
    etiquettes, nombre = ndimage.label(masque)
    trouvees = []
    for i, tranche in enumerate(ndimage.find_objects(etiquettes), start=1):
        if tranche is None:
            continue
        local = etiquettes[tranche] == i
        surface = int(local.sum()) * (PAS_M / 1000) ** 2
        if surface < SURFACE_MIN_KM2:
            continue
        lignes, colonnes = numpy.nonzero(local)
        lignes, colonnes = lignes + tranche[0].start, colonnes + tranche[1].start
        valeurs = grille.taux[lignes, colonnes]
        trouvees.append({
            "etiquette": i, "lignes": lignes, "colonnes": colonnes, "surface_km2": surface,
            "max_mmh": float(numpy.nanmax(valeurs)), "moyenne_mmh": float(numpy.nanmean(valeurs)),
            "centre": (float(lignes.mean()), float(colonnes.mean())),
        })
    return trouvees, etiquettes


def deplacement(precedente, courante, centre, minutes, demi=48):
    """Déplacement (lignes, colonnes par minute) de ce qui est autour de `centre` entre deux
    images, par corrélation de phase sur une fenêtre de 2 × `demi` km. None si la corrélation
    n'est pas nette (pic trop faible) ou si la vitesse n'est pas plausible."""
    import numpy

    if precedente is None or minutes <= 0:
        return None
    r, c = int(round(centre[0])), int(round(centre[1]))
    h, w = courante.shape
    if r - demi < 0 or c - demi < 0 or r + demi > h or c + demi > w:
        return None
    a = numpy.nan_to_num(precedente[r - demi:r + demi, c - demi:c + demi])
    b = numpy.nan_to_num(courante[r - demi:r + demi, c - demi:c + demi])
    if a.max() < SEUIL_MMH / 2 or b.max() < SEUIL_MMH / 2:
        return None
    fenetre = numpy.outer(numpy.hanning(2 * demi), numpy.hanning(2 * demi))
    fa, fb = numpy.fft.fft2(a * fenetre), numpy.fft.fft2(b * fenetre)
    produit = fb * numpy.conj(fa)
    produit /= numpy.abs(produit) + 1e-9
    correlation = numpy.real(numpy.fft.ifft2(produit))
    pic = numpy.unravel_index(numpy.argmax(correlation), correlation.shape)
    nettete = correlation[pic] / (numpy.abs(correlation).mean() + 1e-9)
    if nettete < 8:
        return None
    dl = pic[0] if pic[0] <= demi else pic[0] - 2 * demi
    dc = pic[1] if pic[1] <= demi else pic[1] - 2 * demi
    vitesse_kmh = math.hypot(dl, dc) * PAS_M / 1000 / minutes * 60
    if vitesse_kmh > VITESSE_MAX_KMH:
        return None
    return dl / minutes, dc / minutes


def forme(cellule):
    """Longueur (km), allongement et orientation (degrés, 0 = nord, sens horaire) du grand axe."""
    import numpy

    if len(cellule["lignes"]) < 3:
        return 0.0, 1.0, None
    nord = -(cellule["lignes"] - cellule["lignes"].mean())   # vers le nord = lignes décroissantes
    est = cellule["colonnes"] - cellule["colonnes"].mean()
    covariance = numpy.cov(numpy.vstack([est, nord]))
    valeurs, vecteurs = numpy.linalg.eigh(covariance)
    grand, petit = max(valeurs[1], 1e-6), max(valeurs[0], 1e-6)
    longueur = 4 * math.sqrt(grand) * PAS_M / 1000
    vx, vy = vecteurs[:, 1]
    orientation = (math.degrees(math.atan2(vx, vy)) + 180) % 180
    return longueur, math.sqrt(grand / petit), orientation


def cap_et_vitesse(vitesse):
    """(lignes, colonnes par minute) -> (cap en degrés vers lequel ça va, 0 = nord ; km/h)."""
    dl, dc = vitesse
    kmh = math.hypot(dl, dc) * PAS_M / 1000 * 60
    cap = (math.degrees(math.atan2(dc, -dl)) + 360) % 360
    return cap, kmh


POINTS_CARDINAUX = ("le nord", "le nord-est", "l'est", "le sud-est", "le sud", "le sud-ouest", "l'ouest", "le nord-ouest")


def vers(cap):
    return POINTS_CARDINAUX[int((cap + 22.5) % 360 // 45)]


# ── Communes ─────────────────────────────────────────────────────────────────

class IndexCommunes:
    """Centres des communes, placés une fois pour toutes dans la grille radar."""

    _cache = {}

    def __init__(self, grille):
        import numpy
        from .models import Commune
        lignes = list(Commune.objects.exclude(centre_latitude__isnull=True).exclude(centre_longitude__isnull=True)
                      .values_list("code", "nom", "centre_longitude", "centre_latitude"))
        self.codes = [l[0] for l in lignes]
        self.noms = [l[1] or l[0] for l in lignes]
        # Pour placer les communes sur la carte.
        self.lons = [round(float(l[2]), 4) for l in lignes]
        self.lats = [round(float(l[3]), 4) for l in lignes]
        r, c = grille.depuis_geo([l[2] for l in lignes], [l[3] for l in lignes])
        self.lignes = numpy.round(r).astype(int) if len(r) else numpy.array([], dtype=int)
        self.colonnes = numpy.round(c).astype(int) if len(c) else numpy.array([], dtype=int)

    @classmethod
    def pour(cls, grille):
        cle = (grille.projdef, round(grille.x0), round(grille.y0), grille.forme)
        if cle not in cls._cache:
            if len(cls._cache) >= len(ZONES):      # une grille par mosaïque, pas davantage
                cls._cache = {}
            cls._cache[cle] = cls(grille)
        return cls._cache[cle]

    def codes_dans_la_grille(self, forme):
        """Codes des communes dont le centre tombe dans la grille : celles dont cette mosaïque
        répond (les cumuls et estimations des autres mosaïques n'y sont pas touchés)."""
        import numpy
        h, w = forme
        dedans = (self.lignes >= 0) & (self.lignes < h) & (self.colonnes >= 0) & (self.colonnes < w)
        return {self.codes[i] for i in numpy.nonzero(dedans)[0]}

    def dans_masque(self, masque, decalage=(0.0, 0.0), parmi=None):
        """Indices des communes dont le centre tombe dans `masque` décalé de `decalage`."""
        import numpy
        indices = numpy.arange(len(self.codes)) if parmi is None else parmi
        r = numpy.round(self.lignes[indices] - decalage[0]).astype(int)
        c = numpy.round(self.colonnes[indices] - decalage[1]).astype(int)
        h, w = masque.shape
        dedans = (r >= 0) & (r < h) & (c >= 0) & (c < w)
        touchees = numpy.zeros(len(indices), dtype=bool)
        touchees[dedans] = masque[r[dedans], c[dedans]]
        return indices[touchees]


# ── Ce que Météo-France prévoit, ce que les stations mesurent ────────────────

def prevu_par_meteo_france(points, heure):
    """Grêle et rafales prévues par AROME-PI au quart d'heure de `heure`, aux points donnés
    [(lon, lat)] : {"grele": bool, "rafale_kmh": palier ou None, "echeance": …}."""
    from . import precipitations_hiver, rafales
    from .models import ImagePrecipitationHiver, ImageRafales

    resultat = {"grele": False, "rafale_kmh": None, "echeance": None}
    for modele, cle in ((ImagePrecipitationHiver, "grele"), (ImageRafales, "rafale_kmh")):
        image = (modele.objects.filter(echeance__gte=heure).order_by("echeance").first()
                 or modele.objects.filter(echeance__lte=heure).order_by("-echeance").first())
        if image is None or abs((image.echeance - heure).total_seconds()) > 1800:
            continue
        resultat["echeance"] = image.echeance
        png = bytes(image.image)
        for lon, lat in points:
            if cle == "grele":
                if precipitations_hiver.famille_au_point(png, lat, lon) == "GRELE":
                    resultat["grele"] = True
                    break
            else:
                palier = rafales.palier_au_point(png, lat, lon)
                if palier is not None and (resultat["rafale_kmh"] is None or palier > resultat["rafale_kmh"]):
                    resultat["rafale_kmh"] = palier
    return resultat


#: Diagnostic de grêle d'AROME-PI (`DIAG_GRELE`, kg/m²). Seuils de Météo-France pour classer
#: la grêle dans ses types de précipitation : au-delà de 8, grêle ; au-delà de 12, grosse grêle.
#: Vérifié le 19/11/2026 sur un découpage réel : valeurs de 0 à 10,8 sur les Landes un soir
#: orageux. C'est un contenu diagnostiqué par le modèle, pas une quantité tombée au sol.
COUVERTURE_GRELE = "DIAG_GRELE__GROUND_OR_WATER_SURFACE"
SEUIL_GRELE_KGM2, SEUIL_GROSSE_GRELE_KGM2 = 8.0, 12.0
#: Au plus autant de découpages par image : chaque découpage est un appel à Météo-France.
DECOUPAGES_MAX = 8
MARGE_DEG = 0.1


def niveau_grele(kgm2):
    if kgm2 is None:
        return None
    if kgm2 >= SEUIL_GROSSE_GRELE_KGM2:
        return "grosse grêle possible"
    if kgm2 >= SEUIL_GRELE_KGM2:
        return "grêle possible"
    return None


def _regrouper(boites):
    """Fusionne les boîtes (ouest, sud, est, nord) qui se chevauchent : un découpage par groupe."""
    groupes = []
    for i, boite in enumerate(boites):
        for groupe in groupes:
            o, s, e, n = groupe["boite"]
            if boite[0] <= e and boite[2] >= o and boite[1] <= n and boite[3] >= s:
                groupe["boite"] = (min(o, boite[0]), min(s, boite[1]), max(e, boite[2]), max(n, boite[3]))
                groupe["membres"].append(i)
                break
        else:
            groupes.append({"boite": boite, "membres": [i]})
    return groupes


def diagnostic_grele(contours, heure):
    """Le diagnostic de grêle d'AROME-PI le plus fort sous chaque contour, au quart d'heure qui
    suit l'image : [kg/m² ou None]. Lu par petits découpages autour des cellules (quelques
    centaines de kilo-octets) plutôt que sur la France entière (13 Mo par échéance)."""
    import numpy
    from django.contrib.gis.geos import Point
    from . import rafales
    from .models import ImageRafales

    resultat = [None] * len(contours)
    derniere = ImageRafales.objects.filter(calcul__lte=heure).order_by("-calcul").first()
    if derniere is None or not contours:
        return resultat
    calcul = derniere.calcul
    echeance = heure + datetime.timedelta(minutes=(15 - heure.minute % 15) % 15 or 15)
    echeance = echeance.replace(second=0, microsecond=0)
    if echeance - calcul > datetime.timedelta(hours=6):
        return resultat
    boites = []
    for contour in contours:
        o, s, e, n = contour.extent
        boites.append((o - MARGE_DEG, s - MARGE_DEG, e + MARGE_DEG, n + MARGE_DEG))
    groupes = sorted(_regrouper(boites), key=lambda g: -len(g["membres"]))[:DECOUPAGES_MAX]
    cle = meteo_france.lire_cle()
    for groupe in groupes:
        o, s, e, n = groupe["boite"]
        identifiant = f"{COUVERTURE_GRELE}___{calcul.astimezone(datetime.timezone.utc):%Y-%m-%dT%H.%M.%SZ}"
        try:
            r = requests.get(rafales.URL_WCS, headers={"apikey": cle}, timeout=DELAI_REPONSE_S, params=[
                ("service", "WCS"), ("version", "2.0.1"), ("coverageid", identifiant),
                ("subset", f"time({echeance.astimezone(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ})"),
                ("subset", f"lat({s:.3f},{n:.3f})"), ("subset", f"long({o:.3f},{e:.3f})"),
                ("format", "image/tiff")])
            if r.status_code != 200 or r.content[:4] not in (b"II*\x00", b"MM\x00*"):
                continue
            grille, ouest, nord, pas = rafales.lire_grille_tiff(r.content)
        except Exception:
            logger.warning("Diagnostic de grêle illisible pour %s.", groupe["boite"], exc_info=True)
            continue
        grille = numpy.asarray(grille, dtype=float)
        for i in groupe["membres"]:
            contour = contours[i].prepared
            co, cs, ce, cn = contours[i].extent
            c0, c1 = max(0, int((co - ouest) / pas)), min(grille.shape[1], int((ce - ouest) / pas) + 2)
            l0, l1 = max(0, int((nord - cn) / pas)), min(grille.shape[0], int((nord - cs) / pas) + 2)
            meilleur = None
            for ligne in range(l0, l1):
                for colonne in range(c0, c1):
                    valeur = grille[ligne, colonne]
                    if not numpy.isfinite(valeur) or valeur < 0 or valeur > 500:
                        continue
                    if contour.contains(Point(ouest + colonne * pas, nord - ligne * pas, srid=4326)):
                        meilleur = valeur if meilleur is None else max(meilleur, valeur)
            resultat[i] = round(float(meilleur), 1) if meilleur is not None else None
    return resultat


def rafale_mesuree(contour, heure):
    """La plus forte rafale mesurée sous la cellule (contour élargi de ~5 km) dans les 20 minutes
    autour de l'image : {"kmh", "station", "mesure_le"} ou None."""
    from .models import ObservationMeteo

    zone = contour.buffer(0.05)
    meilleure = (ObservationMeteo.objects
                 .filter(location__within=zone, rafale_kmh__isnull=False,
                         mesure_le__gte=heure - datetime.timedelta(minutes=20),
                         mesure_le__lte=heure + datetime.timedelta(minutes=20))
                 .order_by("-rafale_kmh").first())
    if meilleure is None:
        return None
    return {"kmh": round(meilleure.rafale_kmh), "station": meilleure.nom or meilleure.station,
            "mesure_le": meilleure.mesure_le.isoformat() if meilleure.mesure_le else None}


# ── Analyse complète ─────────────────────────────────────────────────────────

def _polygone(grille, lignes, colonnes, decalages=((0.0, 0.0),)):
    """Enveloppe convexe des points (décalés), en coordonnées géographiques."""
    import numpy
    from django.contrib.gis.geos import Polygon
    from scipy.spatial import ConvexHull, QhullError

    pts = numpy.vstack([numpy.column_stack([lignes + dl, colonnes + dc]) for dl, dc in decalages])
    # Les coins de chaque maille, pour qu'une cellule d'un seul point ait une surface.
    coins = numpy.vstack([pts + [a, b] for a in (-0.5, 0.5) for b in (-0.5, 0.5)])
    try:
        enveloppe = coins[ConvexHull(coins).vertices]
    except (QhullError, ValueError):
        return None
    geo = grille.vers_geo(enveloppe[:, 0] - 0.5, enveloppe[:, 1] - 0.5)
    return Polygon(geo + [geo[0]], srid=4326)


def analyser(grille, precedente=None, minutes_ecoulees=5.0, cellules_precedentes=(), avec_diagnostic_grele=False,
             champ_mouvement=None, noyaux=None, avec_arome_pi=True):
    """Analyse une image : rend la liste des cellules, prêtes à enregistrer.

    `noyaux` : les noyaux de la dernière image suivis par tobac sur l'heure (core/suivi_tobac),
    ou None sans ce suivi."""
    import numpy
    from scipy import ndimage

    trouvees, etiquettes = cellules(grille)
    index = IndexCommunes.pour(grille)
    resultat = []
    for cellule in trouvees:
        masque_cellule = ndimage.binary_dilation(etiquettes == cellule["etiquette"], iterations=1)
        # Le flux optique de pysteps (une vitesse par point) d'abord ; à défaut, la corrélation de
        # phase autour de la cellule (19/11/2026).
        vitesse = None
        if champ_mouvement is not None:
            from .prevision_immediate import vitesse_sous
            vitesse = vitesse_sous(champ_mouvement, cellule["lignes"], cellule["colonnes"])
            if vitesse is not None and cap_et_vitesse(vitesse)[1] > VITESSE_MAX_KMH:
                vitesse = None
        if vitesse is None:
            vitesse = deplacement(precedente, grille.taux, cellule["centre"], minutes_ecoulees)

        # Suivi : la cellule précédente dont la position estimée est la plus proche.
        precedente_cellule, meilleure = None, DISTANCE_SUIVI_KM
        for ancienne in cellules_precedentes:
            v = ancienne.get("vitesse") or (0.0, 0.0)
            estimee = (ancienne["centre"][0] + v[0] * minutes_ecoulees, ancienne["centre"][1] + v[1] * minutes_ecoulees)
            distance = math.hypot(cellule["centre"][0] - estimee[0], cellule["centre"][1] - estimee[1]) * PAS_M / 1000
            if distance < meilleure:
                precedente_cellule, meilleure = ancienne, distance
        if precedente_cellule is not None:
            ancienne_v = precedente_cellule.get("vitesse")
            if vitesse is None and minutes_ecoulees > 0:
                vitesse = ((cellule["centre"][0] - precedente_cellule["centre"][0]) / minutes_ecoulees,
                           (cellule["centre"][1] - precedente_cellule["centre"][1]) / minutes_ecoulees)
                if cap_et_vitesse(vitesse)[1] > VITESSE_MAX_KMH:
                    vitesse = None
            if vitesse is not None and ancienne_v:
                # Lissage : une estimation isolée ne fait pas tourner une cellule de 90°.
                vitesse = ((vitesse[0] + ancienne_v[0]) / 2, (vitesse[1] + ancienne_v[1]) / 2)
            elif vitesse is None and ancienne_v:
                vitesse = tuple(ancienne_v)
        identifiant = precedente_cellule["identifiant"] if precedente_cellule else uuid.uuid4().hex[:8]
        trace = list(precedente_cellule.get("trace", [])) if precedente_cellule else []
        tendance = (cellule["max_mmh"] - precedente_cellule["max_mmh"]) if precedente_cellule else None

        # Communes sous la pluie, et communes atteintes dans l'heure si rien ne change.
        touchees = index.dans_masque(masque_cellule)
        estimees = {}
        if vitesse is not None:
            portee = math.hypot(*vitesse) * HORIZON_MIN + 30
            r0, c0 = cellule["centre"]
            proches = numpy.nonzero((numpy.abs(index.lignes - r0) <= portee) & (numpy.abs(index.colonnes - c0) <= portee))[0]
            deja = set(touchees.tolist())
            for minutes in range(5, HORIZON_MIN + 1, 5):
                for i in index.dans_masque(masque_cellule, (vitesse[0] * minutes, vitesse[1] * minutes), proches):
                    if i not in deja:
                        estimees[int(i)] = minutes
                        deja.add(int(i))

        contour = _polygone(grille, cellule["lignes"], cellule["colonnes"])
        if contour is None:
            continue
        couloir = None
        if vitesse is not None:
            couloir = _polygone(grille, cellule["lignes"], cellule["colonnes"],
                                [(vitesse[0] * m, vitesse[1] * m) for m in (0, HORIZON_MIN)])
        centre_geo = grille.vers_geo([cellule["centre"][0]], [cellule["centre"][1]])[0]
        cap, kmh = cap_et_vitesse(vitesse) if vitesse is not None else (None, None)
        longueur, allongement, orientation = forme(cellule)
        ligne_de_grain = bool(
            longueur >= LIGNE_LONGUEUR_MIN_KM and allongement >= LIGNE_ALLONGEMENT_MIN
            and kmh is not None and kmh >= LIGNE_VITESSE_MIN_KMH
            and orientation is not None and 45 <= abs(((cap - orientation) + 180) % 360 - 180) <= 135)
        sommets = list(contour.exterior_ring.coords)[:-1]
        echantillon = [centre_geo] + sommets[::max(1, len(sommets) // 12)]
        prevision = (prevu_par_meteo_france(echantillon, grille.heure) if avec_arome_pi
                     else {"grele": False, "rafale_kmh": None, "echeance": None})
        # [heure, lat, lon, intensité maximale] : l'intensité permet de colorer la trajectoire
        # (20/11/2026 ; les points plus anciens n'en ont pas).
        trace = (trace + [[grille.heure.isoformat(), round(centre_geo[1], 4), round(centre_geo[0], 4),
                           round(cellule["max_mmh"], 1)]])[-12:]

        suivi = None
        if noyaux:
            from .suivi_tobac import resumer
            h, w = masque_cellule.shape
            siens = [n for n in noyaux if 0 <= round(n["ligne"]) < h and 0 <= round(n["colonne"]) < w
                     and masque_cellule[int(round(n["ligne"])), int(round(n["colonne"]))]]
            suivi = resumer(siens)
            if suivi is not None:
                # Où sont les noyaux, pour la carte.
                positions = grille.vers_geo([n["ligne"] for n in siens], [n["colonne"] for n in siens])
                suivi["noyaux_positions"] = [
                    {"lon": round(lon, 4), "lat": round(lat, 4), "seuil": n["seuil"], "max_mmh": n["max_mmh"],
                     "fusion": n["fusion"], "division": n["division"]}
                    for n, (lon, lat) in zip(siens, positions)]

        resultat.append({
            "grele_diagnostic_kgm2": None, "suivi": suivi,
            "identifiant": identifiant, "centre": cellule["centre"], "vitesse": vitesse, "trace": trace,
            "max_mmh": round(cellule["max_mmh"], 1), "moyenne_mmh": round(cellule["moyenne_mmh"], 1),
            "surface_km2": round(cellule["surface_km2"], 1), "tendance_mmh": round(tendance, 1) if tendance is not None else None,
            "cap_deg": round(cap) if cap is not None else None, "vitesse_kmh": round(kmh) if kmh is not None else None,
            "longueur_km": round(longueur), "ligne_de_grain": ligne_de_grain,
            "contour": contour, "couloir": couloir, "centre_geo": centre_geo,
            "communes_touchees": [{"code": index.codes[i], "nom": index.noms[i], "lon": index.lons[i],
                                   "lat": index.lats[i]} for i in touchees],
            "communes_estimees": sorted(({"code": index.codes[i], "nom": index.noms[i], "dans_min": m,
                                          "lon": index.lons[i], "lat": index.lats[i]}
                                         for i, m in estimees.items()), key=lambda x: (x["dans_min"], x["nom"])),
            "grele_prevue": prevision["grele"], "rafale_prevue_kmh": prevision["rafale_kmh"],
            "rafale_mesuree": rafale_mesuree(contour, grille.heure),
        })
    # Éclairs vus par le satellite sous chaque cellule (contour élargi de ~3 km, la précision
    # d'un pixel de l'imageur), dans les 20 minutes qui précèdent l'image et les 10 qui suivent.
    from .foudre import eclairs_dans
    for c in resultat:
        c["eclairs"] = eclairs_dans(c["contour"].buffer(0.03), grille.heure - datetime.timedelta(minutes=20),
                                    grille.heure + datetime.timedelta(minutes=10)).count()
    if avec_diagnostic_grele and resultat:
        try:
            for c, valeur in zip(resultat, diagnostic_grele([c["contour"] for c in resultat], grille.heure)):
                c["grele_diagnostic_kgm2"] = valeur
        except meteo_france.CleAbsente:
            pass
    return resultat


def enregistrer(grille, analyse, maintenant=None, zone=ZONE_PAR_DEFAUT):
    """Remplace les cellules en cours, garde l'image (pour le prochain déplacement) et une trace
    résumée de l'analyse (pour régler les seuils)."""
    from django.contrib.gis.geos import Point
    from django.db import transaction
    from .models import AnalyseOrages, CelluleOrage, ImageRadarOrage

    maintenant = maintenant or timezone.now()
    hauteur, largeur = grille.forme
    with transaction.atomic():
        CelluleOrage.objects.filter(zone=zone).delete()
        CelluleOrage.objects.bulk_create([CelluleOrage(
            identifiant=c["identifiant"], zone=zone, heure_image=grille.heure,
            centre=Point(*c["centre_geo"], srid=4326), contour=c["contour"], couloir=c["couloir"],
            ligne=c["centre"][0], colonne=c["centre"][1],
            vitesse_lignes=c["vitesse"][0] if c["vitesse"] else None,
            vitesse_colonnes=c["vitesse"][1] if c["vitesse"] else None,
            max_mmh=c["max_mmh"], moyenne_mmh=c["moyenne_mmh"], surface_km2=c["surface_km2"],
            tendance_mmh=c["tendance_mmh"], cap_deg=c["cap_deg"], vitesse_kmh=c["vitesse_kmh"],
            longueur_km=c["longueur_km"], ligne_de_grain=c["ligne_de_grain"],
            communes_touchees=c["communes_touchees"], communes_estimees=c["communes_estimees"],
            grele_prevue=c["grele_prevue"], rafale_prevue_kmh=c["rafale_prevue_kmh"],
            rafale_mesuree=c["rafale_mesuree"], trace=c["trace"], releve_le=maintenant,
            grele_diagnostic_kgm2=c.get("grele_diagnostic_kgm2"), eclairs=c.get("eclairs"),
            suivi=c.get("suivi"),
        ) for c in analyse])
        ImageRadarOrage.objects.update_or_create(zone=zone, heure=grille.heure, defaults={
            "largeur": largeur, "hauteur": hauteur, "projdef": grille.projdef,
            "x0": grille.x0, "y0": grille.y0, "grille": grille.compacte(),
            "radars": grille.radars, "radars_absents": grille.absents, "releve_le": maintenant})
        anciennes = ImageRadarOrage.objects.filter(zone=zone).order_by("-heure").values_list("heure", flat=True)[IMAGES_GARDEES:]
        ImageRadarOrage.objects.filter(zone=zone, heure__in=list(anciennes)).delete()
        if zone != ZONE_PAR_DEFAUT:
            # La trace de trente jours sert à régler les seuils sur la métropole ; son heure est
            # sa clé, une autre mosaïque l'écraserait.
            return len(analyse)
        AnalyseOrages.objects.update_or_create(heure=grille.heure, defaults={
            "radars_absents": grille.absents,
            "cellules": [{k: c[k] for k in ("identifiant", "max_mmh", "surface_km2", "vitesse_kmh", "cap_deg",
                                            "ligne_de_grain", "grele_prevue", "rafale_prevue_kmh",
                                            "grele_diagnostic_kgm2")}
                         | {"lat": round(c["centre_geo"][1], 3), "lon": round(c["centre_geo"][0], 3),
                            "rafale_mesuree_kmh": (c["rafale_mesuree"] or {}).get("kmh"),
                            "evolution": (c.get("suivi") or {}).get("evolution"),
                            "communes": len(c["communes_touchees"])} for c in analyse],
            "releve_le": maintenant})
        AnalyseOrages.objects.filter(heure__lt=maintenant - ANALYSES_GARDEES).delete()
    return len(analyse)


def relever_reunion(maintenant=None):
    return relever(maintenant, zone="REUNION")


def relever(maintenant=None, zone=ZONE_PAR_DEFAUT):
    """Analyse la dernière image radar de la mosaïque `zone` si elle est nouvelle. Rend le nombre de cellules en cours. Lève une exception si l'image n'a pas changé depuis trop
    longtemps : la trace de la veille le dira, la supervision aussi."""
    from .models import CelluleOrage, ImageRadarOrage

    maintenant = maintenant or timezone.now()
    heure = heure_disponible(zone)
    images = ImageRadarOrage.objects.filter(zone=zone)
    derniere = images.order_by("-heure").first()
    if derniere is not None and derniere.heure >= heure:
        if maintenant - heure > FRAICHEUR_MAX:
            raise RuntimeError(f"Image radar inchangée depuis {heure:%H:%M} UTC.")
        return CelluleOrage.objects.filter(zone=zone).count()     # déjà analysée : la trace garde le bon compte
    grille = lire(telecharger(zone))
    precedente, minutes = None, 5.0
    if derniere is not None and derniere.largeur == grille.forme[1] and derniere.hauteur == grille.forme[0]:
        minutes = (grille.heure - derniere.heure).total_seconds() / 60
        if 0 < minutes <= 20:
            precedente = GrilleRadar.depuis_compacte(derniere.grille, derniere.largeur, derniere.hauteur)
    # Images consécutives (pas de cinq minutes, même grille) pour le flux optique de pysteps.
    successives = []
    if precedente is not None and abs(minutes - 5) < 1:
        successives = [precedente, grille.taux]
        avant = images.filter(heure=derniere.heure - datetime.timedelta(minutes=5)).first()
        if avant is not None and avant.largeur == derniere.largeur and avant.hauteur == derniere.hauteur:
            successives.insert(0, GrilleRadar.depuis_compacte(avant.grille, avant.largeur, avant.hauteur))
    champ = None
    if successives:
        from . import prevision_immediate
        try:
            champ = prevision_immediate.champ_de_deplacement(successives)
        except Exception:
            logger.exception("Flux optique impossible : repli sur la corrélation de phase.")
    noyaux = suivre_sur_l_heure(grille, derniere, precedente, zone)
    anciennes = [{"identifiant": c.identifiant, "centre": (c.ligne, c.colonne), "max_mmh": c.max_mmh,
                  "vitesse": (c.vitesse_lignes, c.vitesse_colonnes) if c.vitesse_lignes is not None else None,
                  "trace": c.trace} for c in CelluleOrage.objects.filter(zone=zone)] if precedente is not None else []
    arome_pi = ZONES[zone]["arome_pi"]
    analyse = analyser(grille, precedente, minutes, anciennes, avec_diagnostic_grele=arome_pi, champ_mouvement=champ,
                       noyaux=noyaux, avec_arome_pi=arome_pi)
    nombre = enregistrer(grille, analyse, maintenant, zone)
    if champ is not None:
        from . import prevision_immediate
        try:
            prevue = prevision_immediate.extrapoler(grille.taux, champ)
            prevision_immediate.enregistrer_images(grille, prevue, maintenant, zone)
            index = IndexCommunes.pour(grille)
            prevision_immediate.enregistrer(grille.heure, prevision_immediate.par_commune(prevue, index),
                                            maintenant, codes=index.codes_dans_la_grille(grille.forme))
        except Exception:
            logger.exception("Prévision immédiate par commune non calculée.")
    try:
        cumuler_pluie(grille, maintenant, zone)
    except Exception:
        # Les cumuls ne doivent pas faire échouer l'analyse des orages.
        logger.exception("Cumuls de pluie par commune non calculés.")
    return nombre


def suivre_sur_l_heure(grille, derniere, precedente, zone=ZONE_PAR_DEFAUT):
    """Noyaux de l'image courante suivis par tobac sur les images consécutives de l'heure
    écoulée (même grille, pas de cinq minutes), ou None si tobac manque ou échoue."""
    from . import suivi_tobac
    from .models import ImageRadarOrage

    if not suivi_tobac.disponible():
        return None
    grilles, heures = [grille.taux], [grille.heure]
    if precedente is not None and derniere is not None and grille.heure - derniere.heure == datetime.timedelta(minutes=5):
        images = {i.heure: i for i in ImageRadarOrage.objects.filter(
            zone=zone, heure__gte=grille.heure - datetime.timedelta(minutes=5 * (suivi_tobac.IMAGES_MAX - 1)),
            heure__lt=grille.heure)}
        heure = grille.heure - datetime.timedelta(minutes=5)
        while heure in images and images[heure].largeur == grille.forme[1] and images[heure].hauteur == grille.forme[0]:
            image = images[heure]
            grilles.insert(0, precedente if heure == derniere.heure else
                           GrilleRadar.depuis_compacte(image.grille, image.largeur, image.hauteur))
            heures.insert(0, heure)
            heure -= datetime.timedelta(minutes=5)
    try:
        return suivi_tobac.suivre(grilles, heures)
    except Exception:
        logger.exception("Suivi des cellules par tobac impossible : analyse sans ce suivi.")
        return None


# ── Cumuls de pluie par commune ──────────────────────────────────────────────

#: Fenêtres des cumuls, en nombre d'images de cinq minutes.
FENETRES_CUMUL = {"1h": 12, "3h": 36, "24h": 288}
#: Cumuls à partir desquels une commune est signalée (mm) : pluies qui débordent les réseaux
#: et font monter les petits cours d'eau. Repères, pas des seuils de vigilance.
SEUILS_CUMUL_MM = {"1h": 30, "3h": 50, "24h": 80}


def cumuler_pluie(grille, maintenant=None, zone=ZONE_PAR_DEFAUT):
    """Pluie tombée en cinq minutes au centre de chaque commune (moyenne sur 3 × 3 km), gardée
    25 heures, puis cumuls glissants 1 h / 3 h / 24 h. Seules les communes où il a plu sont
    écrites : une nuit sèche ne fait pas 35 000 lignes."""
    import numpy
    from scipy import ndimage
    from django.db import transaction
    from .models import CumulPluieCommune, PluieCommunesImage

    maintenant = maintenant or timezone.now()
    index = IndexCommunes.pour(grille)
    lissee = ndimage.uniform_filter(numpy.nan_to_num(grille.taux_moyen), size=3) / 12      # mm en 5 min
    h, w = lissee.shape
    dedans = (index.lignes >= 0) & (index.lignes < h) & (index.colonnes >= 0) & (index.colonnes < w)
    valeurs = {}
    for i in numpy.nonzero(dedans)[0]:
        mm = float(lissee[index.lignes[i], index.colonnes[i]])
        if mm >= 0.05:
            valeurs[index.codes[i]] = round(mm, 1)
    # Une ligne par heure pour toutes les mosaïques : les communes de celle-ci y remplacent les
    # leurs, celles des autres mosaïques (publiées à la même heure) restent.
    miennes = index.codes_dans_la_grille(grille.forme)
    existante = PluieCommunesImage.objects.filter(heure=grille.heure).values_list("valeurs", flat=True).first() or {}
    valeurs = {code: mm for code, mm in existante.items() if code not in miennes} | valeurs
    PluieCommunesImage.objects.update_or_create(heure=grille.heure, defaults={"valeurs": valeurs})
    PluieCommunesImage.objects.filter(heure__lt=grille.heure - datetime.timedelta(hours=25)).delete()

    images = list(PluieCommunesImage.objects.filter(
        heure__gt=grille.heure - datetime.timedelta(hours=24)).order_by("-heure").values_list("heure", "valeurs"))
    sommes = {}
    for rang, (heure, image) in enumerate(images):
        age_min = (grille.heure - heure).total_seconds() / 60
        for code, mm in image.items():
            s = sommes.setdefault(code, [0.0, 0.0, 0.0])
            s[2] += mm
            if age_min < 180:
                s[1] += mm
            if age_min < 60:
                s[0] += mm
    disponibles = {cle: sum(1 for heure, _ in images if (grille.heure - heure).total_seconds() / 60 < n * 5)
                   for cle, n in FENETRES_CUMUL.items()}
    with transaction.atomic():
        CumulPluieCommune.objects.all().delete()
        CumulPluieCommune.objects.bulk_create([CumulPluieCommune(
            commune_code=code, mm_1h=round(s[0], 1), mm_3h=round(s[1], 1), mm_24h=round(s[2], 1),
            heure=grille.heure) for code, s in sommes.items() if s[2] >= 0.5], batch_size=2000)
    _ecrire_disponibilite(disponibles, grille.heure, zone)
    return len(sommes)


def _ecrire_disponibilite(disponibles, heure, zone=ZONE_PAR_DEFAUT):
    """Combien d'images chaque fenêtre de cumul contient vraiment (un service relancé depuis
    une heure n'a pas de cumul sur 24 h) : gardé sur la dernière image."""
    from .models import ImageRadarOrage
    ImageRadarOrage.objects.filter(zone=zone, heure=heure).update(images_par_fenetre=disponibles)


def palier(mmh):
    """Libellé d'intensité d'une pluie en mm/h."""
    if mmh >= 100:
        return "pluie torrentielle"
    if mmh >= 50:
        return "pluie très intense"
    return "pluie intense"
