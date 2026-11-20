"""La pluie du radar, en images pour la carte (20/11/2026).

Deux séries, que l'écran ne mélange pas :
- SELON LES RELEVÉS : les images observées gardées par core/orages.py (une heure, ImageRadarOrage) ;
- NOS ESTIMATIONS : les images de l'heure qui vient extrapolées par pysteps
  (core/prevision_immediate, ImageRadarEstimee) — pas une prévision.

Chaque grille (1 km, dans la projection de sa mosaïque : stéréographique polaire pour la
métropole, Mercator pour La Réunion ; mm/h) est reprojetée vers le Web
Mercator de la carte, puis peinte par paliers. MapLibre pose une image en étirant ses quatre coins
dans SA projection : sans reprojection, l'écart atteindrait plusieurs kilomètres sur les bords.

La reprojection est calculée UNE fois par géométrie de grille : GDAL reprojette une grille des
numéros de points, ce qui donne pour chaque pixel de la carte le point radar qui le colore. Chaque
image n'est plus ensuite qu'un réindexage (quelques dizaines de millisecondes) : la boucle de
vingt-cinq images de la carte se calcule sans attendre. Rien n'est stocké ; les images récentes
restent en mémoire du processus.
"""
import io
import zlib

#: Paliers d'intensité (mm/h, à partir de) et leur teinte. Les trois derniers reprennent les
#: paliers des cellules orageuses (core/orages.PALIERS_MMH).
PALIERS = (
    (0.5, "#bfdbfe"), (2, "#60a5fa"), (5, "#2563eb"), (10, "#16a34a"), (20, "#facc15"),
    (30, "#f97316"), (50, "#dc2626"), (100, "#a21caf"),
)
OPACITE = 210
#: Images gardées en mémoire : une heure observée et une heure estimée, avec de la marge.
IMAGES_EN_MEMOIRE = 30
_IMAGES = {}
_GEOMETRIES = {}


def legende():
    return [{"a_partir_de_mmh": seuil, "couleur": couleur} for seuil, couleur in PALIERS]


def _rgb(couleur):
    return tuple(int(couleur[i:i + 2], 16) for i in (1, 3, 5))


def _geometrie(image):
    """(numéros des points radar par pixel de la carte, -1 hors grille ; coins en lon/lat)."""
    cle = (image.projdef, round(image.x0, 3), round(image.y0, 3), image.largeur, image.hauteur)
    if cle in _GEOMETRIES:
        return _GEOMETRIES[cle]

    import numpy
    from django.contrib.gis.gdal import CoordTransform, GDALRaster, SpatialReference
    from django.contrib.gis.geos import Point

    from .orages import PAS_M

    numeros = numpy.arange(image.largeur * image.hauteur, dtype=numpy.int32).reshape(image.hauteur, image.largeur)
    source = GDALRaster({
        "driver": "MEM", "srid": 4326, "width": image.largeur, "height": image.hauteur, "datatype": 5,
        "origin": [image.x0, image.y0], "scale": [PAS_M, -PAS_M],
        "bands": [{"data": numeros, "nodata_value": -1}],
    })
    source.srs = SpatialReference(image.projdef)
    # transform() calcule l'emprise et la maille de destination (warp() garderait celles de la source).
    mercator = source.transform(3857, driver="MEM", resampling="NearestNeighbour")
    correspondance = mercator.bands[0].data().astype(numpy.int64)

    ox, oy = mercator.origin
    sx, sy = mercator.scale
    largeur, hauteur = mercator.width, mercator.height
    vers_geo = CoordTransform(SpatialReference(3857), SpatialReference(4326))
    coins = []
    for x, y in ((ox, oy), (ox + sx * largeur, oy), (ox + sx * largeur, oy + sy * hauteur), (ox, oy + sy * hauteur)):
        point = Point(x, y, srid=3857)
        point.transform(vers_geo)
        coins.append([round(point.x, 5), round(point.y, 5)])
    if len(_GEOMETRIES) >= 6:          # une géométrie par mosaïque, avec de la marge
        _GEOMETRIES.clear()
    _GEOMETRIES[cle] = (correspondance, coins)
    return _GEOMETRIES[cle]


def rendre(image, cle=None):
    """(png, coins) d'une grille compacte (ImageRadarOrage ou ImageRadarEstimee). `coins` :
    haut-gauche, haut-droite, bas-droite, bas-gauche, en (lon, lat) — l'ordre qu'attend une source
    d'image MapLibre. `cle` désigne l'image dans la mémoire (par défaut, son heure)."""
    cle = cle if cle is not None else (image.zone, image.heure)
    if cle in _IMAGES:
        return _IMAGES[cle]

    import numpy
    from PIL import Image

    from .orages import NODATA

    correspondance, coins = _geometrie(image)
    octets = numpy.frombuffer(zlib.decompress(bytes(image.grille)), dtype=numpy.uint8).ravel()
    dedans = correspondance >= 0
    valeurs = numpy.full(correspondance.shape, NODATA, dtype=numpy.uint8)
    valeurs[dedans] = octets[correspondance[dedans]]

    # Index de palette : 0 transparent (rien, ou le radar ne voit pas), puis un par palier.
    index = numpy.digitize(valeurs.astype("float32"), [seuil for seuil, _ in PALIERS]).astype(numpy.uint8)
    index[valeurs == NODATA] = 0
    peinte = Image.fromarray(index, mode="P")
    palette = [0, 0, 0] + [composante for _, couleur in PALIERS for composante in _rgb(couleur)]
    peinte.putpalette(palette + [0] * (768 - len(palette)))
    tampon = io.BytesIO()
    peinte.save(tampon, format="PNG", transparency=bytes([0] + [OPACITE] * len(PALIERS)))

    resultat = (tampon.getvalue(), coins)
    while len(_IMAGES) >= IMAGES_EN_MEMOIRE:
        del _IMAGES[next(iter(_IMAGES))]
    _IMAGES[cle] = resultat
    return resultat
