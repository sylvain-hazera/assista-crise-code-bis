"""Suivi des cellules orageuses par tobac (20/11/2026) — SELON LES RELEVÉS : ce module décrit
ce que les images radar de la dernière heure ont montré, il ne prévoit rien.

tobac (« Tracking and Object-Based Analysis of Clouds », bibliothèque de référence du suivi
d'objets atmosphériques) est appliqué aux images de lame d'eau à 1 km déjà gardées par
core/orages.py, sur la dernière heure :

1. détection des NOYAUX à plusieurs seuils (30, 50 et 100 mm/h) : une grande zone de pluie forte
   qui contient deux cœurs intenses donne deux noyaux, là où l'étiquetage à un seul seuil de
   core/orages ne voit qu'une cellule ;
2. segmentation (ligne de partage des eaux) : la surface de pluie forte rattachée à chaque noyau ;
3. suivi d'une image à l'autre (trackpy, prédiction par la vitesse) ;
4. fusions et divisions (méthode MEST de tobac) : deux cellules qui se rejoignent — ce qui précède
   souvent un renforcement — ou une cellule qui se scinde.

Ce qui en sort, pour chaque cellule de core/orages : depuis combien de temps elle est suivie, son
nombre de noyaux, l'évolution de sa surface et de son intensité sur les dix dernières minutes, et
s'il y a eu fusion ou division dans l'heure.

tobac n'est installé que dans l'image du service `orages` (Dockerfile.meteo) : ailleurs,
`disponible()` rend False et l'analyse se fait sans ce suivi.

Vérifié le 20/11/2026 sur trois vraies images consécutives (05:55-06:05 UTC) : 18 noyaux,
7 cellules suivies, une fusion et une division repérées, 1,2 s de calcul.
"""
import logging

logger = logging.getLogger(__name__)

#: Seuils de détection des noyaux (mm/h), et surface minimale à chaque seuil (points de 1 km²).
SEUILS_MMH = (30, 50, 100)
POINTS_MIN = (4, 4, 2)
PAS_S = 300
PAS_M = 1000
#: Une heure d'images, l'image courante comprise.
IMAGES_MAX = 13
#: 150 km/h, comme core/orages.VITESSE_MAX_KMH.
VITESSE_MAX_MS = 150 / 3.6
#: Distance sous laquelle deux cellules qui se rejoignent sont dites fusionnées.
DISTANCE_FUSION_M = 15000
#: Marge autour de la pluie forte, pour ne pas calculer sur toute la France quand il ne pleut
#: qu'en Bretagne (13 images entières pèseraient plus de 150 Mo).
MARGE = 30
#: Évolution comparée à l'image d'il y a dix minutes.
ECART_EVOLUTION_MIN = 10
RENFORCEMENT_MMH = 10
RENFORCEMENT_SURFACE = 0.3


def disponible():
    import warnings
    try:
        with warnings.catch_warnings():
            # « Numba not able to be imported » : sans effet ici (pas de bords périodiques).
            warnings.simplefilter("ignore")
            import tobac  # noqa: F401
    except ImportError:
        return False
    return True


def suivre(grilles, heures):
    """Noyaux de la DERNIÈRE image, avec leur histoire sur les précédentes.

    `grilles` : intensités (mm/h, NaN là où le radar ne voit pas), de la plus ancienne à la plus
    récente, à cinq minutes d'intervalle ; `heures` : leurs heures. Rend
    [{ligne, colonne, seuil, age_min, nouveau, surface_km2, max_mmh, surface_10min_km2,
    max_10min_mmh, fusion, division}] — `age_min` None pour un noyau apparu sur la dernière image.
    """
    import warnings

    import numpy
    import pandas
    import xarray

    grilles, heures = list(grilles)[-IMAGES_MAX:], list(heures)[-IMAGES_MAX:]
    pile = numpy.nan_to_num(numpy.stack(grilles).astype("float32"), nan=0.0)
    fortes = numpy.nonzero((pile >= SEUILS_MMH[0]).any(axis=0))
    if not len(fortes[0]):
        return []
    hauteur, largeur = pile.shape[1:]
    l0, l1 = max(0, fortes[0].min() - MARGE), min(hauteur, fortes[0].max() + MARGE + 1)
    c0, c1 = max(0, fortes[1].min() - MARGE), min(largeur, fortes[1].max() + MARGE + 1)
    pile = pile[:, l0:l1, c0:c1]
    donnees = xarray.DataArray(pile, dims=("time", "y", "x"), name="taux", coords={
        "time": pandas.to_datetime([h.replace(tzinfo=None) for h in heures]),
        "y": numpy.arange(pile.shape[1]), "x": numpy.arange(pile.shape[2])})

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import tobac
        import trackpy
        trackpy.quiet()
        noyaux = tobac.feature_detection_multithreshold(
            donnees, dxy=PAS_M, threshold=list(SEUILS_MMH), target="maximum",
            n_min_threshold=list(POINTS_MIN), position_threshold="weighted_diff", sigma_threshold=0.5,
            min_distance=5)
        if noyaux is None or noyaux.empty:
            return []
        masque, noyaux = tobac.segmentation_2D(noyaux, donnees, dxy=PAS_M, threshold=SEUILS_MMH[0], target="maximum")
        derniere = len(heures) - 1
        if derniere == 0 or noyaux["frame"].nunique() < 2:
            noyaux["cell"] = -1
            familles = None
        else:
            noyaux = tobac.linking_trackpy(
                noyaux, donnees, dt=PAS_S, dxy=PAS_M, v_max=VITESSE_MAX_MS, stubs=2, method_linking="predict",
                adaptive_stop=0.2, adaptive_step=0.95, subnetwork_size=50)
            familles = _fusions_divisions(noyaux)

    # Intensité la plus forte de la surface de chaque noyau, image par image.
    from scipy import ndimage
    valeurs_masque = masque.values
    maxima = {}
    for image, groupe in noyaux.groupby("frame"):
        ids = groupe["feature"].to_numpy()
        for ident, valeur in zip(ids, ndimage.maximum(pile[image], labels=valeurs_masque[image], index=ids)):
            maxima[int(ident)] = float(valeur)

    resultat = []
    for _, n in noyaux[noyaux["frame"] == derniere].iterrows():
        cellule = int(n["cell"]) if not pandas.isna(n["cell"]) else -1
        histoire = noyaux[noyaux["cell"] == cellule].sort_values("frame") if cellule >= 0 else n.to_frame().T
        premiere = int(histoire["frame"].iloc[0])
        surface = float(n["ncells"]) * (PAS_M / 1000) ** 2
        maximum = maxima.get(int(n["feature"]), 0.0)
        reference = histoire[histoire["frame"] <= derniere - ECART_EVOLUTION_MIN * 60 // PAS_S]
        if len(reference):
            avant = reference.iloc[-1]
            surface_10 = round(surface - float(avant["ncells"]) * (PAS_M / 1000) ** 2, 1)
            max_10 = round(maximum - maxima.get(int(avant["feature"]), 0.0), 1)
        else:
            surface_10 = max_10 = None
        fusion, division = (familles or {}).get(cellule, (False, False))
        resultat.append({
            "ligne": float(n["hdim_1"]) + l0, "colonne": float(n["hdim_2"]) + c0,
            "seuil": int(n["threshold_value"]),
            "age_min": (derniere - premiere) * PAS_S // 60 if cellule >= 0 else None,
            "surface_km2": round(surface, 1), "max_mmh": round(maximum, 1),
            "surface_10min_km2": surface_10, "max_10min_mmh": max_10,
            "fusion": bool(fusion), "division": bool(division),
        })
    return resultat


def _fusions_divisions(noyaux):
    """{cellule tobac: (fusion, division)} : une fusion quand une autre cellule de la même famille
    s'est terminée en la rejoignant, une division quand la cellule ou une sœur est née d'une
    scission — dans la fenêtre d'une heure."""
    import tobac
    suivis = noyaux[noyaux["cell"] >= 0]
    if suivis["cell"].nunique() < 2:
        return {}
    try:
        familles = tobac.merge_split.merge_split_MEST(suivis, dxy=PAS_M, distance=DISTANCE_FUSION_M)
    except Exception:
        logger.exception("Fusions et divisions non calculées.")
        return {}
    cellules = familles["cell"].values.tolist()
    parents = dict(zip(cellules, familles["cell_parent_track_id"].values.tolist()))
    fusions = dict(zip(cellules, familles["cell_ends_with_merge"].values.tolist()))
    divisions = dict(zip(cellules, familles["cell_starts_with_split"].values.tolist()))
    resultat = {}
    for cellule in cellules:
        soeurs = [k for k in cellules if parents[k] == parents[cellule]]
        resultat[int(cellule)] = (any(fusions[k] for k in soeurs if k != cellule),
                                  any(divisions[k] for k in soeurs))
    return resultat


def resumer(noyaux):
    """Ce que les noyaux d'UNE cellule de core/orages disent d'elle, ou None s'il n'y en a pas."""
    if not noyaux:
        return None
    principal = max(noyaux, key=lambda n: (n["seuil"], n["surface_km2"]))
    ages = [n["age_min"] for n in noyaux if n["age_min"] is not None]
    surface_10, max_10 = principal["surface_10min_km2"], principal["max_10min_mmh"]
    evolution = None
    if max_10 is not None:
        surface_avant = principal["surface_km2"] - surface_10
        croissance = surface_10 / surface_avant if surface_avant > 0 else 0.0
        if max_10 >= RENFORCEMENT_MMH or croissance >= RENFORCEMENT_SURFACE:
            evolution = "renforcement"
        elif max_10 <= -RENFORCEMENT_MMH or croissance <= -RENFORCEMENT_SURFACE:
            evolution = "affaiblissement"
        else:
            evolution = "stable"
    return {
        "suivie_depuis_min": max(ages) if ages else 0,
        "noyaux": len(noyaux), "noyaux_intenses": sum(1 for n in noyaux if n["seuil"] >= SEUILS_MMH[1]),
        "surface_10min_km2": surface_10, "max_10min_mmh": max_10, "evolution": evolution,
        "fusion": any(n["fusion"] for n in noyaux), "division": any(n["division"] for n in noyaux),
    }
