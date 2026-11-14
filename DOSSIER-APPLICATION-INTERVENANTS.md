# Application mobile des intervenants — dossier de conception

État : **projet, aucune ligne de code écrite.** Document de travail du 13/11/2026.

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
| SDK Android | **absent** (`ANDROID_HOME` non défini) |
| `gradle`, `adb`, `sdkmanager` | absents du PATH |

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
| Ordre | **MeshCore d'abord** | Parc dominant, licence MIT, transport le plus simple |
| Public | Intervenants d'abord, citoyens greffables plus tard | Application authentifiée ; le mode citoyen reste conçu, pas construit |
| Chat | **Délégué à Element X en v1** | Supprime la pièce la plus coûteuse et tout le risque juridique |
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
- **Pas de configuration de la radio depuis l'application.** C'est un métier entier, et les
  applications officielles le font déjà. La nôtre *utilise* une radio déjà configurée.
- **Pas d'application montre, pas de fox hunt.**

---

## 3. Architecture

### Kotlin Multiplatform, et la raison du choix

La pièce irremplaçable y est officiellement supportée.

| Besoin | Solution | Pourquoi elle décide |
|---|---|---|
| Matrix (v2) | `matrix-rust-sdk`, **bindings Kotlin officiels**, Apache-2.0 | Le moteur exact d'Element X, sans son interface ni sa licence. Le chiffrement de bout en bout est ce qu'on ne peut pas écrire à moitié |
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
3. **il répond à la question GPL du lot 4** — vérifié le 13/11/2026 en lisant leur code.

**Vérification faite : ils ont écrit leur propre encodage protobuf.**
`meshcrossway_meshtastic_protocol.h`, 767 lignes, un seul fichier : lecteur et écrivain varint
maison (`struct Reader`, `struct Writer`), numéros de champs codés en dur. Aucun `.proto`,
aucun `*.pb.h`, aucun nanopb, aucun `pb_encode`/`pb_decode`. L'en-tête déclare *« No upstream
.proto/generated binding/firmware code is compiled into this client »*, et
`THIRD_PARTY_NOTICES.md` que les sources GPL-3.0 *« were consulted only to understand
interoperability »*. Aucune licence GPL déclarée, `LICENSES/` n'en contient aucune.

- **Ce que ça règle** : un client PhoneAPI tient dans un fichier, avec une poignée de numéros
  de champs. La voie du lot 4 est démontrée faisable.
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

## 9. Chat : délégué en v1

L'application ouvre le bon salon dans **Element X**, installé à côté (gratuit sur les deux
stores, et c'est déjà votre Synapse derrière). Un lien profond depuis une mission.

Ce que ça supprime : la pièce la plus coûteuse, tout le risque juridique, et la gestion du
chiffrement. Ce que ça coûte : deux applications sur le téléphone, et une couture visible.

À deux, pour avoir quelque chose d'utilisable sur le terrain en quelques mois plutôt qu'en un
an, c'est le bon arbitrage. L'intégration native reste en lot 5, décidée à l'usage.

---

## 10. Découpage en lots

Chaque lot se termine sur quelque chose de **vérifiable**. Sans critère, on ne sait jamais si
un lot est fini.

| Lot | Contenu | Fini quand |
|---|---|---|
| **0** | Socle KMP **cible Android seule**, authentification, missions, file d'attente, indicateur de lien | Un intervenant voit ses missions, déclare un changement de statut en mode avion, et le voit partir au retour du réseau |
| **1** | Carte, ma position, position des équipes, points déclarés + photos en 4G | Un point déclaré sans réseau apparaît sur le central au retour du réseau, photo comprise |
| **2** | Géoloc en mission uniquement, consentement, arrêt automatique | Le suivi démarre à l'engagement, s'arrête à la fin, et l'indicateur est visible en permanence. Consommation batterie mesurée sur 8 h |
| **3** | **MeshCore** derrière l'abstraction | Une position et un point traversent le mesh, téléphone en mode avion, appairage PIN exigé |
| **4** | **Meshtastic** derrière la même abstraction | Idem, **sans une ligne modifiée** dans les lots 0 à 2 — c'est le test de l'abstraction |
| **5** | Chat natif Matrix, ou maintien d'Element X | Décidé à l'usage |

Le critère du lot 4 est le seul qui juge la conception : si brancher la seconde radio oblige à
toucher au domaine, c'est que l'abstraction a épousé la forme de la première.

---

## 11. Risques et inconnues

| Risque | Gravité | Ce qu'on fait |
|---|---|---|
| **Protobufs Meshtastic en GPL-3.0** | **Abaissé** (13/11/2026) | Antériorité vérifiée : MeshCrossway (MIT) écrit son propre encodage varint, 767 lignes, sans aucun `.proto` ni nanopb. La voie est démontrée faisable. Reste à faire **confirmer juridiquement** la réécriture *clean room* — leur déclaration n'en est pas une |
| **Spécification MeshCore « en développement »**, V2 en discussion | Moyen | L'abstraction isole le choc. Épingler une version de firmware de référence |
| **Compose Multiplatform sur iOS** | Moyen | Repli : socle KMP partagé + interface SwiftUI native. À trancher au lot 0, pas après |
| **Revue App Store sur la géoloc d'arrière-plan** | Élevé | Justification honnête, indicateur visible, arrêt automatique. Prévoir une vidéo de démonstration |
| **Batterie** | Élevé | Mesuré au lot 2, pas en fin de projet |
| **Carte muette sans réseau** | Moyen | Cache MapLibre + région hors ligne à la demande. Contrainte par les conditions du fournisseur, à trancher avant le lot 1 |

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

# Annexe A — Relais série par le navigateur

**Chantier distinct, indépendant des lots 0 à 5.** Autre public, autre calendrier, bien plus
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
| **R1** | Cadrage et commandes MeshCore, page « Devenir passerelle », Web Serial, cycle de relais | ✅ **Codé** — 14 tests sur les trames. **Reste à valider sur une vraie radio** |
| **R2** | Reconnexion avec recul progressif, reprise sans geste de l'utilisateur, verrou d'écran, battement, compteurs | ✅ **Codé**, même réserve matérielle |

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

## Ce que ce chantier n'est pas

**Ce n'est pas un satellite.** Il ajoute de la portée radio au central ; il n'ajoute **aucune
résilience**. Si internet tombe, le navigateur ne joint plus l'API — contrairement à un
satellite `full`, qui porte son propre Django. Les deux répondent à des besoins opposés et ne se
remplacent pas.
