# mosquitto — broker MQTT

Broker MQTT [Eclipse Mosquitto](https://mosquitto.org/) de la pile (conteneur `ac_mqtt`). MQTT
est le protocole de messagerie léger utilisé par les réseaux radio Meshtastic : un appareil ou
un service *publie* des messages sur un *topic*, ceux qui y sont *abonnés* les reçoivent.

## Qui l'utilise

- **Appareils et ponts Meshtastic** configurés pour utiliser ce broker local. Un companion
  Meshtastic (`CompagnonMeshtastic`) peut aussi pointer vers un broker tiers (ex. Gaulix,
  `mqtt.gaulix.fr`) : voir [meshtastic-bridge/README.md](../meshtastic-bridge/README.md).
- **Satellites** : chaque Raspberry Pi a son propre broker (voir
  [satellite/README.md](../satellite/README.md)).
- **Monitoring** : `mosquitto-exporter` s'y abonne pour produire les métriques
  (`mosquitto_up`, clients connectés, messages).

Le backend Django ne s'y connecte pas directement.

## Configuration (`config/mosquitto.conf`)

| Réglage | Effet |
|---|---|
| `listener 1883` | MQTT sur le port 1883 |
| `allow_anonymous true` | connexion sans identifiant (voir ci-dessous) |
| `persistence true` | messages et abonnements conservés dans `data/` (volume, non versionné) |
| `log_dest stdout` | journaux visibles avec `docker compose logs mosquitto` |

Ports publiés (dev et production) : 1883 et 9001. Seul 1883 est configuré : aucun `listener`
n'écoute sur 9001 (habituellement MQTT sur WebSocket), ce port publié ne mène donc à rien. Soit
ajouter `listener 9001` + `protocol websockets` si un client web en a besoin, soit retirer ce
port des fichiers Compose.

## Accès anonyme : décision en attente

L'accès sans identifiant est conservé pour l'instant : les appareils Meshtastic se connectent
avec des identifiants propres à chaque appareil, et activer l'authentification impose de créer
un compte pour **chaque** client. C'est une décision d'équipe (voir
[DOCUMENTATION.md](../DOCUMENTATION.md), § 10.2). Pour l'activer :

```bash
docker compose exec mosquitto mosquitto_passwd -c /mosquitto/config/passwd <client>   # -c seulement pour le premier
```

puis, dans `mosquitto.conf`, remplacer `allow_anonymous true` par :

```
allow_anonymous false
password_file /mosquitto/config/passwd
```

et `docker compose restart mosquitto`. Le fichier `passwd` n'est jamais commité
(`.gitignore`). Penser à donner un compte à `mosquitto-exporter` et à chaque pont.

## Tester

```bash
# s'abonner à tout (laisser tourner)
docker compose exec mosquitto mosquitto_sub -h localhost -t '#' -v
# publier depuis un autre terminal
docker compose exec mosquitto mosquitto_pub -h localhost -t test/hello -m 'bonjour'
```
