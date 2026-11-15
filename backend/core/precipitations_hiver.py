"""Neige, verglas et grêle prévus dans les heures qui viennent : le « type de précipitation » de
la prévision immédiate de Météo-France, peint par ce serveur et copié en base pour la carte.

SOURCE
Modèle AROME-PI, même clé, même service de valeurs (WCS) et même calcul horaire que les rafales
(core/rafales.py), Licence Ouverte 2.0. Le champ est le type de précipitation le plus sévère des
quinze minutes qui précèdent chaque échéance : un code par point de grille.

POURQUOI LES VALEURS ET NON L'IMAGE
Le service d'images dessine ce champ, mais dans des teintes dont la légende n'est pas
accessible : une carte dont on ne peut pas dire ce que veulent dire les couleurs ne sert à rien.

LES CODES
1 à 12 : la table 4.201 de la norme GRIB2 de l'Organisation météorologique mondiale (1 pluie,
3 pluie verglaçante, 5 neige, 6 neige humide, 7 pluie et neige mêlées, 8 granules de glace,
9 grésil, 10 grêle, 11 bruine, 12 bruine verglaçante). Au-delà de 192 les codes sont propres à
Météo-France et nous n'en avons pas trouvé la table. Constat du 15/11/2026 sur une grille
réelle : 201 couvre le pays comme la pluie (1), 205, 206 et 207 se trouvent en montagne au
contact de la neige (5, 6, 7) -- « 200 + n » est donc lu comme une variante du type n (averses).
C'est une DÉDUCTION, écrite ici pour être corrigée le jour où la table sera connue. Les codes
qui ne se rattachent à rien (193, 213…) ne sont pas peints.

La pluie et la bruine ordinaires ne sont pas peintes : la pluie a son propre calque, et celui-ci
ne doit montrer que ce qui change la conduite à tenir.

CE QUE C'EST, ET CE QUE CE N'EST PAS
Une PRÉVISION à trois heures du type de ce qui tombe, pas de la quantité, et pas de la tenue au
sol : « neige » ne dit pas qu'elle tiendra sur la route. Pas une alerte : la vigilance
« neige-verglas » reste celle de Météo-France. Métropole seulement.

Même poids que les rafales : 13 Mo par échéance, treize échéances par heure. Seule l'image
peinte est gardée.
"""
from django.utils import timezone

from . import pluie, rafales

COUVERTURE = "SEVERE_PRECIPITATION_TYPE_15_MIN__GROUND_OR_WATER_SURFACE"

# (clé, libellé, teinte, codes de la table 4.201). L'ordre est celui de la légende ; les
# variantes « 200 + n » sont ajoutées plus bas.
FAMILLES = (
    ("VERGLAS", "Pluie ou bruine verglaçante", (219, 39, 119), (3, 12)),
    ("NEIGE", "Neige", (56, 189, 248), (5,)),
    ("NEIGE_HUMIDE", "Neige humide, pluie et neige mêlées", (79, 70, 229), (6, 7)),
    ("GRESIL", "Grésil, granules de glace", (245, 158, 11), (8, 9)),
    ("GRELE", "Grêle", (127, 29, 29), (10,)),
)
TEINTES = tuple(famille[2] for famille in FAMILLES)
OPACITES = (255,) * len(FAMILLES)
DECALAGE_VARIANTE = 200
# Du plus dangereux au moins dangereux : sert à dire le pire de ce qui est prévu à un endroit.
ORDRE_DE_GRAVITE = ("VERGLAS", "GRELE", "NEIGE", "NEIGE_HUMIDE", "GRESIL")


def _table_des_rangs():
    """Table code -> rang de palette (0 : non peint), pour tous les codes de 0 à 255."""
    import numpy

    table = numpy.zeros(256, dtype=numpy.uint8)
    for rang, (_cle, _libelle, _teinte, codes) in enumerate(FAMILLES, start=1):
        for code in codes:
            table[code] = rang
            if code + DECALAGE_VARIANTE < 256:
                table[code + DECALAGE_VARIANTE] = rang
    return table


def peindre(grille):
    """Image PNG, en projection Mercator, d'une grille de codes de type de précipitation."""
    import numpy

    lisible = numpy.isfinite(grille) & (grille >= 0) & (grille <= 255)
    codes = numpy.where(lisible, grille, 0).round().astype(numpy.uint8)
    return rafales.peindre_rangs(_table_des_rangs()[codes], TEINTES, OPACITES)


def preparer(octets):
    return peindre(rafales.lire_tiff(octets))


def famille_au_point(png, latitude, longitude):
    """Clé de la famille peinte à un endroit (« NEIGE »…), "" si rien n'y est peint, None hors
    de l'image."""
    rang = rafales.rang_au_point(png, latitude, longitude)
    if rang is None:
        return None
    return FAMILLES[rang - 1][0] if rang else ""


def legende():
    return [{"cle": cle, "libelle": libelle, "couleur": "#%02x%02x%02x" % teinte}
            for cle, libelle, teinte, _codes in FAMILLES]


def telecharger_grille(calcul, echeance):
    return rafales.telecharger_couverture(COUVERTURE, calcul, echeance)


def relever(maintenant=None):
    """Complète la copie des images de types de précipitation (voir `pluie.completer_serie`)."""
    from .models import ImagePrecipitationHiver

    return pluie.completer_serie(ImagePrecipitationHiver, telecharger_grille, preparer,
                                 maintenant or timezone.now(), "Neige et verglas")
