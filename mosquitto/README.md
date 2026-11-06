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
| `config/mosquitto.114.conf` | **.114** (`docker-compose.114.yml`) | **authentifié + liste de droits** |
| `config/mosquitto.dev.conf` | dev (`docker-compose.override.yml`) | **authentifié** |
| `config/mosquitto.conf` | exemple hérité, plus déployé | anonyme — **ne pas utiliser** |

Communs aux deux : un seul listener, MQTT sur le port **1883** (seul port publié),
persistance dans `data/` (volume, non versionné), journaux sur la sortie standard
(`docker compose logs mosquitto`).

### Sur .114 : comptes, droits et exposition

Trois comptes, chacun au minimum nécessaire (`config/acl.114`) :

| Compte | Droits | Utilisé par |
|---|---|---|
| `exporter` | **lecture** de `$SYS/#` seulement | `mosquitto-exporter` (métriques du broker) |
| `pont` | lecture/écriture sur `msh/EU_868/#` | `ac_meshtastic_bridge` |
| `passerelle1` | lecture/écriture sur `msh/EU_868/#` | une passerelle radio (un compte **par site**) |

Vérifié en service : un client anonyme reçoit `Connection Refused: not authorised`, `exporter` ne
peut rien publier sur la racine radio, et `pont` ne peut pas lire `$SYS/`.

**Exposition.** Un seul listener, en clair, publié sur **`172.16.1.114:1883`** et jamais sur
`0.0.0.0` — Docker contourne UFW, un port publié sur toutes les interfaces serait joignable
depuis Internet malgré le pare-feu. Aucune redirection sur la box, aucun listener TLS : seuls les
nœuds radio du même réseau local atteignent le broker. Ouvrir le broker à des passerelles
distantes demanderait un listener 8883 avec certificat, et une décision explicite.

**Mots de passe.** Un fichier de secret par compte dans `~/.config/assista-crise/secrets/`
(`mqtt_*_password.txt`), généré par `scripts/init-secrets.sh` (idempotent : il ne remplace jamais
une valeur existante). Le fichier de mots de passe **haché** est reconstruit à chaque démarrage du
conteneur dans un tmpfs (`command` du service) : il n'est jamais écrit sur disque ni versionné.

**La racine de topic doit correspondre** à `CompagnonMeshtastic.topic_racine`. Ce champ vaut par
défaut `Traitement/msh/EU_868` (racine du réseau Gaulix, broker tiers) : pour un companion qui
pointe vers CE broker, mettre `msh/EU_868`, la seule racine autorisée par `acl.114`. Une racine
qui ne correspond pas coupe le flux **sans message d'erreur**.

#### Ajouter une passerelle radio

1. `create_secret mqtt_<nom>_password 32` dans `scripts/init-secrets.sh`, puis relancer le script
   (`SECRETS_DIR=~/.config/assista-crise/secrets ./scripts/init-secrets.sh`).
2. Le secret dans le bloc `secrets:` de `docker-compose.114.yml`, et dans la liste `secrets:` du
   service `mosquitto`.
3. Une ligne `mosquitto_passwd -b /tmp/passwd <nom> "$$(cat /run/secrets/mqtt_<nom>_password)" &&`
   dans la `command` du service.
4. Un bloc `user <nom>` / `topic readwrite msh/EU_868/#` dans `config/acl.114`.
5. `docker compose -f docker-compose.114.yml up -d --no-deps --force-recreate mosquitto` — une
   **recréation** est nécessaire : la configuration est un montage de *fichier*, et l'éditer en
   crée un nouvel inode que le conteneur en service continue d'ignorer.

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
