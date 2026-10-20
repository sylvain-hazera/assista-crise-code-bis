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
| Mise à jour | `git pull` puis `./installer.sh demarrer` |
| Identifiants perdus / compromis | bouton **Régénérer les identifiants** sur la page Satellites |
| Vérifier l'état | `docker compose --profile <gw\|full> ps` |

### Ancien parcours (installations commencées avant le 20/10/2026)

`./installer.sh enroler <jeton> <nom> <gw|full>`, validation (identifiants affichés une seule
fois à l'administrateur), puis `./installer.sh demarrer` (questions interactives). Toujours
accepté. Fichiers utiles : `.env` (configuration), `.satellite_id` (identifiant du satellite,
désormais correctement mémorisé), `.profil`.

## Ce que chaque service fait

| Service | Profil | Rôle |
|---|---|---|
| `detecter-noeud` | outillage (un coup, pas en continu) | Détecte et différencie MeshCore/Meshtastic sur les devices série candidats, enregistre le nœud auprès du central — pour un sondage manuel ponctuel. |
| `surveiller-noeuds` | gw, full (en continu) | Équivalent automatique de `detecter-noeud` : relance le même sondage toutes les `INTERVALLE_DETECTION_SECONDES` (30s par défaut) — un nœud branché après coup est reconnu sans commande manuelle. |
| `meshcore-proxy` | gw, full | Détient la connexion réelle au nœud MeshCore (USB/série ou TCP), s'annonce en mDNS sur le LAN — voir `meshcore-bridge/proxy.py`. |
| `meshcore-bridge` | gw, full | Relaie les messages entre le proxy et `assista-crise.fr` (ou le central configuré). Bascule vers l'assista-crise local si le central passe hors-ligne (profil full, voir `meshcore-bridge/README.md`). |
| `etat-connectivite` | gw, full | Vérifie périodiquement si le central répond, écrit l'état dans un volume partagé (`etat_connectivite.py`) — source de vérité unique pour tout futur composant qui en a besoin (bannière, écran de statut). |
| `db`, `mosquitto`, `backend`, `frontend` | full | Instance assista-crise locale, identique au déploiement central. |
| `telecharger-tuiles` | full | Conteneur one-shot : télécharge les tuiles du département + limitrophes (`telecharger_tuiles.py`). |
| `tileserver` | full | Sert les tuiles téléchargées (`maptiler/tileserver-gl`) ; pas encore utilisé par le frontend (voir DOCUMENTATION.md, chantiers ouverts). |
| `annoncer-backend-local` | full | Annonce ce backend en mDNS sur le LAN, pour qu'un satellite GW séparé sur le même site le trouve sans IP configurée à la main. |
| `meshtastic-bridge` | gw, full | Optionnel — pilote un ou plusieurs `CompagnonMeshtastic` (MQTT, TCP ou SERIE) ; voir la note ci-dessous. |
| `sync-sortant` | full | Pousse périodiquement vers le central les écritures locales en attente — voir "Synchronisation local → central" ci-dessous. |
| `sync-entrant` | full | Sens inverse : applique localement le rafraîchissement central → local pour Dossier/Mission. |
| `appliquer-config-proxy` | gw, full | Reconfigure `meshcore-proxy` à distance (voir "Reconfiguration distante" ci-dessous), sans action locale/SSH. |

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
docker compose --profile outillage run --rm detecter-noeud
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

Décidée le 2026-09-18, périmètre v1 du sens LOCAL -> CENTRAL (`EvenementSynchronisation`) : le
travail des acteurs institutionnels sur place pendant une coupure — `Dossier` (+ son fil
`DossierCommentaire`/`DossierHistorique`), `DeclarationSecurite`, `Mission`, `MessageMeshLog`.
PAS `Request`/`Offer`/`Information` dans CE sens (citoyens, alimentés via internet, jamais via
le LAN privé d'un satellite) — voir `backend/core/sync_outbox.py` pour ajouter un modèle plus
tard sans redesign. Le sens CENTRAL -> LOCAL (`donnees()`/`sync-entrant`, voir plus bas) couvre
lui ces trois modèles en plus de Dossier/Mission — une demande soumise par un citoyen au site
public doit redescendre vers le satellite, même si elle ne remonte jamais.

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
