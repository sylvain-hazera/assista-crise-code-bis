# matrix-bridge — pont Matrix ↔ Assista-Crise

Service qui relie l'application à un serveur Matrix (Synapse) pour la messagerie des équipes
dans Element. Vue d'ensemble de l'intégration Matrix (SSO, salons) :
[DOCUMENTATION.md](../DOCUMENTATION.md), § 7.1.

> **Statut** : non vérifié sur un vrai client Element. La forme des événements de position
> live (MSC3489) vient de la spécification ; les événements bruts sont journalisés avec
> `LOG_LEVEL=DEBUG` pour ajuster si un nom de champ diffère en pratique.

## Ce que fait le pont

En boucle, sans exposer de port :

1. **Salons d'équipe** : lit dans l'API les équipes pour lesquelles un salon Matrix a été
   demandé (`SalonMatrixEquipe`), crée le salon privé s'il n'existe pas encore, puis
   **resynchronise ses membres** sur ceux de l'équipe (invitation des nouveaux, retrait des
   anciens ; jamais de retrait dans le salon de la cellule de crise).
2. **Salons d'institution** : deux salons par institution, `PERMANENTS` (personnel) et
   `BENEVOLES` (membres des équipes actives), recalculés en continu.
3. **Sujet du salon** : y affiche le régulateur de l'équipe et ses coordonnées.
4. **Positions live** : relaie les balises de position Element (`m.beacon_info` /
   `m.beacon`) vers l'API, qui les enregistre pour que les régulateurs suivent leurs équipes
   sur la carte.

Les identifiants Matrix des utilisateurs sont calculés par Django (`core/matrix.py`) et fournis
par l'API : le pont ne recalcule jamais la correspondance compte ↔ Matrix.

## Authentification

- **Vers Django** : compte de service dédié, JWT (même principe que les ponts radio).
- **Vers Synapse** : un compte « bot » administrateur, créé une fois par enregistrement HMAC
  (`registration_shared_secret` de Synapse). Les comptes humains n'ont pas de mot de passe
  Matrix (SSO uniquement), le bot ne peut donc pas se reconnecter par `/login` : son jeton est
  enregistré dans `TOKEN_FILE` et **le dossier `/data` doit être un volume persistant**.

## Configuration

| Variable | Obligatoire | Rôle |
|---|---|---|
| `DJANGO_API_URL` | oui | URL de l'API, ex. `http://backend:8000/api` |
| `DJANGO_BRIDGE_EMAIL`, `DJANGO_BRIDGE_PASSWORD` | oui | compte de service Assista-Crise |
| `SYNAPSE_SERVER_NAME` | oui | nom du serveur Matrix, identique à `MATRIX_SERVER_NAME` du backend |
| `SYNAPSE_REGISTRATION_SHARED_SECRET` | oui | secret d'enregistrement de Synapse |
| `SYNAPSE_URL` | non | `http://synapse:8008` par défaut |
| `SYNAPSE_BOT_LOCALPART`, `SYNAPSE_BOT_PASSWORD` | non | nom et mot de passe du bot (`pont-matrix` ; mot de passe = secret par défaut) |
| `TOKEN_FILE`, `SYNC_STATE_FILE` | non | jeton du bot et position de synchronisation (dans `/data`) |
| `SALONS_POLL_INTERVAL_SECONDS` | non | intervalle de resynchronisation des salons (30) |
| `SYNC_TIMEOUT_MS` | non | durée d'attente d'un `/sync` Synapse (30000) |
| `LOG_LEVEL` | non | `INFO` par défaut, `DEBUG` pour voir les événements bruts |

## Déploiement

Le pont ne fait pas partie des fichiers Compose du dépôt : en production, il est lancé avec
Synapse, MAS et Element sur la machine `.114`. Image : `Dockerfile` de ce dossier
(Python + `httpx`, seule dépendance).

```bash
docker build -t assista-crise/matrix-bridge matrix-bridge/
docker run -d --name ac_matrix_bridge --network <réseau de backend et synapse> \
  -v matrix_bridge_data:/data --env-file <fichier hors dépôt> assista-crise/matrix-bridge
```

## Pièges connus

- Ne jamais pré-créer un compte Matrix humain via l'API d'administration de Synapse : le
  premier SSO échouerait (« Localpart not available »).
- `SYNAPSE_SERVER_NAME` différent de `MATRIX_SERVER_NAME` côté backend : les identifiants
  calculés ne correspondent à aucun compte, personne n'est invité.
- Perte du volume `/data` : le bot ne peut plus se reconnecter ; le recréer exige de
  réenregistrer un compte bot.
