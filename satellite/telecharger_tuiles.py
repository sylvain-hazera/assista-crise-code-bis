"""Prépare le fichier de tuiles locales du serveur cartographique d'un satellite (profil Full,
voir le cadrage "Chantier B" section 7) — son département ET les départements limitrophes, pas
juste sa commune : une équipe doit pouvoir naviguer au-delà de la limite administrative pendant
une crise réelle, sans dépendre d'internet.

Découpe un extrait régional depuis la base cartographique globale Protomaps (format PMTiles,
cloud-optimisé) via l'outil `pmtiles extract` (binaire Go, voir Dockerfile.tuiles) — celui-ci
ne télécharge QUE la zone demandée par requêtes HTTP par plage d'octets, jamais le fichier
planète complet (~120 Go), voir https://docs.protomaps.com/basemaps/downloads. Vérifié le
2026-09-17 : `pmtiles extract SOURCE.pmtiles SORTIE.pmtiles --bbox=min_lon,min_lat,max_lon,max_lat`.

L'adjacence entre départements (data/departements_limitrophes.json) est PRÉ-CALCULÉE — pas une
liste tapée à la main, ni recalculée ici : générée une fois depuis les géométries officielles
(https://github.com/gregoiredavid/france-geojson, contours communaux/départementaux publics)
par intersection géométrique réelle (shapely `.touches()`/`.intersects()`, en excluant les
contacts ponctuels — 4 départements qui se touchent à un seul coin ne sont pas "limitrophes"
au sens de cet usage). Vérifié sur des cas connus (75 borde 92/93/94, 38 borde 7 départements
alpins/rhodaniens, 33 borde 17/24/40/47) — voir la commande de régénération en bas de fichier.
Départements métropolitains uniquement (96) ; l'outre-mer n'est pas couvert par ce fichier."""
import argparse
import io
import json
import logging
import os
import shutil
import subprocess
import urllib.request
import zipfile

logger = logging.getLogger("telecharger-tuiles")

DATA_DEPARTEMENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "departements_limitrophes.json")

# Vide par défaut : le dernier build publié est alors trouvé tout seul (dernier_build), plus
# besoin de recopier une URL datée depuis https://maps.protomaps.com/builds (20/10/2026).
PMTILES_SOURCE_DEFAUT = os.environ.get("PMTILES_SOURCE")
BUILDS_PROTOMAPS = "https://build-metadata.protomaps.dev/builds.json"
# L'agent par défaut « Python-urllib » est refusé (403) par build-metadata.protomaps.dev
# (constaté le 20/10/2026) : sans lui, aucun satellite n'obtenait son fond de carte.
ENTETES_HTTP = {"User-Agent": "assista-crise-satellite/1.0 (+https://assista-crise.fr)"}
URL_BUILD_PROTOMAPS = "https://build.protomaps.com/{cle}"


def dernier_build(lecteur=None):
    """URL du build PMTiles le plus récent (liste officielle Protomaps : clés datées
    AAAAMMJJ.pmtiles, donc la plus grande est la plus récente). `lecteur` injectable pour les
    tests (aucun vrai réseau)."""
    import urllib.request

    if lecteur is None:
        def lecteur(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers=ENTETES_HTTP), timeout=30) as reponse:
                return reponse.read()
    builds = json.loads(lecteur(BUILDS_PROTOMAPS))
    cles = sorted(b["key"] for b in builds if str(b.get("key", "")).endswith(".pmtiles"))
    if not cles:
        raise RuntimeError("Liste des builds Protomaps vide ou illisible.")
    return URL_BUILD_PROTOMAPS.format(cle=cles[-1])


def _charger_departements():
    with open(DATA_DEPARTEMENTS, encoding="utf-8") as f:
        return json.load(f)


def bbox_zone(code_departement, inclure_limitrophes=True, departements=None):
    """Bounding box (min_lon, min_lat, max_lon, max_lat) couvrant le département donné, et ses
    limitrophes si demandé — union simple des bbox individuelles, pas un contour précis
    (`pmtiles extract` accepte aussi `--region=fichier.geojson` pour un polygone exact, mais une
    bbox élargie est un compromis raisonnable ici : un peu plus de tuiles téléchargées que le
    strict nécessaire, en échange d'une logique beaucoup plus simple)."""
    departements = departements or _charger_departements()
    if code_departement not in departements:
        raise ValueError(f"Département inconnu (métropole uniquement) : {code_departement!r}")
    codes = [code_departement]
    if inclure_limitrophes:
        codes += departements[code_departement]["limitrophes"]
    bboxes = [departements[c]["bbox"] for c in codes if c in departements]
    return (
        min(b[0] for b in bboxes),  # min_lon
        min(b[1] for b in bboxes),  # min_lat
        max(b[2] for b in bboxes),  # max_lon
        max(b[3] for b in bboxes),  # max_lat
    )


def extraire(code_departement, sortie, source=None, maxzoom=None, inclure_limitrophes=True):
    """Lance `pmtiles extract` pour de vrai — nécessite le binaire `pmtiles` dans le PATH (voir
    Dockerfile.tuiles) et un accès réseau vers `source`. Pas mocké : cette fonction fait un vrai
    téléchargement, à ne tester qu'avec subprocess.run mocké (voir test_telecharger_tuiles.py) ou
    en conditions réelles sur un satellite."""
    source = source or PMTILES_SOURCE_DEFAUT or dernier_build()
    logger.info("Source PMTiles : %s", source)
    bbox = bbox_zone(code_departement, inclure_limitrophes=inclure_limitrophes)
    commande = [
        "pmtiles", "extract", source, sortie,
        "--bbox=" + ",".join(str(v) for v in bbox),
    ]
    if maxzoom is not None:
        commande.append(f"--maxzoom={maxzoom}")
    logger.info(
        "Extraction tuiles département %s (+limitrophes=%s), bbox=%s",
        code_departement, inclure_limitrophes, bbox,
    )
    subprocess.run(commande, check=True)
    logger.info("Terminé : %s", sortie)
    return sortie


# Polices et pictogrammes du fond de carte Protomaps (style construit par le frontend, voir
# frontend/src/app/shared/utils/carte-style.ts) : ~7 Mo, sans eux la carte hors ligne n'aurait
# ni noms de rues ni icônes. Servis par nginx-satellite.conf sous /tuiles/assets/.
URL_ASSETS_CARTE = "https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.zip"


def telecharger_assets(dossier, lecteur=None):
    """Extrait fonts/ et sprites/ de l'archive basemaps-assets dans `dossier`. `lecteur`
    injectable pour les tests."""
    lecteur = lecteur or (lambda url: urllib.request.urlopen(urllib.request.Request(url, headers=ENTETES_HTTP), timeout=120).read())
    archive = zipfile.ZipFile(io.BytesIO(lecteur(URL_ASSETS_CARTE)))
    temporaire = dossier + ".tmp"
    shutil.rmtree(temporaire, ignore_errors=True)
    nb = 0
    for nom in archive.namelist():
        morceaux = nom.split("/", 1)   # "basemaps-assets-main/fonts/..." -> "fonts/..."
        if len(morceaux) < 2 or not morceaux[1].startswith(("fonts/", "sprites/")) or nom.endswith("/"):
            continue
        chemin = os.path.join(temporaire, morceaux[1])
        if not os.path.abspath(chemin).startswith(os.path.abspath(temporaire) + os.sep):
            continue   # chemin hors du dossier : ignoré
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "wb") as f:
            f.write(archive.read(nom))
        nb += 1
    shutil.rmtree(dossier, ignore_errors=True)
    os.replace(temporaire, dossier)
    logger.info("Polices et pictogrammes de la carte : %d fichiers dans %s", nb, dossier)
    return nb


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("departement", help="Code département (ex: 38)")
    parser.add_argument("--sortie", default="/data/tuiles.pmtiles")
    parser.add_argument("--source", default=None, help="URL du build PMTiles (def. $PMTILES_SOURCE)")
    parser.add_argument("--maxzoom", type=int, default=None)
    parser.add_argument("--sans-limitrophes", action="store_true")
    parser.add_argument("--forcer", action="store_true", help="Retélécharger même si déjà présent")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Lancé à chaque démarrage du satellite (service one-shot du profil full) : un fond déjà
    # téléchargé est gardé, --forcer pour le régénérer (changement de département, mise à jour).
    if os.path.exists(args.sortie) and not args.forcer:
        logger.info("Fond de carte déjà présent (%s) : conservé (--forcer pour le refaire).", args.sortie)
    else:
        extraire(
            args.departement, args.sortie, source=args.source, maxzoom=args.maxzoom,
            inclure_limitrophes=not args.sans_limitrophes,
        )
    assets = os.path.join(os.path.dirname(os.path.abspath(args.sortie)), "assets")
    if args.forcer or not os.path.isdir(os.path.join(assets, "fonts")):
        telecharger_assets(assets)

# Régénération de data/departements_limitrophes.json (si le contour officiel change, ce qui
# n'arrive normalement jamais pour des limites administratives françaises) :
#   curl -sL -o /tmp/departements.geojson \
#     https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements.geojson
#   pip install shapely
#   python3 -c "
#   import json
#   from shapely.geometry import shape
#   data = json.load(open('/tmp/departements.geojson'))
#   deps, geoms = {}, {}
#   for f in data['features']:
#       c, n = f['properties']['code'], f['properties']['nom']
#       geoms[c] = shape(f['geometry'])
#       deps[c] = {'code': c, 'nom': n, 'bbox': list(geoms[c].bounds), 'limitrophes': []}
#   codes = list(geoms)
#   for i, a in enumerate(codes):
#       for b in codes[i+1:]:
#           if geoms[a].intersects(geoms[b]):
#               inter = geoms[a].intersection(geoms[b])
#               if inter.is_empty or inter.geom_type == 'Point':
#                   continue
#               deps[a]['limitrophes'].append(b); deps[b]['limitrophes'].append(a)
#   for d in deps.values():
#       d['limitrophes'].sort()
#   json.dump(deps, open('data/departements_limitrophes.json', 'w'), ensure_ascii=False, indent=2, sort_keys=True)
#   "
