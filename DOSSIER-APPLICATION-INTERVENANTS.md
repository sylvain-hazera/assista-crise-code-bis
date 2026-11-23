# Application mobile des intervenants — dossier de conception

État : **lots 0 à 4 écrits en grande partie le 14/11/2026, protocoles radio portés** (voir § 15). Document de travail du 13/11/2026, **révisé le
14/11/2026** sur trois arbitrages de Sylvain : pas d'ordre de priorité entre les deux radios,
chat natif dès que possible, grand public dans la v1 (§ 1, § 9, § 10, § 13). Le titre garde
« intervenants » par continuité ; l'application sert désormais aussi les citoyens.

Ce dossier décrit ce qu'il faut construire et pourquoi, pas comment le coder. Chaque décision
structurante porte sa raison : un plan dont on a oublié les raisons se refait entièrement au
premier imprévu.

---

## 0. Android d'abord

Décision du 13/11/2026 : **la v1 est Android.** iOS plus tard, sans date.

- **Pas de Mac, pas de compte Apple requis pour commencer.** Le matériel nécessaire est déjà là.
- **KMP reste le choix**, avec **une seule cible compilée**. Son coût n'est pas dans la
  structure mais dans l'ajout de la cible iOS : modules KMP et logique dans `commonMain`
  aujourd'hui, et iOS devient un ajout plutôt qu'une réécriture. Android pur coûterait à peine
  moins maintenant, et beaucoup plus ensuite.
- **La seule discipline à tenir** : tout ce qui est spécifique à la plateforme reste mince et
  confiné dans `androidMain`. Si la logique métier fuit vers l'interface, la cible iOS devient
  une réécriture — et c'est le genre de dette qu'on ne voit qu'au moment de payer.
- **Compose Multiplatform ou SwiftUI : reporté**, et c'est mieux ainsi — la décision se prendra
  en sachant ce que l'application fait.
- **La clause d'exception App Store sort du chemin critique** : les conditions de Google Play ne
  posent pas le problème de celles d'Apple. Elle reste nécessaire pour iOS, elle ne bloque plus
  rien. À poser au juriste en même temps que la question de la réécriture *clean room* du
  PhoneAPI : même dossier, une seule consultation.

### Où vit le code

**Dans ce dépôt**, sous `mobile/` (décision du 13/11/2026). Raison décisive : ce qu'il ne faut
surtout pas laisser diverger, ce sont les modèles et leurs règles de validation (§ 5). Dans deux
dépôts, la divergence est une question de temps ; dans un seul, elle se voit au diff.

Conséquences à prévoir : entrées Gradle/Android dans `.gitignore` (`build/`, `.gradle/`,
`local.properties`), un `scripts/tester-mobile.sh` sur le modèle de `tester-frontend.sh`, une
section dans `DOCUMENTATION.md`, et une clause d'exception de licence qui nomme les chemins
`mobile/` plutôt que le dépôt entier.

### État de la chaîne d'outils (vérifié le 13/11/2026)

| | État |
|---|---|
| JDK | **21.0.13 présent** — convient à KMP et à l'AGP |
| SDK Android | **installé le 14/11/2026** dans `~/Android/Sdk` (plateforme 35, outils de build, émulateur) |
| JDK complet | le poste n'avait que le JRE : JDK 21 posé dans `~/.local/opt` |
| Gradle | par le lanceur du projet (`mobile/gradlew`), rien à installer |

**Ça ne bloque pas le démarrage.** Les modules `:shared` qui portent la logique testable —
codecs des deux protocoles, file d'attente, machine à états du lien, règles de domaine — se
compilent et se testent avec **le JDK seul**, via une cible JVM de test. Le SDK Android n'est
requis qu'au moment de construire l'application elle-même.

Android Studio sera de toute façon nécessaire côté Sylvain pour le débogage sur appareil
(`adb`), donc c'est lui qui apportera le SDK.

## 1. Décisions actées

| Sujet | Décision | Conséquence |
|---|---|---|
| Équipe | Sylvain + assistant | **Base de code unique obligatoire.** Deux applications natives, c'est deux compétences à tenir |
| Distribution | Play Store **public** en v1, App Store ensuite | Aucun code sous licence contaminante embarquable (contrainte Apple, anticipée dès maintenant) |
| Radios | **MeshCore et Meshtastic**, les deux en v1 | Couche d'abstraction indispensable dès le premier jour |
| Priorité entre radios | **Aucune** (14/11/2026) : l'application utilise celle qui est connectée | Un intervenant a rarement les deux. Ni réglage ni choix à l'écran ; l'ordre de *construction* (MeshCore puis Meshtastic) n'est qu'un ordre de travail |
| Public | **Intervenants et grand public dès la v1** (14/11/2026) | Une seule application, deux modes (§ 13). Le mode citoyen n'est plus « conçu, pas construit » |
| Chat | **Natif sur le Synapse existant, dès que possible** (14/11/2026) | `matrix-rust-sdk` entre dès le lot 1 (§ 9). Element X n'est plus requis sur le téléphone |
| Licence | AGPL-3.0 + exception App Store, **portée étroite** | Ne couvre que ce qui descend dans le binaire |
| Travail de `sauveteur71` | **Hors périmètre** | Aucun accord à demander, rien à faire descendre |

---

## 2. Ce qu'on ne construit pas, et pourquoi

Dire ce qu'on exclut vaut mieux que de le redécouvrir en cours de route.

- **Pas de fork d'Element X.** Double licence AGPL / commerciale : un fork AGPL n'est pas
  publiable sur l'App Store. Et c'est un *messager* ; nous faisons une *application de terrain
  qui contient de la messagerie*. Greffer missions, carte et radio dans son architecture
  (Appyx, FFI Rust) ferait un chantier de fusion permanent à chaque version amont.
- **Pas de reprise des applications Meshtastic.** GPL-3.0.
- **Pas de reprise de `meshcore-sar`.** Aucune licence déclarée, donc tous droits réservés.
  Reste une excellente référence fonctionnelle.
- **Pas de messagerie vocale** (le *push-to-talk* Codec2 de meshcore-sar) — écarté
  explicitement.
- **Pas d'intégration TAK**, présente dans les deux applications Meshtastic : hors de la chaîne
  de commandement d'Assista-Crise.
- ~~Pas de configuration de la radio depuis l'application.~~ **Levé le 22/11/2026** à la demande
  de Sylvain : un interrupteur « Utilisateur radio avancé » ouvre l'intégralité des menus
  (canaux, contacts, réglages, outils) de Meshtastic et de MeshCore. L'écran simple reste celui
  de l'intervenant ordinaire.
- **Pas d'application montre, pas de fox hunt.**

---

## 3. Architecture

### Kotlin Multiplatform, et la raison du choix

La pièce irremplaçable y est officiellement supportée.

| Besoin | Solution | Pourquoi elle décide |
|---|---|---|
| Matrix (lot 1) | `matrix-rust-sdk`, **bindings Kotlin officiels**, Apache-2.0 | Le moteur exact d'Element X, sans son interface ni sa licence. Le chiffrement de bout en bout est ce qu'on ne peut pas écrire à moitié |
| Bluetooth | `Kable`, BLE multiplateforme | **C'est déjà celle de Meshtastic-Android**, passé à KMP. Le chemin est balisé par ceux qui font la radio |
| Carte | MapLibre, SDK natifs Android et iOS | Lit le **même PMTiles** que les satellites produisent déjà |
| Géoloc arrière-plan | Code natif par plateforme | Travail connu, aucune inconnue |

Flutter inverse le risque : écosystème périphérique plus simple, mais le trou tombe sur Matrix
— le SDK Dart disponible est AGPL, donc inutilisable pour un store public, et il faudrait
écrire nous-mêmes un pont FFI vers le SDK Rust.

### Modules

```
:shared:domaine        modèles, règles de validation, états de mission
:shared:donnees        base locale, file d'attente sortante, client API
:shared:lien           ABSTRACTION du lien de terrain  ← le contrat central
:shared:lien:meshcore   protocole companion sur Nordic UART
:shared:lien:meshtastic  protobuf sur son service BLE
:shared:carte          sources de tuiles, couches, points
:androidApp / :iosApp  interface + géoloc + BLE natif
```

`:shared:domaine` est le seul module partagé conceptuellement avec le backend : c'est lui que
l'exception de licence couvre, et c'est le seul dont la divergence ferait un bug de crise. Un
statut de mission qui dérive entre serveur et application ne se voit qu'au pire moment.

---

## 4. La couche de secours — le contrat central

C'est la décision la plus structurante du dossier. **L'application ne nomme jamais Meshtastic
ni MeshCore.** Elle dit : « envoie ceci », « j'ai perdu le réseau », « voici ce qui arrive ».

```kotlin
interface LienTerrain {
    val etat: Flow<EtatLien>                  // INTERNET | MESH | AUCUN
    val capacites: Capacites                  // octets utiles, débit, photos possibles
    suspend fun envoyer(m: MessageSortant): Resultat
    val entrants: Flow<MessageEntrant>
}
```

### Ce qui rend cette abstraction difficile : la taille

C'est le point qu'on ne peut pas découvrir en cours de route.

| Réseau | Charge utile | Conséquence |
|---|---|---|
| MeshCore | **176 octets** de trame (mesuré dans MeshCrossway ; la doc du format de paquet annonce 184) | Un UUID coûte 16 octets. Le modèle de données habituel **ne rentre pas** |
| Meshtastic | ~237 octets | Idem |
| 4G | sans objet | Tout passe |

Deux conséquences dures :

1. **Les messages sont typés par ce qu'ils peuvent traverser.** `TransmissibleParMesh`
   (position, point déclaré, changement de statut, détresse) et `InternetSeulement` (photos,
   pièces jointes, fil de discussion). Ce typage vit dans le **domaine**, pas dans la couche
   réseau : c'est ce qui empêche structurellement de mettre une photo de 2 Mo dans une file de
   184 octets, au lieu de le découvrir par un échec silencieux.
2. **Un encodage compact dédié au mesh**, distinct du JSON de l'API : latitude et longitude en
   virgule fixe sur 4 octets (environ un mètre), type de point sur un octet, horodatage en
   delta, et **identifiants courts** — une séquence locale par crise, pas des UUID. Sans ça,
   une position ne tient pas dans un paquet.

### Ce que « les deux radios » veut dire, et ce que ça ne veut pas dire

**Une radio ne fait pas les deux protocoles.** L'intervenant porte une radio MeshCore *ou* une
radio Meshtastic. Donc :

- l'application parle **à celle qu'il porte**, quelle qu'elle soit — c'est la couverture d'un
  parc mixte, et c'est tout ce que « les deux en v1 » achète ;
- elle ne fait **pas** communiquer un intervenant MeshCore avec un intervenant Meshtastic.

**Règle de choix (14/11/2026) : il n'y en a pas.** L'application se sert de la radio
appairée et connectée, sans préférence pour un protocole. Le cas où les deux sont connectées
en même temps est rare ; il se règle par « la première connectée garde la main », sans écran
de réglage. `LienTerrain` n'expose d'ailleurs qu'un état `MESH` : rien au-dessus ne sait
laquelle des deux radios porte le message.

Cette interopérabilité-là existe déjà, **côté serveur**, par les deux ponts d'Assista-Crise.
Deux intervenants sur des réseaux différents se parlent *via le central*, jamais via leurs
téléphones. Rien à construire sur mobile pour ça.

### Antériorité : MeshCrossway (MIT)

`FriendlyNGeeks/meshcrossway` — firmware ESP32 d'un terminal portable qui pilote **deux
modules radio** par BLE, l'un Meshtastic (protobuf PhoneAPI), l'autre MeshCore (protocole
binaire Companion). 756 commits, **licence MIT**.

Ce n'est pas une passerelle — le README l'écrit : *« It does not bridge or mix traffic between
the networks »* — mais c'est le **précédent exact de notre problème le plus difficile** : un
appareil unique en rôle BLE central, parlant simultanément aux deux protocoles.

Trois usages pour nous :

1. **Référence de code juridiquement lisible** pour les deux clients BLE — nos autres
   références sont sans licence (`meshcore-sar`) ou GPL (applications Meshtastic) ;
2. **il confirme l'architecture du § 4** : *separate protocol adapters*, aucun modèle de
   message unifié, abstraction au niveau du domaine ;
3. **il répond à la question GPL du lot 6** — vérifié le 13/11/2026 en lisant leur code.

**Vérification faite : ils ont écrit leur propre encodage protobuf.**
`meshcrossway_meshtastic_protocol.h`, 767 lignes, un seul fichier : lecteur et écrivain varint
maison (`struct Reader`, `struct Writer`), numéros de champs codés en dur. Aucun `.proto`,
aucun `*.pb.h`, aucun nanopb, aucun `pb_encode`/`pb_decode`. L'en-tête déclare *« No upstream
.proto/generated binding/firmware code is compiled into this client »*, et
`THIRD_PARTY_NOTICES.md` que les sources GPL-3.0 *« were consulted only to understand
interoperability »*. Aucune licence GPL déclarée, `LICENSES/` n'en contient aucune.

- **Ce que ça règle** : un client PhoneAPI tient dans un fichier, avec une poignée de numéros
  de champs. La voie du lot 6 est démontrée faisable.
- **Ce que ça ne règle pas** : c'est leur déclaration, pas une validation juridique, et
  « consultées pour comprendre l'interopérabilité » est la zone grise d'une réécriture *clean
  room*. Preuve d'ingénierie solide, preuve juridique à faire confirmer.

### Faits de protocole relevés dans leur code

| | MeshCore | Meshtastic |
|---|---|---|
| Service BLE | `6e400001-…` (Nordic UART) | `6ba1b218-15a8-461f-9fa8-5dcae273eafd` |
| Écriture | RX `6e400002-…` | ToRadio `f75c76d2-…` |
| Lecture | TX `6e400003-…` (notification) | FromRadio `2c55e69e-…` (lecture longue) + FromNum `ed9da18c-…` (notification) |
| Cadrage | 1 octet de commande + charge utile, **ni début ni longueur**, une trame par écriture GATT | un protobuf complet par écriture |
| Taille | **176 octets max**, **MTU ATT ≥ 155 exigé** | — |
| Commandes | ~60 codes, jusqu'à 66 | — |

La trame MeshCore fait donc **176 octets** et non 184 comme le laissait penser la documentation
du format de paquet : c'est la valeur à retenir pour dimensionner l'encodage compact du § 4.
Les canaux `#nom` dérivent leur clé d'un **SHA-256 tronqué à 16 octets**.

### Deux niveaux de contrat, et non un

Leur code n'a **aucune interface commune** : ni classe de base, ni méthode virtuelle. Les deux
clients sont instanciés à la compilation par une macro. Pourtant leurs deux API ont exactement
la même forme — `attach`, `detach`, `receive`, `next`, `write_done`, `fail`.

Ils ont donc convergé sur un contrat sans le formaliser, et ce contrat est de **transport**,
pas de domaine. D'où la précision à apporter ici :

- **contrat de transport** (par radio) : ouvrir, fermer, pousser des octets, en recevoir,
  signaler un échec. C'est ce que leur code montre, et c'est là que vivent les UUID, le
  cadrage, les codes de commande ;
- **contrat de domaine** (`LienTerrain`, ci-dessus) : « envoie cette position », « j'ai perdu
  le réseau ». Il ne connaît aucun des deux protocoles.

Confondre les deux niveaux est l'erreur qui ferait remonter des codes de commande jusque dans
l'interface.

Avertissement du projet, qui vaut aussi pour nous : *« not certified for safety-critical use.
Do not rely on it as the sole communication device in a rescue or emergency. »*

### Règles de comportement

- **L'état du lien est affiché en permanence**, ainsi que ce qui attend d'être envoyé. Un
  intervenant qui croit avoir transmis est plus dangereux qu'un intervenant qui sait que non.
- **La bascule est automatique mais jamais silencieuse** : perdre la 4G change l'indicateur,
  pas le comportement de l'utilisateur.
- **Les photos ne partent jamais sur le mesh.** Elles attendent le retour du réseau, et
  l'interface le dit.

---

## 5. Données embarquées et synchronisation

### Le principe : des événements, pas des états

Un point déclaré à 14 h 32 est un **fait** : il ne peut pas entrer en conflit avec quoi que ce
soit. Un statut de mission est un **état** : deux écritures concurrentes se contredisent.

- **Append-only** : points déclarés, positions, messages, déclarations de détresse. Jamais de
  conflit possible.
- **État remplaçable** : statut de mission, priorité. Le serveur fait autorité ; la vue locale
  est marquée **« non confirmé »** tant qu'il n'a pas accusé réception.

Le backend a déjà ce vocabulaire — `sync_outbox.py`, groupes `APPEND_ONLY` / `MUTABLE`,
`ConflitSynchronisation`. **L'application doit réutiliser le même**, sinon deux mécanismes de
synchronisation voisins divergeront, ce qui est précisément le piège documenté au § 2b du plan
satellite.

### La file d'attente sortante

Tout passe par elle, y compris en 4G. C'est ce qui rend l'application utilisable le jour où
elle sert :

- persistée sur disque — un redémarrage du téléphone ne perd rien ;
- ordonnée, avec réessai et recul progressif ;
- **visible** : l'utilisateur voit ce qui attend et depuis quand ;
- purgée seulement sur accusé de réception du serveur, jamais sur « envoi tenté ».

---

## 6. Géolocalisation — en mission, et uniquement en mission

### Le cycle

1. **Le démarrage exige le serveur, l'arrêt jamais.** C'est une asymétrie délibérée, et c'est
   elle qui rend le téléphone autonome sans le rendre dangereux :
   - *démarrer* le suivi demande un engagement **confirmé par le serveur**. Un téléphone hors
     ligne ne décide pas tout seul qu'il est en mission ;
   - *arrêter* ne dépend que du téléphone : fin de mission reçue, **plafond dur** (12 h
     proposé), ou arrêt manuel. Faire dépendre l'arrêt du serveur produirait exactement ce
     qu'il ne faut pas — un téléphone qui perd le réseau et suit indéfiniment.
2. Conséquence pratique : un intervenant engagé avant de perdre la 4G continue d'enregistrer
   ses positions **en local**, dans la file d'attente, et elles remontent au retour du réseau.
   Le suivi ne s'interrompt pas parce que le central est injoignable — c'est tout l'intérêt.
3. **Indicateur permanent** dans l'application et notification persistante : « votre position
   est partagée ».
4. Arrêt manuel toujours possible, avec la conséquence affichée — on ne piège personne dans un
   suivi qu'il ne peut pas couper.

### Ce que les stores exigent

| Plateforme | Exigences | Risque de revue |
|---|---|---|
| iOS | Autorisation `Always`, `UIBackgroundModes: location`, texte de justification explicite | **Élevé** : Apple refuse les justifications vagues. Souvent une vidéo de démonstration demandée |
| Android | `ACCESS_BACKGROUND_LOCATION`, service de premier plan de type `location`, formulaire de déclaration Play | Moyen, mais le formulaire est à remplir sérieusement |

La justification qui passe est la vraie : *sécurité d'intervenants déployés en crise, suivi
limité à la durée d'une mission, indicateur visible en permanence, arrêt automatique.* C'est
aussi, accessoirement, ce qui rend l'application acceptable aux bénévoles — qui ont le droit de
refuser d'être suivis le reste du temps.

**À concevoir, pas à corriger : le budget batterie.** Une application de crise qui vide le
téléphone en quatre heures est dangereuse. Cadence de position adaptative selon le déplacement
et l'état du lien, décidée dès le départ.

---

## 7. Bluetooth et secrets

La radio chiffre, pas l'application — vérifié sur notre propre intégration : `meshcore-bridge`
envoie `send_msg(pubkey, contenu)` avec le **contenu en clair** et provisionne un canal par
`set_channel(index, nom, secret)` en passant **la clé brute**.

Bonne nouvelle pour le coût : aucune cryptographie à implémenter côté mobile.

Mauvaise nouvelle, et elle est sérieuse : **le lien téléphone ↔ radio transporte du clair et
des clés de canal**. À portée Bluetooth, un tiers non appairé lit les messages et extrait les
clés.

Deux règles non négociables :

1. **Appairage chiffré obligatoire**, avec code PIN — la documentation MeshCore le donne en
   option, chez nous il ne l'est pas.
2. **Les clés de canal vivent dans le Keystore Android / Keychain iOS**, jamais dans un
   stockage applicatif ordinaire. C'est la transposition mobile de la règle du projet : *on ne
   stocke rien en clair* — ici, *on ne transmet rien en clair sur les dix derniers mètres*.

Sur iOS, recevoir du mesh en arrière-plan demande le mode `bluetooth-central` : une
justification de plus à la revue.

---

## 8. Carte

**Fournisseur de tuiles en ligne classique**, comme le fait déjà l'application web. Pas de
chaîne PMTiles côté mobile, pas de fabrication d'extrait départemental, pas de téléchargement
préalable. Décision du 13/11/2026 : le téléphone n'a pas à dépendre de notre infrastructure
pour afficher un fond de carte.

**La conséquence à assumer, et elle vise le cœur du projet** : sans réseau, plus de fond de
carte. Or l'intervenant qui perd la 4G est précisément celui qui en a besoin. Tout le reste de
l'application bascule sur le mesh ; la carte serait la seule chose qui ne bascule pas.

L'entre-deux retenu ne change ni de fournisseur ni de chaîne : **le cache de tuiles de
MapLibre**, présent dans les SDK Android et iOS. Deux effets, pour quelques lignes :

- les tuiles **déjà consultées** restent disponibles hors ligne — le secteur de l'intervenant
  se met en cache du simple fait qu'il l'a regardé ;
- un bouton **« embarquer ce secteur »** (API de région hors ligne) couvre ce qu'il n'a pas
  encore ouvert.

Ce qui est déclaré sur la carte — positions, points, traces — n'a jamais dépendu des tuiles :
c'est de la donnée vectorielle locale, elle s'affiche même sur fond vide.

### Fournisseur retenu : IGN Géoplateforme

Le critère décisif n'est ni le prix ni le rendu, c'est **le droit de mettre en cache**.

| Fournisseur | Cache / hors ligne | Coût | Verdict |
|---|---|---|---|
| **IGN Géoplateforme** | **Licence Ouverte Etalab 2.0** : réutilisation, rediffusion et modification autorisées → cache et paquets hors ligne permis *par la licence* | Gratuit | **Retenu** |
| Mapbox | Hors ligne supporté mais **préchargement, empaquetage et rediffusion interdits**, et **facturation à la tuile téléchargée** | Payant au volume | Écarté |
| MapTiler | Offre gratuite **non commerciale / R&D seulement** ; cache limité à « un cache personnel temporaire pour un seul utilisateur final » | Payant | Écarté |
| OSM en direct | Usage applicatif à l'échelle proscrit | — | Écarté |

Mapbox est le piège : **chaque tuile téléchargée par chaque bénévole est facturée**. Une flotte
qui embarque son secteur, c'est un coût non plafonné décidé par les utilisateurs.

Quatre raisons, dont une qui n'est pas technique :

1. la licence **autorise** ce que les autres facturent ou interdisent ;
2. gratuit, donc sans coût croissant avec le nombre de bénévoles ;
3. **c'est la cartographie des services publics français** — en crise, regarder la même carte
   que la préfecture et la mairie est un argument opérationnel, pas esthétique ;
4. le projet **parle déjà à `data.geopf.fr`** pour l'altimétrie : même plateforme, même
   attribution, un tiers de moins.

**Faiblesse à ne pas minimiser : aucune garantie de service.** L'IGN l'écrit noir sur blanc, et
affiche 99,5 % de disponibilité visée sur les tuiles vectorielles. Deux parades : le cache
agressif — précisément ce que la licence autorise — et un **style de repli commutable** vers un
second fournisseur. La carte ne doit pas dépendre d'un seul service.

À vérifier avant d'engager (sources contradictoires, pages officielles inaccessibles depuis
ici) : la **politique de clé actuelle** et l'existence d'un **quota de tuiles** documenté. Le
seul plafond explicite trouvé — 5 requêtes/s par IP — porte sur l'API d'altimétrie.

Nuance : l'IGN diffuse aussi les **orthophotos**, très utiles en crise pour voir le terrain
réel. Mais **SCAN 25 reste sous licence IGN, pas sous Etalab** — à ne pas mettre dans le même
panier. Attribution IGN obligatoire dans tous les cas.

Autre point à régler avant la mise en magasin : l'application web pointe aujourd'hui sur un
**style tiers hébergé sur `raw.githubusercontent.com`** (`go2garret/maps`), qui renvoie vers
les serveurs OSM. Acceptable pour une page web ; comme source cartographique d'une application
de terrain, c'est un point de défaillance unique sans engagement de service.

---

## 9. Chat : natif, dès que possible

Décision du 14/11/2026, qui remplace la délégation à Element X : **le chat est dans
l'application**, sur le Synapse existant, et il arrive juste après le socle (lot 1).

- **Moteur** : `matrix-rust-sdk` par ses liaisons Kotlin officielles (Apache-2.0). C'est le
  moteur d'Element X sans son interface ni sa licence ; le § 2 reste vrai, on ne forke rien.
- **Une seule identification.** Synapse délègue déjà sa connexion à Django par OIDC
  (`core/oidc.py`, `/o/authorize/`). L'application ouvre donc sa session Matrix par ce même
  SSO : aucun second mot de passe, aucun compte à créer à la main.
- **Les salons existent déjà.** Salons d'équipe et d'institution sont provisionnés par le
  backend (`provisionner_salons_equipe`, `SalonMatrixEquipeViewSet`,
  `SalonMatrixInstitutionViewSet`). L'application affiche ceux du compte, elle n'en invente pas.
- **Chiffrement de bout en bout** : géré par le SDK. Ce qui reste à notre charge est la
  vérification d'appareil et la sauvegarde des clés — sans elles, un téléphone remplacé perd
  l'historique chiffré. À traiter dans le lot 1, pas après.
- **Hors réseau** : le fil de discussion Matrix ne passe pas sur le mesh (`InternetSeulement`,
  § 4). Les messages courts par radio restent ceux d'Assista-Crise, relayés par les ponts ; ils
  s'affichent dans le même écran, marqués « radio ».

Ce que ça coûte : la pièce la plus lourde du projet entre tôt, et la taille du binaire grossit
(bibliothèque Rust embarquée). Ce que ça achète : une seule application sur le téléphone, et un
lien direct entre une mission et son salon.

---

## 10. Découpage en lots

Chaque lot se termine sur quelque chose de **vérifiable**. Sans critère, on ne sait jamais si
un lot est fini. Découpage révisé le 14/11/2026.

| Lot | Contenu | Fini quand |
|---|---|---|
| **0** | Socle KMP **cible Android seule**, authentification, missions, file d'attente, indicateur de lien | Un intervenant voit ses missions, déclare un changement de statut en mode avion, et le voit partir au retour du réseau |
| **1** | **Chat natif Matrix** : session par le SSO Django, salons d'équipe et d'institution, chiffrement, sauvegarde des clés | Un message chiffré est échangé avec Element Web dans un salon d'équipe, sans seconde saisie de mot de passe, et l'historique survit à une réinstallation |
| **2** | Carte, ma position, position des équipes, points déclarés + photos en 4G | Un point déclaré sans réseau apparaît sur le central au retour du réseau, photo comprise |
| **3** | **Mode grand public** (§ 13) : informations de la commune, demande, offre, signalement, « je vais bien / j'ai besoin d'aide » | Un citoyen dépose une demande en mode avion, elle arrive au central au retour du réseau, et il en suit l'état |
| **4** | Géoloc en mission uniquement, consentement, arrêt automatique, service de premier plan | Le suivi démarre à l'engagement, s'arrête à la fin, et l'indicateur est visible en permanence. Consommation batterie mesurée sur 8 h |
| **5** | **Première radio** (MeshCore) derrière l'abstraction, bascule à trois états, SOS sur toutes les voies | Une position et un point traversent le mesh, téléphone en mode avion, appairage PIN exigé |
| **6** | **Seconde radio** (Meshtastic) derrière la même abstraction | Idem, **sans une ligne modifiée** dans les lots 0 à 4 — c'est le test de l'abstraction |

Le critère du lot 6 est le seul qui juge la conception : si brancher la seconde radio oblige à
toucher au domaine, c'est que l'abstraction a épousé la forme de la première.

Les lots 5 et 6 partent moins de zéro qu'au 13/11 : les deux protocoles ont depuis été écrits
par nous en TypeScript pour le relais navigateur (`frontend/src/app/shared/mesh/` — cadrage,
poignée de main, encodage protobuf minimal), et vérifiés contre les bibliothèques de
référence. Les porter en Kotlin est une traduction, plus une découverte.

---

## 11. Risques et inconnues

| Risque | Gravité | Ce qu'on fait |
|---|---|---|
| **Protobufs Meshtastic en GPL-3.0** | **Abaissé** (13/11/2026) | Antériorité vérifiée : MeshCrossway (MIT) écrit son propre encodage varint, 767 lignes, sans aucun `.proto` ni nanopb. La voie est démontrée faisable. Reste à faire **confirmer juridiquement** la réécriture *clean room* — leur déclaration n'en est pas une |
| **Spécification MeshCore « en développement »**, V2 en discussion | Moyen | L'abstraction isole le choc. Épingler une version de firmware de référence |
| **Compose Multiplatform sur iOS** | Moyen | Repli : socle KMP partagé + interface SwiftUI native. À trancher au lot 0, pas après |
| **Revue App Store sur la géoloc d'arrière-plan** | Élevé | Justification honnête, indicateur visible, arrêt automatique. Prévoir une vidéo de démonstration |
| **Batterie** | Élevé | Mesuré au lot 4, pas en fin de projet |
| **Chat natif tôt dans le projet** (14/11/2026) | Élevé | Le lot 1 est le plus lourd et arrive en deuxième. S'il dérape, il retarde tout : lui fixer un périmètre strict (texte, salons existants, chiffrement), sans appels, sans fils, sans réactions |
| **Grand public sur le Play Store** (14/11/2026) | Moyen | Une application ouverte à tous attire la revue sur les données personnelles et la position : le mode citoyen ne suit jamais en arrière-plan (§ 13) |
| **Carte muette sans réseau** | Moyen | Cache MapLibre + région hors ligne à la demande. Contrainte par les conditions du fournisseur, à trancher avant le lot 2 |

---

## 12. Ce qui reste à décider

1. **La clause d'exception App Store** : à ajouter au dépôt, ou à faire relire d'abord. Elle
   est rédigée, de portée étroite, et ne couvre que la colonne de gauche du § 3.
2. **`CONTRIBUTING.md` + DCO** : à poser tant qu'il n'y a presque aucun contributeur extérieur.
   Sans ça, chaque contribution future crée un co-détenteur dont l'accord serait nécessaire pour
   publier sur iOS.
3. **Compose Multiplatform ou SwiftUI** côté iOS : à trancher au lot 0.
4. **Fournisseur de tuiles : tranché — IGN Géoplateforme** (voir § 8). Restent à vérifier la
   politique de clé et le quota de tuiles, et à choisir le **second fournisseur de repli**,
   l'IGN n'offrant aucune garantie de service. À remplacer avant la mise en magasin : le style
   tiers hébergé sur GitHub qu'utilise le web aujourd'hui.

---

## 13. Grand public (décidé le 14/11/2026)

**Une seule application, deux modes**, choisis par le compte et non par un réglage : un compte
rattaché à une institution ouvre le mode intervenant, tout autre compte le mode citoyen. Deux
applications, ce serait deux fiches de store et deux revues pour une équipe de deux.

Ce que fait le mode citoyen, et qui existe déjà côté serveur :

- lire les informations et alertes de sa commune ;
- déposer une demande, une offre, un signalement, et en suivre l'état ;
- se déclarer « je vais bien » ou « j'ai besoin d'aide » (`DeclarationSecurite`) ;
- déclencher un SOS, par Internet ou par sa radio s'il en a une (`AlerteMeshSOS`).

Trois règles qui le séparent du mode intervenant :

1. **Aucun suivi de position.** La position n'est lue qu'au moment d'un geste (une demande,
   un SOS), jamais en arrière-plan. Le § 6 ne s'applique qu'aux intervenants en mission.
2. **Rien de l'intervenant n'est visible** : ni missions, ni position des équipes, ni salons.
3. **Tout passe par la même file d'attente** (§ 5) : une demande déposée sans réseau part au
   retour du réseau, et l'écran le dit.

Proposé, non tranché : **pas de chat pour les citoyens en v1.** Leur ouvrir Synapse pose des
questions de modération qu'une application de crise ne doit pas découvrir en production.

## 14. Repris du document du 22/10/2026

Le document « Assista-Crise Mobile — Architecture » avait été écrit sans connaître le
backend ; il faisait de Matrix la colonne vertébrale, ce qui n'est pas retenu. Six de ses
idées manquaient ici et sont reprises :

| Idée | Où elle va |
|---|---|
| **Bascule à trois états** : Internet perdu après 60 s sans échange réussi, retour après 2 min sans échec, les deux voies actives pendant la stabilisation | `:shared:lien`, lot 5. Les seuils sont des paramètres, à régler aux essais |
| **SOS sur toutes les voies à la fois**, quel que soit l'état | Règle de comportement du § 4 |
| **Trame de position de 16 octets**, cycle de 15 min en radio, envoi immédiat sur SOS ou changement de statut | Précise l'encodage compact du § 4. Les deux ponts doivent apprendre à la décoder |
| **Dédoublonnage** par intervenant et horodatage GPS, quand une position arrive par deux voies | Côté serveur, à l'ingestion |
| **Service de premier plan**, exemption d'optimisation batterie demandée au premier lancement, guide de réglage par marque (Xiaomi, Samsung, Huawei) | `:androidApp`, lot 4 |
| **Alerte côté cellule** quand une position vieillit au-delà de 20 min | Côté web, hors application |

Non repris : les positions dans un salon Matrix (MSC3489), la passerelle LoRa → Matrix, la
table nœud ↔ compte dans un salon d'administration, le tableau de bord à écrire. Le backend
fait déjà chacune de ces choses.

Reste ouvert : **la bascule vers le satellite de la collectivité** quand le central est
injoignable (le satellite s'annonce déjà en mDNS, `_ac-local._tcp.local.`). Proposée pour le
lot 0, non décidée.

---

## 15. État des lots (14/11/2026)

Code sous `mobile/`, construit par `scripts/tester-mobile.sh`. Première marque : Réserve
Résilience (`org.reserve_resilience.app`, serveur `app.reserve-resilience.org`).

| Lot | État | Ce qui manque |
|---|---|---|
| **0** Socle | **fait** | — |
| **1** Chat | **messagerie d'équipe faite, par le serveur** | le client Matrix natif (voir ci-dessous) |
| **2** Carte | **fond IGN, ma position, positions des équipes** | points déclarés par un intervenant, photos, région hors ligne à la demande |
| **3** Grand public | **fait pour trois gestes** : en sécurité, demander de l'aide, signaler | offre d'aide, photo, suivi de mes dépôts, SOS |
| **4** Géoloc en mission | **fait** | mesure de batterie sur 8 h, envoi de la file application fermée |
| **5** MeshCore | **messages d'équipe par le canal radio, écrits et testés hors Bluetooth** | l'essai sur une vraie radio ; la position par radio |
| **6** Meshtastic | **idem, derrière le même pilote** | idem |

Vérifié : 61 tests de la logique partagée, et des parcours complets dans un émulateur contre
un serveur de test — création de compte, connexion, changement de statut serveur coupé puis
envoi automatique, messagerie d'équipe, carte, démarrage du suivi sur engagement et arrêt à la
mise au repos, reprise du suivi après arrêt forcé de l'application, les trois dépôts citoyens.
**Rien n'a encore tourné sur un vrai téléphone ni contre le serveur de production.**

### Lot 1 : pourquoi la messagerie passe par le serveur, et pas encore par Matrix

L'application affiche le **fil unique de l'équipe** (`messagerie-unifiee`) : salon Matrix et
canaux radio, fusionnés par le serveur, qui écrit dans le salon au nom de la personne. C'est
ce que fait déjà la vue équipe du site. Un message y est lisible hors ligne, s'écrit hors
ligne, et part par la file.

Ce n'est pas le « chat natif » décidé au § 9, et il faut le dire :

- **pas de chiffrement de bout en bout sur le téléphone** — le serveur lit les messages pour
  les relayer, comme sur le site ;
- **seulement les salons d'équipe**, pas ceux d'institution ni les messages directs.

Le client natif (`matrix-rust-sdk`) bute sur un point qui ne se règle pas dans le code de
l'application : Synapse délègue sa connexion au service d'authentification Matrix, qui la
délègue à Django. Il faut y **déclarer l'application comme client**, puis essayer la
connexion sur un vrai téléphone contre le vrai serveur. À faire avec Sylvain, pas à l'aveugle.

### Lots 5 et 6 : le canal radio de l'équipe, quand la 4G tombe

Demande de Sylvain du 14/11/2026 : « pense aux canaux Meshtastic ou MeshCore en cas de
coupure 4G ». C'est le cas d'usage qui a guidé ces deux lots.

**Ce que fait l'application.** L'intervenant connecte sa radio dans l'écran Compte. Elle se
décrit (ses canaux), et l'application dit, pour chaque équipe, si son canal s'y trouve. Puis :

- **sans réseau, un message d'équipe part sur le canal radio de l'équipe**, une seule fois.
  Il reste en file, marqué « parti par radio » : les coéquipiers l'ont entendu, le serveur
  pas encore ;
- **au retour du réseau, il est remis au serveur** avec le protocole par lequel il est déjà
  parti (`deja_emis_radio`). Le serveur l'enregistre comme déjà émis sur ce réseau-là — le
  pont ne le rediffuse pas, et l'exemplaire qu'une passerelle aurait entendu est reconnu
  comme son écho — et le fait encore porter à l'autre réseau ;
- **ce que la radio entend sur le canal d'une de mes équipes entre dans le fil**, marqué
  « par radio », et y reste tant que le serveur ne le rend pas lui-même.

L'application ne configure pas la radio (§ 2) : le canal doit déjà y être. C'est le serveur
qui l'y pousse, par message direct, quand un membre équipé rejoint l'équipe.

**Comment c'est construit.** Tout le dialogue est dans des *pilotes* passifs
(`mobile/shared/lien/PiloteRadio.kt`) : on leur donne ce que la radio a dit, ils rendent ce
qu'il faut répondre. Ni attente ni fil d'exécution, donc tout se teste sans radio, sur les
vecteurs des bibliothèques de référence. `LienTerrain` tient sa promesse : au-dessus des
pilotes, plus rien ne nomme un protocole — le lot 6 n'a pas touché aux lots 0 à 4.

**Ce qui n'est pas vérifié, et il faut le lire comme tel.** La couche Bluetooth
(`LiaisonRadio.kt`) — recherche, appairage, écritures, notifications — est écrite d'après
les clients de référence et **n'a jamais parlé à une radio** : il n'y en avait pas, et un
émulateur n'en simule pas. Le premier essai sur du matériel dira ce qui reste à corriger ;
l'appairage et la reconnexion sont les deux endroits où je m'attends à des surprises.

Reste à faire : la **position par radio** (la trame de seize octets existe et se teste, mais
les deux ponts ne savent pas encore la lire, donc elle n'a pas de destinataire), la bascule à
trois états avec ses délais (§ 14), et la radio tenue par le service de suivi, application
fermée.

### Écarts et constats

1. **Un bénévole ne peut pas déclarer de statut.** Le serveur réserve l'écriture d'une mission
   aux rôles institutionnels (`MissionViewSet.get_permissions`). Un simple membre d'équipe voit
   ses missions sans bouton. Lui donner un geste (« j'y suis », « terminé pour moi ») demande
   une action côté serveur, à concevoir.
2. **Seul le compte de particulier se crée dans l'application.** Mairies et secours doivent
   prouver une institution : ce parcours reste sur le site.
3. **Le serveur ne garde que la dernière position** (`ma-position/`), sans horodatage ni
   historique. Le trajet d'un intervenant resté hors réseau n'est donc pas reconstitué au
   retour : seule sa dernière position remonte. Le garder demanderait un point d'entrée qui
   accepte des relevés datés, comme celui du pont Matrix.
4. **Un message réessayé peut arriver deux fois.** Si la réponse du serveur se perd après
   qu'il a enregistré le message, la file le renvoie. Il faudrait que le serveur reconnaisse
   un identifiant de message déjà vu.
5. **Un signalement apparaît aussitôt dans les informations publiées de la crise**, avant
   toute relecture. C'est le comportement du serveur, pas un choix de l'application.
6. **La file ne part que tant que l'application ou le suivi tourne.** L'envoi application
   fermée (WorkManager) reste à faire.
7. **Publication** : `scripts/publier-mobile.sh` construit l'APK et le dépose dans
   `frontend/public/mobile/` ; il est servi par le site à `/mobile/reserve-resilience.apk`.
   C'est un APK de développement, signé par une clé de test : bon pour des essais, pas pour
   le Play Store.
8. **Le mode se déduit du compte et des équipes** : rattaché à une institution, porteur d'un
   rôle institutionnel ou membre d'une équipe, on est intervenant ; sinon citoyen, et l'on ne
   voit que les crises et son compte.
9. **La base locale est un jeu de fichiers chiffrés**, pas encore SQLite. Suffisant à ce
   volume.

Constat utile à la bascule vers le satellite (§ 14) : sur le Wi-Fi d'un satellite coupé
d'Internet, Android juge le réseau « sans connexion ». L'indicateur de lien se fie donc
d'abord à l'échange réel avec le serveur, et seulement à défaut à l'avis du système.

Versions d'outils : Kotlin 2.1.0, AGP 8.7.3, Gradle 8.11.1, MapLibre 11.5.2 — choisies parce
que connues pour aller ensemble, pas parce qu'elles sont les dernières. À monter avant la
mise en magasin.

## 16. Mobiliser par l'application, et savoir ce que le message est devenu (14/11/2026)

Demande : que la messagerie de l'application serve aux campagnes de mobilisation, « avec un
feedback de qui a eu la notif, vu, lu, répondu (une réponse négative est une réponse) », que
l'application ait des notifications, et que le chemin du bénévole y soit possible comme sur le
site. Version **0.4.0**.

### Un cinquième canal de campagne : « Application mobile »

Il s'ajoute à l'email, aux deux SMS et à Matrix dans `core/canaux_campagne.py`, avec la même
honnêteté sur sa portée : il n'atteint que les personnes dont un téléphone a parlé au serveur
dans les 45 derniers jours (`AppareilMobile`). Les autres sont rendues « injoignables » par ce
canal, pas « envoyées » — c'est à elles qu'il faut un SMS.

Ce qu'il apporte et que les autres n'ont pas, ce sont quatre étapes datées par personne
(`NotificationApplication`, titre et corps chiffrés) :

| Étape | Ce qu'elle atteste | Qui l'écrit |
|---|---|---|
| reçu | le téléphone a reçu le message **et le système a accepté de l'afficher** | l'application, après affichage |
| vu | la personne a ouvert la liste des notifications | l'application |
| lu | elle a ouvert le message | l'application |
| répondu | elle a répondu, oui ou non — par l'application **ou par le site** | le serveur |

Deux choix à connaître :

- **Lire la liste n'accuse rien.** C'est le téléphone qui dit ensuite ce qu'il a fait. Déduire
  « reçu » d'un appel réseau compterait comme prévenue une personne dont l'application a planté
  avant d'afficher quoi que ce soit.
- **Notifications coupées = jamais « reçu ».** Le message attend dans l'application ; le suivi
  affiche « notifications coupées sur son téléphone » à côté de la personne.

### « Non » est une réponse

Jusqu'ici, répondre non voulait dire ne rien cocher, donc être relancé. Il y a maintenant un
geste, sur le site comme dans l'application : « Je ne suis pas disponible sur cette période »
(`POST mes-disponibilites/indisponible/`). Il retire les créneaux déjà posés sur la période —
le moteur n'a qu'une règle, « pas de ligne = indisponible » — et sort la personne des relances.

### Défaut trouvé au passage, et corrigé

La page « Ma fiche de bénévole » du site **ne lisait pas** le paramètre `?campagne=` que porte le
lien des emails et des SMS. On arrivait sur l'onglet d'identité, la grille montrait les quinze
prochains jours au lieu de la période demandée, et aucun créneau coché n'était rattaché à la
campagne : le suivi restait à « sans réponse » pour des gens qui avaient répondu. Le serveur,
lui, savait faire depuis l'origine ; c'est l'écran qui ne lui passait rien.

### Les notifications de l'application

Trois sources, un seul relevé (`Veille`, code partagé, le même application ouverte ou fermée) :
les notifications du serveur, les messages d'équipe, les missions nouvelles. Une chose ne sonne
qu'une fois ; ce que la personne a déjà sous les yeux ne sonne pas ; le premier relevé après
connexion prend acte de l'existant sans rien faire sonner.

**Le téléphone vient chercher, il n'est pas réveillé.** Application ouverte, le relevé a lieu
chaque minute. Application fermée, c'est une tâche de fond (WorkManager) : **un quart d'heure
au mieux**, davantage si Android économise la batterie. C'est le prix de l'absence de service de
réveil d'un fabricant (Firebase chez Google), qui demanderait un compte chez lui au nom de
Réserve Résilience et ferait transiter un signal par ses serveurs. Conséquence pratique : une
mobilisation réellement urgente se double d'un SMS — et le suivi dit justement à qui.
Brancher un service de réveil plus tard ne change rien au reste : il n'aura qu'à dire « viens
lire ».

### Le chemin du bénévole dans l'application

| Sur le site | Dans l'application 0.4.0 |
|---|---|
| Créer un compte, se connecter, mot de passe oublié | fait (0.1) |
| Répondre à une campagne | fait — notification, lecture, grille sur la période, « non » |
| Mes disponibilités (15 jours × 4 créneaux) | fait — en ligne seulement, voir ci-dessous |
| Ma fiche (adresse, situation, engagement) | fait |
| Mes justificatifs : état, motif d'un refus | fait en lecture ; **le dépôt d'une pièce reste sur le site** |
| Mes équipes, parler à mon équipe | fait (0.2), y compris sans réseau par la radio |
| Mes interventions : dossiers, statut, itinéraire, appel | fait — statut réservé au chef et au régulateur, comme sur le site |
| Missions, carte, suivi de position | fait (0.2) |
| Demander de l'aide, signaler, se déclarer en sécurité | fait (0.3) |
| Proposer une ressource (hébergement, matériel) | **pas fait** |
| Choisir ou changer son mot de passe depuis sa fiche | **pas fait** (le « mot de passe oublié » existe) |
| Hébergement d'une équipe, priorité et ordre des dossiers | **pas fait** |

**Disponibilités, fiche et statut de dossier exigent le serveur**, contrairement aux messages
et aux statuts de mission. Une disponibilité cochée sans réseau et envoyée trois heures plus
tard arriverait peut-être après que la garde a été constituée, et la personne croirait avoir
répondu. L'écran dit quand le réseau manque, et la case ne change pas.

### Vérifié, et pas vérifié

Vérifié : 19 tests serveur du canal (225 sur le dossier bénévoles), 80 tests du code partagé,
551 tests du site ; et sur téléphone virtuel, contre un serveur de test : campagne envoyée →
le téléphone sonne → le serveur voit « reçu » → ouverture → « vu » et « lu » → créneaux cochés →
« a répondu, 4 créneaux » ; seconde campagne → « non » → « 1 répondu, dont 1 non » ;
fiche ; interventions avec changement de statut ; tâche de fond inscrite auprès du système.

Pas vérifié : le délai réel de la tâche de fond sur un vrai téléphone, écran éteint et en
économie d'énergie — c'est le point à observer en premier.

## 17. Le terrain : dossiers, commentaires, photos tracées, carte (14/11/2026)

Retour de Sylvain sur la 0.4.0 : l'onglet principal montrait les missions sans leurs dossiers ;
l'intervenant doit pouvoir commenter et photographier, dans le circuit de traçabilité existant ;
et la carte doit situer les interventions et permettre de créer du doigt. Version **0.5.0**.

### Les dossiers sous leur mission

L'onglet Missions range chaque dossier sous sa mission (`Dossier.mission`), et montre à part ceux
confiés à l'équipe sans mission — un dossier qu'on ne voit pas est un dossier qu'on ne traite
pas. Toucher une ligne ouvre la fiche du dossier : lieu, contact, appel, itinéraire, statut
(chef et régulateur), photos, commentaires.

### Photos : le circuit existant, appliqué à l'identique

Le serveur avait déjà tout (`DocumentViewSet`) : empreinte SHA-256 du fichier reçu, position lue
dans les métadonnées de la photo et rangée parmi les données réservées à l'équipe, ligne
d'historique au dépôt, journal de chaque consultation. L'application fait l'autre moitié :

| Étape | Où | Ce qui est garanti |
|---|---|---|
| Prise | appareil photo du téléphone, vers un fichier du cache privé | jamais dans la galerie |
| Préparation | `Photographe` | réduite à 2048 px, heure et position **inscrites dans la photo** par l'application |
| Scellé | `Photographe.empreinte` | SHA-256 des octets définitifs, calculé sur le téléphone |
| Attente | magasin chiffré (Keystore) | le fichier en clair est effacé aussitôt ; rien ne reste lisible |
| Envoi | file d'attente | part seule au retour du réseau |
| Contrôle | `Synchronisation.envoyerPhoto` | l'empreinte rendue par le serveur est comparée à celle du téléphone |

Pourquoi l'application écrit elle-même la position : l'appareil photo ne le fait que si la
personne a activé un réglage, et la réduction de l'image l'effacerait. L'écran dit **avant** la
prise ce que la photo emportera (« à 5 m près »), ou qu'elle partira sans lieu. Une empreinte
qui ne correspond pas n'est pas effacée en silence : la photo reste affichée « refusée », avec
la raison.

L'application ne demande pas la permission d'utiliser la caméra : elle confie la prise à
l'appareil photo du téléphone et ne photographie jamais elle-même.

### Qui peut commenter et photographier : corrigé côté serveur

Seuls les « participants » d'un dossier le pouvaient, et cette liste est figée à l'affectation.
Un intervenant entré dans l'équipe le lendemain pouvait donc **voir** les photos mais ni en
ajouter ni commenter. Désormais : les participants, et les membres actuels de l'équipe chargée
du dossier (`_contribue_au_dossier`). La position d'une photo leur est visible aux mêmes
conditions. Le fil de commentaires se filtre enfin par dossier (`?dossier=`).

### La carte

- les **dossiers situés** de mes équipes (orange, rouge si urgent), nommés dans la liste sous la
  carte ; toucher le point ou « Ouvrir » mène à la fiche ;
- les **périmètres des crises** ouvertes ;
- **maintenir le doigt** sur un point propose d'y créer une demande d'aide, un signalement ou
  une offre d'aide, sur la crise choisie. Le lieu touché l'emporte sur la position du téléphone :
  c'est là que ça se passe, pas là où l'on se tient.

L'offre d'aide est nouvelle dans l'application (aussi depuis l'onglet Aide). Elle couvre l'offre
simple — type, quelques mots, lieu, contact ; les précisions propres à l'hébergement ou au
transport restent sur le site.

### Limites connues

- Une mission n'a pas de zone à elle en base : elle est située par ses dossiers. Un dossier n'a
  de position que si la demande ou le signalement d'origine en avait une.
- Les photos se prennent, elles ne se choisissent pas dans la galerie : une photo ancienne
  n'aurait ni l'heure ni le lieu du constat.
- Le serveur garde les fichiers de `Document` sans chiffrement au repos (préexistant, hors de ce
  chantier) — à traiter avec le reste des pièces si la règle « rien en clair » doit s'y étendre.

### Vérifié

8 tests serveur nouveaux (165 sur le dossier « dossiers »), 88 tests du code partagé. Sur
téléphone virtuel : dossier ouvert depuis la mission, commentaire, photo prise → reçue par le
serveur avec la même empreinte, la position du téléphone, la précision et l'heure, et rien de la
position dans les métadonnées publiques ; carte ; offre d'aide créée par appui long et acceptée.
Pas vérifié : un vrai appareil photo (orientation, taille des fichiers), et la prise sans réseau
sur un vrai téléphone.

## 18. Mêmes fonctions des deux côtés : où l'on en est (14/11/2026, version 0.5.1)

Demande de Sylvain : « il faut que j'aie les mêmes fonctions des deux côtés ». Cette section est
l'état de l'écart, tenue à jour à chaque version : ce qui manque y est écrit, pas sous-entendu.

### Ce que la 0.5.1 a mis au niveau du site

- **Demande d'aide, signalement, offre d'aide** : une photo peut être jointe aux trois, depuis
  l'onglet Aide comme depuis la carte.
- **Précisions par type**, comme sur le site (`Precisions`, décrites en données) : hébergement
  offert ou cherché (durée, loyer, logement, niveau et accès, pièces, capacité, animaux, jardin,
  fauteuil roulant, accueil de sinistrés ou d'intervenants, rayon de recherche), transport,
  matériel, soins, soutien psychologique, bénévolat.

Une différence voulue avec les photos de dossier : **la position n'est pas inscrite dans la
photo** d'une demande, d'un signalement ou d'une offre. Ces dépôts sont visibles au-delà d'une
équipe ; le lieu voyage dans le formulaire, où le serveur le protège, et une position cachée
dans l'image y échapperait.

### Ce qui manque encore à l'application

| Fonction du site | État |
|---|---|
| Offre d'engins par catalogue (plusieurs lignes), choix de compétences | pas fait |
| Demande d'hébergement : liste de communes de recherche | pas fait (le rayon l'est) |
| Signalement : direction de prise de vue (boussole) | pas fait |
| Adresse saisie au clavier avec suggestions | pas fait : position du téléphone ou point touché |
| « Je suis en sécurité » : centre d'accueil, régime alimentaire | pas fait |
| Déclarer une crise | pas fait |
| Dépôt d'un justificatif ; profil ; mot de passe | **fait en 0.7.0** (section 20) |
| Hébergement d'une équipe ; priorité et ordre des dossiers | pas fait |
| Recherche de personnes, recensement des dégâts, suivi d'une habitation | pas fait |
| Modifier ou retirer une demande, un signalement, une offre déjà déposés | pas fait |

### Ce que l'application fait et que le site ne fait pas

Fonctionner sans réseau (file d'attente, radio), suivre la position en mission, faire sonner le
téléphone, sceller une photo par son empreinte dès la prise.

### Vérifié

93 tests du code partagé. Sur téléphone virtuel, **depuis la carte** : signalement avec photo
(reçu avec la photo, sans position dans l'image, lieu = point touché) ; demande d'hébergement
avec précisions (durée, étage, capacité reçues) ; offre d'aide (0.5.0).

## 19. QR codes de mobilisation, dès l'ouverture (14/11/2026, version 0.6.0)

Demande : un bouton rapide, dès la page d'accueil et même sans compte, pour lire les QR codes
de mobilisation ; et pour l'intervenant, présenter rapidement le sien. Fait des deux côtés.

| | Application | Site |
|---|---|---|
| Lire un QR code, sans compte | bouton sur l'écran de connexion | bouton sur la page d'accueil |
| Lire un QR code, connecté | bouton en tête de l'onglet Missions | même bouton |
| Présenter mon QR code | « Mon QR code », en tête de l'onglet Missions | « Mon QR code », page d'accueil |

**Lire.** L'adresse lue n'est jamais ouverte : on en tire le jeton, soumis à notre serveur. Un
QR code collé par-dessus un autre n'obtient au pire que « aucune attestation ne correspond ».
Sans compte, le verdict dit valide, révoquée ou inconnue, la référence, l'institution et la
crise — ni le nom ni le lieu, comme le serveur le décide déjà (`verdict_mobilisation`). Sans
réponse du serveur, l'écran ne dit ni valide ni invalide : il dit qu'il ne sait pas.

Dans l'application, la caméra est analysée image par image sur le téléphone (CameraX et ZXing,
sans service d'un fabricant) ; rien n'est enregistré. C'est la seule raison de la permission
caméra, demandée au premier usage. L'application se propose aussi quand l'appareil photo du
téléphone lit lui-même un QR code d'attestation.

**Présenter.** Le serveur réservait la liste des demandes de mobilisation aux acteurs
institutionnels : le bénévole mobilisé ne pouvait pas lire la sienne. Nouvel accès
`mes-mobilisations/`, limité aux demandes adressées à l'appelant, qui rend l'adresse et l'image
du QR code **telles que sur l'attestation PDF**. L'application garde ces demandes chiffrées :
le QR code s'affiche sans réseau (c'est celui qui le lit qui a besoin du serveur), noir sur
blanc et écran à pleine luminosité.

Vérifié : 4 tests serveur, 98 tests du code partagé, 551 tests du site. Sur téléphone virtuel :
QR code affiché relu par la bibliothèque de référence (bonne adresse, bon jeton) ; verdicts
valide, révoquée, inconnue ; sans compte, verdict sans nom ni lieu ; ouverture du lecteur.
**Pas vérifié : la lecture d'un vrai QR code par la caméra** (le téléphone virtuel n'en a pas
devant lui) — les verdicts ont été obtenus en passant l'adresse à l'application. Les deux
boutons du site n'ont pas été essayés dans un navigateur.

## 20. Dossiers dans les missions d'équipe, et « Mon compte » (14/11/2026, version 0.7.0)

Deux retours de Sylvain après essai de la 0.6.0.

### « Les dossiers sont censés être dans des missions d'équipes »

La 0.5.0 rangeait à part, sous « autres dossiers de mes équipes », tout dossier dont le serveur
n'avait pas écrit la mission. C'était lire la base au lieu de lire l'organisation : un dossier
confié à une équipe fait partie de la mission de cette équipe. L'onglet Missions suit
maintenant l'organisation — **équipe → mission → dossiers** (`rangerParEquipe`) :

- la mission écrite sur le dossier, quand il y en a une ;
- sinon la mission en cours de l'équipe (`Team.mission_active`) ;
- sinon, si l'équipe n'a qu'une mission non terminée, celle-là.

Il ne reste à part que les dossiers d'une équipe sans aucune mission, ou qui en a plusieurs
sans qu'aucune soit « en cours » : l'écran les montre comme une anomalie à signaler, plutôt
que de deviner. Une mission partagée par deux de mes équipes apparaît sous chacune, avec les
seuls dossiers de cette équipe. Aucun changement côté serveur : le site affiche encore missions
et dossiers en deux listes séparées (page « Mon équipe ») — à aligner si cette lecture est la
bonne là aussi.

### « Mon compte »

Écran distinct de « Ma fiche de bénévole », ouvert depuis l'onglet Compte, avec les rubriques
du site :

| Rubrique | Ce qu'on y fait | Appel |
|---|---|---|
| Mon identité | prénom, nom, téléphone | `PATCH me/` |
| Ma connexion | voir son identifiant ; changer de mot de passe, ou en choisir un si le compte n'en a pas | `change-password/`, `definir-mon-mot-de-passe/` |
| Mes documents | état de chaque pièce et motif d'un refus ; déposer ou redéposer, par photo ou par fichier (image, PDF) | `qualifications-membres/` |

Trois choix :

- **Une pièce ne passe pas par la file d'attente.** Elle part tout de suite ou pas du tout : une
  pièce d'identité n'attend pas sur un téléphone qu'un réseau revienne. La photo du document
  est réduite, sans position, et le fichier du cache est effacé aussitôt.
- **Ce que deviendra la pièce est dit avant le dépôt** (« sera détruit dès qu'il aura été
  vérifié », ou la durée de conservation), comme sur le site.
- **Redéposer une pièce refusée la remplace** au lieu de déclarer le titre une seconde fois.

Pas fait dans cette rubrique : changer d'adresse e-mail ou d'identifiant (il faut la
revérifier ; l'écran renvoie au site), la photo de profil, télécharger une pièce déjà déposée,
la liste de mes demandes, offres et signalements avec leur retrait, les pièces d'identité de la
candidature à la réserve.

### Vérifié

107 tests du code partagé. Sur téléphone virtuel : les deux dossiers d'essai rangés sous la
mission de leur équipe ; téléphone modifié et enregistré ; document déposé par photo (reçu par
le serveur avec sa pièce, statut « déclarée ») ; mot de passe changé (l'ancien refusé, le
nouveau accepté). Pas essayé : le dépôt par « Choisir un fichier », et le cas d'un compte sans
mot de passe.

---

# Annexe A — Relais série par le navigateur

**Chantier distinct, indépendant des lots 0 à 6.** Autre public, autre calendrier, bien plus
court. Il ne dépend d'aucun jalon de l'application mobile et peut être mené en parallèle.

## Le besoin, et il est réel

Cas présenté le 13/11/2026 : **urgence sur un poste verrouillé où l'on ne peut rien installer**
— typiquement un PC de mairie sous contrôle informatique. Pas de Docker, pas d'exécutable, pas
de pilote. **Mais l'USB fonctionne**, et quelqu'un a un nœud LoRa dans la poche.

Le profil `gw` du satellite répond déjà à « un PC qui sert de passerelle », en mieux : c'est un
service, il survit au redémarrage, il gère les deux radios et le Wi-Fi. **Mais il exige
Docker.** Sur ce poste-là, il est hors d'atteinte. C'est la seule situation qui justifie une
seconde voie — et elle ne la remplace pas.

**Préalables vérifiés sur le poste réel avant d'écrire la moindre ligne**, et tous deux passés
le 13/11/2026 :

1. **Chrome autorise Web Serial** (la politique d'entreprise `DefaultSerialGuardSetting` peut
   le désactiver — le même verrouillage qui interdit d'installer restreint souvent les API de
   périphériques) ;
2. **le nœud apparaît comme port série sans pilote.** Dépend de la puce USB : ESP32-S3 en USB
   natif et CP2102 passent sur Windows 10/11 ; **CH340 exige un pilote**, donc échoue. Sur une
   autre carte, à revérifier.

## La conception : le navigateur EST le pont

**Première conception écartée.** Elle passait par une WebSocket transportant des octets bruts,
le central branchant le pont existant derrière par son transport `create_tcp`. Abandonnée après
vérification : **le projet est en WSGI pur** — gunicorn, ni Channels ni serveur ASGI. Une
WebSocket exigeait une dépendance, un processus et une infrastructure nouvelle, et un tuyau
d'octets imposait en plus un état long par session sur le central. Disproportionné pour un
chantier annexe.

```
Nœud USB ──Web Serial── Navigateur ──HTTP── endpoints EXISTANTS de meshcore-bridge
```

**Le navigateur appelle les mêmes endpoints que le pont Python** (`/messages-meshcore/…`) :
ils existent, ils sont éprouvés, et le serveur n'a rien de nouveau à décoder. Le navigateur est
un pont qui se trouve tourner dans un onglet.

### Périmètre réellement couvert, et ce qui ne l'est pas

| | État |
|---|---|
| **MeshCore en USB** | ✅ implémenté |
| MeshCore en Wi-Fi / TCP | ❌ **impossible depuis un navigateur** — il ne peut pas ouvrir de TCP brut ; il faudrait un pont WebSocket, donc le serveur qu'on voulait éviter |
| Meshtastic en USB | ❌ non implémenté — le client ne parle que MeshCore |
| Meshtastic en Wi-Fi | ❌ non implémenté (techniquement possible : le nœud expose du HTTP) |
| Canaux, clés, télémétrie, répéteurs | ❌ **exclu volontairement** — voir la règle de sécurité plus bas |

Le choix de MeshCore d'abord suit celui des lots : parc dominant, et c'est le protocole que
notre pont Python parle déjà, donc celui dont les formats sont vérifiables sans matériel.

**Correction d'une affirmation antérieure de ce dossier** : la conception en tuyau d'octets
aurait fait marcher « les deux radios d'emblée », puisqu'un tuyau ignore ce qui passe dedans.
La conception retenue — le navigateur parle le protocole — ne le permet pas : chaque réseau
demande son client. Meshtastic en USB est un ajout court (le cadrage `0x94 0xC3` et quelques
champs protobuf), mais il reste à écrire.

### Ce qu'il parle du protocole, et rien de plus

Quatre choses : s'annoncer, relever les messages en attente, en envoyer un, lister les contacts.
Tout le reste — canaux, télémétrie, administration de répéteurs — reste au pont Python. Ce n'est
pas une réimplémentation du protocole, c'est le strict nécessaire d'un relais.

**Et tout est relevé dans la bibliothèque Python `meshcore` dont dépend déjà notre pont** —
`reader.py`, `packets.py`, `commands/messaging.py`, `commands/base.py` — pas dans une
documentation de seconde main. C'est ce qui permet d'écrire ce client **sans radio sous la
main** et de le vérifier sur des vecteurs :

| | Relevé |
|---|---|
| Cadrage série | `0x3e` + longueur sur 2 octets little-endian |
| `APP_START` / `SEND_TXT_MSG` / `GET_CONTACTS` / `SYNC_NEXT_MESSAGE` | 1 / 2 / 4 / 10 |
| Envoi d'un message | `0x02 0x00 \| tentative(1) \| horodatage(4 LE) \| destination(6) \| texte` |
| Destination | **préfixe de 6 octets** de la clé publique, pas la clé entière |
| Message reçu | type 7, ou type 16 (V3) qui **préfixe 3 octets** — SNR + 2 réservés |
| Débit série | 115 200 |

Les deux pièges que ces relevés évitent : envoyer 32 octets de destination au lieu de 6 décale
le texte et fait refuser la commande ; confondre les formats 7 et 16 décale toute la trame et
produit des messages illisibles sans qu'on sache pourquoi.

### Conscient des trames, aveugle au contenu

Le découpeur rend des charges utiles sans les interpréter, et **conserve le reliquat** : une
lecture série coupe une trame n'importe où, c'est la première chose qui casse quand on
l'oublie. Il jette aussi tout octet précédant un début de trame — un branchement à chaud ou une
reconnexion laisse du bruit sur le fil, et c'est à cela que sert `0x3e`.

## Ce qui reste dur

- **L'onglet doit rester ouvert.** Incontournable. Demander un verrou d'écran (*Wake Lock*) et
  afficher un état sans ambiguïté : « ce poste relaie, ne fermez pas cet onglet ». Une page
  n'est pas un service, et il faut le dire plutôt que de le laisser découvrir.
- **Le central porte un état par navigateur connecté** : une socket et une session par relais.
  Plus lourd à exploiter qu'un satellite qui appelle. Borner le nombre de relais simultanés et
  nettoyer les sessions mortes.
- **L'authentification est critique.** Le relais injecte des trames dans le maillage : il doit
  être rattaché à un compte authentifié **et à un companion précis**, sinon n'importe qui émet
  sur la radio d'autrui.
- **Chrome et Edge uniquement**, en HTTPS. Ni Firefox, ni Safari, ni iOS. À dire dans
  l'interface, pas à laisser découvrir.

## Lots

| Lot | Contenu | Fini quand |
|---|---|---|
| **R0** | Session liée à un compte et à un companion, droit recalculé à chaque appel, plafond d'un relais par radio, ménage des sessions mortes. **Et fermeture d'une faille préexistante** | ✅ **Fait** — 16 tests, dont quatre qui auraient échoué la veille |
| **R1** | Cadrage et commandes MeshCore, page « Devenir passerelle », Web Serial, cycle de relais | ✅ **Codé** — 14 tests sur les trames, cadrage corrigé le 14/11 (voir plus bas). **Reste à valider sur une vraie radio** |
| **R2** | Reconnexion avec recul progressif, reprise sans geste de l'utilisateur, verrou d'écran, battement, compteurs | ✅ **Codé**, même réserve matérielle |
| **R3** | Meshtastic : cadrage série, protobuf minimal, configuration, messages directs et de canal | ✅ **Codé** le 14/11 — vecteurs `mesh_pb2`, même réserve matérielle |
| **R4** | Bluetooth, les deux protocoles | ✅ **Codé** le 14/11, même réserve |
| **R5** | Réseau local, Meshtastic seulement (API HTTP) | ✅ **Codé** le 14/11, même réserve |
| **R6** | Identification par la radio, plusieurs radios par poste, bouton sur les pages companions | ✅ **Codé** le 14/11 |

R0 et le cadrage de R1 sont vérifiables **sans matériel ni navigateur** — c'est précisément
pourquoi les formats ont été relevés dans la bibliothèque plutôt que dans une documentation.
Ce qui reste à découvrir sur le poste réel se limite au comportement du port série lui-même.

### La faille que R0 a dû fermer

`MessageMeshLogViewSet` accordait `create`, `partial_update` et `a-envoyer` à `IsAuthenticated`
seul, en **supposant dans un commentaire** que l'appelant était un compte de service — sans le
vérifier. Conséquences, jusqu'au 13/11/2026 :

- `/messages-meshcore/a-envoyer/` **sans paramètre** rendait la file sortante de **tous les
  companions de la plateforme**, contenu des messages compris, à tout compte inscrit ;
- n'importe qui pouvait déposer un **faux message entrant** attribué à une radio.

Désormais `PeutAgirPourCompagnon` : compte de service de pont, satellite approuvé, administrateur
au rôle **réel**, ou relais navigateur **avec une session vivante sur cette radio précise**. Et
un relais ne peut plus interroger sans nommer sa radio.

Deux règles de sécurité posées au passage :

- **le relais ne provisionne aucun canal et ne lit aucune clé.** Il n'entre jamais dans
  `EstComptePont`, dont le commentaire dit qu'un tel compte « ne doit pas pouvoir être fabriqué
  par une requête HTTP ». La radio qu'on branche est déjà configurée — son propriétaire
  l'apporte ;
- **le droit est recalculé à chaque appel**, jamais porté par la session : un membre sorti de
  l'institution perd la main immédiatement, sans attendre l'expiration.

## Correction de cadrage du 14/11/2026

**R1 était construit à l'envers**, et l'essai sur l'écran l'a montré immédiatement : un
administrateur ayant déclaré ses deux nœuds lisait « aucune radio accessible ».

La page exigeait une **passerelle institutionnelle déjà déclarée** (`CompagnonMeshCore`) et
l'appartenance à l'institution propriétaire. Or le cas visé est « quelqu'un **sans** satellite
branche **son** nœud en USB » : cette personne n'a par construction aucune passerelle déclarée.
On lui demandait d'avoir déjà ce que le relais est censé fournir.

Trois défauts distincts, tous réels :

1. **la liste contredisait la règle.** `peut_relayer()` acceptait l'administrateur, mais la vue
   pré-filtrait d'abord sur `ContactInstitution` — autorisé par la règle, exclu par la liste.
   Les deux se décident désormais au même endroit (`radios_relayables`) ;
2. **un nœud personnel déclaré ne comptait pas.** `NoeudMeshUtilisateur` (« cette clé publique
   est à moi ») et `CompagnonMeshCore` (« cette clé est une passerelle ») n'étaient reliés par
   rien. Ils le sont maintenant par la **clé publique**, seule chose qu'ils ont en commun : au
   démarrage du relais, le nœud est promu en passerelle série, une fois, de façon idempotente
   par clé. Aucun secret n'est lu ni écrit — la frontière de `EstComptePont` reste entière ;
3. **l'absence de Meshtastic n'était pas dite à l'écran.** Un nœud Meshtastic branché là ne
   serait pas reconnu, et rien ne l'annonçait. La page le dit maintenant.

Trois titres, un seul nécessaire : administrateur au rôle **réel** (jamais un `demo_role`
prêté), **propriétaire** du nœud, ou membre actif de l'institution propriétaire. La possession
physique reste exigée de fait par l'USB dans tous les cas.

**La leçon pour les lots 0 à 6** : la règle d'autorisation et la liste servie à l'écran doivent
être calculées par le même code. Deux endroits qui décident « qui a le droit » finissent par
diverger, et c'est l'écran qui a tort — il refuse ce que la règle autorise, sans rien dire.

## Second cadrage corrigé le 14/11/2026 : le relais va là où sont les radios

**Une page dédiée était le mauvais endroit.** Les écrans qui listent les companions existent
déjà (`/admin/meshcore-companions`, `/admin/meshtastic-companions`) : c'est là qu'on regarde
son parc, donc là qu'on veut un bouton « Connecter ». Demande du 14/11 : « un simple bouton
connecter, et hop », **plusieurs nœuds depuis le même écran, sans changer d'onglet**, et la
liste de ceux qu'on relaie.

Trois conséquences de conception, dont deux n'étaient pas des détails :

1. **le moteur sort du composant.** Port série, lecteur, découpeur de trames, minuterie et
   verrou d'écran vivent désormais dans `RelaisLocalService` (`providedIn: 'root'`). Un moteur
   dans un composant s'arrête à `ngOnDestroy`, c'est-à-dire **au premier clic ailleurs** — on
   branchait une radio et on la perdait en allant voir la carte ;
2. **N relais simultanés**, chacun avec son port, son découpeur et sa minuterie. Le découpeur
   doit être par relais : c'est lui qui garde le reliquat d'une trame coupée, et deux radios
   qui le partageraient mélangeraient leurs octets ;
3. **la reconnexion garde la référence de son port.** La première version reprenait
   `getPorts()[0]` après un débranchement — correct avec une seule radio, faux avec plusieurs :
   on aurait parlé à la mauvaise. L'objet `SerialPort` reste valide au rebranchement, c'est lui
   qu'on rouvre.

Un composant partagé (`<app-relais-locaux>`) affiche la liste, les compteurs et le bouton
« Débrancher ». Même implémentation aux trois points d'entrée : page des companions MeshCore,
page publique « Devenir passerelle » (qui reste, parce qu'un bénévole n'est pas administrateur
et ne peut pas ouvrir `/admin/…`), et plus tard Meshtastic.

### « Ou de mon réseau local » : non, et il faut le dire

La demande incluait « connecter un nœud USB **ou de mon réseau local** ». Ce second cas est
**hors d'atteinte d'un navigateur**, et ce n'est pas un manque de travail :

| Chemin | Verdict |
|---|---|
| MeshCore en Wi-Fi (TCP 5000) | **Impossible.** Aucune API navigateur n'ouvre une connexion TCP brute. Il faudrait un pont WebSocket côté serveur — écarté, le projet est en WSGI pur |
| Meshtastic en Wi-Fi (HTTP) | **Bloqué en pratique.** Une page en HTTPS ne peut pas appeler `http://192.168.x.x` (contenu mixte), et le certificat auto-signé du nœud en HTTPS est refusé |
| Companion déclaré en TCP, atteint par le serveur | **Déjà couvert** par `meshcore-bridge` — mais seulement si **le serveur** joint le nœud. Un nœud sur le réseau de la personne, non |

Donc pour un nœud sur son propre réseau local, deux réponses honnêtes : **le brancher en USB**,
ou **installer le profil `gw`** du satellite sur une machine de ce réseau. Le bouton est
désactivé sur les companions TCP et BLE, avec la raison en infobulle — désactivé plutôt que
caché, sinon on cherche pourquoi il manque.

## Troisième étape, 14/11/2026 : Meshtastic, Bluetooth et réseau local

Demande : « code les Meshtastic, code le TCP et le BLE ». Résultat :

| | USB (Web Serial) | Bluetooth (Web Bluetooth) | Réseau local |
|---|---|---|---|
| **MeshCore** | ✅ | ✅ service UART Nordic | ❌ **impossible** — TCP brut sur le port 5000 |
| **Meshtastic** | ✅ cadrage `0x94 0xC3` | ✅ TO_RADIO / FROM_NUM / FROM_RADIO | ✅ API HTTP du nœud |

**Le « TCP » MeshCore reste impossible, et ce n'est pas faute d'avoir cherché.** Aucune API de
navigateur n'ouvre une connexion TCP brute ; Chrome 154 ajoute l'accès local aux *WebSocket*,
pas au TCP, et le firmware MeshCore ne parle pas WebSocket. **Meshtastic, lui, passe** : son
firmware expose `PUT /api/v1/toradio` et `GET /api/v1/fromradio` avec
`Access-Control-Allow-Origin: *` (relevé dans `ContentHandler.cpp`), et Chrome accepte qu'une page
HTTPS appelle une IP privée en `http://` une fois l'autorisation « appareils du réseau local »
donnée par l'utilisateur.

### La radio dit qui elle est

Le geste demandé — « un simple bouton connecter, et hop, ça me rajoute comme passerelle de
l'institution » — n'est possible que si la radio s'identifie elle-même. Le navigateur lit donc,
avant d'ouvrir la moindre session, la **clé publique** MeshCore (`SELF_INFO`) ou le **numéro de
nœud** Meshtastic (`MyNodeInfo`), et le serveur retrouve ou crée le companion :

1. radio déjà connue → ce companion, si l'on a la main dessus ;
2. c'est mon nœud déclaré → promu en passerelle de mon institution courante ;
3. radio inconnue → créée pour l'institution courante, **par un acteur institutionnel
   seulement** — sinon n'importe quel compte inscrit enregistrerait des passerelles.

C'est aussi un garde-fou : choisir « radio A » dans une liste puis brancher la radio B
attribuait le trafic de B à A. Et une reconnexion automatique vérifie que c'est toujours la même
radio au bout du câble.

Les companions créés ainsi ont `connexion_type = NAVIGATEUR`, **exclu** de
`actifs-avec-identifiants` : le pont Meshtastic traite tout type inconnu comme du MQTT, il se
serait donc connecté au broker avec l'identité de cette radio.

### Ce que la relecture a trouvé, et qui aurait cassé en situation

Les quatre défauts ci-dessous étaient dans du code « fini, testé » :

1. **en-tête série MeshCore faux dans le sens application → radio** : `0x3e` au lieu de `0x3c`.
   Une vraie radio ignorait toutes nos commandes. Le test `encadre une charge utile` attendait
   `0x3e` — il figeait l'erreur ;
2. **`APP_START` tronqué** : `0x01` seul au lieu de `0x01 0x03` + 6 octets + nom ;
3. **un relais navigateur ne pouvait pas marquer un message envoyé** : `PATCH
   /messages-meshcore/<id>/ {statut}` ne nomme pas le companion, la permission refusait. Le
   navigateur aurait renvoyé le même message **à chaque cycle, indéfiniment** ;
4. **la faille fermée la veille côté MeshCore existait aussi côté Meshtastic** et sur les deux
   files de canaux : lecture des files sortantes de toutes les radios, dépôt de faux entrants.

La correction de méthode qui en découle : **les vecteurs de test sont désormais produits par les
bibliothèques de référence** (`meshcore` et `mesh_pb2`, exécutées dans les images des ponts),
jamais écrits à la main. Un test qui vérifie un encodeur contre l'hypothèse de son auteur ne
prouve rien.

### Vérification croisée avec les clients web de référence

Sur une suggestion de Sylvain, le code a ensuite été relu contre les clients qui font **la même
chose depuis un navigateur** : `meshtastic/web` (transports HTTP, Bluetooth et série du client
officiel, et son SDK), `meshcore-dev/meshcore.js`, `liamcottle/meshcore-web` et
`meshcore-dev/meshcore-ha`. Ce qu'ils ont confirmé : le sens des en-têtes série MeshCore
(`0x3c` / `0x3e`), la disposition de `SELF_INFO`, les UUID et la lecture en boucle Bluetooth
Meshtastic, l'approche Local Network Access pour le réseau local.

Ce qu'ils ont **appris**, dont deux points bloquants :

| Constat | Conséquence sans correction |
|---|---|
| Depuis le firmware 2.7.23, la radio **jette un `ToRadio` identique au précédent** ; le nonce 1 fait diffuser la fiche du nœud | notre battement fixe `3a00` ne passait qu'une fois — **bloquant** |
| Tampon de lecture série de 64 Ko (255 octets par défaut) | ESP32-S3 en USB natif : **trames perdues** pendant le téléchargement des nœuds — **bloquant** |
| Poignée de main Meshtastic en deux temps, `69420` puis `69421`, valeurs traitées à part par le firmware ; ne jamais renvoyer `want_config` dans la même session | tout d'un bloc, et risque de figer le firmware |
| DTR et RTS levés ensemble à l'ouverture | basculés séparément, un ESP32 peut redémarrer |
| Délais d'expiration HTTP (7 s / 4 s) | une requête pendue bloquait la lecture pour toujours |
| Connexion GATT retentée une fois après 750 ms | radio qui sort de veille : échec au premier essai |
| `DEVICE_QUERY` v3 et mise à l'heure de la radio à la connexion (MeshCore) | nœud sans horloge : annonces horodatées faux |
| Bluetooth MeshCore : appairage avec code | sans le dire, on croit à une panne |

### Défaut préexistant constaté, non corrigé ici

Le pont Meshtastic, pour un appareil TCP ou série, enregistre les messages de canal reçus avec
`canal: None` (`bridge.py`, `logger_canal_entrant(None, …)`). Le sérialiseur exige un canal non
nul : **ces messages sont refusés (400) et perdus en silence depuis toujours.** Le relais
navigateur, lui, retrouve le canal par son nom parmi ceux déclarés, et affiche ceux qu'il n'a
pas pu rattacher. Le même correctif est à porter dans le pont.

### Ce qui reste à valider sur du matériel

Rien n'a encore touché une vraie radio : tout est vérifié contre les bibliothèques de référence
et contre de faux transports. Ordre suggéré : MeshCore USB (le plus simple), Meshtastic USB,
Meshtastic réseau local, puis les deux en Bluetooth. Sous Linux, Web Bluetooth exige le drapeau
`chrome://flags/#enable-experimental-web-platform-features`.

## Règle des passerelles locales Meshtastic (fixée le 14/11/2026)

Décidée par Sylvain, implémentée dans `backend/core/canaux_locaux.py` :

| | Règle |
|---|---|
| **Isolement** | Une passerelle locale (radio en USB : navigateur ou satellite) est **isolée par défaut**. Ce qu'elle entend est enregistré dans Assista-Crise — la cellule de crise le voit — mais **n'est réémis par aucune autre passerelle**. Elle **ne réémet que ce qui concerne sa crise et sa commune** (canaux de son institution, de ses équipes, des crises en cours où elle est impliquée). Réglage `relais_reseau` pour l'ouvrir. |
| **Canaux communautaires** | `Fr_Balise` et `Fr_EMCOM` d'office. Leurs clés sont lues dans les canaux **déclarés** dans Assista-Crise, jamais inventées : non déclaré, non proposé. |
| **Canaux locaux** | Un canal **par crise** et un **par commune**, créés au premier besoin. Noms de 11 octets au plus (limite du firmware) : `Moissac`, `CriseInonda`. |
| **Clé** | **Publique par défaut** — « tant pis » — avec un avertissement partout où l'on écrit dessus : au branchement, et dans le chat des canaux. |
| **Annonce** | Les noms des canaux de crise et de commune sont annoncés sur `Fr_EMCOM` **par la seule passerelle locale** (message ciblé, aucune autre ne le reçoit), au plus une fois par demi-heure. |
| **Mutualisation** | Le canal de crise est celui de la **crise**, pas de la commune : toutes les communes impliquées dans la même crise le partagent. |
| **Branchement** | On lit les 8 emplacements de la radio, on propose d'ajouter `Fr_Balise` puis `Fr_EMCOM` s'ils manquent, puis la crise et la commune selon la place, en proposant d'en supprimer d'autres si besoin. **Rien n'est écrit sans le clic de la personne.** Le primaire n'est jamais touché. |

### Deux conséquences de conception

**Le statut unique d'un message de canal ne suffisait plus.** La première passerelle qui émettait
un message de canal le marquait envoyé, et les autres ne le recevaient plus. Pour un canal de
crise partagé entre deux communes, une seule l'aurait émis. Chaque passerelle isolée suit
désormais **sa propre diffusion** (`DiffusionCanalMeshtastic`), notée quand elle prend le message
— pas quand elle le confirme : le pont Python d'un satellite marque l'envoi sans dire quelle
passerelle l'a fait, et attendre sa confirmation ferait renvoyer le message à chaque relève. Une
passerelle isolée ne rattrape que les 15 dernières minutes : se brancher ne vide pas l'historique
sur le réseau.

**Écrire un canal sur la radio exige une clé de session**, même en local : on la demande à la
radio (`get_owner_request`), elle revient dans la réponse, et on la recopie dans chaque commande
— comme le client web officiel et Android. Les clés passant par le navigateur sont publiques par
construction (clé par défaut, clés de convention) : aucun secret ne transite.

### Ce qui reste à faire

- **Satellites existants** : la migration les a laissés ouverts au réseau (`relais_reseau` à
  vrai) pour ne pas changer leur comportement sans décision. Les passer en isolé est un réglage
  par companion.
- **MeshCore** : 40 emplacements, la contrainte de place y est moindre ; la même règle reste à
  porter (commandes `GET_CHANNEL` / `SET_CHANNEL` du protocole companion).
- **Le sens montant « ouvert »** n'existe pas : rien, dans Assista-Crise, ne réémet
  automatiquement ce qu'une passerelle a entendu. Cocher `relais_reseau` n'ouvre que le sens
  descendant. Une vraie passerelle inter-réseaux demanderait anti-écho, anti-boucle et quotas.

## Passerelle Windows (15/11/2026)

Troisième façon de tenir une radio, entre le relais navigateur (rien à installer, mais limité)
et le satellite Docker (complet, mais demande Docker) : **une application Windows**, dans
`passerelle-windows/`. Cahier des charges de Sylvain : simple pour un non-averti, s'arrête à la
fermeture, raccourci sur le bureau, pas de démarrage automatique, pas de recherche automatique
en Bluetooth ni sur le réseau — c'est la personne qui désigne la radio.

| | Relais navigateur | **Application Windows** | Satellite Docker |
|---|---|---|---|
| Installation | aucune | un double-clic, sans droits d'administrateur | Docker |
| Tourne | onglet ouvert | fenêtre ouverte | en permanence |
| MeshCore en Wi-Fi (TCP) | impossible | **oui** | oui |
| Canaux d'équipe, clés, administration | non | **oui** (ce sont les ponts) | oui |

**Elle ne réinvente rien** : elle lance comme sous-processus les ponts du satellite, inchangés,
et s'enrôle par le jeton des satellites. Ce qui est propre à Windows tient en peu de choses :

- **l'arrêt** : chaque pont garde un tuyau ouvert vers l'application et s'arrête quand il se
  ferme — donc aussi quand l'application est tuée sans pouvoir faire le ménage ;
- **le secret** : mot de passe du compte de service protégé par DPAPI, jamais en clair ;
- **le port COM qui change** : la radio est reconnue par son identité, pas par son port ;
- **l'installeur** : un `.bat` généré par la page Satellites (adresse du site + code), qui
  télécharge `installer.ps1` et l'archive depuis le site. Python est installé dans le profil.

Trois défauts corrigés au passage, hors de Windows :

1. **messages de canal Meshtastic perdus** par tout appareil TCP ou série (envoyés avec
   `canal: None`, refusés par le serveur) : le pont retrouve désormais le canal par son nom ;
2. **Meshtastic en Bluetooth** n'existait pas dans le pont (seulement TCP et série) ;
3. **une radio retirée d'une passerelle restait « active »** et pouvait se voir confier des
   messages : `retirer-du-satellite` la désactive, la rebrancher la réactive.

**Vérifié ici** : 43 tests de l'application (enrôlement, radios, arrêt, fenêtre sur écran
virtuel, archive distribuée), syntaxe de l'installeur par un vrai PowerShell, démarrage et arrêt
des deux vrais ponts depuis l'archive. **À valider sur un vrai PC** : l'installeur lui-même
(Python, raccourci), les ports COM, le Bluetooth Windows, et l'accueil de l'antivirus —
l'application n'est pas signée.

## Ce que ce chantier n'est pas

**Ce n'est pas un satellite.** Il ajoute de la portée radio au central ; il n'ajoute **aucune
résilience**. Si internet tombe, le navigateur ne joint plus l'API — contrairement à un
satellite `full`, qui porte son propre Django. Les deux répondent à des besoins opposés et ne se
remplacent pas.

## 17. Version 0.13.0 (22/11/2026) : arrière-plan, messages de terrain, GPS hors ligne, radio avancée

- **Service de terrain** : radio tenue écran éteint et application fermée ; position en mission
  seulement, démarrée application fermée à l'engagement (permission « Toujours » et exemption
  d'économie d'énergie demandées), coupée à la libération ; reprise au redémarrage du téléphone.
- **Messages de terrain** : dix gestes (dont premiers secours avec motif), par les données ou par
  radio avec une étiquette lisible `⚑CODE mission6.auteur6.ident texte` reconnue par le serveur.
- **GPS hors ligne** : régions IGN embarquées, points de la crise, « Autour de moi », « Aller vers ».
- **Radio avancée** :
  - Meshtastic : messages d'administration (port 6) au nœud local, réglages décrits par
    `SchemaMeshtastic` (généré depuis la bibliothèque officielle du pont, numéros seulement :
    **licence GPL-3.0 des définitions à faire valider avant diffusion publique**), écriture
    encadrée par begin/commit_edit_settings, champs inconnus conservés ; canaux (clé, rôle,
    MQTT, précision), lien et QR de partage, nœuds (favori, oubli, message direct), identité,
    redémarrage, réinitialisation, retour usine.
  - MeshCore : formats relevés dans la bibliothèque `meshcore` (MIT) : canaux (« #nom » public ou
    secret), contacts (message, chemin, partage, export/import de carte, suppression), nom,
    position, puissance, paramètres radio, autres réglages, code Bluetooth, annonces,
    redémarrage, retour usine.
  - Confirmation résumée de chaque écriture, renforcée pour ce qui peut couper la radio du
    réseau ; relecture après écriture. Non fait : traceroute Meshtastic.
- **Rien n'a été essayé sur une vraie radio** : à valider sur le matériel de Sylvain.

## 18. Version 0.15.0 (22/11/2026) : messagerie radio

Pour l'utilisateur radio avancé, l'écran Équipes montre la radio du nœud : **tous ses canaux**
(pas seulement ceux des équipes) et **ses contacts** (nœuds Meshtastic, contacts MeshCore),
avec recherche par nom. Chacun ouvre une conversation : parler sur un canal, ou en **message
direct**, émis et reçu (les pilotes remontent désormais les messages adressés au nœud). Les
conversations sont gardées dans le magasin chiffré, 200 messages chacune ; en formation, les
messages émis suivent la règle « [démo] ». Pas d'accusé de réception affiché pour l'instant.

## 19. Version 0.16.0 (23/11/2026) : les boutons de terrain dans le dossier

Les dix messages de terrain sont dans la fiche du dossier (l'intervention), à l'intérieur de la
mission, et plus dans l'écran Missions. Chaque message porte son dossier ; la mission s'en
déduit. Par radio, il part sur le **canal de l'équipe** chargée du dossier (il n'y a pas de canal
par dossier) ; l'étiquette gagne un quatrième groupe facultatif, le début de l'identifiant du
dossier (`⚑ARR 3f2a9c.9c1e0b.a1b2c3.7d41e0 …`). Serveur : migration 0375 ; un dossier qui n'est
pas confié aux équipes de l'intervenant est refusé. Le poste de commandement affiche le dossier
de chaque message dans la fiche de la mission.

## 20. Version 0.17.0 (23/11/2026) : deux radios à la fois, canaux d'équipe protégés

- **Une radio Meshtastic et une radio MeshCore en même temps** : une liaison par protocole
  (`LiaisonRadio`), coordonnées par `Radios` ; chacune retenue et reconnectée seule, la
  notification les nomme toutes. Sans réseau, un message d'équipe ou de terrain part sur
  **chaque** radio qui porte le canal de l'équipe ; au retour du réseau, `deja_emis_radio`
  vaut alors « MESHTASTIC,MESHCORE » et les ponts ne le répètent sur aucun des deux réseaux
  (le serveur accepte la liste). Messagerie radio et menus avancés : on choisit la radio quand
  il y en a deux ; les conversations sont rangées par protocole.
- **Alignement sur les canaux** (« on en a peu, il faut éviter la perte de données ») :
  l'application ne crée aucun canal. Elle n'emploie que le canal de l'équipe tel que la
  plateforme l'installe, retrouvé par son nom ; absent de la radio, le message attend le réseau.
  Dans le menu radio avancé, les canaux d'équipe sont signalés (« géré par la plateforme ») ;
  les modifier ou les retirer demande de taper CONFIRMER, après l'énoncé des conséquences.
- Ancien choix de radio (un seul fichier « radio ») : repris par l'emplacement de son protocole.

## 21. Version 0.18.0 (23/11/2026) : notifications radio, ordre des messageries, auteur Meshtastic

Retour du premier essai réel (radio Meshtastic et MeshCore connectées, formation) :
- **Notifications des messages radio.** Rien ne sonnait pour ce que la radio entendait : la
  veille l'écarte (« déjà sur le téléphone »), et la messagerie radio ne notifiait pas.
  Désormais : un message entendu sur le **canal d'une équipe** sonne comme un message d'équipe
  (toucher ouvre la messagerie de l'équipe) ; un **message direct** sonne toujours ; un autre
  canal sonne si on l'a demandé (cloche dans la conversation : un canal public bavard, avec
  des robots, ne doit pas faire vibrer le téléphone sans fin). Rien ne sonne pour la
  conversation qu'on a sous les yeux.
- **Ordre** : dans Équipes, la messagerie interne des équipes d'abord, la radio ensuite.
- **Qui a écrit, en Meshtastic** : le pilote remonte l'émetteur d'un message de canal (nœud
  « !1a2b3c4d »), affiché par son nom long, ou court, d'après la liste des nœuds. Aussi dans le
  fil d'équipe, au lieu de « Par radio ».
