# Service-pont MeshCore — phase de test

Connecte assista-crise à UN companion MeshCore réel (série USB, BLE ou TCP), pour valider le
matériel avant de construire la fonctionnalité définitive décrite dans le document de conception
« Maillage Terrain ». Voir `bridge.py` pour les détails et les limites connues.

Le proxy (`ac_meshcore_proxy` sur `.113`) sert plusieurs clients à la fois sur le même
companion réel : Home Assistant, un téléphone de test, le pont `ac_meshcore_bridge` de `.113`
lui-même, **et le pont de `.114` (site démonstration), qui s'y connecte à distance** — partage
volontaire du même companion physique entre les deux sites, pas une fuite de configuration.

## Préparer un companion de test

1. Créer une ligne `CompagnonMeshCore` via le Django admin (`/django-admin/core/compagnonmeshcore/`)
   ou directement via l'API (`POST /api/compagnons-meshcore/`) — noter son `id`.
2. Créer un compte utilisateur dédié pour le pont (pas votre compte personnel) — c'est lui qui
   s'authentifie auprès de l'API pour journaliser/envoyer les messages.

## Variables d'environnement

| Variable | Obligatoire | Exemple |
|---|---|---|
| `DJANGO_API_URL` | oui | `http://backend:8000/api` |
| `DJANGO_BRIDGE_EMAIL` | oui | `pont-meshcore@assista-crise.fr` |
| `DJANGO_BRIDGE_PASSWORD` | oui | — |
| `COMPAGNON_ID` | oui | l'UUID du `CompagnonMeshCore` créé ci-dessus |
| `MESHCORE_CONNEXION_TYPE` | oui | `TCP`, `SERIE` ou `BLE` |
| `MESHCORE_TCP_HOST` / `MESHCORE_TCP_PORT` | si TCP | `192.168.1.50` / `5000` |
| `MESHCORE_SERIE_DEVICE` | si SERIE | `/dev/ttyUSB0` |
| `MESHCORE_BLE_ADRESSE` | si BLE | adresse MAC du companion |
| `POLL_INTERVAL_SECONDS` | non (def. 15) | fréquence d'interrogation des messages à envoyer |
| `LOG_LEVEL` | non (def. INFO) | passer en `DEBUG` pour voir les payloads bruts des événements |

## `proxy.py` — variables d'environnement propres au proxy

En plus de `MESHCORE_TCP_HOST`/`MESHCORE_TCP_PORT` (le companion réel) et `LOG_LEVEL` ci-dessus :

| Variable | Obligatoire | Exemple |
|---|---|---|
| `PROXY_LISTEN_HOST` | non (def. `0.0.0.0`) | interface d'écoute locale |
| `PROXY_LISTEN_PORT` | non (def. `5050`) | port local partagé par plusieurs clients (HA, ce pont, etc.) |
| `RECONNECT_DELAY_SECONDS` | non (def. `5`) | délai avant nouvelle tentative si le companion réel se déconnecte |
| `PROXY_MDNS_ANNONCE` | non (def. `true`) | `false` pour désactiver l'annonce mDNS du proxy sur le LAN |
| `PROXY_MDNS_NOM` | non (def. hostname du conteneur) | nom d'instance mDNS — à fixer explicitement si le hostname Docker change à chaque recréation |

Le proxy s'annonce en mDNS (`_meshcore._tcp.local.`, `properties={"role": "proxy"}`) comme le
ferait un vrai nœud MeshCore sur le LAN — voir `satellite/decouverte_lan.py`. Sur un déploiement
Docker avec un réseau isolé (ex: `assista-back`), l'IP annoncée serait l'IP interne du
conteneur, pas joignable depuis le vrai LAN — c'est pourquoi `ac_meshcore_proxy` tourne
**en `--network host` sur `.113`**, voir ci-dessous.

## Déploiement réel sur `.113` (`ac_meshcore_proxy` + `ac_meshcore_bridge`)

Ces deux conteneurs ne sont **pas gérés par docker-compose** (contrairement au reste du projet)
— recréés manuellement à chaque changement de code, même image `assista-crise-code-bis-meshcore-bridge:latest`
pour les deux, `Cmd` différent :

```bash
# Rebuild après un changement de code (bridge.py, proxy.py ou requirements.txt) :
docker build -t assista-crise-code-bis-meshcore-bridge:latest -f meshcore-bridge/Dockerfile meshcore-bridge/

docker stop ac_meshcore_proxy ac_meshcore_bridge && docker rm ac_meshcore_proxy ac_meshcore_bridge

docker run -d --name ac_meshcore_proxy --network host \
  -e LOG_LEVEL=DEBUG -e MESHCORE_TCP_HOST=172.16.1.58 -e MESHCORE_TCP_PORT=5000 -e PROXY_LISTEN_PORT=5050 \
  --restart unless-stopped \
  assista-crise-code-bis-meshcore-bridge:latest python -u proxy.py

docker run -d --name ac_meshcore_bridge --network assista-back \
  -e MESHCORE_CONNEXION_TYPE=TCP -e MESHCORE_TCP_HOST=172.16.1.113 -e MESHCORE_TCP_PORT=5050 \
  -e LOG_LEVEL=DEBUG \
  -e DJANGO_API_URL=http://backend:8000/api \
  -e DJANGO_BRIDGE_EMAIL=<voir le compte de service existant> \
  -e DJANGO_BRIDGE_PASSWORD=<voir le compte de service existant> \
  -e COMPAGNON_ID=<UUID du CompagnonMeshCore> \
  --restart unless-stopped \
  assista-crise-code-bis-meshcore-bridge:latest python -u bridge.py
```

**`ac_meshcore_proxy` DOIT rester en `--network host`** (pas `assista-back`) pour que l'annonce
mDNS porte une IP réellement joignable sur le LAN (voir plus haut) — `ac_meshcore_bridge`, lui,
reste sur `assista-back` (il doit aussi joindre `backend:8000`) et se connecte au proxy via
l'IP LAN de `.113`, pas via le nom de conteneur Docker (qui ne résout plus une fois le proxy
sorti du réseau `assista-back`).

**Prérequis pare-feu (déjà en place sur `.113`, à ne pas oublier lors d'une réinstallation)** :
`ufw` bloque par défaut tout le trafic entrant, et un conteneur en `--network host` est vu par
le noyau comme un simple process de l'hôte — il lui faut donc une règle **`ALLOW IN`**, pas
`ALLOW FWD` (celle-ci ne vaut que pour la publication de port classique d'un conteneur en
réseau bridge, `docker run -p`, qui traverse le hôte plutôt que de s'y terminer) :
```bash
sudo ufw allow in 5050/tcp
```
Erreur rencontrée le 2026-09-17 : une règle `ALLOW FWD` avait été ajoutée par réflexe (le
schéma habituel pour un port docker publié), ce qui ne débloquait rien puisque le trafic vers ce
port en mode host ne "traverse" pas l'hôte, il s'y termine directement — `ufw status verbose`
doit montrer `5050/tcp ALLOW IN`, pas `FWD`.

## Lancer en local (sans Docker)

```
cd meshcore-bridge
pip install -r requirements.txt
export DJANGO_API_URL=http://localhost:8000/api
export DJANGO_BRIDGE_EMAIL=... DJANGO_BRIDGE_PASSWORD=...
export COMPAGNON_ID=...
export MESHCORE_CONNEXION_TYPE=TCP MESHCORE_TCP_HOST=192.168.1.50 MESHCORE_TCP_PORT=5000
python bridge.py
```

## Non vérifié — à confirmer au premier test matériel

- Noms exacts des champs dans les événements `CONTACT_MSG_RECV` et `SELF_INFO` (voir
  commentaires dans `bridge.py`, `LOG_LEVEL=DEBUG` affiche les payloads bruts pour ajuster).
- Comportement de `send_msg` si le companion ciblé a changé de chemin réseau (délai de
  réparation avant redécouverte, voir le document de conception).
- Comportement en cas de connexion série interrompue (câble débranché) — la reconnexion
  automatique de ce pont n'a été testée que sur le principe, pas en conditions réelles.
