"""Conduits troposphériques pour la VHF, l'UHF et la LoRa 868 MHz : NOS ESTIMATIONS (28/11/2026).

Demande de Sylvain, pour la carte ouverte « pour les copains » : la propagation radio. En VHF et
au-delà, la portée dépasse l'horizon quand l'air se stratifie : sous une inversion (air chaud et
sec au-dessus d'air frais et humide), l'indice de réfraction décroît vite avec l'altitude, les
ondes se courbent vers le sol et peuvent être guidées sur des centaines de kilomètres.

MÉTHODE
- Réfractivité N = 77,6 / T · (p + 4810 · e / T), T en kelvins, p et e (pression de vapeur) en
  hPa : la formule de la recommandation UIT-R P.453.
- Calculée au sol (2 m) et à chaque niveau de pression d'ARPEGE situé à moins de 2 km au-dessus
  du sol ; on retient le gradient le plus négatif entre deux points successifs.
- Classes, d'après les seuils usuels de l'UIT-R (P.453 / P.834) :
    gradient ≥ −79 N/km            normal ou presque : rien n'est peint ;
    −157 < gradient < −79 N/km     super-réfraction : portée accrue ;
    gradient ≤ −157 N/km           conduit : propagation guidée, très loin.

LIMITES, à afficher avec la couche
- Le profil est celui d'ARPEGE, maille d'environ 10 km, quelques niveaux sous 2 km : une couche
  d'inversion mince près du sol (les conduits de surface, fréquents la nuit et sur la mer) est
  mal résolue. La réalité peut donc être plus favorable que la carte.
- Les heures sont celles déjà calculées pour le potentiel d'orage de feu (après-midi) : aucun
  appel de plus à Météo-France.

Seul le serveur appelle Météo-France ; ce module ne fait que calculer sur les grilles lues par
core/orages_de_feu.py.
"""
import io
import zlib

GRAVITE = 9.80665
HAUTEUR_MAX_M = 2000.0
#: Écart minimal entre deux points d'un même profil : en deçà, le gradient n'a plus de sens.
ECART_MIN_M = 20.0
SUPER_REFRACTION = -79.0
CONDUIT = -157.0
CLASSES = ((1, "super-réfraction", "portée accrue au-delà de l'horizon"),
           (2, "conduit", "propagation guidée, parfois à plusieurs centaines de kilomètres"))
TEINTES = ((125, 211, 252), (37, 99, 235))
OPACITES = (120, 170)
GRADIENT_ABSENT = 32767


def _es(tc):
    """Pression de vapeur saturante (hPa), formule de Magnus (comme core/orages_de_feu.py)."""
    import numpy

    return 6.112 * numpy.exp(17.67 * tc / (tc + 243.5))


def refractivite(tc, hr, p_hpa):
    """N (unités N) pour une température (°C), une humidité relative (%) et une pression (hPa)."""
    import numpy

    tk = numpy.asarray(tc, dtype=float) + 273.15
    e = numpy.clip(hr, 0, 100) / 100.0 * _es(numpy.asarray(tc, dtype=float))
    return 77.6 / tk * (p_hpa + 4810.0 * e / tk)


def calculer(sol, niveaux):
    """{"gradient": N/km le plus négatif sous 2 km (nan si inconnu), "rang": classe 0 à 2}.

    `sol` : grilles ps (Pa), zsol (m), t2 (°C), hr2 (%) ; `niveaux` : {hPa: {t, hr, geo}}, comme
    les lit core/orages_de_feu.telecharger_echeance."""
    import numpy

    ps = numpy.asarray(sol["ps"], dtype=float) / 100.0
    zsol = numpy.asarray(sol["zsol"], dtype=float)
    n_prec = refractivite(sol["t2"], sol["hr2"], ps)
    z_prec = zsol + 2.0
    minimum = numpy.full(ps.shape, numpy.inf)
    for niveau in sorted(niveaux, reverse=True):           # du plus bas au plus haut
        champs = niveaux[niveau]
        z = numpy.asarray(champs["geo"], dtype=float) / GRAVITE
        au_dessus = z - zsol
        valide = (niveau < ps - 1) & (au_dessus <= HAUTEUR_MAX_M) & (z - z_prec >= ECART_MIN_M)
        n = refractivite(champs["t"], champs["hr"], float(niveau))
        with numpy.errstate(invalid="ignore", divide="ignore"):
            gradient = (n - n_prec) / (z - z_prec) * 1000.0
        minimum = numpy.where(valide, numpy.minimum(minimum, gradient), minimum)
        n_prec = numpy.where(valide, n, n_prec)
        z_prec = numpy.where(valide, z, z_prec)
    gradient = numpy.where(numpy.isfinite(minimum), minimum, numpy.nan)
    return {"gradient": gradient, "rang": classer(gradient)}


def classer(gradient):
    import numpy

    g = numpy.nan_to_num(numpy.asarray(gradient, dtype=float), nan=0.0)
    rang = numpy.zeros(g.shape, numpy.uint8)
    rang[g < SUPER_REFRACTION] = 1
    rang[g <= CONDUIT] = 2
    return rang


def coder(grilles):
    import numpy

    g = grilles["gradient"]
    entiers = numpy.where(numpy.isfinite(g), numpy.clip(numpy.round(g), -32000, 32000), GRADIENT_ABSENT)
    return zlib.compress(entiers.astype("<i2").tobytes() + grilles["rang"].astype(numpy.uint8).tobytes())


def decoder(octets, largeur, hauteur):
    import numpy

    brut = zlib.decompress(bytes(octets))
    n = largeur * hauteur
    g = numpy.frombuffer(brut[:2 * n], dtype="<i2").reshape(hauteur, largeur).astype(float)
    g[g == GRADIENT_ABSENT] = numpy.nan
    rang = numpy.frombuffer(brut[2 * n:3 * n], dtype=numpy.uint8).reshape(hauteur, largeur)
    return {"gradient": g, "rang": rang}


def peindre(rang, agrandir=4):
    """PNG en projection Mercator (0 transparent, 1 super-réfraction, 2 conduit), sur la même
    emprise que le potentiel d'orage de feu."""
    import numpy
    from PIL import Image

    from . import orages_de_feu, pluie

    grand = numpy.kron(rang, numpy.ones((agrandir, agrandir), numpy.uint8))
    hauteur, largeur = grand.shape
    ouest, sud, est, nord = orages_de_feu.EMPRISE_IMAGE
    grand = grand[pluie.lignes_mercator(hauteur, largeur, sud, nord, ouest, est)]
    image = Image.fromarray(grand)
    image.putpalette([0, 0, 0] + [c for teinte in TEINTES for c in teinte])
    sortie = io.BytesIO()
    image.save(sortie, format="PNG", optimize=True, transparency=bytes((0,) + OPACITES))
    return sortie.getvalue()


def legende():
    return [{"classe": classe, "libelle": libelle, "effet": effet, "couleur": "#%02x%02x%02x" % TEINTES[classe - 1]}
            for classe, libelle, effet in CLASSES]


def enregistrer(echeance, calcul, sol, niveaux, ouest, nord):
    """Calcule et range l'échéance (appelé par core/orages_de_feu.relever, sur les grilles déjà
    lues). Une erreur ici ne doit pas faire perdre le potentiel d'orage de feu : l'appelant
    l'attrape."""
    from django.utils import timezone

    from .models import PropagationTropo

    grilles = calculer(sol, niveaux)
    hauteur, largeur = grilles["rang"].shape
    PropagationTropo.objects.update_or_create(echeance=echeance, defaults={
        "calcul": calcul, "largeur": largeur, "hauteur": hauteur, "ouest": ouest, "nord": nord,
        "grilles": coder(grilles), "image": peindre(grilles["rang"]), "releve_le": timezone.now(),
    })
