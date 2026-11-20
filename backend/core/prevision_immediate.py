"""Prévision immédiate de la pluie par pysteps (19/11/2026) — NOS ESTIMATIONS, qui ne sont pas
des prévisions officielles.

À partir des deux ou trois dernières images radar (core/orages.py, grilles à 1 km en mm/h) :

1. un champ de déplacement par flux optique (Lucas-Kanade, la méthode de référence de pysteps) :
   chaque point a sa propre vitesse, là où l'ancienne estimation donnait une seule vitesse par
   cellule. Comparé le 19/11/2026 sur deux vraies images : ~70 km/h vers l'est, en accord avec la
   corrélation de phase ;
2. l'extrapolation semi-lagrangienne de la pluie sur l'heure qui vient, par pas de cinq minutes ;
3. pour chaque commune : dans combien de temps la pluie intense arriverait, la pluie la plus
   forte attendue, et le cumul attendu dans l'heure.

Ce que ce n'est pas : l'extrapolation déplace la pluie sans la faire naître ni mourir. Un orage
qui se forme dans l'heure n'y figure pas ; un orage qui s'effondre y reste. C'est pourquoi ces
chiffres sont présentés comme des estimations, à côté de la prévision Météo-France (AROME-PI).

pysteps et OpenCV ne sont installés que dans l'image du service `orages` (Dockerfile.meteo) :
ailleurs, ce module se tait (`disponible()` rend False).
"""
import datetime
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

#: Pas des images radar et horizon des estimations.
PAS_MIN = 5
PAS_HORIZON = 12              # 12 × 5 min = une heure
SEUIL_INTENSE_MMH = 30


def disponible():
    try:
        import cv2  # noqa: F401
        import pysteps  # noqa: F401
    except ImportError:
        return False
    return True


def champ_de_deplacement(grilles):
    """Champ de déplacement (2, lignes, colonnes) en points de grille par pas de cinq minutes, à
    partir des grilles successives (mm/h, NaN là où le radar ne voit pas), de la plus ancienne à la
    plus récente. None si pysteps manque ou s'il n'y a pas deux images."""
    if len(grilles) < 2 or not disponible():
        return None
    import numpy
    from pysteps import motion
    pile = numpy.stack([numpy.nan_to_num(g, nan=0.0) for g in grilles[-3:]]).astype("float64")
    return motion.get_method("lucaskanade")(pile)


def extrapoler(grille, champ, pas=PAS_HORIZON):
    """Pile (pas, lignes, colonnes) des intensités extrapolées (mm/h), de +5 min à +5×pas min."""
    import numpy
    from pysteps import nowcasts
    depart = numpy.nan_to_num(grille, nan=0.0).astype("float64")
    prevue = nowcasts.get_method("extrapolation")(depart, champ, pas)
    return numpy.nan_to_num(prevue, nan=0.0)


def vitesse_sous(champ, lignes, colonnes, minutes_par_pas=PAS_MIN):
    """Vitesse moyenne du champ sous une cellule, en (lignes, colonnes) par MINUTE — la convention
    de core/orages. pysteps range la composante est-ouest en premier (colonnes)."""
    import numpy
    u = float(numpy.nanmean(champ[0][lignes, colonnes]))
    v = float(numpy.nanmean(champ[1][lignes, colonnes]))
    if not (numpy.isfinite(u) and numpy.isfinite(v)):
        return None
    return v / minutes_par_pas, u / minutes_par_pas


def par_commune(prevue, index):
    """{code INSEE: (dans_min ou None, max_mmh, cumul_mm)} pour les communes où il pleuvrait.
    `index` : core.orages.IndexCommunes, déjà placé dans la grille."""
    import numpy
    nombre, hauteur, largeur = prevue.shape
    dedans = (index.lignes >= 0) & (index.lignes < hauteur) & (index.colonnes >= 0) & (index.colonnes < largeur)
    resultat = {}
    indices = numpy.nonzero(dedans)[0]
    series = prevue[:, index.lignes[indices], index.colonnes[indices]]          # (pas, communes)
    cumuls = series.sum(axis=0) * PAS_MIN / 60
    maxima = series.max(axis=0)
    intense = series >= SEUIL_INTENSE_MMH
    premiers = numpy.where(intense.any(axis=0), intense.argmax(axis=0), -1)
    for k, i in enumerate(indices):
        if cumuls[k] < 0.5 and premiers[k] < 0:
            continue
        dans = int((premiers[k] + 1) * PAS_MIN) if premiers[k] >= 0 else None
        resultat[index.codes[i]] = (dans, round(float(maxima[k]), 1), round(float(cumuls[k]), 1))
    return resultat


def enregistrer_images(grille, prevue, maintenant=None, zone="METROPOLE"):
    """Garde les images extrapolées de l'heure qui vient (+5 à +60 min), pour la boucle de la
    carte — remplacées à chaque image. Même grille compacte que les images observées."""
    import zlib

    import numpy
    from django.db import transaction
    from .models import ImageRadarEstimee
    maintenant = maintenant or timezone.now()
    hauteur, largeur = grille.forme
    with transaction.atomic():
        ImageRadarEstimee.objects.filter(zone=zone).delete()
        ImageRadarEstimee.objects.bulk_create([ImageRadarEstimee(
            zone=zone, minutes=(i + 1) * PAS_MIN, heure_base=grille.heure, largeur=largeur, hauteur=hauteur,
            projdef=grille.projdef, x0=grille.x0, y0=grille.y0,
            grille=zlib.compress(numpy.clip(numpy.nan_to_num(image), 0, 254).astype(numpy.uint8).tobytes(), 6),
            releve_le=maintenant) for i, image in enumerate(prevue)])
    return len(prevue)


def enregistrer(heure, valeurs, maintenant=None, codes=None):
    """Remplace les estimations par commune (une ligne par commune où il pleuvrait). `codes` :
    les communes couvertes par la mosaïque qui les a calculées ; les autres gardent les leurs."""
    from django.db import transaction
    from .models import PrevisionPluieCommune
    maintenant = maintenant or timezone.now()
    with transaction.atomic():
        anciennes = PrevisionPluieCommune.objects.all()
        (anciennes.filter(commune_code__in=list(codes)) if codes is not None else anciennes).delete()
        PrevisionPluieCommune.objects.bulk_create([PrevisionPluieCommune(
            commune_code=code, heure_image=heure, dans_min_intense=dans, max_mmh=maximum, cumul_mm=cumul,
            releve_le=maintenant) for code, (dans, maximum, cumul) in valeurs.items()], batch_size=2000)
    return len(valeurs)
