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
import json
import logging
import os
import subprocess

logger = logging.getLogger("telecharger-tuiles")

DATA_DEPARTEMENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "departements_limitrophes.json")

# Se périme (un build daté) — voir https://maps.protomaps.com/builds pour l'URL du jour au
# moment de l'installation d'un satellite. Pas de "latest" stable côté Protomaps à ce jour.
PMTILES_SOURCE_DEFAUT = os.environ.get("PMTILES_SOURCE")


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
    source = source or PMTILES_SOURCE_DEFAUT
    if not source:
        raise RuntimeError(
            "Aucune source PMTiles fournie (argument --source ou variable PMTILES_SOURCE) — "
            "voir https://maps.protomaps.com/builds pour l'URL du build du jour."
        )
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("departement", help="Code département (ex: 38)")
    parser.add_argument("--sortie", default="/data/tuiles.pmtiles")
    parser.add_argument("--source", default=None, help="URL du build PMTiles (def. $PMTILES_SOURCE)")
    parser.add_argument("--maxzoom", type=int, default=None)
    parser.add_argument("--sans-limitrophes", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    extraire(
        args.departement, args.sortie, source=args.source, maxzoom=args.maxzoom,
        inclure_limitrophes=not args.sans_limitrophes,
    )

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
