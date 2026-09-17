# Satellite — Raspberry Pi déployé sur site

Boîtiers décrits dans le cadrage "Chantier B" du plan de développement : pont/proxy
MeshCore local et, pour le profil Full, une instance assista-crise complète utilisable
même sans internet. **Décision du 2026-09-17 : Docker + docker-compose sur Raspberry Pi
OS standard, pas une image disque pré-construite** — réutilise directement les images
déjà éprouvées du reste du projet.

## Démarrage rapide

```bash
cp .env.example .env    # compléter : identifiants du compte de service, device série, etc.
docker compose --profile gw up -d      # pont + proxy MeshCore + détecteur de connectivité
# ou
docker compose --profile full up -d    # gw + assista-crise complet + tuiles offline
```

Le compte de service (`SATELLITE_EMAIL`/`SATELLITE_PASSWORD`) s'obtient via la vue
**Satellites** côté central (génération de jeton → le satellite s'enrôle → un
administrateur valide → identifiants affichés **une seule fois**) — voir
`backend/core/views.py:SatelliteViewSet`.

## Ce que chaque service fait

| Service | Profil | Rôle |
|---|---|---|
| `meshcore-proxy` | gw, full | Détient la connexion réelle au nœud MeshCore (USB/série ou TCP), s'annonce en mDNS sur le LAN — voir `meshcore-bridge/proxy.py`. |
| `meshcore-bridge` | gw, full | Relaie les messages entre le proxy et `assista-crise.fr` (ou le central configuré). |
| `etat-connectivite` | gw, full | Vérifie périodiquement si le central répond, écrit l'état dans un volume partagé (`etat_connectivite.py`) — source de vérité unique pour tout futur composant qui en a besoin (bannière, écran de statut). |
| `db`, `mosquitto`, `backend`, `frontend` | full | Instance assista-crise locale, identique au déploiement central. |
| `telecharger-tuiles` | full | Conteneur one-shot : télécharge les tuiles du département + limitrophes (`telecharger_tuiles.py`). |
| `tileserver` | full | Sert les tuiles téléchargées — même image que le central (`maptiler/tileserver-gl`). |

**Manque à ce jour : Meshtastic.** `meshtastic-bridge/` ne sait parler qu'à un broker MQTT
tiers (Gaulix) — voir son README, « aucun matériel radio, aucune connexion série/BLE ». Pas de
service Meshtastic ici tant qu'un nœud ne peut pas être branché en USB/série comme MeshCore ;
ajouter ce support (la lib officielle `meshtastic` le permet nativement) est un préalable non
fait dans ce chantier.

## Nœuds branchés en USB/série

`MESHCORE_CONNEXION_TYPE=SERIE` + `MESHCORE_SERIE_DEVICE=/dev/ttyUSB0` (ou `/dev/ttyACM0`,
voir `ls /dev/tty*` une fois le nœud branché) — `meshcore-proxy` détient alors directement la
connexion série, exactement comme il détenait une connexion TCP sur `.113`. Support ajouté le
2026-09-17 à `meshcore-bridge/proxy.py` (`serial_asyncio_fast`, même bibliothèque que
`bridge.py` utilise déjà en interne via la lib `meshcore`).

## `decouverte_lan.py`

Combine deux méthodes pour repérer les nœuds MeshCore/Meshtastic sur le LAN d'un satellite à
l'installation (utile pour un nœud resté en TCP plutôt que branché en série) :
- **mDNS** (zeroconf) — `_meshcore._tcp.local.` est confirmé trouvable pour un
  `meshcore-proxy` (il s'annonce lui-même, `role=proxy` dans les properties pour le
  distinguer d'un vrai nœud) ; pas confirmé pour un firmware de nœud réel (noms de service
  hypothétiques, voir `SERVICE_TYPES_MDNS`).
- **Scan TCP du port 5000** (port MeshCore par défaut) sur le sous-réseau local —
  protocole-agnostique, indépendant de toute annonce.

Ne fait pas le handshake protocolaire de confirmation — réutilisable depuis
`MeshLocalDetecterView` côté Django (`_detecter_meshcore_local`/`_detecter_meshtastic_local`).

```bash
python3 decouverte_lan.py
```

## `telecharger_tuiles.py`

Département du satellite + départements limitrophes (pas juste sa commune), découpés depuis
la base cartographique globale Protomaps (PMTiles) via l'outil `pmtiles extract` — ne
télécharge que la zone demandée (requêtes HTTP par plage d'octets), jamais le fichier planète
complet (~120 Go). Adjacence pré-calculée dans `data/departements_limitrophes.json`, générée
une fois depuis des géométries officielles (voir le commentaire en bas de
`telecharger_tuiles.py` pour la régénérer), vérifiée par intersection géométrique réelle
(shapely), pas une liste tapée à la main. Métropole uniquement (96 départements).

```bash
# PMTILES_SOURCE : voir https://maps.protomaps.com/builds pour l'URL du build du jour (se
# périme, pas de "latest" stable).
python3 telecharger_tuiles.py 38 --sortie /data/tuiles.pmtiles --source https://build.protomaps.com/YYYYMMDD.pmtiles
```

## `etat_connectivite.py`

Vérifie périodiquement si `assista-crise.fr` (ou `$CENTRAL_URL`) répond, écrit l'état
(`en_ligne`, `depuis`, `derniere_verification`) dans un fichier JSON — écriture atomique
(fichier temporaire puis renommage), jamais un lecteur concurrent qui voit un JSON tronqué.
Un seul processus vérifie, tout composant qui a besoin de savoir si le central est joignable
lit ce fichier plutôt que de refaire sa propre requête réseau.

```bash
python3 etat_connectivite.py
cat /var/run/satellite/etat_connectivite.json
```

## Installer les dépendances et lancer les tests

```bash
pip install -r requirements-dev.txt
pytest
```

Aucun matériel MeshCore/Meshtastic réel requis, ni vraie connexion au central, ni vrai
téléchargement de tuiles : le scan de port est vérifié contre un serveur TCP local factice, la
découverte mDNS sur son repli (zeroconf absent), `etat_connectivite` avec un transport httpx
factice (`httpx.MockTransport`), et `telecharger_tuiles.extraire()` avec `subprocess.run`
mocké — seule la fonction `bbox_zone` est vérifiée contre le vrai fichier de données (généré
depuis des géométries réelles, pas un mock).

Les deux Dockerfiles (`Dockerfile.tuiles`, `Dockerfile.etat`) et `docker-compose.yml` ont été
buildés et testés en conditions quasi réelles le 2026-09-17 (build réussi, `pmtiles version`
exécuté, extraction de tuiles lancée pour de vrai contre une fausse URL — échoue proprement
avec un message clair, pas un bug côté code) — mais jamais encore sur un vrai Raspberry Pi.
