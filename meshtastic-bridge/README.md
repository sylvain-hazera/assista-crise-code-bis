# Service-pont Meshtastic — phase de test

Connecte assista-crise au réseau Meshtastic soit via un broker MQTT tiers (ex: Gaulix,
`mqtt.gaulix.fr`, en se comportant comme un **nœud Meshtastic purement logiciel**, sans
matériel radio), soit en pilotant un **vrai appareil** connecté en TCP local ou en série/USB
(`CompagnonMeshtastic.connexion_type` = `TCP`/`SERIE`, voir plus bas) — dans ce dernier cas,
c'est le firmware de l'appareil qui gère lui-même le chiffrement, comme `meshcore-bridge/`.
Voir `bridge.py` et `crypto.py` (mode MQTT uniquement) pour les détails.

**Ce service n'est volontairement pas déployé sur .114** — il vit sur la branche git
`feature/meshtastic-poc`, séparée de `feature/meshcore-poc` (deux protocoles distincts), tant
que ni le chiffrement ni le comportement réseau n'ont été validés contre du vrai matériel.

## Ce qui est différent de meshcore-bridge

La lib officielle `meshtastic` (PyPI) ne fait que piloter un vrai appareil connecté en
série/BLE/TCP — l'appareil chiffre/déchiffre lui-même en firmware, la lib Python ne voit jamais
que des paquets déjà en clair. Comme ce pont n'a pas d'appareil du tout, **le chiffrement AES-CTR
par canal est réimplémenté à la main** dans `crypto.py`, à partir du code source du firmware
officiel (`github.com/meshtastic/firmware`, `CryptoEngine.cpp` et `Channels.cpp`) :

- Nonce = 8 octets packet_id (little-endian) + 4 octets node_num émetteur (little-endian) + 4
  octets à zéro.
- AES-CTR, clé 16 ou 32 octets selon la PSK du canal (raccourcis d'index 0x01-0x0A pris en
  charge, voir `crypto.deriver_cle`).
- Hash de canal (`MeshPacket.channel`) = XOR du nom ^ XOR de la clé résolue.

Le PKC (chiffrement par clé publique/privée pour les DM, firmware 2.5+) **est implémenté**
(`crypto.chiffrer_pkc`/`dechiffrer_pkc` — X25519 + SHA256 + AES-CCM, tag 8 octets, dérivé de
`CryptoEngine::encryptCurve25519`) mais **désactivé à l'ENVOI par défaut** (`ENVOI_PKI_ACTIF=0`,
voir plus bas). On reste capable de DÉCHIFFRER un DM PKI reçu de quelqu'un d'autre (voir
`on_message`) — seul l'envoi proactif est mis en retrait.
Chaque `CompagnonMeshtastic` génère quand même sa propre paire de clés X25519 à la création
(clé privée jamais exposée par l'API, voir `CompagnonMeshtasticSerializer`).

### Pourquoi le chiffré ne marche pas via Gaulix (conclusion du 13/09)

Deux vrais bugs identifiés et corrigés côté pont en lisant le firmware officiel
(`github.com/meshtastic/firmware`, tag exact du firmware testé — pas seulement `master`) :

- **DM classique (PSK de canal) rejeté par le firmware récent** : `Router.cpp::perhapsDecode`
  refuse explicitement un texte adressé (`to=`) déchiffré via la PSK *partagée* d'un canal
  ("Rejecting legacy DM") — mesure anti-usurpation, un vrai DM privé nécessite le PKI. C'est
  pour ça qu'un DM doit rester en clair (`decoded`) pour être accepté : ce filtre ne s'applique
  qu'à la branche `encrypted`.
- **PKI jamais tenté côté récepteur** : `Router.cpp::perhapsDecode` ne tente le déchiffrement
  PKI que si `packet.channel == 0`, et `MQTT.cpp::onSend` publie/attend le topic/`channel_id`
  littéral `"PKI"`, pas un nom de canal. Le pont laissait `channel` au hash du canal classique
  et publiait sous le nom du canal — corrigé (`paquet.channel = 0`, `channel_id="PKI"` dans
  `boucle_envoi_dm`).

Malgré ces deux corrections, **aucun contenu chiffré (PSK classique ou PKI, DM ou broadcast,
canal custom ou canal `Fr_Balise` d'origine jamais modifié) n'a pu être confirmé reçu par un
vrai appareil (SH2) via le broker Gaulix**, alors que le calcul de hash de canal a été revérifié
byte-à-byte contre la config live de l'appareil et contre le tag de firmware exact qu'il fait
tourner (2.6.11.60ec05e) — tout correspond sur le papier. Le clair (`decoded`), lui, arrive
systématiquement, DM comme broadcast. Conclusion retenue : **Gaulix (le broker MQTT, ou un
composant intermédiaire) bloque ou filtre le trafic Meshtastic chiffré** — sans accès aux logs
internes de l'appareil (pas de console série, seulement l'API TCP), impossible d'aller plus
loin dans ce diagnostic. Le correctif PKI reste dans le code (correct et réutilisable si un jour
testé sur un autre relais MQTT), mais **le clair reste la seule voie confirmée fonctionnelle sur
Gaulix**, DM comme canal.

## Connexion directe à un vrai appareil (TCP ou série) — pas de crypto.py ici

Tout ce qui précède (chiffrement fait maison, PKI, hash de canal) ne concerne QUE le mode
MQTT (`connexion_type=MQTT`, la valeur par défaut). Un `CompagnonMeshtastic` peut aussi piloter
un vrai appareil directement, comme `meshcore-bridge/` le fait pour MeshCore — le firmware gère
alors lui-même le chiffrement, `crypto.py` n'est jamais appelé :

- `connexion_type=TCP` : appareil sur le LAN, API TCP native du firmware (`tcp_host`/`tcp_port`,
  port 4403 par défaut) — `meshtastic.tcp_interface.TCPInterface`.
- `connexion_type=SERIE` : appareil branché en USB directement sur l'hôte du pont —
  `serie_device` (ex: `/dev/ttyUSB0`) — `meshtastic.serial_interface.SerialInterface`. Cas
  d'un satellite Raspberry Pi, voir `satellite/docker-compose.yml`. Ajouté le 2026-09-17, en
  miroir exact du mode TCP (voir `_executer_compagnon_interface_locale` dans `bridge.py`, qui
  factorise les deux — seule la construction de l'interface diffère).

Les deux modes sont limités en v1 aux DM (envoi/réception) et à la réception de messages de
canal — pas d'envoi sur un canal précis : les canaux d'un vrai appareil sont déjà configurés
dessus (PSK gérées par son propre firmware), pas par `CanalMeshtastic` (pensé pour le mode MQTT
logiciel). `node_num` reste néanmoins requis à la création du `CompagnonMeshtastic` même dans
ces deux modes (mis à jour automatiquement dès la connexion à la vraie valeur de l'appareil,
voir `on_connection` dans `bridge.py`) — la contrainte `unique=True` du modèle l'exige.

**Non testé sur du vrai matériel série à ce jour** (contrairement au mode TCP, validé le
13/09 — voir plus bas) : la construction `SerialInterface(devPath=...)` et le dispatch sont
vérifiés par un test isolé (mock), pas encore contre un appareil réel branché en USB.

## `admin_meshtastic.py` — administration à distance des nœuds (06/11/2026)

Lire et modifier la configuration d'un nœud par la radio (`ADMIN_APP`, protobuf
`AdminMessage`). **Mode TCP ou série uniquement** : c'est le firmware de l'appareil qui chiffre le
message d'administration, un companion MQTT n'a pas d'appareil. Les tâches viennent de Django
(`TacheAdminMeshtastic`), sont réclamées par `boucle_taches_admin` toutes les 20 s et exécutées
une par une dans un thread (`asyncio.to_thread`) : la lib officielle est bloquante et une
opération attend une réponse radio qui met de quelques secondes à plusieurs minutes.

Trois choses lues dans le firmware (`AdminModule::handleReceivedProtobuf`), que la documentation
Meshtastic ne dit pas et dont tout dépend :

1. Un message venant d'un autre nœud n'est accepté que s'il est `pki_encrypted` **et** que la clé
   publique de l'émetteur figure dans l'une des **trois** fentes `config.security.admin_key` de la
   cible. Sinon : `ADMIN_PUBLIC_KEY_UNAUTHORIZED`. La clé qui compte est celle de l'**appareil**
   passerelle (`iface.getPublicKey()`, rapportée à Django par `rapporter-cle-publique`), pas
   l'identité logicielle X25519 du companion.
2. Il existe une voie historique — canal nommé « admin » avec `admin_channel_enabled`, sans
   aucune vérification de clé. **On ne l'utilise jamais** : elle donne l'administration de tous
   les nœuds à quiconque possède la PSK de ce canal. D'où `channelIndex=0` forcé, au lieu du
   `localNode._getAdminChannelIndex()` de la lib officielle, qui basculerait dessus dès qu'un
   canal « admin » existe sur la passerelle.
3. Les lectures sont dispensées de clé de session, les écritures l'exigent. La clé est un jeton
   de 8 octets glissé dans toute réponse de lecture, valable 300 s et **renouvelé dès qu'une
   réponse est construite plus de 150 s après la précédente**. Le module construit donc son
   message d'écriture d'abord (ce qui, pour une puissance, relit la configuration et rapporte une
   clé au passage), puis écrit ; sur `ADMIN_BAD_SESSION_KEY` il oublie la clé, relit et réessaie
   **une** fois.

La passerelle elle-même (cible vide) est le seul cas qui ne demande aucun provisionnement : le
firmware traite le message comme venant du téléphone (`mp.from == 0`). C'est par là qu'il faut
commencer pour vérifier la chaîne.

`set_config.lora` **remplace tout le bloc** côté firmware : définir la puissance relit la
configuration et la renvoie entière avec le seul `tx_power` modifié. N'envoyer que `tx_power`
effacerait la région, et un nœud sans région ne transmet plus du tout. Le firmware redémarre de
lui-même après ce changement.

Tests : `test_admin_meshtastic.py`, en `unittest` (pas de pytest dans l'image).

```
docker run --rm -v "$PWD/meshtastic-bridge":/src -w /src \
  --entrypoint python assista-crise-meshtastic-bridge:prod -m unittest -v test_admin_meshtastic
```

**Jamais essayé sur du matériel réel** : tout est vérifié contre un faux appareil et contre le
code du firmware.

## Recette validée en conditions réelles (13/09)

DM **en clair** (`Fr_BlaBla`, canal sans PSK — pas de chiffrement du tout, voir plus haut
pourquoi le chiffré ne passe pas via Gaulix) — confirmé reçu à trois reprises, vers deux
destinataires distincts, dont un à plusieurs centaines de km (département 42) nécessitant un
relais LoRa intermédiaire :
- `hop_limit` ET `hop_start` réglés à la même valeur (7, le maximum du protocole) — **manquer
  `hop_start` a été le premier bug trouvé** : sans lui (valeur protobuf par défaut 0), l'état
  `hop_limit > hop_start` est incohérent et un relais LoRa intermédiaire peut l'ignorer
  silencieusement (un destinataire reçu directement, sans relais, n'y est pas sensible — d'où
  des premiers tests trompeurs, réussis uniquement à courte distance).
- Canal marqué `principal` (topic/hash de canal résolus automatiquement si aucun n'est précisé
  à la création du DM) : `Fr_BlaBla`, sans PSK — c'est la config par défaut de ce pont
  désormais, aucun paramètre à passer pour la reproduire.

## ⚠️ Le chiffré ne fonctionne pas via Gaulix (ni PSK de canal, ni PKI)

Voir la section plus haut « Pourquoi le chiffré ne marche pas via Gaulix » pour le détail :
déchiffrer du trafic chiffré déjà présent sur Gaulix fonctionne très bien (NodeInfo/Position de
dizaines de nœuds réels décodés correctement), mais **envoyer** du contenu chiffré (PSK de
canal ou PKI, DM ou broadcast) et le faire confirmer reçu par un vrai appareil n'a jamais
fonctionné, y compris sur le canal `Fr_Balise` d'origine avec sa PSK par défaut. Le clair est la
seule voie confirmée de bout en bout.

Autres limites connues :
- Pas de confirmation de réception automatique : `ENVOYE` signifie seulement "publié sur le
  broker MQTT", jamais "reçu par le destinataire" (contrairement à MeshCore, dont la lib gère un
  accusé de réception radio) — seule une réponse du destinataire le confirme.
- Aucune notion de "route la plus proche" : ce pont ne fait que relayer via UN broker MQTT fixe,
  pas de sélection de passerelle par proximité géographique (voir discussion architecture plus
  large, hors scope de ce pont).

## `proxy.py` — partager un nœud WiFi entre plusieurs clients (téléphone, Home Assistant, assista-crise)

Contrairement à un companion MeshCore série (exclusif à une seule connexion), un vrai nœud
Meshtastic WiFi accepte déjà nativement plusieurs connexions TCP simultanées sur son API (port
`4403` par défaut) — `proxy.py` n'est donc pas nécessaire pour "débloquer" un partage autrement
impossible. Il sert à donner à tous les clients une seule adresse stable à connaître (celle du
proxy, pas celle du nœud) et à amortir une coupure réseau sans que chaque client gère sa propre
reconnexion — même image Docker que `bridge.py`
(`assista-crise-code-bis-meshtastic-bridge:latest`), `Cmd` différent, en miroir exact de
`meshcore-bridge/proxy.py`/`ac_meshcore_proxy`.

Le point délicat, propre au protocole Meshtastic (voir la docstring de `proxy.py` pour le
détail) : la rafale de configuration initiale (`ToRadio.want_config_id` /
`FromRadio.config_complete_id`) doit être livrée UNIQUEMENT au client qui l'a demandée, pas
diffusée à tous — sans quoi chaque client recevrait le nodedb complet à chaque connexion d'un
autre. Le proxy s'en charge en interceptant ces trames, le reste du trafic est diffusé à tous les
clients connectés, exactement comme le ferait le firmware lui-même en multi-client.

⚠️ **Non testé contre un vrai nœud WiFi à ce jour** — écrit à partir du protocole documenté dans
le code source de la lib `meshtastic` déjà vendue dans ce projet (voir plus haut, mode TCP validé
le 13/09), mais aucun nœud WiFi Meshtastic n'est configuré dans cet environnement pour vérifier
bout en bout la logique de rafale de configuration. À valider avec un vrai appareil avant un
usage en cellule de crise réelle.

```bash
docker build -t assista-crise-code-bis-meshtastic-bridge:latest -f meshtastic-bridge/Dockerfile meshtastic-bridge/

docker run -d --name ac_meshtastic_proxy \
  -e MESHTASTIC_TCP_HOST=<IP du nœud réel> -e MESHTASTIC_TCP_PORT=4403 \
  -e PROXY_LISTEN_PORT=4403 -e LOG_LEVEL=DEBUG \
  --restart unless-stopped \
  assista-crise-code-bis-meshtastic-bridge:latest python -u proxy.py
```

Puis reconfigurer CHAQUE client (app officielle, intégration Home Assistant, le `CompagnonMeshtastic`
d'assista-crise en mode TCP — `tcp_host`/`tcp_port` pointant sur l'IP/port de CE proxy, pas sur le
nœud réel directement) — sinon rien n'est mutualisé.

## Préparer un companion de test

1. Créer une ligne `CompagnonMeshtastic` via l'API (`POST /api/compagnons-meshtastic/`) ou la
   page admin dédiée — choisir un `node_num` (32 bits) qui ne collisionne pas avec un vrai
   appareil déjà connu (un nombre aléatoire suffit, ce n'est pas un identifiant de matériel).
2. Créer au moins un `CanalMeshtastic` dont le `nom` correspond EXACTEMENT à un canal déjà
   configuré sur les appareils cibles (ex: `Fr_Balise`), avec sa PSK réelle en hex.
3. Créer un compte utilisateur dédié pour le pont (pas un compte personnel).

## Variables d'environnement

| Variable | Obligatoire | Exemple |
|---|---|---|
| `DJANGO_API_URL` | oui | `http://backend:8000/api` |
| `DJANGO_BRIDGE_EMAIL` | oui | `pont-meshtastic@assista-crise.fr` |
| `DJANGO_BRIDGE_PASSWORD` | oui | — |
| `COMPAGNON_ID` | oui | l'UUID du `CompagnonMeshtastic` créé ci-dessus |
| `POLL_INTERVAL_SECONDS` | non (def. 15) | fréquence d'interrogation des messages à envoyer |
| `CANAUX_REFRESH_INTERVAL_SECONDS` | non (def. 60) | fréquence de rafraîchissement des clés de canal |
| `CONTACTS_FLUSH_INTERVAL_SECONDS` | non (def. 30) | fréquence d'envoi groupé des nœuds découverts |
| `LIAISONS_FLUSH_INTERVAL_SECONDS` | non (def. 60) | fréquence d'envoi groupé des liaisons observées |
| `TACHES_ADMIN_POLL_INTERVAL_SECONDS` | non (def. 20) | fréquence de relève des tâches d'administration |
| `LOG_LEVEL` | non (def. INFO) | `DEBUG` pour plus de détails |

L'adresse du broker (`mqtt.gaulix.fr`, port 1883 par défaut) et la racine de topic
(`Traitement/msh/EU_868` pour Gaulix — pas `msh/EU_868` comme documenté publiquement, vérifié en sniffant leur broker) sont des champs du `CompagnonMeshtastic` lui-même, pas des variables
d'environnement — récupérés via l'API au démarrage.

**Bascule vers l'assista-crise local (satellite, profil Full)** : `LOCAL_API_URL`/
`LOCAL_BRIDGE_EMAIL`/`LOCAL_BRIDGE_PASSWORD`/`FICHIER_ETAT_CONNECTIVITE`, ajoutés le 2026-09-17
— même mécanisme que `meshcore-bridge/README.md` (voir cette section pour le détail et la
limite connue sur la réconciliation UUID), pas dupliqué ici.

## Lancer en local (sans Docker)

```
cd meshtastic-bridge
pip install -r requirements.txt
export DJANGO_API_URL=http://localhost:8000/api
export DJANGO_BRIDGE_EMAIL=... DJANGO_BRIDGE_PASSWORD=...
export COMPAGNON_ID=...
python bridge.py
```
