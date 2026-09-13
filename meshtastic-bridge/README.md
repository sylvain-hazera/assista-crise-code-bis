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

Le PKC (chiffrement par clé publique/privée pour les DM, firmware 2.5+) **est implémenté**
(`crypto.chiffrer_pkc`/`dechiffrer_pkc` — X25519 + SHA256 + AES-CCM, tag 8 octets, dérivé de
`CryptoEngine::encryptCurve25519`) mais **désactivé à l'ENVOI par défaut** (`ENVOI_PKI_ACTIF=0`,
voir plus bas) — un DM chiffré PSK de canal, lui, est confirmé arriver à destination en
conditions réelles ; un DM PKI envoyé dans la foulée, vers la même personne et le même canal,
ne l'a jamais été (comparaison contrôlée le 13/09). Cause exacte non identifiée : la
construction du paquet a été comparée en détail à une lib externe de référence activement
maintenue (`pdxlocations/mmqtt`) sans trouver de divergence. On reste capable de DÉCHIFFRER un
DM PKI reçu de quelqu'un d'autre (voir `on_message`) — seul l'envoi proactif est mis en retrait.
Chaque `CompagnonMeshtastic` génère quand même sa propre paire de clés X25519 à la création
(clé privée jamais exposée par l'API, voir `CompagnonMeshtasticSerializer`), prêt à réactiver
l'envoi PKI une fois la cause trouvée.

## Recette validée en conditions réelles (13/09)

DM chiffré avec la PSK d'un canal PARTAGÉ (pas PKI) — confirmé reçu à trois reprises, vers deux
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

## ⚠️ Non vérifié sur matériel réel

Le chiffrement PSK par canal a été validé en DÉCHIFFRANT du vrai trafic Gaulix en direct
(NodeInfo/Position de dizaines de nœuds réels décodés correctement) ET en ENVOYANT (voir recette
ci-dessus, confirmée par les destinataires réels). **Le PKC, lui, reste non confirmé en
conditions réelles** malgré un aller-retour local correct (chiffrer avec une clé, déchiffrer
avec l'autre donne le texte d'origine, échange Diffie-Hellman symétrique) — voir plus haut.

Autres limites connues :
- Pas de confirmation de réception automatique : `ENVOYE` signifie seulement "publié sur le
  broker MQTT", jamais "reçu par le destinataire" (contrairement à MeshCore, dont la lib gère un
  accusé de réception radio) — seule une réponse du destinataire le confirme.
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
(`Traitement/msh/EU_868` pour Gaulix — pas `msh/EU_868` comme documenté publiquement, vérifié en sniffant leur broker) sont des champs du `CompagnonMeshtastic` lui-même, pas des variables
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
