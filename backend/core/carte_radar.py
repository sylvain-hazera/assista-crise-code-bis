"""La pluie observée par le radar, en image pour la carte (20/11/2026) — SELON LES RELEVÉS.

La dernière lame d'eau analysée par core/orages.py (grille à 1 km, intensité la plus forte des
quatre points de 500 m, en mm/h) est reprojetée de la stéréographique polaire de Météo-France vers
le Web Mercator de la carte, puis peinte par paliers. MapLibre pose une image en étirant ses
quatre coins dans SA projection : sans reprojection, l'écart atteindrait plusieurs kilomètres sur
les bords du pays.

Rien n'est stocké : l'image se recalcule à la demande depuis la grille gardée en base (moins d'une
seconde) et les deux dernières restent en mémoire du processus.
"""
import io
import zlib

#: Paliers d'intensité (mm/h, à partir de) et leur teinte. Les quatre derniers reprennent les
#: paliers des cellules orageuses (core/orages.PALIERS_MMH, à partir de 30 mm/h).
PALIERS = (
    (0.5, "#bfdbfe"), (2, "#60a5fa"), (5, "#2563eb"), (10, "#16a34a"), (20, "#facc15"),
    (30, "#f97316"), (50, "#dc2626"), (100, "#a21caf"),
)
OPACITE = 210
_CACHE = {}


def legende():
    return [{"a_partir_de_mmh": seuil, "couleur": couleur} for seuil, couleur in PALIERS]


def _rgb(couleur):
    return tuple(int(couleur[i:i + 2], 16) for i in (1, 3, 5))


def rendre(image):
    """(png, coins) pour une ImageRadarOrage. `coins` : haut-gauche, haut-droite, bas-droite,
    bas-gauche, en (lon, lat) — l'ordre qu'attend une source d'image MapLibre."""
    cle = image.heure
    if cle in _CACHE:
        return _CACHE[cle]

    import numpy
    from django.contrib.gis.gdal import CoordTransform, GDALRaster, SpatialReference
    from django.contrib.gis.geos import Point
    from PIL import Image

    from .orages import NODATA, PAS_M

    octets = numpy.frombuffer(zlib.decompress(bytes(image.grille)), dtype=numpy.uint8).reshape(image.hauteur, image.largeur)
    source = GDALRaster({
        "driver": "MEM", "srid": 4326, "width": image.largeur, "height": image.hauteur, "datatype": 1,
        "origin": [image.x0, image.y0], "scale": [PAS_M, -PAS_M],
        "bands": [{"data": numpy.ascontiguousarray(octets), "nodata_value": NODATA}],
    })
    source.srs = SpatialReference(image.projdef)
    # transform() calcule l'emprise et la maille de destination (warp() garderait celles de la source).
    mercator = source.transform(3857, driver="MEM", resampling="NearestNeighbour")
    valeurs = mercator.bands[0].data()

    # Index de palette : 0 transparent (rien, ou le radar ne voit pas), puis un par palier.
    index = numpy.digitize(valeurs.astype("float32"), [seuil for seuil, _ in PALIERS]).astype(numpy.uint8)
    index[valeurs == NODATA] = 0
    peinte = Image.fromarray(index, mode="P")
    palette = [0, 0, 0] + [composante for _, couleur in PALIERS for composante in _rgb(couleur)]
    peinte.putpalette(palette + [0] * (768 - len(palette)))
    tampon = io.BytesIO()
    peinte.save(tampon, format="PNG", optimize=True,
                transparency=bytes([0] + [OPACITE] * len(PALIERS)))

    ox, oy = mercator.origin
    sx, sy = mercator.scale
    largeur, hauteur = mercator.width, mercator.height
    vers_geo = CoordTransform(SpatialReference(3857), SpatialReference(4326))
    coins = []
    for x, y in ((ox, oy), (ox + sx * largeur, oy), (ox + sx * largeur, oy + sy * hauteur), (ox, oy + sy * hauteur)):
        point = Point(x, y, srid=3857)
        point.transform(vers_geo)
        coins.append([round(point.x, 5), round(point.y, 5)])

    resultat = (tampon.getvalue(), coins)
    for ancienne in sorted(_CACHE)[:-1]:
        del _CACHE[ancienne]
    _CACHE[cle] = resultat
    return resultat
