"""Propagation en ondes courtes (HF) : la météo de l'espace, d'après la NOAA (28/11/2026).

Demande de Sylvain, pour la carte ouverte « pour les copains » : la propagation radio. La VHF,
l'UHF et la LoRa sont dans core/tropo.py ; ici, les ondes courtes, qui dépendent du Soleil.

SOURCE : Space Weather Prediction Center de la NOAA (services.swpc.noaa.gov), données publiques
du gouvernement américain. Fichiers vérifiés le 28/11/2026 sur le répertoire du service :
- products/noaa-scales.json : les échelles officielles R (coupures radio), S (tempête de
  protons), G (orage géomagnétique), pour hier (« -1 »), maintenant (« 0 ») et les trois jours
  à venir (« 1 » à « 3 », avec des probabilités) ;
- products/noaa-planetary-k-index.json : l'indice Kp planétaire, toutes les trois heures ;
- products/noaa-planetary-k-index-forecast.json : Kp observé, estimé et prévu (`observed`) ;
- products/summary/10cm-flux.json : le flux solaire à 10,7 cm (F10.7) ;
- json/goes/primary/xray-flares-7-day.json : les éruptions X de la semaine (classe au maximum).

AUCUNE RÈGLE DE NOTRE CRU : on affiche les échelles de la NOAA et leurs effets sur les ondes
courtes tels que la NOAA les décrit (NOAA Space Weather Scales), traduits ici.
"""
import datetime
import logging

import requests
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

RACINE = "https://services.swpc.noaa.gov/"
FICHIERS = {
    "echelles": "products/noaa-scales.json",
    "kp": "products/noaa-planetary-k-index.json",
    "kp_prevu": "products/noaa-planetary-k-index-forecast.json",
    "flux": "products/summary/10cm-flux.json",
    "eruptions": "json/goes/primary/xray-flares-7-day.json",
}
DELAI_S = 30
ATTRIBUTION = "NOAA Space Weather Prediction Center"

#: Effets sur les ondes courtes, d'après les échelles de la NOAA (R : éruptions, côté jour).
EFFETS_R = {
    0: "Pas de coupure radio liée aux éruptions.",
    1: "Légère dégradation des ondes courtes côté jour, pertes de contact occasionnelles.",
    2: "Coupures limitées des ondes courtes côté jour, pertes de contact de quelques dizaines de minutes.",
    3: "Coupures étendues des ondes courtes, pertes de contact d'environ une heure côté jour.",
    4: "Coupure des ondes courtes sur la plus grande partie du côté jour, pendant une à deux heures.",
    5: "Coupure complète des ondes courtes sur tout le côté jour, pendant plusieurs heures.",
}
#: Effets sur les ondes courtes, d'après les échelles de la NOAA (G : orages géomagnétiques).
EFFETS_G = {
    0: "Champ magnétique calme.",
    1: "Orage faible : effets mineurs, aurores aux hautes latitudes.",
    2: "La propagation HF peut s'affaiblir aux hautes latitudes.",
    3: "La propagation HF peut devenir intermittente.",
    4: "La propagation HF devient sporadique.",
    5: "La propagation HF peut être impossible dans de nombreuses régions pendant un à deux jours.",
}
LIBELLES = {0: "aucun", 1: "mineur", 2: "modéré", 3: "fort", 4: "sévère", 5: "extrême"}


class ReponseInattendue(Exception):
    pass


def _lire(client, chemin):
    try:
        r = client.get(RACINE + chemin, timeout=DELAI_S)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as erreur:
        raise ReponseInattendue(f"{chemin} : {erreur}") from erreur


def _entier(v):
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def _nombre(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def kp_vers_g(kp):
    """Échelle G de la NOAA d'après Kp : 5 → G1, 6 → G2, 7 → G3, 8 et 9- → G4, 9 → G5."""
    if kp is None:
        return None
    if kp >= 9:
        return 5
    for seuil, g in ((8, 4), (7, 3), (6, 2), (5, 1)):
        if kp >= seuil:
            return g
    return 0


def classe_vers_r(classe):
    """Échelle R de la NOAA d'après la classe d'une éruption : M1 → R1, M5 → R2, X1 → R3,
    X10 → R4, X20 → R5 ; A, B et C : rien."""
    if not classe:
        return 0
    lettre, valeur = classe[0].upper(), _nombre(classe[1:]) or 0.0
    if lettre == "X":
        return 5 if valeur >= 20 else 4 if valeur >= 10 else 3
    if lettre == "M":
        return 2 if valeur >= 5 else 1
    return 0


def _rang_classe(classe):
    ordre = "ABCMX"
    if not classe or classe[0].upper() not in ordre:
        return -1.0
    return ordre.index(classe[0].upper()) * 100 + (_nombre(classe[1:]) or 0.0)


def resumer(brut, maintenant):
    """Le relevé lisible à partir des cinq fichiers (dictionnaire `brut` par clé de FICHIERS)."""
    echelles = brut.get("echelles") or {}
    actuel = echelles.get("0") or {}
    prevus = []
    for cle in ("1", "2", "3"):
        jour = echelles.get(cle) or {}
        prevus.append({
            "date": jour.get("DateStamp"),
            "g": _entier((jour.get("G") or {}).get("Scale")),
            "r_mineur_pct": _entier((jour.get("R") or {}).get("MinorProb")),
            "r_majeur_pct": _entier((jour.get("R") or {}).get("MajorProb")),
        })

    kp_obs = [k for k in (brut.get("kp") or []) if _nombre(k.get("Kp")) is not None]
    dernier = kp_obs[-1] if kp_obs else None
    kp = _nombre(dernier["Kp"]) if dernier else None

    a_venir = [k for k in (brut.get("kp_prevu") or []) if k.get("observed") == "predicted" and _nombre(k.get("kp")) is not None]
    kp_max_prevu = max((_nombre(k["kp"]) for k in a_venir), default=None)

    flux = None
    for ligne in brut.get("flux") or []:
        flux = _entier(ligne.get("flux")) or flux

    depuis = maintenant - datetime.timedelta(hours=24)
    eruptions = []
    for e in brut.get("eruptions") or []:
        quand = parse_datetime(str(e.get("max_time") or ""))
        if quand is not None and quand >= depuis and e.get("max_class"):
            eruptions.append((e["max_class"], quand))
    plus_forte = max(eruptions, key=lambda x: _rang_classe(x[0]), default=None)

    g = _entier((actuel.get("G") or {}).get("Scale"))
    r = _entier((actuel.get("R") or {}).get("Scale"))
    g = g if g is not None else kp_vers_g(kp)
    r = r if r is not None else classe_vers_r(plus_forte[0] if plus_forte else None)
    return {
        "kp": kp, "kp_le": dernier.get("time_tag") if dernier else None,
        "kp_max_prevu_3j": kp_max_prevu,
        "flux_10cm": flux,
        "eruption_max_24h": {"classe": plus_forte[0], "le": plus_forte[1].isoformat()} if plus_forte else None,
        "g": g, "r": r,
        "g_libelle": LIBELLES.get(g), "r_libelle": LIBELLES.get(r),
        "effet_g": EFFETS_G.get(g), "effet_r": EFFETS_R.get(r),
        "prevision": prevus,
    }


def relever(maintenant=None, client=None):
    """Lit les cinq fichiers et range le relevé. Rend 1."""
    from .models import ReleveEspace

    maintenant = maintenant or timezone.now()
    client = client or requests.Session()
    client.headers.update({"User-Agent": "client-meteo"})
    brut = {cle: _lire(client, chemin) for cle, chemin in FICHIERS.items()}
    if not isinstance(brut["echelles"], dict) or not isinstance(brut["kp"], list):
        raise ReponseInattendue("format des fichiers de la NOAA changé")
    ReleveEspace.objects.update_or_create(pk=1, defaults={"donnees": resumer(brut, maintenant), "releve_le": maintenant})
    return 1


def dernier():
    from .models import ReleveEspace

    r = ReleveEspace.objects.filter(pk=1).first()
    return (dict(r.donnees, releve_le=r.releve_le.isoformat())) if r else None
