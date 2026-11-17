# Satellite — Raspberry Pi déployé sur site

Boîtiers décrits dans le cadrage "Chantier B" du plan de développement : pont/proxy
MeshCore local et, pour le profil Full, une instance assista-crise complète utilisable
même sans internet. **Décision du 2026-09-17 : Docker + docker-compose sur Raspberry Pi
OS standard, pas une image disque pré-construite** — réutilise directement les images
déjà éprouvées du reste du projet.

## Démarrage rapide (20/10/2026) — une commande, aucune question

### 1. Sur le central (administrateur de l'institution)

Page **Satellites** → choisir le type :

- **Passerelle radio** (`gw`) : relaie les messages MeshCore / Meshtastic vers le site ;
- **Complet** (`full`) : passerelle + site Assista-Crise local, utilisable sans Internet, avec
  cartes hors ligne du département de l'institution (et des départements voisins).

puis **« Générer le jeton et les commandes »**. La page affiche les commandes exactes à copier
(jeton inclus, valable 24 h, usage unique).

### 2. Sur la machine du satellite (Raspberry Pi ou PC sous Linux, connecté à Internet)

```bash
git clone https://github.com/sylvain-hazera/assista-crise-code-bis.git
cd assista-crise-code-bis/satellite
./installer.sh installer <JETON>
```

(`git` absent : `sudo apt install -y git`. Dépôt déjà cloné : `cd assista-crise-code-bis && git pull`.)

Le script, sans rien demander :

1. installe Docker si besoin (passe par `sudo` tant que vous n'êtes pas dans le groupe `docker`) ;
2. enrôle le satellite (nom = nom de la machine, profil et département donnés par le central) ;
3. **attend la validation** : il affiche l'adresse de la page Satellites et patiente ;
4. une fois validé, **récupère seul ses identifiants** (aucune recopie) ;
5. génère tous les secrets locaux (`.env`, lisible par vous seul) ;
6. **détecte les radios** branchées (MeshCore et/ou Meshtastic), les enregistre au central ;
   une radio absente met seulement son service en attente ;
7. démarre le satellite (et, en profil complet, télécharge la carte du dernier build Protomaps).

### 3. Sur le central

Le satellite apparaît **« En attente de validation »** : cliquer **Valider**. C'est tout : il
apparaît **« Actif »** environ une minute plus tard.

### Ensuite

| Situation | Commande (dans `satellite/`) |
|---|---|
| Installation interrompue (Ctrl+C, coupure) | `./installer.sh installer` (sans jeton : reprend où il en était) |
| Radio branchée après l'installation | `./installer.sh connecter-noeud` |
| **Mise à jour sur place** | **`./installer.sh mettre-a-jour`** (récupère le code et redémarre) |
| **Mise à jour à distance** | bouton **Mettre à jour** de la page Satellites — voir « Mise à jour depuis le central » plus bas |
| Identifiants perdus / compromis | bouton **Régénérer les identifiants** sur la page Satellites |
| Vérifier l'état | `docker compose --profile <gw\|full> ps` |

> **Le satellite porte la charte de son institution**, recopiée à l'enrôlement : nom affiché,
> couleurs, polices et logo (téléchargé une fois, puis servi hors ligne). Elle est **figée** —
> un changement de logo côté central n'arrive ici qu'à la prochaine mise à jour — et
> **mono-institution**, un satellite appartenant à une institution et à une seule. Un
> satellite enrôlé avant le 13/11/2026 affiche « Assista-Crise » tant qu'il n'a pas été
> réenrôlé : la charte est capturée à l'enrôlement, pas rattrapée après coup.

> **Les fichiers déposés sur un satellite restent sur ce satellite.**
> `FILE_ENCRYPTION_KEY` est générée **localement** par `installer.sh` et n'est pas celle du
> central : une pièce d'identité ou un justificatif chiffré ici n'est **pas** lisible là-bas,
> et réciproquement. Ces pièces ne sont pas dans le périmètre de synchronisation, donc rien
> ne remonte — c'est cohérent, mais il faut le savoir avant de demander à un bénévole de
> déposer son permis depuis le satellite. **Sauvegardez `.env`** : cette clé perdue, les
> fichiers déjà déposés sur place deviennent définitivement illisibles.

> **`demarrer` reconstruit les images sur place** (`up -d --build`). En profil `full`, cela
> inclut le build Angular de production : c'est lourd pour un Raspberry Pi. En cas de doute,
> lancer d'abord `docker compose --profile full build backend frontend` pour voir si la
> construction passe, et ajouter du swap si elle échoue par manque de mémoire.

### Ancien parcours (installations commencées avant le 20/10/2026)

`./installer.sh enroler <jeton> <nom> <gw|full>`, validation (identifiants affichés une seule
fois à l'administrateur), puis `./installer.sh demarrer` (questions interactives). Toujours
accepté. Fichiers utiles : `.env` (configuration), `.satellite_id` (identifiant du satellite,
désormais correctement mémorisé), `.profil`.

## Mise à jour depuis le central (14/11/2026)

Un satellite peut être mis à jour depuis la page **Satellites** du central, sans se déplacer
ni ouvrir de port chez lui : c'est toujours lui qui appelle.

### Ce qui se passe

1. Sur la page Satellites, **Mettre à jour** enregistre un ordre vers la dernière version
   **signée**. Peuvent le donner : l'administrateur de la plateforme et ceux qui administrent ce
   satellite (les mêmes que pour le valider ou le révoquer). Pendant une crise ouverte de
   l'institution, il faut confirmer une seconde fois.
2. L'**agent** du satellite (`agent_mise_a_jour.py`, lancé toutes les deux minutes par systemd
   **sur la machine**, pas dans un conteneur) vient chercher l'ordre.
3. Il **vérifie la signature** avec la clé publique gardée sur place, puis, dans cet ordre :
   sauvegarde de la base locale (profil complet), récupération du code, **construction**, et
   seulement si elle réussit, redémarrage. Tant que la construction n'a pas abouti, l'ancienne
   version continue de tourner.
4. Chaque étape et le résultat remontent sur la page Satellites (bouton **Historique**, avec le
   journal des commandes).

### Ce que la signature garantit — et ne garantit pas

Le central **transmet** un numéro de commit et sa signature ; il ne peut rien rendre
installable. Seul le détenteur de la clé privée le peut : cette clé n'est jamais dans le dépôt,
et jamais en clair sur le serveur. Voler un compte d'administrateur ou prendre la main sur le
dépôt GitHub ne suffit donc pas à faire exécuter du code sur un satellite.

**Nuance depuis le 15/11/2026** (signature depuis la page, voir plus bas) : le central garde une
copie de la clé **chiffrée par la phrase de passe**, et c'est lui qui sert la page où la phrase
est tapée. Sans la phrase, cette copie ne sert à rien ; mais quelqu'un qui prendrait la main
sur le central lui-même pourrait modifier la page pour capter la phrase à la prochaine
signature. C'est le prix, accepté, d'une signature en un geste. Pour y renoncer : vider
`signature_satellites_web.json` dans le dossier des secrets et signer dans un terminal.

- **La clé publique est copiée une fois** sur le satellite (`.cle-signature.pub`) et n'est
  **jamais remplacée automatiquement**. Si elle suivait le dépôt, il suffirait de pousser une
  nouvelle clé pour tout faire accepter. Changer de clé se fait sur place : supprimer
  `.cle-signature.pub`, puis `./installer.sh mettre-a-jour`.
- **Pas de retour en arrière** : l'agent n'installe qu'une version qui est une *suite* de celle
  en place. Une vieille version reste correctement signée pour toujours ; c'est l'ordre des
  commits qui interdit de la rejouer pour rouvrir une faille corrigée.
- **La première confiance** est celle du jour où la clé est copiée : ce jour-là, le satellite
  croit le dépôt qu'il vient de récupérer — comme pour toute mise à jour faite sur place.
- **Ce que la signature ne couvre pas** : les images de base téléchargées pendant la
  construction (Python, Node, PostGIS) et les paquets qu'elles installent.


### Diagnostic et redémarrage depuis le central (17/11/2026)

Un satellite a fini une mise à jour « à jour et en échec » : le code avait avancé, son serveur
local ne redémarrait pas, et il a fallu téléphoner pour apprendre pourquoi. Trois choses en
sont sorties :

- **Tout échec au redémarrage emporte son diagnostic.** À la fin du journal : la version du
  code, la place libre, l'état de chaque service, et les soixante derniers messages de ceux qui
  sont en panne — toujours ceux du serveur local, puisque c'est lui qui applique les migrations.
- **Une liste « Demander au satellite… »**, sur la page Satellites. Douze ordres, que l'agent
  connaît d'avance (`ACTIONS` dans `agent_mise_a_jour.py`) :

  | Regarder — ne change rien | Agir — ce que ferait quelqu'un sur place |
  |---|---|
  | Diagnostic | Redémarrer les services |
  | Journaux de tous les services | Appliquer les migrations (base sauvegardée d'abord, une par une) |
  | État des migrations | Reconstruire et redémarrer |
  | État de la machine | Libérer de la place |
  | État du réseau | Sauvegarder la base |
  | État du code installé | Revenir à la version précédente |

Ce sont des mots d'une **liste fermée, sans paramètre** : le central ne transmet toujours aucune
commande, et l'agent refuse tout mot qu'il ne connaît pas. Ils ne sont pas signés, parce qu'ils
ne font entrer aucun code ; la mise à jour, elle, reste signée. Le résultat se lit dans
l'historique du satellite, comme une mise à jour. Un essai vérifie que la liste du central et
celle de l'agent sont les mêmes.

« État des migrations » et « Appliquer les migrations » lancent `manage.py` dans l'image du
serveur **sans son point d'entrée** (qui applique les migrations) et sans que le serveur
tourne : c'est quand il ne démarre pas qu'on en a besoin.

**Revenir à la version précédente.** Avant chaque mise à jour l'agent note de quoi revenir
(`.maj-precedente.json` : la version d'avant, et la sauvegarde de la base). L'ordre ne porte
aucun paramètre : le central ne choisit jamais vers quoi un satellite revient. La sauvegarde est
rechargée dans une base **neuve, à côté** ; tant que ce chargement n'a pas réussi, la base en
service n'est pas touchée. Les deux sont ensuite échangées par renommage, et la base d'avant le
retour est gardée (`assista-db_avant_<date>`) : rien n'est détruit, ce qui a été saisi depuis
est seulement mis de côté. Essayé contre un vrai PostgreSQL avec PostGIS — base revenue à la
sauvegarde, base d'avant intacte, sauvegarde abîmée refusée sans rien toucher. Ce qui n'a pas
été essayé : le parcours complet sur une vraie machine de satellite (arrêt des services,
reconstruction de l'ancienne version, redémarrage).

**Le pare-feu du central.** Le journal d'une mise à jour est fait de lignes de commande : le
pare-feu applicatif y voyait une attaque et répondait 403 à tout compte rendu qui en portait.
Le compte rendu final restait en attente, l'agent ne revenait plus chercher d'ordre, et trois
refus par heure faisaient bannir le satellite. La règle `900206` de
`proxy/modsecurity-override.conf` cesse de lire le corps sur ce seul chemin. Côté agent, un
compte rendu refusé pour son contenu repart sans son journal : il ne bloque plus rien.

Pas fait : le retour en arrière n'est jamais automatique — c'est quelqu'un qui le décide — et
le redémarrage de la machine elle-même n'est pas dans la liste.

### Mise en place, une fois

Sur le poste du responsable de la plateforme :

```bash
scripts/satellites/creer-cle-signature.sh   # crée la clé, protégée par une phrase de passe
```

La clé privée va dans `~/.config/assista-crise/` — **à sauvegarder hors de la machine**. La clé
publique est ajoutée à `backend/core/signature_satellites.pub`, à enregistrer dans le dépôt, à
pousser, puis le central est redéployé.

Sur **chaque satellite déjà installé**, une dernière fois sur place :

```bash
./installer.sh mettre-a-jour    # garde la clé publique et installe l'agent
```

### À chaque nouvelle version

**Depuis la page Satellites** (le chemin ordinaire) : après `git push`, le cadre « Signer la
dernière version » montre le dernier commit poussé ; on tape la phrase de passe, on clique
« Signer et publier ». La signature est calculée **dans le navigateur** : la phrase de passe
n'est pas envoyée, le serveur ne reçoit que le numéro de version et sa signature, qu'il vérifie
comme avant. Chaque remise de la clé chiffrée au navigateur est inscrite à la main courante.

À préparer une fois, dans un terminal du central (et à refaire si la phrase de passe change) :

```bash
scripts/satellites/preparer-signature-web.sh   # demande la phrase, dépose la clé chiffrée
```

Il faut un navigateur qui signe en Ed25519 : Chrome ou Edge 137, Firefox 129, Safari 17, ou
plus récent.

**Dans un terminal** (toujours possible, et la seule voie si la clé n'a pas été préparée) :

```bash
git push                                   # un satellite récupère son code sur le dépôt distant
scripts/satellites/signer-version.sh       # demande la phrase de passe, affiche commit + signature
```

Coller ce que le script affiche dans le cadre **Versions signées** de la page Satellites. La
version devient la référence : les satellites qui n'y sont pas passent « En retard », et le
bouton **Mettre à jour** apparaît.

### Quand ça ne se passe pas bien

| Ce que dit l'historique | Ce qui a été modifié | Quoi faire |
|---|---|---|
| Signature refusée | rien | vérifier que la version a bien été signée avec la clé que ce satellite connaît |
| Fichiers modifiés sur place | rien | sur place : `git status`, puis `git stash` |
| Retour en arrière refusé | rien | publier une version plus récente que celle installée |
| Moins de 3 Go libres | rien | faire de la place (`docker system prune`) |
| La sauvegarde a échoué | rien | vérifier que la base locale tourne |
| La construction a échoué | le code est remis à la version précédente, qui n'a pas cessé de tourner | lire le journal ; sur un Raspberry Pi, souvent la mémoire — ajouter du swap |
| Le redémarrage a échoué | **le satellite peut être en partie sur la nouvelle version** | sur place : `./installer.sh demarrer`. Sauvegarde dans `satellite/sauvegardes/` |
| Plus de nouvelles du satellite | inconnu | il rendra compte à son retour ; sinon voir sur place |

Les trois dernières sauvegardes sont gardées dans `satellite/sauvegardes/` (lisibles par le
seul propriétaire). Revenir en arrière après une migration se fait à la main, à partir de
l'une d'elles : rien ne le fait automatiquement, parce qu'un retour automatique sur une base
déjà migrée ferait plus de dégâts qu'il n'en répare.

**Jamais testé sur un vrai satellite à ce jour.** La logique de l'agent est testée avec de
vrais dépôts git et de vraies signatures (`test_agent_mise_a_jour.py`, 27 tests) et de bout en
bout contre un serveur de test, mais Docker, `pg_dump` réel, l'unité systemd et la durée d'une
construction sur Raspberry Pi restent à vérifier au premier essai réel — sur un satellite de
test, pas sur celui d'une mairie.

Une passerelle Windows n'a pas d'agent : la page ne lui propose pas la mise à jour.

## Ce que chaque service fait

| Service | Profil | Rôle |
|---|---|---|
| `detecter-noeud` | outillage (un coup, pas en continu) | Détecte et différencie MeshCore/Meshtastic sur les devices série candidats, enregistre le nœud auprès du central — pour un sondage manuel ponctuel. |
| `surveiller-noeuds` | gw, full (en continu) | Équivalent automatique de `detecter-noeud` : relance le même sondage toutes les `INTERVALLE_DETECTION_SECONDES` (30s par défaut) — un nœud branché après coup est reconnu sans commande manuelle. |
| `meshcore-proxy` | gw, full | Détient la connexion réelle au nœud MeshCore (USB/série ou TCP), s'annonce en mDNS sur le LAN — voir `meshcore-bridge/proxy.py`. |
| `meshcore-bridge` | gw, full | Relaie les messages entre le proxy et `assista-crise.fr` (ou le central configuré). Bascule vers l'assista-crise local si le central passe hors-ligne (profil full, voir `meshcore-bridge/README.md`). |
| `etat-connectivite` | gw, full | Vérifie périodiquement si le central répond, écrit l'état dans un volume partagé (`etat_connectivite.py`) — source de vérité unique pour tout futur composant qui en a besoin (bannière, écran de statut). |
| `mosquitto` | full | **Broker MQTT local du site**, authentifié, publié sur la seule IP du LAN — voir « Broker MQTT du site » plus bas. Jamais relié au broker du central. |
| `db`, `backend`, `frontend` | full | Instance assista-crise locale, identique au déploiement central. **Application web** pour les téléphones et PC du site, sans internet : `http://<IP du satellite>/` (port `WEB_PORT`, 80 par défaut, réseaux privés RFC 1918 uniquement, voir `nginx-satellite.conf`). URL et compte admin local affichés en fin d'installation et par `./installer.sh acces-web`. |
| `telecharger-tuiles` | full | Conteneur one-shot : télécharge le fond de carte du département + limitrophes (PMTiles Protomaps, ~0,5 à 1 Go) et ses polices/pictogrammes, lus directement par l'application (`frontend/src/app/shared/utils/carte-style.ts`). Gardé ensuite ; `--forcer` pour le refaire. |
| `annoncer-backend-local` | full | Annonce ce backend en mDNS sur le LAN, pour qu'un satellite GW séparé sur le même site le trouve sans IP configurée à la main. |
| `meshtastic-bridge` | gw, full | Optionnel — pilote un ou plusieurs `CompagnonMeshtastic` (MQTT, TCP ou SERIE) ; voir la note ci-dessous. |
| `sync-sortant` | full | Pousse périodiquement vers le central les écritures locales en attente — voir "Synchronisation local → central" ci-dessous. |
| `sync-mesh` | full | Récupère du central les messages mesh à émettre sur la radio de ce satellite et lui rapporte ce qui est parti. **Intervalle court (30 s)**, à part de `sync-entrant` : envoyer un message en crise ne peut pas attendre 5 minutes. |
| `sync-entrant` | full | Sens inverse : applique localement le rafraîchissement central → local (crises, demandes, dossiers, missions…) et **copie les comptes de l'institution** (hash du mot de passe seulement) : chacun se connecte à l'application locale avec ses identifiants habituels. |
| `appliquer-config-proxy` | gw, full | Reconfigure `meshcore-proxy` à distance (voir "Reconfiguration distante" ci-dessous), sans action locale/SSH. |

## Broker MQTT du site

Depuis le 06/11/2026, le broker local (`mosquitto-config/mosquitto.conf`) n'est plus réservé aux
conteneurs : **des nœuds Meshtastic du site peuvent s'y connecter en passerelle MQTT**.

| Compte | Droits | Utilisé par |
|---|---|---|
| `pont` | lecture/écriture sur `msh/EU_868/#` | `meshtastic-bridge` du satellite |
| `passerelle` | lecture/écriture sur `msh/EU_868/#` | le nœud Meshtastic du site configuré en passerelle MQTT |

- **Authentification obligatoire** et liste de droits (`mosquitto-config/acl`), comme sur le
  central. Testé : un client anonyme reçoit `Connection Refused: not authorised`, et `pont` ne
  peut rien faire hors de sa racine.
- **Port publié sur la seule IP du LAN**, `SATELLITE_LAN_IP:1883`, jamais sur `0.0.0.0` : Docker
  contourne le pare-feu de la machine, et un Pi posé chez une mairie peut se trouver derrière une
  box qui redirige des ports. L'IP est détectée par `installer.sh` à **chaque** passage (un
  satellite déménage, change de box : une IP périmée rendrait le broker injoignable sans rien
  signaler). Sans IP privée détectée, le repli est `127.0.0.1` — volontairement inutilisable
  depuis le LAN : mieux vaut un nœud qui n'arrive pas à se connecter qu'un broker ouvert à tous.
- **Mots de passe** dans `.env` (`MQTT_PONT_PASSWORD`, `MQTT_PASSERELLE_PASSWORD`), générés une
  seule fois par `installer.sh` — les régénérer couperait les nœuds déjà configurés sur place. Le
  fichier de mots de passe **haché** est reconstruit à chaque démarrage dans un tmpfs : rien n'est
  écrit sur la carte SD, qui s'use et qu'on peut retirer du Pi.
- Déclarer le companion correspondant côté application : `CompagnonMeshtastic` en
  `connexion_type=MQTT`, `broker_host=mosquitto`, `mqtt_username=pont`, et le champ **`satellite`**
  renseigné (« radio branchée sur CETTE machine »). La racine `topic_racine` doit valoir
  `msh/EU_868`, seule racine autorisée par la liste de droits — une racine qui ne correspond pas
  coupe le flux **sans message d'erreur**.

> **Ce broker n'est jamais relié à celui du central** (décision du 06/11/2026). Les échanges
> satellite ↔ central passent par `sync-sortant` / `sync-entrant`, faits pour les coupures
> longues. Un pont MQTT demanderait d'exposer le broker du central sur Internet et n'éviterait
> aucun travail : tout ce qui arrive doit de toute façon être écrit dans les modèles Django pour
> être exploitable (carte, messages, positions, chiffrement au repos).

> **À retenir, par site** : un nœud Meshtastic ne relaie vers MQTT que les canaux présents dans
> ses 8 emplacements, et seulement s'il a pu les déchiffrer — `Router.cpp` du firmware exige
> `DECODE_SUCCESS` avant toute publication. Couvrir N canaux distincts demande donc N/7
> passerelles sur le site, pas une seule.

## Nœuds branchés en USB/série

**MeshCore** : `MESHCORE_CONNEXION_TYPE=SERIE` + `MESHCORE_SERIE_DEVICE=/dev/ttyUSB0` (ou
`/dev/ttyACM0`, voir `ls /dev/tty*` une fois le nœud branché) — `meshcore-proxy` détient alors
directement la connexion série, exactement comme il détenait une connexion TCP sur `.113`.
Support ajouté le 2026-09-17 à `meshcore-bridge/proxy.py` (`serial_asyncio_fast`, même
bibliothèque que `bridge.py` utilise déjà en interne via la lib `meshcore`).

**Meshtastic** : support série ajouté le 2026-09-17 à `meshtastic-bridge/bridge.py`, en miroir
exact du mode TCP déjà validé (`_executer_compagnon_interface_locale`, lib officielle
`meshtastic`) — voir `meshtastic-bridge/README.md`. Contrairement à MeshCore, le
`connexion_type` (MQTT/TCP/SERIE) et le `serie_device` se règlent **par `CompagnonMeshtastic`
côté Django**, pas par variable d'environnement du conteneur — `MESHTASTIC_SERIE_DEVICE` dans
`.env` ne sert qu'au passage du périphérique Docker (`devices:`), doit correspondre exactement
à la valeur choisie côté Django. **Non testé sur du vrai matériel série à ce jour**, contrairement
au mode TCP.

## `decouverte_lan.py`

Combine deux méthodes pour repérer les nœuds MeshCore/Meshtastic sur le LAN d'un satellite à
l'installation (utile pour un nœud resté en TCP plutôt que branché en série) :
- **mDNS** (zeroconf) — `_meshcore._tcp.local.` est confirmé trouvable pour un
  `meshcore-proxy` (il s'annonce lui-même, `role=proxy` dans les properties pour le
  distinguer d'un vrai nœud) ; pas confirmé pour un firmware de nœud réel (noms de service
  hypothétiques, voir `SERVICE_TYPES_MDNS`).
- **Scan TCP du port 5000** (port MeshCore par défaut) sur le sous-réseau local —
  protocole-agnostique, indépendant de toute annonce.

**Handshake protocolaire de confirmation** (ajouté le 2026-09-17, `confirmer_protocole_tcp`) :
vraie connexion MeshCore puis Meshtastic sur chaque candidat (même technique que
`MeshLocalDetecterView` côté Django) — dit si `ip:port` est vraiment MeshCore/Meshtastic, pas
juste "quelque chose y écoute". Coûte plusieurs secondes réelles par candidat, désactivé par
défaut dans `decouvrir_noeuds_lan()` (`confirmer=True` pour l'activer), mais utilisé par défaut
par le CLI ci-dessous.

```bash
python3 decouverte_lan.py
```

## `detecter_noeud_serie.py`

Détecte quel protocole (MeshCore ou Meshtastic) répond sur chaque device `/dev/ttyUSB*`/
`/dev/ttyACM*` à l'installation (réutilise exactement les mêmes techniques de sondage que
`MeshLocalDetecterView` côté Django, déjà validées en TCP), puis enregistre le nœud auprès du
central (`CompagnonMeshCoreViewSet`/`CompagnonMeshtasticViewSet`.`enregistrer_depuis_satellite`
— idempotent, identifié par la clé publique/le node_num du nœud, PAS par le chemin du device
qui peut changer après un redémarrage). Une fois un device confirmé, **la config est persistée
et réutilisée telle quelle tant qu'il répond** — pas de re-sondage à chaque démarrage :

```bash
docker compose --profile outillage run --build --rm detecter-noeud
```

Si le central est injoignable au moment du sondage, la détection locale reste valable
(persistée quand même) — seul l'enregistrement central est différé au prochain passage.

**Détection automatique (ajouté le 15/10, demande utilisateur)** : les profils `gw`/`full`
démarrent aussi `surveiller-noeuds`, le même script en boucle (`DETECTION_CONTINUE=true`, voir
`detecter_noeud_serie.py:boucle`) — brancher un nœud après le démarrage du satellite suffit, il
est reconnu et enregistré au prochain passage (30s par défaut,
`INTERVALLE_DETECTION_SECONDES` dans `.env`), sans commande manuelle. `detecter-noeud` (profil
`outillage`) reste disponible tel quel pour un sondage ponctuel immédiat (ex: juste après avoir
branché, sans attendre le prochain passage de la boucle).

⚠️ **Compromis sécurité assumé** : `detecter-noeud` n'était privilégié/`/dev` entier monté que
le temps d'une seule commande — `surveiller-noeuds` garde ce même niveau d'accès **en
permanence** (nécessaire : on ne sait jamais à l'avance sur quel device un nouveau nœud va
apparaître). Choix délibéré (discuté le 15/10) plutôt qu'une règle udev hôte (qui aurait gardé
l'accès ponctuel d'origine, mais plus complexe à installer et moins portable selon l'OS).

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

## `annoncer_backend_local.py`

S'annonce en mDNS (`_ac-local._tcp.local.`, `role=backend-local`) sur le LAN — permet à un
satellite GW SÉPARÉ sur le même site (modèle à 2 Pi) de trouver ce backend local sans IP
configurée à la main (voir `meshcore-bridge/README.md`, section "Bascule vers l'assista-crise
local", pour l'ordre de résolution complet côté pont). N'annonce que — le backend Django
lui-même tourne dans son propre conteneur et écoute déjà sur son port, ce script ne fait
transiter aucune donnée.

```bash
python3 annoncer_backend_local.py
```

## Synchronisation local → central (profil full uniquement)

Décidée le 2026-09-18, périmètre du sens LOCAL -> CENTRAL (`EvenementSynchronisation`) : le
travail des acteurs institutionnels sur place pendant une coupure — `Dossier` (+ son fil
`DossierCommentaire`/`DossierHistorique`), `DeclarationSecurite`, `Mission`, et depuis le
06/11/2026 **tout le domaine mesh observé sur place** : `CanalMeshCore`, `CanalMeshtastic`,
`MessageMeshLog`, `MessageCanalMeshCore`, `MessageMeshtasticLog`, `MessageCanalMeshtastic`,
`AlerteMeshSOS`. Jusque-là seuls les DM MeshCore remontaient, et un satellite observait donc du
trafic radio que le central ne voyait jamais. Les canaux en font partie parce qu'un satellite en
crée localement (le canal « Public » est auto-provisionné dès qu'un companion voit son trafic) :
sans eux, leurs messages arriveraient au central avec une clé étrangère introuvable. La file étant
rejouée dans l'ordre de création, un canal précède toujours ses messages.
PAS `Request`/`Offer`/`Information` dans CE sens (citoyens, alimentés via internet, jamais via
le LAN privé d'un satellite) — voir `backend/core/sync_outbox.py` pour ajouter un modèle plus
tard sans redesign. Le sens CENTRAL -> LOCAL (`donnees()`/`sync-entrant`, voir plus bas) couvre
lui ces trois modèles en plus de Dossier/Mission — une demande soumise par un citoyen au site
public doit redescendre vers le satellite, même si elle ne remonte jamais.

### Envoyer un message depuis le central vers la radio d'un satellite

Sens descendant **à part**, avec son propre conteneur `sync-mesh` et son propre intervalle
(`SATELLITE_SYNC_MESH_INTERVALLE_S`, **30 s** par défaut). Deux raisons :

- `sync-entrant` tourne toutes les 300 s : très bien pour rafraîchir des crises et des dossiers,
  inacceptable pour envoyer un message en crise ;
- la file montante ne suit que les **créations** (append-only), donc un `EN_ATTENTE -> ENVOYE`
  n'y remonterait jamais — or un opérateur du central doit savoir si son message est parti.

Enchaînement complet :

```
central : MessageCanalMeshtastic(SORTANT, EN_ATTENTE) sur un companion dont `satellite` = ce sat
  -> sync-mesh le récupère (GET  /api/satellites/<id>/mesh-a-emettre/) et le crée à l'identique
     en local, même uuid, avec le canal qui l'accompagne
  -> le pont local le voit par l'action habituelle `a-envoyer` et l'émet sur la radio
  -> le pont met le statut local à ENVOYE
  -> sync-mesh rapporte ce statut (POST /api/satellites/<id>/mesh-emis/), le central cesse de
     le proposer
```

Idempotent de bout en bout : un rapport perdu laisse le message dans la liste du central, qui
sera recréé en local (déjà présent, donc ignoré) puis rapporté à nouveau.

**Meshtastic seulement** pour l'instant : le rattachement à un satellite passe par
`CompagnonMeshtastic.satellite`. `CompagnonMeshCore` n'a pas ce champ — l'étendre à MeshCore
demande d'abord de l'ajouter.

> **Aucun pont MQTT entre le broker du satellite et celui du central** (décision du 06/11/2026).
> Il faudrait exposer le broker du central sur Internet, et il n'éviterait aucun travail : ce qui
> arrive doit de toute façon être écrit dans les modèles Django pour être exploitable. Il
> n'achèterait que la latence, qu'on traite ici par un appel court **initié par le satellite** —
> rien à exposer, ça traverse le NAT, et ça tolère une liaison médiocre (un satellite peut être à
> La Réunion). Le risque de boucle radio, lui, ne s'applique pas : les sites sont trop éloignés
> pour qu'un chemin radio existe entre eux.

- **Côté backend local** (`INSTANCE_SATELLITE_LOCALE=True`, posé automatiquement sur le
  service `backend` du profil full) : chaque écriture pertinente peuple
  `EvenementSynchronisation` (signaux Django, `core/sync_outbox.py`). Deux régimes : les
  modèles "append-only" (jamais réédités après création — commentaires, historique,
  déclarations, messages mesh) s'upsertent simplement par id côté central ; les modèles
  "mutables" (`Dossier`, `Mission`) capturent une `version_de_base` (leur `modifie_le` juste
  avant la première écriture hors-ligne) pour détecter un conflit plutôt que d'écraser
  silencieusement une modification faite entre-temps côté central.
- **`sync-sortant`** (nouveau conteneur, même image que `backend`, sans
  `INSTANCE_SATELLITE_LOCALE`) : boucle `synchroniser_sortant` (commande de gestion Django,
  `SATELLITE_SYNC_SORTANT_INTERVALLE_S` secondes entre deux passages, 300 par défaut) — pousse
  les événements en attente vers `POST /api/satellites/<id>/synchroniser/`. Toujours tenté,
  que le central soit vu en ligne ou non par `etat-connectivite` : échoue proprement tout seul
  si injoignable, retente au passage suivant.
- **Conflits** : jamais résolus automatiquement — un `ConflitSynchronisation` est créé côté
  central, les contacts actifs de l'institution sont notifiés (`Notification`), l'événement
  local reste marqué `CONFLIT` (pas retenté). Arbitrage via la page `/admin/conflits-
  synchronisation` (frontend, comparaison champ par champ version centrale/locale) ou
  directement `POST /api/conflits-synchronisation/<id>/resoudre/`
  (`{"choix": "GARDE_CENTRAL"|"GARDE_LOCAL"}`) — voir `ConflitSynchronisationViewSet`.
- **`sync-entrant`** (nouveau conteneur, même image que `backend`, SANS
  `INSTANCE_SATELLITE_LOCALE`) : sens inverse de `sync-sortant` — boucle `synchroniser_entrant`
  (`SATELLITE_SYNC_ENTRANT_INTERVALLE_S`, 300 par défaut), applique localement le
  rafraîchissement `GET /api/satellites/<id>/donnees/`, en deux régimes :
  - `Dossier`/`Mission` (mutables) : un objet avec une écriture locale encore `EN_ATTENTE` est
    ignoré (jamais écrasé silencieusement) ; un conflit tranché côté central (`resoudre`)
    redescend donc vers la copie locale dès le passage suivant, puisque rien ne le bloque plus
    une fois résolu. `modifie_le` posé à la valeur EXACTE reçue du central (`QuerySet.update()`,
    aucun signal déclenché) — indispensable pour qu'une future écriture locale calcule une
    `version_de_base` qui corresponde vraiment à ce que le central connaît, plutôt qu'un
    horodatage arbitraire qui déclencherait un faux conflit au prochain envoi.
  - `Crisis`/`Request`/`Offer`/`Information` : simple upsert (jamais édités localement, le
    central fait toujours autorité). Un champ géométrique (`location`/`zone`/`zone_secteurs`)
    voyage en GeoJSON et se reconstruit via `GEOSGeometry`. Les FK vers un catalogue partagé
    (`RequestType`/`OfferType`/`InformationType`/`MaterielCatalogue`/`Competence` — peuplé
    indépendamment par ses propres migrations sur chaque déploiement, un même uuid n'a AUCUNE
    raison de coïncider entre central et satellite) sont résolues par CLÉ NATURELLE (le nom
    métier, unique des deux côtés), créées localement si absentes — cohérent avec la
    philosophie déjà en place de ces tables ("n'importe quel centre peut ajouter une entrée,
    immédiatement réutilisable"). Un `author`/`validator` pas encore connu localement (aucune
    synchronisation des comptes utilisateurs à ce jour) est mis à `None` plutôt que de bloquer
    tout l'enregistrement. `photo` (fichier binaire) volontairement exclu — jamais transféré par
    ce canal JSON, déjà le cas avant ce chantier.
- **Identité** : l'auteur apparent côté central reste le compte de service du satellite
  (aucun nouveau mécanisme d'auth) ; le vrai auteur local (peut n'exister QUE côté local, pas
  de compte web) est conservé dans `auteur_local_email`/`auteur_local_nom` et apparaît dans le
  commentaire d'audit posé à l'application de l'événement.

Testé par `backend/core/tests/satellites/test_synchronisation.py` (peuplement de la file, application côté
endpoint des deux sens — y compris résolution des FK de catalogue par clé naturelle et
reconstruction GeoJSON pour Crisis/Request/Offer/Information —, commandes
`synchroniser_sortant`/`synchroniser_entrant`, résolution de conflit) — **jamais testé de bout
en bout entre deux vraies instances** (central + satellite Full réels), seulement en isolation
avec mocks. `photo` (fichiers binaires) reste hors périmètre de ce canal JSON, comme avant ce
chantier — aucun transfert d'image entre central et satellite.

## Routage MeshCore : régions et meilleur companion (2026-09-18)

Recherché avant de coder (pas supposé) : **MeshCore n'a aucune notion protocolaire de région
ou d'ACL géographique**. L'ACL du firmware est une table de permissions par répéteur/room
server/capteur (qui a le droit de l'administrer), sans aucun rapport avec la géographie. Les
« régions » françaises (ex. `#fr-naq`) sont une pure convention communautaire de nom de canal.

- `CompagnonMeshCore.region_tag`/`ContactMeshCore.region_tag` : étiquettes texte libres,
  posées à la main (page `/admin/meshcore-companions`), aucune inférence automatique.
- `ContactMeshCore.nombre_sauts` : capté par `meshcore-bridge/bridge.py:boucle_contacts` depuis
  `out_path_len` (déjà renvoyé par la lib `meshcore` dans le même événement `CONTACTS` déjà
  consommé — pas de nouvelle plomberie protocolaire) ; `None` si aucun chemin confirmé
  (sentinel firmware 255, jamais interprété comme "255 sauts").
- `backend/core/routage_mesh.py:meilleur_compagnon_pour_contact` : contact déjà entendu
  (au plus court en sauts) > région correspondante > companion principal > premier actif.
  Exposé via `GET /api/compagnons-meshcore/meilleur-pour-contact/` et branché automatiquement
  sur `MessageMeshLogViewSet.perform_create` quand le client ne précise pas `compagnon` (un
  choix explicite reste toujours prioritaire). La page de messagerie d'équipe
  (`equipe-messagerie-mesh.component`) suggère désormais ce companion avec sa raison, affichée
  à l'utilisateur — jamais un choix opaque.
- Émission "à l'aveugle" sur le canal régional (`#fr-naq`) plutôt qu'un DM ciblé quand aucun
  contact direct n'est connu : reste une décision humaine (le résultat de
  `meilleur_compagnon_pour_contact` porte `region_tag` pour que l'appelant le sache), pas
  automatisée — le canal MeshCore (`MessageCanalMeshCore`) existe déjà, non re-câblé ici.

14 tests dédiés (`backend/core/tests/mesh/test_routage_mesh.py`).

## Reconfiguration distante du proxy (2026-09-18)

Referme le manque signalé : configurer un satellite depuis le site central pour lui ajouter un
nœud dans son LAN, sans SSH ni action locale. `appliquer-config-proxy` (voir
`appliquer_config_proxy.py`) poll périodiquement `GET /api/compagnons-meshcore/<id>/` — si
`connexion_type`/`tcp_host`/`tcp_port`/`serie_device` diffèrent de `.env`, le réécrit
(atomique) puis force `docker compose up -d --no-deps meshcore-proxy` (PAS `docker restart`,
qui ne relirait jamais les nouvelles variables d'environnement déjà figées à la création du
conteneur). Nécessite le socket Docker monté — accès root de facto sur l'hôte, même compromis
déjà accepté pour `detecter-noeud` (`--privileged` pour `/dev`).

10 tests dédiés (`satellite/test_appliquer_config_proxy.py`, logique pure — requests/subprocess
mockés). **Jamais testé sur du vrai matériel** — la recréation via `docker compose up -d
--no-deps` est la partie la plus fragile (suppose le plugin compose v2, normalement inclus par
`get.docker.com`) à vérifier au premier essai réel.

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
