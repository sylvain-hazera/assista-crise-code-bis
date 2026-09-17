# Service-pont MeshCore — phase de test

Connecte assista-crise à UN companion MeshCore réel (série USB, BLE ou TCP), pour valider le
matériel avant de construire la fonctionnalité définitive décrite dans le document de conception
« Maillage Terrain ». Voir `bridge.py` pour les détails et les limites connues.

**Ce service n'est volontairement pas déployé sur .114** — il vit sur la branche git
`feature/meshcore-poc`, pas sur `main`, tant que le matériel n'a pas été validé.

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
ferait un vrai nœud MeshCore sur le LAN — voir `satellite/decouverte_lan.py`. **Sur un
déploiement Docker avec un réseau isolé (ex: `assista-back`), l'IP annoncée est l'IP interne du
conteneur, pas joignable depuis le vrai LAN** — le conteneur doit tourner en `--network host`
(ou équivalent) pour que cette annonce serve à quelque chose en dehors de Docker lui-même.

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
