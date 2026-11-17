"""Les cartes en annexe du plan communal de sauvegarde.

Deux planches, dessinées par le serveur à partir de ce que la commune a déjà dans l'application :

1. **Quartiers et lieux du plan** : le découpage en quartiers, les lieux d'accueil et les points
   des dispositifs, les sites sensibles retenus ;
2. **Zones inondables et enjeux** : la zone inondée simulée (au niveau médian et au plus haut
   niveau), les zones inondables officielles quand elles ont été relevées, et les mêmes enjeux,
   marqués quand l'eau les atteint.

**Par défaut ce sont des schémas, sans fond de plan.** Ni rues ni bâtiments : seulement nos
propres couches, à l'échelle, avec une barre d'échelle et le nord en haut. Cela n'attend aucun
service extérieur au moment d'imprimer, et se photocopie bien. **Sur demande** (case à cocher à
l'édition), les planches sont posées sur le Plan IGN : une image par planche, demandée à la
Géoplateforme pour la seule emprise de la carte (`fond_ign`). Si l'IGN ne répond pas, le plan
s'édite quand même, en schéma.
Pour une carte détaillée, les couches s'exportent vers un logiciel de cartographie
(core/couches_carto.py).

Les repères sont numérotés et la légende les nomme : on ne tasse pas de noms sur le dessin.
Le registre des personnes vulnérables n'y figure jamais.
"""
import json
import math

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable

SOMBRE = colors.HexColor("#1e293b")
GRIS = colors.HexColor("#6b7280")
CADRE = colors.HexColor("#cbd5e1")
QUARTIER = colors.HexColor("#475569")
EAU_HAUTE = colors.HexColor("#bfdbfe")
EAU_MEDIANE = colors.HexColor("#60a5fa")
OFFICIEL = colors.HexColor("#b91c1c")
LIEU = colors.HexColor("#15803d")
SITE = colors.HexColor("#c2410c")
ATTEINT = colors.HexColor("#1d4ed8")

_METRES_PAR_DEGRE = 111_320.0
_PAS_ECHELLE = (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)


def _anneaux(geometrie: dict) -> list:
    """Les contours extérieurs et intérieurs d'une surface GeoJSON, à plat."""
    if not geometrie:
        return []
    if geometrie["type"] == "Polygon":
        return list(geometrie["coordinates"])
    if geometrie["type"] == "MultiPolygon":
        return [anneau for polygone in geometrie["coordinates"] for anneau in polygone]
    return []


class Planche(Flowable):
    """Une carte schématique : des surfaces, des repères numérotés, une échelle.

    `surfaces` : `[(geometrie GeoJSON, couleur de fond ou None, couleur de trait ou None, épaisseur, tirets)]`,
    dessinées dans l'ordre. `reperes` : `[(longitude, latitude, numéro, couleur, forme)]`, forme
    « rond » ou « carre » — la forme distingue les natures, la couleur seule ne suffit pas à
    l'impression en noir et blanc."""

    def __init__(self, surfaces, reperes, largeur=180 * mm, hauteur=150 * mm, fond=None):
        super().__init__()
        self.surfaces, self.reperes = surfaces, reperes
        self.width, self.height = largeur, hauteur
        #: `fond(lon_min, lat_min, lon_max, lat_max, largeur_px, hauteur_px)` -> image (octets)
        #: couvrant exactement cette emprise, ou None. Voir `fond_ign`.
        self.fond = fond
        self.fond_pose = False

    def _emprise(self):
        xs, ys = [], []
        for geometrie, *_reste in self.surfaces:
            for anneau in _anneaux(geometrie):
                xs += [p[0] for p in anneau]
                ys += [p[1] for p in anneau]
        xs += [r[0] for r in self.reperes]
        ys += [r[1] for r in self.reperes]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def draw(self):
        c = self.canv
        c.setStrokeColor(CADRE)
        c.setLineWidth(0.6)
        c.rect(0, 0, self.width, self.height)
        emprise = self._emprise()
        if emprise is None:
            c.setFillColor(GRIS)
            c.setFont("Helvetica-Oblique", 9)
            c.drawCentredString(self.width / 2, self.height / 2, "Rien à dessiner pour l'instant.")
            return
        lon_min, lat_min, lon_max, lat_max = emprise
        # À plat, à la latitude du milieu : juste à l'échelle d'une commune.
        metres_x = _METRES_PAR_DEGRE * math.cos(math.radians((lat_min + lat_max) / 2))
        large = max((lon_max - lon_min) * metres_x, 200.0)
        haut = max((lat_max - lat_min) * _METRES_PAR_DEGRE, 200.0)
        marge = 7 * mm
        echelle = min((self.width - 2 * marge) / large, (self.height - 2 * marge - 6 * mm) / haut)   # points par mètre
        decalage_x = (self.width - large * echelle) / 2
        decalage_y = 6 * mm + (self.height - 6 * mm - haut * echelle) / 2

        def placer(lon, lat):
            return (decalage_x + (lon - lon_min) * metres_x * echelle,
                    decalage_y + (lat - lat_min) * _METRES_PAR_DEGRE * echelle)

        if self.fond is not None:
            # L'emprise de tout le cadre, pas seulement des couches : l'image le remplit.
            ouest = lon_min - decalage_x / (metres_x * echelle)
            est = ouest + self.width / (metres_x * echelle)
            sud = lat_min - (decalage_y - 6 * mm) / (_METRES_PAR_DEGRE * echelle)
            nord = sud + (self.height - 6 * mm) / (_METRES_PAR_DEGRE * echelle)
            largeur_px = 1400
            hauteur_px = max(1, round(largeur_px * (self.height - 6 * mm) / self.width))
            try:
                image = self.fond(ouest, sud, est, nord, largeur_px, hauteur_px)
                if image:
                    import io

                    from reportlab.lib.utils import ImageReader
                    c.drawImage(ImageReader(io.BytesIO(image)), 0, 6 * mm, width=self.width, height=self.height - 6 * mm)
                    self.fond_pose = True
            except Exception:
                pass   # pas de fond : la planche reste un schéma, on n'empêche pas d'éditer le plan

        for geometrie, fond, trait, epaisseur, tirets in self.surfaces:
            chemin = c.beginPath()
            for anneau in _anneaux(geometrie):
                if len(anneau) < 3:
                    continue
                x, y = placer(*anneau[0][:2])
                chemin.moveTo(x, y)
                for point in anneau[1:]:
                    x, y = placer(*point[:2])
                    chemin.lineTo(x, y)
                chemin.close()
            c.saveState()
            if fond is not None:
                # Sur un fond de plan, les aplats deviennent translucides pour laisser lire les rues.
                c.setFillColor(fond, alpha=0.45 if self.fond_pose else 1)
            if trait is not None:
                c.setStrokeColor(trait)
                c.setLineWidth(epaisseur)
                c.setDash(tirets or [])
            # Règle pair-impair : les trous d'une surface restent des trous.
            c.drawPath(chemin, stroke=1 if trait is not None else 0, fill=1 if fond is not None else 0, fillMode=0)
            c.restoreState()

        for lon, lat, numero, couleur, forme in self.reperes:
            x, y = placer(lon, lat)
            c.setFillColor(couleur)
            c.setStrokeColor(colors.white)
            c.setLineWidth(0.8)
            if forme == "carre":
                c.rect(x - 3.6, y - 3.6, 7.2, 7.2, stroke=1, fill=1)
            else:
                c.circle(x, y, 4.2, stroke=1, fill=1)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 5.5 if numero < 100 else 4.5)
            c.drawCentredString(x, y - 1.9, str(numero))

        # Barre d'échelle : la plus grande longueur ronde qui tient dans un quart de la largeur.
        pas = max((p for p in _PAS_ECHELLE if p * echelle <= self.width / 4), default=_PAS_ECHELLE[0])
        x0, y0 = 5 * mm, 3 * mm
        c.setStrokeColor(SOMBRE)
        c.setLineWidth(1)
        c.line(x0, y0, x0 + pas * echelle, y0)
        c.line(x0, y0 - 1.5, x0, y0 + 1.5)
        c.line(x0 + pas * echelle, y0 - 1.5, x0 + pas * echelle, y0 + 1.5)
        c.setFillColor(SOMBRE)
        c.setFont("Helvetica", 7)
        c.drawString(x0 + pas * echelle + 3, y0 - 2.3, f"{pas} m" if pas < 1000 else f"{pas // 1000} km")
        c.drawRightString(self.width - 5 * mm, y0 - 2.3,
                          "Nord en haut — fond de plan : IGN, Plan IGN" if self.fond_pose else "Nord en haut — schéma sans fond de plan")


IGN_WMS = "https://data.geopf.fr/wms-r"
_DERNIER_FOND = [0.0]


def fond_ign(lon_min, lat_min, lon_max, lat_max, largeur_px, hauteur_px):
    """Le Plan IGN de cette emprise, en une image (service public de la Géoplateforme, sans clé).

    Seule l'emprise de la carte part vers l'IGN — un rectangle autour de la commune —, jamais
    une adresse ni un repère. Une image par planche, et une seconde d'écart entre deux : on ne
    découpe pas en tuiles. Rend None si le service ne répond pas ; la planche reste alors le
    schéma habituel."""
    import time
    import urllib.parse
    import urllib.request

    attente = 1.0 - (time.time() - _DERNIER_FOND[0])
    if attente > 0:
        time.sleep(attente)
    _DERNIER_FOND[0] = time.time()
    parametres = urllib.parse.urlencode({
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2",
        "STYLES": "", "CRS": "EPSG:4326", "FORMAT": "image/png", "WIDTH": largeur_px, "HEIGHT": hauteur_px,
        # WMS 1.3.0 en EPSG:4326 : latitude d'abord.
        "BBOX": f"{lat_min},{lon_min},{lat_max},{lon_max}",
    })
    try:
        with urllib.request.urlopen(f"{IGN_WMS}?{parametres}", timeout=25) as reponse:
            if "image" not in (reponse.headers.get("Content-Type") or ""):
                return None
            return reponse.read()
    except Exception:
        return None


def _simplifiee(geos, tolerance=0.00008):
    """Un contour allégé pour l'impression (~8 m) : une zone inondée issue d'une grille compte
    des milliers de sommets qui alourdiraient le fichier sans se voir sur une page."""
    if geos is None or geos.empty:
        return None
    simple = geos.simplify(tolerance, preserve_topology=True)
    return json.loads((simple if not simple.empty else geos).geojson)


def planches(institution, environment, fond=None) -> dict:
    """Ce qu'il faut pour dessiner les deux planches et écrire leur légende.

    Rend `{"quartiers": [...noms], "reperes": [{numero, nom, nature, seuil_m, zone_officielle}],
    "planche_plan": Planche | None, "planche_eau": Planche | None, "niveaux": (médian, haut) | None,
    "zonage_officiel": libellé | ""}`."""
    from . import enjeux_exposes, zonages_officiels
    from .couches_carto import ZONE_AUTOMATIQUE
    from .habitations import COUCHES_DEBORDEMENT_GEORISQUES
    from .models import Plan, StatutSiteSensible, SuiviSiteSensible, Zone

    commune_code = institution.commune_code or ""
    zones = list(Zone.objects.filter(institution=institution, environment=environment, actif=True)
                 .exclude(zone_precise__isnull=True).exclude(nom=ZONE_AUTOMATIQUE).order_by("nom"))
    territoire = (Zone.objects.filter(institution=institution, environment=environment, nom=ZONE_AUTOMATIQUE)
                  .exclude(zone_precise__isnull=True).first())
    paliers = enjeux_exposes.paliers_de(commune_code, environment) if commune_code else []
    paliers = [p for p in paliers if not p.polygone.empty]
    zonages = zonages_officiels.en_base(commune_code, environment) if commune_code else {}

    lieux = {}
    for plan in Plan.objects.filter(institution=institution, environment=environment, actif=True).prefetch_related("points__type"):
        for point in plan.points.all():
            if point.location is not None:
                lieux[point.id] = point
    sites = [s.site for s in SuiviSiteSensible.objects
             .filter(institution=institution, environment=environment, statut=StatutSiteSensible.RETENU)
             .select_related("site") if s.site.location is not None]

    reperes = []
    for nature, forme, couleur, objets in (
            ("Lieu d'accueil ou point", "carre", LIEU, sorted(lieux.values(), key=lambda p: p.nom.casefold())),
            ("Site sensible", "rond", SITE, sorted(sites, key=lambda s: s.nom.casefold()))):
        for objet in objets:
            reperes.append({
                "numero": len(reperes) + 1, "nom": objet.nom, "nature": nature, "forme": forme, "couleur": couleur,
                "lon": objet.location.x, "lat": objet.location.y,
                "seuil_m": enjeux_exposes.seuil_d_un_point(objet.location, paliers),
                "zone_officielle": zonages_officiels.zone_d_un_point(objet.location, zonages),
            })

    contours = [(_simplifiee(z.zone_precise, 0.00003), None, QUARTIER, 0.9, None) for z in zones]
    if territoire is not None:
        contours.insert(0, (_simplifiee(territoire.zone_precise, 0.00005), None, SOMBRE, 1.2, None))
    contours = [surface for surface in contours if surface[0]]

    planche_plan = None
    if contours or reperes:
        planche_plan = Planche(contours, [(r["lon"], r["lat"], r["numero"], r["couleur"], r["forme"]) for r in reperes], fond=fond)

    planche_eau, niveaux, zonage_officiel = None, None, ""
    surfaces_eau = []
    if paliers:
        haut, median = paliers[-1], paliers[len(paliers) // 2]
        niveaux = (median.niveau_metres, haut.niveau_metres)
        surfaces_eau.append((_simplifiee(haut.polygone), EAU_HAUTE, None, 0, None))
        if median.pk != haut.pk:
            surfaces_eau.append((_simplifiee(median.polygone), EAU_MEDIANE, None, 0, None))
    # Le scénario officiel de référence : le débordement moyen, à défaut le premier relevé.
    for couche in ("ALEA_SYNT_01_02MOY_FXX", *COUCHES_DEBORDEMENT_GEORISQUES):
        zonage = zonages.get(couche)
        if zonage is not None and zonage.polygone is not None and not zonage.polygone.empty:
            surfaces_eau.append((_simplifiee(zonage.polygone), None, OFFICIEL, 1.1, [3, 2]))
            zonage_officiel = COUCHES_DEBORDEMENT_GEORISQUES[couche]
            break
    surfaces_eau = [surface for surface in surfaces_eau if surface[0]]
    if surfaces_eau:
        planche_eau = Planche(
            surfaces_eau + contours,
            [(r["lon"], r["lat"], r["numero"],
              ATTEINT if (r["seuil_m"] is not None or r["zone_officielle"]) else r["couleur"], r["forme"]) for r in reperes],
            fond=fond)

    return {"quartiers": [z.nom for z in zones], "reperes": reperes, "planche_plan": planche_plan,
            "planche_eau": planche_eau, "niveaux": niveaux, "zonage_officiel": zonage_officiel}
