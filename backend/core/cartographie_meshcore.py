"""Cartographie du réseau MeshCore public, copiée depuis les instances CoreScope (meshstats).

Jusqu'au 23/11/2026, un import manuel seulement (`importer_cartographie_meshcore`), fait une
fois le 10/11 : treize jours plus tard, les « derniers vus » des répéteurs étaient figés, et le
tableau radio comme le diagnostic raisonnaient sur une carte périmée. « Il faut synchroniser
plus souvent avec les CoreScope de meshstat. » Désormais relevé chaque heure par la veille du
territoire (core/sources_ouvertes.py), pour chaque instance déjà importée ou configurée.

**Répéteurs et rooms seulement.** Les companions sont volontairement exclus : l'appareil
personnel de quelqu'un, dont la position est souvent son domicile. Voir `NoeudPublicMeshCore`.

L'import est **idempotent** : il met à jour les lignes existantes, sans doublon. Un nœud que
l'instance ne sert plus n'est pas supprimé — il garde sa dernière date vue.

Débit : pages de 200 et une pause entre deux. C'est le service de quelqu'un d'autre ; une
synchronisation par heure suffit (les instances recalculent leurs scores à ce rythme).
Agent générique : on n'envoie aucune information sur qui interroge.
"""
import logging
import time

import requests
from django.contrib.gis.geos import Point
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

ROLES = ("repeater", "room")          # `companion` et `sensor` en sont absents EXPRÈS
TAILLE_PAGE = 200
PAUSE_ENTRE_PAGES_S = 0.3
# Un opérateur qui ne veut pas être affiché renomme son nœud avec l'un de ces préfixes.
PREFIXES_MASQUES = ("🚫",)


class ImportImpossible(Exception):
    """L'instance n'a pas répondu comme attendu."""


def _pages(client, instance, role, region):
    """Parcourt /api/nodes page par page. `has_more` fait foi, pas `total` (taille de la PAGE)."""
    offset = 0
    while True:
        params = {"role": role, "limit": TAILLE_PAGE, "offset": offset}
        if region:
            params["region"] = region
        try:
            reponse = client.get(f"{instance}/api/nodes", params=params, timeout=30)
            reponse.raise_for_status()
            charge = reponse.json()
        except (requests.RequestException, ValueError) as erreur:
            raise ImportImpossible(f"Échec de lecture de {instance} : {erreur}") from erreur
        if not isinstance(charge, dict):
            raise ImportImpossible(f"Réponse inattendue de {instance}.")
        noeuds = charge.get("nodes") or []
        yield from noeuds
        if not charge.get("has_more") or not noeuds:
            return
        offset += len(noeuds)
        time.sleep(PAUSE_ENTRE_PAGES_S)


def _traiter(noeud, instance, environment, compter, maintenant, bilan, hashs):
    from .models import NoeudPublicMeshCore

    cle = (noeud.get("public_key") or "").strip().lower()
    if len(cle) != 64:
        return
    nom = (noeud.get("name") or "").strip()
    if any(nom.startswith(p) for p in PREFIXES_MASQUES):
        bilan["masques"] += 1
        return
    lat, lon = noeud.get("lat"), noeud.get("lon")
    if lat is None or lon is None:
        bilan["sans_position"] += 1     # rien à cartographier
        return
    taille = noeud.get("hash_size")
    if isinstance(taille, int) and taille > 0:
        hashs[taille] = hashs.get(taille, 0) + 1
    if compter:
        return
    _, cree = NoeudPublicMeshCore.objects.update_or_create(
        instance=instance, pubkey_hex=cle, environment=environment,
        defaults={
            "nom": nom[:100],
            "role": (noeud.get("role") or "")[:20],
            "location": Point(float(lon), float(lat), srid=4326),
            "premier_vu": parse_datetime(noeud.get("first_seen") or "") or None,
            "dernier_vu": parse_datetime(noeud.get("last_seen") or "") or None,
            "relais_actif": bool(noeud.get("relay_active")),
            "relais_24h": int(noeud.get("relay_count_24h") or 0),
            "score_couverture": noeud.get("coverage_score"),
            "score_redondance": noeud.get("redundancy_score"),
            "score_pont": noeud.get("bridge_score"),
            "score_utilite": noeud.get("usefulness_score"),
            "note_utilite": (noeud.get("usefulness_grade") or "")[:4],
            "taille_hash": taille if isinstance(taille, int) else None,
            "date_import": maintenant,
        },
    )
    bilan["crees" if cree else "majs"] += 1


def importer(instance, environment=None, region=None, compter=False):
    """Importe une instance. Rend le bilan {lus, sans_position, masques, crees, majs, hashs}."""
    from .models import Environment

    instance = instance.rstrip("/")
    environment = environment or Environment.PROD
    maintenant = timezone.now()
    bilan = {"lus": 0, "sans_position": 0, "masques": 0, "crees": 0, "majs": 0}
    hashs = {}
    with requests.Session() as client:
        client.headers.update({"User-Agent": "curl"})
        for role in ROLES:
            for noeud in _pages(client, instance, role, region):
                bilan["lus"] += 1
                _traiter(noeud, instance, environment, compter, maintenant, bilan, hashs)
    bilan["hashs"] = hashs
    return bilan


def instances():
    """Les instances à synchroniser : celles déjà importées, et les sources d'observation de type
    CoreScope configurées."""
    from .models import NoeudPublicMeshCore, SourceObservateurMeshCore

    connues = {i.rstrip("/") for i in NoeudPublicMeshCore.objects.values_list("instance", flat=True).distinct() if i}
    for hote in SourceObservateurMeshCore.objects.filter(type_source="CORESCOPE", actif=True).values_list("broker_host", flat=True):
        hote = (hote or "").strip().removeprefix("https://").removeprefix("wss://").rstrip("/")
        if hote:
            connues.add(f"https://{hote}")
    return sorted(connues)


def relever():
    """Pour la veille du territoire : synchronise chaque instance. Rend le nombre de nœuds lus ;
    lève si AUCUNE instance n'a répondu (une seule en panne n'arrête pas les autres)."""
    total, erreurs, liste = 0, [], instances()
    if not liste:
        return 0
    for instance in liste:
        try:
            bilan = importer(instance)
            total += bilan["lus"]
            logger.info("Cartographie MeshCore %s : %d lus, %d créés, %d mis à jour.",
                        instance, bilan["lus"], bilan["crees"], bilan["majs"])
        except ImportImpossible as erreur:
            erreurs.append(str(erreur))
            logger.warning("%s", erreur)
    if erreurs and len(erreurs) == len(liste):
        raise ImportImpossible(" ; ".join(erreurs))
    return total
