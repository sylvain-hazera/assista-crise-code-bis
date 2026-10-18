# mosquitto — broker MQTT

Broker MQTT [Eclipse Mosquitto](https://mosquitto.org/) de la pile (conteneur `ac_mqtt`). MQTT
est le protocole de messagerie léger utilisé par les réseaux radio Meshtastic : un appareil ou
un service *publie* des messages sur un *topic*, ceux qui y sont *abonnés* les reçoivent.

## Qui l'utilise

- **Appareils et ponts Meshtastic** configurés pour utiliser ce broker. Un companion
  Meshtastic (`CompagnonMeshtastic`) peut aussi pointer vers un broker tiers (ex. Gaulix,
  `mqtt.gaulix.fr`) : voir [meshtastic-bridge/README.md](../meshtastic-bridge/README.md).
- **Satellites** : chaque Raspberry Pi a son propre broker (voir
  [satellite/README.md](../satellite/README.md)).
- **Monitoring** : `mosquitto-exporter` s'y connecte pour produire les métriques
  (`broker_clients_connected`, messages…).

Le backend Django ne s'y connecte pas directement.

## Deux configurations

| Fichier | Utilisé | Accès |
|---|---|---|
| `config/mosquitto.conf` | production | **anonyme** (en attendant la décision de l'équipe) |
| `config/mosquitto.dev.conf` | dev (`docker-compose.override.yml`) | **authentifié** |

Communs aux deux : un seul listener, MQTT sur le port **1883** (seul port publié),
persistance dans `data/` (volume, non versionné), journaux sur la sortie standard
(`docker compose logs mosquitto`).

### En dev : comptes et mots de passe

`./scripts/init-secrets.sh` génère deux mots de passe dans `.env` ; au démarrage, la commande
du service construit le fichier de mots de passe (`/tmp/passwd`, dans le conteneur) :

| Compte | Mot de passe (`.env`) | Utilisé par |
|---|---|---|
| `exporter` | `MQTT_EXPORTER_PASSWORD` | `mosquitto-exporter` (`MQTT_USER` / `MQTT_PASS`) |
| `dev` | `MQTT_DEV_PASSWORD` | tests manuels, outils, un pont lancé en local |

Changer un mot de passe : le modifier dans `.env`, puis
`docker compose up -d mosquitto mosquitto-exporter`. Ajouter un compte : une ligne
`mosquitto_passwd -b /tmp/passwd <compte> "$$<VARIABLE>"` dans la commande du service
(override) et la variable dans `.env` et `init-secrets.sh`.

Tester :

```bash
P=$(grep '^MQTT_DEV_PASSWORD=' .env | cut -d= -f2-)
docker compose exec mosquitto mosquitto_sub -h localhost -u dev -P "$P" -t '#' -v        # écoute tout
docker compose exec mosquitto mosquitto_pub -h localhost -u dev -P "$P" -t test/hello -m bonjour
docker compose exec mosquitto mosquitto_pub -h localhost -t test -m x                    # refusé : not authorised
```

### En production : passer à l'authentification

Aujourd'hui, n'importe qui peut lire ou publier sur le broker de production (port 1883
publié, accès anonyme). Pour l'authentifier, sans couper les appareils :

1. **Recenser les clients** : appareils et ponts Meshtastic, `mosquitto-exporter` (les
   connexions apparaissent dans `docker compose logs mosquitto`).
2. **Créer un compte par client**, dans un fichier hors du dépôt :
   ```bash
   docker compose exec mosquitto mosquitto_passwd -c /mosquitto/config/passwd exporter   # -c pour le premier seulement
   docker compose exec mosquitto mosquitto_passwd /mosquitto/config/passwd <client>
   ```
   (`mosquitto/config/passwd` est dans `.gitignore`.)
3. **Configurer chaque client** avec son identifiant ; pour l'exporter, `MQTT_USER` et
   `MQTT_PASS` dans `docker-compose.prod.yml`.
4. **Basculer** `config/mosquitto.conf` :
   ```
   allow_anonymous false
   password_file /mosquitto/config/passwd
   ```
   puis `docker compose restart mosquitto` et vérifier dans les journaux que chaque client se
   reconnecte (`u'<compte>'`).

C'est une décision d'équipe : un client oublié perd sa connexion à la bascule.

## WebSocket

Aucun client n'utilise MQTT sur WebSocket (habituellement le port 9001, utile à un navigateur) :
ce port a été retiré. Pour le réactiver, ajouter à la configuration `listener 9001` puis
`protocol websockets`, et publier le port dans les fichiers Compose.
