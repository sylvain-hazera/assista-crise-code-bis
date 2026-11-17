"""Les zones inondables officielles de l'État, à côté de nos simulations.

Nos paliers d'inondation sont des hypothèses : un niveau d'eau étendu sur le relief. L'État
publie de son côté, sur Géorisques, les zones inondables cartographiées des territoires à risque
important d'inondation (débordement fréquent, moyen, rare ; ruissellement ; submersion marine).
Quand une commune en a, c'est la référence, et le plan doit la montrer.

**On ne presse pas Géorisques.** C'est un service public partagé, qui se protège des clients trop
rapides. Donc :

- les zones sont relevées **une fois**, à la demande d'un agent, et **gardées en base**
  (`ZonageOfficiel`) : ni la carte, ni le document, ni l'export ne le réinterrogent ;
- les requêtes d'un relevé sont **espacées** (`PAUSE_S` secondes entre deux), et l'espacement
  vaut pour tout le serveur, pas seulement pour un relevé (dernier appel gardé en cache) ;
- un relevé de moins de `FRAICHEUR_JOURS` jours n'est pas refait : ces zones ne changent qu'à
  chaque nouveau rapportage, tous les six ans ;
- une erreur de leur côté n'efface pas ce qu'on avait déjà.

En dehors des territoires à risque important, Géorisques ne rend rien : ce n'est pas « pas de
risque », c'est « pas de cartographie nationale ici ». L'écran le dit.
"""
import datetime
import time

from django.contrib.gis.geos import MultiPolygon
from django.core.cache import cache
from django.utils import timezone

from .habitations import COUCHES_DEBORDEMENT_GEORISQUES, COUCHES_GEORISQUES
from .models import ZonageOfficiel

#: Secondes entre deux requêtes à Géorisques, tous relevés confondus.
PAUSE_S = 5
#: En deçà, on ne refait pas le relevé d'une commune.
FRAICHEUR_JOURS = 30
_CLE_DERNIER_APPEL = "georisques:dernier-appel"
#: Du plus fréquent au plus rare : un lieu en zone « fréquente » est aussi en zone « rare » ;
#: on retient le scénario le plus fréquent qui l'atteint.
ORDRE_DEBORDEMENT = tuple(COUCHES_DEBORDEMENT_GEORISQUES)


def _attendre_son_tour():
    """Laisse passer `PAUSE_S` secondes depuis le dernier appel, d'où qu'il vienne."""
    dernier = cache.get(_CLE_DERNIER_APPEL)
    if dernier is not None:
        attente = PAUSE_S - (time.time() - dernier)
        if attente > 0:
            time.sleep(attente)
    cache.set(_CLE_DERNIER_APPEL, time.time(), 3600)


def en_base(commune_code: str, environment) -> dict:
    """`{couche: ZonageOfficiel}` de ce qui a été relevé pour la commune."""
    return {z.couche: z for z in ZonageOfficiel.objects.filter(commune_code=commune_code, environment=environment)}


def etat(commune_code: str, environment) -> dict:
    """Ce qu'on sait des zonages de la commune, pour l'écran : relevé ou non, quand, et quels
    scénarios ont une zone ici."""
    zonages = en_base(commune_code, environment) if commune_code else {}
    dates = [z.releve_le for z in zonages.values()]
    return {
        "releve": bool(zonages),
        "releve_le": min(dates) if dates else None,
        "complet": len(zonages) == len(COUCHES_GEORISQUES),
        "couches": [{"couche": couche, "libelle": libelle, "relevee": couche in zonages,
                     "presente": bool(couche in zonages and zonages[couche].polygone)}
                    for couche, libelle in COUCHES_GEORISQUES.items()],
    }


def relever(commune_code: str, environment, forcer: bool = False) -> dict:
    """Relève auprès de Géorisques les zones de la commune, une requête par scénario, espacées.
    Rend `{"relevees": [...], "ignorees": [...], "erreurs": {couche: message}}`."""
    from .habitations import zones_georisques

    deja = en_base(commune_code, environment)
    limite = timezone.now() - datetime.timedelta(days=FRAICHEUR_JOURS)
    bilan = {"relevees": [], "ignorees": [], "erreurs": {}}
    for couche in COUCHES_GEORISQUES:
        if not forcer and couche in deja and deja[couche].releve_le > limite:
            bilan["ignorees"].append(couche)
            continue
        _attendre_son_tour()
        resultat = zones_georisques(commune_code, couche)
        if resultat["erreur"]:
            # On garde ce qu'on avait : une panne de leur côté n'efface pas un relevé.
            bilan["erreurs"][couche] = resultat["erreur"]
            continue
        garder(commune_code, couche, environment, resultat["polygone"])
        bilan["relevees"].append(couche)
    return bilan


def garder(commune_code: str, couche: str, environment, polygone):
    """Garde en base la zone relevée pour ce scénario (`polygone` None = rien ici). Sert au
    relevé complet comme à la carte de simulation, qui relève un scénario à la demande : une
    seule mémoire, quel que soit l'écran qui a posé la question à Géorisques."""
    if polygone is not None:
        polygone = polygone.simplify(0.00005, preserve_topology=True)   # ~5 m : assez pour une carte
        if polygone.geom_type == "Polygon":
            polygone = MultiPolygon(polygone, srid=4326)
        if polygone.empty or polygone.geom_type != "MultiPolygon":
            polygone = None
    ZonageOfficiel.objects.update_or_create(
        commune_code=commune_code, couche=couche, environment=environment, defaults={"polygone": polygone})


def zone_d_un_point(point, zonages: dict) -> str:
    """Le scénario de débordement le plus fréquent dont la zone officielle contient ce point :
    son libellé, ou une chaîne vide s'il n'est dans aucune (ou si rien n'a été relevé)."""
    if point is None:
        return ""
    for couche in ORDRE_DEBORDEMENT:
        zonage = zonages.get(couche)
        if zonage is not None and zonage.polygone is not None and zonage.polygone.contains(point):
            return COUCHES_DEBORDEMENT_GEORISQUES[couche]
    return ""
