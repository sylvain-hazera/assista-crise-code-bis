# tileserver — serveur de tuiles cartographiques (inutilisé)

> **État (octobre 2026) : ce service tourne mais n'est utilisé par rien.**

## Ce que contient le dossier

| Fichier | Contenu |
|---|---|
| `bordeaux.mbtiles` | tuiles vectorielles des bâtiments de Bordeaux (zoom 10 à 15, issues d'OpenStreetMap) |
| `config.json` | configuration de [TileServer GL](https://github.com/maptiler/tileserver-gl) servant ce fichier |

## Constat

- Le service `tileserver` (`maptiler/tileserver-gl`, conteneur `ac_maps`) est déclaré dans
  `docker-compose.yml`, mais **ce dossier n'y est pas monté** : le conteneur télécharge et sert
  le jeu d'exemple par défaut de l'image (Zurich), pas `bordeaux.mbtiles`.
- Le frontend affiche ses fonds de carte depuis un style OpenStreetMap externe (voir
  `frontend/src/app/shared/components/common/map/map.component.ts`) ; aucune route Nginx ne
  mène au tileserver.
- En production, il n'a aucun port publié.

## Que décider

- **Le supprimer** (service Compose, dépendance `depends_on` du proxy, ce dossier) : économise
  des ressources et un téléchargement à chaque démarrage.
- **Ou l'utiliser vraiment**, par exemple pour des cartes **hors ligne** sur les satellites :
  monter ce dossier (`./tileserver:/data`), ajouter une route Nginx, et pointer le style
  MapLibre du frontend vers lui.

En dev, l'interface du tileserver est visible sur http://localhost:8080.
