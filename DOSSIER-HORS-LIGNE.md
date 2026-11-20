# Ce qui doit marcher sans réseau — satellite et application de terrain

Dossier ouvert le 20/11/2026 à la demande de Sylvain : « un tableau de ce qui doit marcher sur un
satellite offline, et de ce qu'il doit y avoir sur l'application de terrain en mode online /
dégradé / offline », avec l'évaluation des dégâts comme exemple de référence.

État relevé dans le code le 20/11/2026 (`backend/core/sync_outbox.py`, `satellite/`,
`mobile/`, `DOSSIER-APPLICATION-INTERVENANTS.md`). Chaque ligne dit ce qui doit marcher, ce qui
marche aujourd'hui, et ce qui manque. À tenir à jour à chaque lot.

Légende : ✅ fait · 🟡 partiel · ❌ à faire · ❓ à vérifier · — sans objet

## 1. Les trois modes

| Mode | Ce qu'on a | Ce qu'on n'a pas |
|---|---|---|
| **En ligne** | Internet (4G, fibre) : le central répond | — |
| **Dégradé** | Pas d'Internet, mais un réseau local : le Wi-Fi d'un **satellite** de la collectivité, et/ou la **radio** LoRa (MeshCore, Meshtastic) par un compagnon Bluetooth | le central |
| **Hors ligne** | Le téléphone seul | tout réseau |

Règle commune aux trois : **tout passe par la file d'attente**, même en ligne (dossier de
l'application, § 5). Une action faite hors ligne est la même action, envoyée plus tard.

## 2. Le satellite coupé d'Internet

Un satellite (profil `full`) fait tourner sur place le serveur, le site, la base, les ponts radio
et le broker. Coupé du central, il doit permettre à la commune de **continuer à travailler**, puis
tout remonter au retour du lien.

| Fonction | Doit marcher hors ligne | Aujourd'hui | Ce qui manque |
|---|---|---|---|
| Site de la collectivité servi sur le Wi-Fi / réseau local | oui | ✅ | — |
| Connexion des agents sans Internet | oui | ✅ comptes de l'institution recopiés sur le satellite (empreinte du mot de passe, jamais le clair : `core/sync_comptes.py`) | — |
| **Créer un compte sur place** pendant la coupure (renfort, bénévole arrivé sur les lieux) | oui (décidé le 20/11/2026) | ❌ | création locale, puis réconciliation au central au retour du lien (même adresse e-mail = même personne, **proposée**, jamais fusionnée d'office) |
| Dossiers, leur fil (commentaires, historique), missions | créer, modifier ; remonter au retour | ✅ | — |
| Déclarations « en sécurité » | oui | ✅ | — |
| Stock (dépôts, articles, mouvements) | oui | ✅ | — |
| Radio : messages d'équipe, canaux, SOS | oui | ✅ | — |
| Message du central vers la radio d'un satellite | en ligne seulement | ✅ | — |
| Demandes, signalements, offres des citoyens | redescendre ; en créer sur place | 🟡 redescendent | celles **créées sur place** ne remontent pas (hors du périmètre de synchronisation) |
| Fond de carte du département | oui | ✅ PMTiles téléchargé à l'installation | — |
| **Adresses de la commune** (Base Adresse Nationale) | oui : base de l'évaluation des dégâts et des secteurs vulnérables | ✅ copiées du central (lots A et B, 20/11/2026) | — |
| **Habitations référencées et évaluations des dégâts** | oui | ✅ biens, constats, historique, commentaires et types, dans les deux sens (lot F, 20/11/2026) | — |
| **Photos et pièces jointes** (`Document`) | oui, scellées | ✅ photos des biens et des dossiers, empreinte vérifiée par le central (lot F) | — |
| Registre des personnes vulnérables | oui, copie chiffrée lisible des seules personnes habilitées (décidé le 20/11/2026) | ❌ | descente chiffrée vers le satellite de la commune ; jamais au-delà |
| Secteurs vulnérables sur la carte (cercles, sans identité) | oui | ❌ | dépend des adresses et du registre |
| Vigilance, radar, orages, feux (veille) | impossible par nature | ❌ | au mieux, montrer la **dernière copie** avant la coupure, datée |
| Registre et plan communal imprimables | oui | 🟡 PDF au central | à préparer avant la crise, ou à générer sur place |
| Mise à jour du satellite | en ligne seulement | ✅ | — |

## 3. L'application de terrain

| Fonction | En ligne | Dégradé (radio ou Wi-Fi satellite) | Hors ligne | Ce qui manque |
|---|---|---|---|---|
| Rester connecté (session ouverte) | ✅ | ❓ | ❓ | vérifier qu'une session ouverte survit sans réseau |
| Mes missions et dossiers (lecture) | ✅ | ✅ copie locale chiffrée | ✅ copie locale chiffrée | — |
| Commenter, changer un statut | ✅ | 🟡 en file | ✅ en file | envoi par le satellite (bascule, ci-dessous) |
| Photos scellées (empreinte, heure, lieu) | ✅ | 🟡 en file | ✅ en file | pas encore essayé sur un vrai téléphone |
| Déclarer une demande, un signalement, une offre | ✅ | 🟡 en file | ✅ en file | — |
| Messages d'équipe | ✅ par le serveur | ✅ par le canal radio de l'équipe | 🟡 en file | essai sur une vraie radio |
| Détresse / SOS | ✅ | 🟡 | 🟡 en file | SOS par radio, SOS grand public |
| Position en mission | ✅ | ❌ | 🟡 gardée | la position par radio |
| Fond de carte | ✅ IGN | 🟡 tuiles déjà vues | 🟡 tuiles déjà vues | bouton « embarquer ce secteur » ; ou le PMTiles du satellite |
| Basculer vers le serveur du satellite (Wi-Fi du satellite, adresse locale) | — | ❌ | voir § 5.3 |
| **Évaluation des dégâts** | ❌ (sur le site seulement) | ❌ | ❌ | tout le § 4 |
| **Adresses préchargées** | ❌ | ❌ | ❌ | § 4 |
| Secteurs des personnes vulnérables | ❌ | ❌ | ❌ | afficher les cercles, sans identité |
| Notifications (mobilisation, alertes) | ✅ | ❌ | ❌ | par nature ; la radio peut porter une alerte courte |

## 4. L'évaluation des dégâts hors ligne — le parcours de référence

Exemple de Sylvain : précharger les adresses, précharger les dossiers déjà ouverts, faire son
évaluation et ses photos hors ligne, ajouter des points, des biens ou des dossiers (une voiture
retrouvée isolée et détruite), puis tout synchroniser au retour de la 4G, avec création ou
**fusion** des dossiers.

Ce qui existe déjà sur le site (« pointage terrain », `core/habitations.py`) et que le parcours
réutilise : une maison pointée à la position du téléphone avec son adresse ; pas de doublon
d'une maison déjà référencée ; le pointage d'un intervenant attend la **validation de la
commune** ; le constat validé devient l'évaluation ; une maison détruite ouvre un dossier ; la
cause se précise maison par maison ; le rapport de crise compte les maisons détruites.

### 4.1 Avant de partir : précharger un secteur

| Donnée | Pourquoi | Volume indicatif |
|---|---|---|
| Adresses de la Base Adresse Nationale du secteur | pointer une maison sans réseau, et la retrouver au retour par son identifiant national | quelques milliers de lignes par commune, quelques centaines de Ko |
| Habitations déjà référencées pour la crise, avec leur dernier état | ne pas refaire ce qui est fait, voir ce qui reste | idem |
| Dossiers ouverts de la crise sur le secteur (pas seulement les miens) | rattacher un constat à un dossier existant plutôt qu'en ouvrir un second | quelques centaines |
| Secteurs des personnes vulnérables (cercles, sans identité) | savoir où passer en priorité | faible |
| Fond de carte du secteur (région hors ligne) | se repérer | quelques dizaines de Mo |

Le préchargement est **explicite** (« embarquer ce secteur ») et **daté** : l'écran dit de quand
date la copie. Tout est chiffré sur le téléphone, comme la file d'attente.

### 4.2 Sur place, sans réseau

- **Évaluer une habitation** : choisie dans les adresses préchargées (ou sur la carte), état,
  cause, photos scellées, commentaire.
- **Ajouter un bien qui n'a pas d'adresse** : voiture détruite isolée, bâtiment agricole, engin.
  Un point, une catégorie, des photos ; sans adresse, rattaché au lieu touché.
- **Ouvrir un dossier** depuis un constat (personne à reloger, bien dangereux).
- Chaque création reçoit **sur le téléphone** un identifiant définitif (UUID) : la renvoyer deux
  fois ne crée jamais deux objets.

### 4.3 Au retour du réseau : synchroniser, rapprocher, fusionner

La règle du projet s'applique : **des événements, pas des états** (dossier de l'application, § 5).

| Ce qui remonte | Régime | Au central |
|---|---|---|
| Constat (évaluation datée, auteur, photos) | ajout seul | jamais de conflit : un constat de 14 h 32 est un fait |
| Photo scellée | ajout seul | empreinte vérifiée, comme aujourd'hui |
| Habitation pointée avec une adresse nationale | rapprochement **par identifiant d'adresse** | même adresse = même habitation ; le constat s'y ajoute |
| Bien sans adresse (voiture…) | rapprochement **par distance** sur la même crise | un bien du même type à moins de 50 m → **proposé à la fusion**, jamais fusionné d'office |
| Dossier ouvert hors ligne | rapprochement par habitation ou par bien | un dossier ouvert existe déjà pour ce bien → le nouveau y est **proposé au rattachement** |
| État de l'habitation (« détruite », « à surveiller ») | état remplaçable | la commune fait autorité ; le terrain propose, la commune valide (circuit actuel) |

Les propositions de fusion rejoignent la file de **validation de la commune**, qui existe déjà
pour les pointages : un écran, deux fiches côte à côte, « même bien » ou « biens différents ».
Rien ne se fusionne sans un humain.

Le même parcours vaut **par le satellite** (mode dégradé) : le téléphone envoie au serveur du
satellite, qui remonte au central au retour du lien, avec les mêmes règles.

## 5. Décisions

1. **Registre des personnes vulnérables hors ligne : oui** (20/11/2026). Copie chiffrée sur le
   satellite de la commune, lisible des seules personnes habilitées ; les cercles sans identité
   descendent aussi sur les téléphones.
2. **Comptes locaux : oui** (20/11/2026). Les comptes de l'institution sont déjà recopiés ; il
   reste à pouvoir en **créer** sur place pendant la coupure, et à les réconcilier au retour.
3. **La bascule du téléphone, précisée.** Sans 4G, le téléphone ne joint pas le central : la
   bascule vise **le serveur du satellite**, sur son Wi-Fi, qui remonte au central quand lui-même
   retrouve un lien. Moyens de le trouver et de s'y fier :
   - **Wi-Fi du satellite + adresse locale** : le satellite s'annonce déjà sur le réseau local
     (mDNS, `_ac-local._tcp`) ; l'application le découvre seule, ou on lui donne l'adresse.
   - **QR code d'appairage** affiché par l'écran d'état du satellite : adresse locale et empreinte
     de son certificat, scannés une fois (avant la crise ou sur place).
   - **Le certificat**, point délicat : le téléphone refuse un serveur qu'il ne sait pas
     authentifier. Deux voies : un certificat public pour un nom propre au satellite
     (`sat-xxx.<domaine>`, obtenu par défi DNS tant qu'il a Internet, renouvelé à chaque
     reconnexion), ou l'empreinte épinglée par le QR code.
   - **Le satellite comme point d'accès** (il émet son propre Wi-Fi) quand il n'y a plus de
     réseau local du tout.
   - **Un lien de secours du satellite lui-même** (clé 4G d'un autre opérateur, liaison
     satellitaire) : le téléphone sur le Wi-Fi du satellite atteint alors le central à travers lui.
   - **Un autre téléphone en partage de connexion**, s'il capte encore : rien à construire, la
     file part seule.
   - **La radio** pour l'essentiel en petits messages (SOS, statut, position), jamais les photos.
4. **Fusion : proposée, jamais automatique** (20/11/2026). Biens, dossiers et comptes.
5. **Reste à fixer** : le seuil de rapprochement des biens sans adresse (50 m proposé) et leurs
   catégories.

## 5 bis. Un référentiel d'adresses chargé dès la création

Question de Sylvain (20/11/2026) : charger la liste des adresses de la commune dès sa création,
et s'appuyer dessus ensuite. Proposition :

- **Une table d'adresses à part entière**, par commune du territoire de chaque institution, au
  lieu du relevé que remplit aujourd'hui la simulation d'inondation (`AdresseSimuleeInondation`,
  qui porte aussi ses niveaux d'eau). La simulation y rattache ses niveaux par identifiant
  national.
- **Chargée à la création de l'institution** (et quand une commune entre dans son territoire), à
  partir du **fichier complet du département** publié chaque nuit par la Base Adresse Nationale
  (Gironde : 27,5 Mo compressés, vérifié le 20/11/2026), au lieu d'un appel par rue.
- **Rafraîchie chaque semaine** : nouvelles adresses ajoutées, adresses retirées marquées comme
  telles et jamais effacées (les liens des fiches et des habitations tiennent).
- **Donnée publique** : pas de chiffrement nécessaire ; ce sont les liens vers une personne qui
  sont chiffrés, comme aujourd'hui.
- **Elle sert partout** : rattachement du registre, secteurs vulnérables, pointage et évaluation
  des dégâts, simulation sans nouveau balayage, recherche d'adresse sans service extérieur,
  préchargement des téléphones et des satellites.

## 6. Ordre proposé

| Lot | Contenu | Pourquoi dans cet ordre |
|---|---|---|
| 0 | **Référentiel d'adresses** chargé dès la création (§ 5 bis) | tout le reste s'appuie dessus |
| 1 | Évaluation des dégâts **en ligne** dans l'application (parité avec le pointage du site) | le geste d'abord, avec le circuit de validation existant |
| 2 | **Préchargement** d'un secteur et évaluation **hors ligne** par la file | c'est l'exemple de référence |
| 3 | **Rapprochement et fusion** au central (identifiants du téléphone, propositions dans la file de validation) | sans lui, le hors ligne crée des doublons |
| 4 | Satellite : adresses, habitations, évaluations, photos, registre chiffré, comptes créés sur place et créations citoyennes **dans le périmètre de synchronisation** | ferme les trous du § 2 |
| 5 | **Bascule** du téléphone vers le satellite | donne un vrai mode dégradé |
