"""Foudre selon le satellite MTG d'EUMETSAT (19/11/2026).

SOURCE
Imageur de foudre (« Lightning Imager ») du satellite géostationnaire MTG-I1, produit de niveau 2
« LI Lightning Flashes » (collection EO:EUM:DAT:0691 du Data Store d'EUMETSAT). Vérifié le
19/11/2026 sur le service réel :

- droits annoncés par la collection : « NoConditions » ;
- un produit par tranche de dix minutes, parfois en plusieurs fichiers, disponible environ dix à
  vingt minutes après le début de la tranche — ce n'est PAS du temps réel ;
- une archive ZIP contenant du NetCDF-4 (lu comme du HDF5) : `latitude`, `longitude` (entiers
  à multiplier par `scale_factor`), `flash_time` (secondes depuis le 01/01/2000), `flash_duration`
  (ms), `radiance`, `flash_filter_confidence` ;
- environ 4 000 éclairs par tranche sur tout le disque vu du satellite ; ce soir-là, ceux tombés
  sur la France coïncidaient avec les cellules les plus intenses du radar.

Ce que c'est : des ÉCLAIRS vus de l'espace (nuage-sol et intra-nuage confondus), à la précision
d'un pixel de l'imageur (environ 4,5 km sous le satellite, davantage vers le nord). Ce n'est pas un
réseau de détection au sol des impacts.

Pourquoi pas Blitzortung : ses conditions interdisent expressément l'usage de ses données « pour
des systèmes d'alerte aux orages », même obtenues par des sites tiers.

MÊME RÈGLE QUE LE RESTE DE LA VEILLE
Seul le serveur appelle EUMETSAT, depuis la tâche planifiée. Les identifiants (clé et secret du
Data Store) sont un secret Docker, jamais journalisés.
"""
import datetime
import io
import logging
import os
import zipfile
from pathlib import Path

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

URL_JETON = "https://api.eumetsat.int/token"
URL_RECHERCHE = "https://api.eumetsat.int/data/search-products/1.0.0/os"
COLLECTION = "EO:EUM:DAT:0691"
DELAI_REPONSE_S = 60

#: Emprises gardées : métropole et Corse. Le reste du disque n'a rien à faire dans notre base.
EMPRISES = (
    (-5.8, 41.0, 10.0, 51.6),
)
#: Éclairs gardés 48 heures.
DUREE_GARDEE = datetime.timedelta(hours=48)
#: Au-delà, la copie n'est plus présentée comme actuelle (les produits arrivent 10 à 20 min
#: après coup ; trois quarts d'heure sans rien signale une panne).
FRAICHEUR_MAX = datetime.timedelta(minutes=45)
#: Produits lus au plus par passage, pour ne pas rattraper des heures d'un coup après une panne.
PRODUITS_MAX = 12
EPOQUE = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)


class IdentifiantsAbsents(Exception):
    pass


def _chemin_identifiants():
    return Path(os.environ.get("EUMETSAT_API_FILE", "/run/secrets/eumetsat_api"))


def lire_identifiants():
    """(clé, secret) du Data Store, depuis le secret « clé:secret ». Jamais journalisés."""
    try:
        texte = _chemin_identifiants().read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        raise IdentifiantsAbsents()
    cle, _, secret = texte.partition(":")
    if not cle or not secret:
        raise IdentifiantsAbsents()
    return cle.strip(), secret.strip()


def jeton():
    cle, secret = lire_identifiants()
    r = requests.post(URL_JETON, data={"grant_type": "client_credentials"}, auth=(cle, secret),
                      timeout=DELAI_REPONSE_S)
    r.raise_for_status()
    return r.json()["access_token"]


def produits_depuis(entete, depuis):
    """Produits de la collection dont la tranche commence après `depuis`, du plus ancien au plus
    récent : [(identifiant, url, debut, fin)]."""
    r = requests.get(URL_RECHERCHE, headers=entete, timeout=DELAI_REPONSE_S, params={
        "pi": COLLECTION, "format": "json", "si": 0, "c": 100, "sort": "start,time,1",
        "dtstart": depuis.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    r.raise_for_status()
    produits = []
    for f in r.json().get("features", []):
        p = f.get("properties", {})
        url = ((p.get("links") or {}).get("data") or [{}])[0].get("href")
        debut, _, fin = (p.get("date") or "").partition("/")
        if not url or not debut:
            continue
        produits.append((f.get("id"), url, _instant(debut), _instant(fin or debut)))
    return sorted(produits, key=lambda p: (p[2], p[0]))


def _instant(texte):
    return datetime.datetime.fromisoformat(texte.replace("Z", "+00:00"))


def _attr(variable, nom, defaut):
    valeur = variable.attrs.get(nom, defaut)
    return float(valeur[0]) if hasattr(valeur, "__len__") and not isinstance(valeur, (str, bytes)) else float(valeur)


def lire_eclairs(archive):
    """Éclairs d'un produit (archive ZIP de NetCDF) tombés dans nos emprises :
    [{instant, latitude, longitude, duree_ms, radiance, confiance}]."""
    import h5py
    import numpy

    eclairs = []
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for nom in z.namelist():
            if not nom.endswith(".nc"):
                continue
            with h5py.File(io.BytesIO(z.read(nom)), "r") as h:
                if "latitude" not in h or "longitude" not in h or "flash_time" not in h:
                    continue
                vlat, vlon = h["latitude"], h["longitude"]
                brut_lat, brut_lon = vlat[:].astype(float), vlon[:].astype(float)
                manque = (brut_lat == _attr(vlat, "_FillValue", -32767)) | (brut_lon == _attr(vlon, "_FillValue", -32767))
                lat = brut_lat * _attr(vlat, "scale_factor", 1) + _attr(vlat, "add_offset", 0)
                lon = brut_lon * _attr(vlon, "scale_factor", 1) + _attr(vlon, "add_offset", 0)
                dans = numpy.any([(lon >= o) & (lon <= e) & (lat >= s) & (lat <= n) for o, s, e, n in EMPRISES], axis=0)
                garde = ~manque & dans
                if not garde.any():
                    continue
                temps = h["flash_time"][:]
                duree = h["flash_duration"][:] if "flash_duration" in h else numpy.zeros(len(lat))
                radiance = h["radiance"][:] if "radiance" in h else numpy.zeros(len(lat))
                confiance = h["flash_filter_confidence"][:] if "flash_filter_confidence" in h else numpy.full(len(lat), numpy.nan)
                for i in numpy.nonzero(garde)[0]:
                    eclairs.append({
                        "instant": EPOQUE + datetime.timedelta(seconds=float(temps[i])),
                        "latitude": round(float(lat[i]), 4), "longitude": round(float(lon[i]), 4),
                        "duree_ms": int(duree[i]), "radiance": float(radiance[i]),
                        "confiance": float(confiance[i]) if numpy.isfinite(confiance[i]) else None,
                    })
    return eclairs


def relever(maintenant=None):
    """Lit les produits parus depuis le dernier relevé. Rend le nombre d'éclairs ajoutés."""
    from django.contrib.gis.geos import Point
    from .models import ImpactFoudre, ProduitFoudre

    maintenant = maintenant or timezone.now()
    entete = {"Authorization": f"Bearer {jeton()}"}
    dernier = ProduitFoudre.objects.order_by("-debut").first()
    depuis = dernier.debut if dernier else maintenant - datetime.timedelta(hours=1)
    deja = set(ProduitFoudre.objects.filter(debut__gte=depuis).values_list("identifiant", flat=True))
    ajoutes = 0
    for identifiant, url, debut, fin in [p for p in produits_depuis(entete, depuis) if p[0] not in deja][:PRODUITS_MAX]:
        r = requests.get(url, headers=entete, timeout=DELAI_REPONSE_S * 2)
        r.raise_for_status()
        eclairs = lire_eclairs(r.content)
        ImpactFoudre.objects.bulk_create([ImpactFoudre(
            instant=e["instant"], location=Point(e["longitude"], e["latitude"], srid=4326),
            duree_ms=e["duree_ms"], radiance=e["radiance"], confiance=e["confiance"]) for e in eclairs])
        ProduitFoudre.objects.create(identifiant=identifiant, debut=debut, fin=fin, eclairs=len(eclairs),
                                     releve_le=maintenant)
        ajoutes += len(eclairs)
    limite = maintenant - DUREE_GARDEE
    ImpactFoudre.objects.filter(instant__lt=limite).delete()
    ProduitFoudre.objects.filter(debut__lt=limite).delete()
    dernier = ProduitFoudre.objects.order_by("-fin").first()
    if dernier is None or maintenant - dernier.fin > FRAICHEUR_MAX:
        raise RuntimeError("Aucun produit de foudre récent chez EUMETSAT.")
    return ajoutes


def eclairs_dans(zone, depuis, jusqu_a=None):
    """Éclairs gardés dans une géométrie, sur une période."""
    from .models import ImpactFoudre
    qs = ImpactFoudre.objects.filter(location__within=zone, instant__gte=depuis)
    if jusqu_a is not None:
        qs = qs.filter(instant__lte=jusqu_a)
    return qs
