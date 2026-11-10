"""Résoudre un saut de chemin MeshCore vers un nœud connu — et savoir quand on ne peut pas.

Porté de l'algorithme de désambiguïsation de **CoreScope**
(https://github.com/Kpa-clawbot/CoreScope, GPL-3.0, commit `1577b57d` du 09/11/2026,
`docs/HASH-PREFIX-DISAMBIGUATION.md`). Le raisonnement est le sien ; le code est réécrit.

**Le problème.** Chaque saut d'un chemin MeshCore est un préfixe de la clé publique du relais
— le firmware le dit sans détour : « hash is just prefix of pub_key » (`src/Identity.h:20`),
ce n'est pas un condensé. Sa longueur est de 1, 2 ou 3 octets (`hash_size = (pathByte>>6)+1`,
`src/Packet.cpp:13-18`). **Un octet n'a que 256 valeurs** : au-delà d'une vingtaine de nœuds,
les collisions sont certaines. Mesuré par CoreScope sur un réseau réel, 56 % des sauts observés
portent un préfixe d'un seul octet.

**Pourquoi c'est dangereux et pas seulement imprécis.** Un saut mal résolu ne produit pas une
donnée floue, il produit une **liaison fausse** : un trait sur la carte entre deux nœuds qui ne
se sont jamais entendus, et une conclusion « ça passe par là » qui envoie quelqu'un sur un
point haut pour rien.

**Ce que ce module rend donc** : pour chaque saut, le nœud résolu *et comment* il l'a été.
Trois certitudes, et elles ne valent pas la même chose :

- `unique` : un seul nœud connu porte ce préfixe. C'est une résolution, pas une supposition ;
- `deduit` : plusieurs candidats, départagés par la géographie (le plus proche du saut voisin
  déjà résolu). **C'est une hypothèse**, utilisable pour afficher un tracé, jamais comme preuve
  de topologie ;
- `ambigu` / `inconnu` : on ne tranche pas. Mieux vaut un trou dans le chemin qu'un trait faux.

La règle qui en découle, et qui est appliquée par `core/analyse_liaisons.py` : seul `unique`
alimente le diagnostic.
"""
import math

from .decodeur_meshcore import prefixe_fiable

# Au-delà, un saut est géographiquement invraisemblable au regard de ses voisins dans le
# chemin. Distinct de `analyse_liaisons.DISTANCE_MAX_KM` (120 km), qui porte sur une liaison
# RF DIRECTE : ici on juge la cohérence d'un itinéraire, pas la portée d'une radio.
DISTANCE_INVRAISEMBLABLE_KM = 200.0


def _distance_km(a, b):
    if not a or not b:
        return None
    r = math.pi / 180
    s = (math.sin(((b[0] - a[0]) * r) / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(((b[1] - a[1]) * r) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(min(1.0, s)))


def indexer(noeuds):
    """{préfixe: [clés complètes]} pour toutes les longueurs utiles (1 à 3 octets).

    `noeuds` est un dict {clé publique hex: (lat, lon) ou None}."""
    index = {}
    for cle in noeuds:
        cle = (cle or "").lower()
        for octets in (1, 2, 3):
            index.setdefault(cle[:octets * 2], []).append(cle)
    return index


def resoudre_chemin(sauts, taille_hash, noeuds, minimum_octets=1):
    """Résout chaque saut d'un chemin, en disant comment.

    `sauts` : les préfixes hexadécimaux rendus par le décodeur. `noeuds` : {clé hex: position}.

    Deux passes, parce qu'un saut ambigu peut être éclairé aussi bien par celui qui le précède
    que par celui qui le suit : on résout d'abord de gauche à droite, puis de droite à gauche
    pour ce qui reste. Sans la seconde passe, un chemin dont le premier saut est ambigu ne se
    résoudrait jamais."""
    index = indexer(noeuds)
    fiable = prefixe_fiable(taille_hash, minimum_octets)

    resolus = []
    for prefixe in sauts:
        prefixe = (prefixe or "").lower()
        candidats = index.get(prefixe, [])
        if len(candidats) == 1:
            resolus.append({"prefixe": prefixe, "pubkey": candidats[0], "certitude": "unique",
                            "candidats": 1})
        elif not candidats:
            resolus.append({"prefixe": prefixe, "pubkey": None, "certitude": "inconnu",
                            "candidats": 0})
        else:
            resolus.append({"prefixe": prefixe, "pubkey": None, "certitude": "ambigu",
                            "candidats": len(candidats)})

    def departager(indice, ancre):
        """Choisit, parmi les candidats du saut `indice`, le plus proche de `ancre`."""
        position_ancre = noeuds.get(ancre)
        if not position_ancre:
            return False
        candidats = index.get(resolus[indice]["prefixe"], [])
        notes = [(d, c) for c in candidats
                 if (d := _distance_km(noeuds.get(c), position_ancre)) is not None]
        if not notes:
            return False
        notes.sort()
        resolus[indice].update(pubkey=notes[0][1], certitude="deduit")
        return True

    # Passe avant, puis passe arrière sur ce qui reste.
    for i, saut in enumerate(resolus):
        if saut["certitude"] == "ambigu":
            for j in range(i - 1, -1, -1):
                if resolus[j]["pubkey"]:
                    departager(i, resolus[j]["pubkey"])
                    break
    for i in range(len(resolus) - 1, -1, -1):
        if resolus[i]["certitude"] == "ambigu":
            for j in range(i + 1, len(resolus)):
                if resolus[j]["pubkey"]:
                    departager(i, resolus[j]["pubkey"])
                    break

    # Contrôle de vraisemblance : un saut à plus de 200 km de ses DEUX voisins résolus n'est
    # pas sur cet itinéraire, quelle que soit la façon dont il a été résolu.
    for i, saut in enumerate(resolus):
        saut["fiable"] = fiable and saut["certitude"] == "unique"
        saut["invraisemblable"] = False
        position = noeuds.get(saut["pubkey"]) if saut["pubkey"] else None
        if not position:
            continue
        voisines = []
        for j in (i - 1, i + 1):
            if 0 <= j < len(resolus) and resolus[j]["pubkey"]:
                voisine = noeuds.get(resolus[j]["pubkey"])
                if voisine:
                    voisines.append(_distance_km(position, voisine))
        if voisines and all(d > DISTANCE_INVRAISEMBLABLE_KM for d in voisines):
            saut["invraisemblable"] = True
            saut["fiable"] = False

    return resolus


def resume(resolus):
    """De quoi dire à l'écran ce que vaut ce chemin, sans que l'interface recompte."""
    return {
        "sauts": len(resolus),
        "uniques": sum(1 for s in resolus if s["certitude"] == "unique"),
        "deduits": sum(1 for s in resolus if s["certitude"] == "deduit"),
        "ambigus": sum(1 for s in resolus if s["certitude"] == "ambigu"),
        "inconnus": sum(1 for s in resolus if s["certitude"] == "inconnu"),
        "invraisemblables": sum(1 for s in resolus if s["invraisemblable"]),
        # Vrai seulement si TOUT le chemin est sûr : un seul saut deviné suffit à rendre
        # l'itinéraire discutable, et c'est l'itinéraire qu'on affiche.
        "chemin_sur": bool(resolus) and all(s["fiable"] for s in resolus),
    }
