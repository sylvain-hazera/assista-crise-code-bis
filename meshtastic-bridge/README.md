# Service-pont Meshtastic — phase de test

Connecte assista-crise au réseau Meshtastic via un broker MQTT tiers (ex: Gaulix,
`mqtt.gaulix.fr`), en se comportant comme un **nœud Meshtastic purement logiciel** — aucun
matériel radio, aucune connexion série/BLE, contrairement à `meshcore-bridge/`. Voir `bridge.py`
et `crypto.py` pour les détails.

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

Le PKC (chiffrement par clé publique/privée pour les DM, firmware 2.5+) **n'est pas implémenté**
— seuls les DM "classiques" (chiffrés avec la PSK d'un canal partagé, adressés à un `node_num`
précis) et les messages de canal sont supportés pour l'instant.

## ⚠️ Non vérifié sur matériel réel

Le chiffrement a été testé en aller-retour (chiffrer puis déchiffrer avec la même clé donne bien
le texte d'origine) mais **jamais confirmé contre un vrai appareil Meshtastic** — un test
autoconsistant ne prouve pas l'interopérabilité réelle (un décalage d'ordre d'octets, par
exemple, donnerait quand même un aller-retour correct tout en étant incompréhensible pour un
vrai nœud). Premier test à faire avec un message très court, vers un nœud que vous contrôlez et
pouvez inspecter directement (voir les logs de l'appareil ou l'app companion), avant toute
utilisation réelle.

Autres limites connues :
- Pas de confirmation de réception : `ENVOYE` signifie seulement "publié sur le broker MQTT",
  jamais "reçu par le destinataire" (contrairement à MeshCore, dont la lib gère un accusé de
  réception radio) — sauf si le destinataire répond lui-même.
- Aucune notion de "route la plus proche" : ce pont ne fait que relayer via UN broker MQTT fixe,
  pas de sélection de passerelle par proximité géographique (voir discussion architecture plus
  large, hors scope de ce pont).

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
| `LOG_LEVEL` | non (def. INFO) | `DEBUG` pour plus de détails |

L'adresse du broker (`mqtt.gaulix.fr`, port 1883 par défaut) et la racine de topic
(`msh/EU_868`) sont des champs du `CompagnonMeshtastic` lui-même, pas des variables
d'environnement — récupérés via l'API au démarrage.

## Lancer en local (sans Docker)

```
cd meshtastic-bridge
pip install -r requirements.txt
export DJANGO_API_URL=http://localhost:8000/api
export DJANGO_BRIDGE_EMAIL=... DJANGO_BRIDGE_PASSWORD=...
export COMPAGNON_ID=...
python bridge.py
```
