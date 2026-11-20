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
| Connexion des agents sans Internet | oui | ❓ | vérifier que l'authentification ne dépend pas du central |
| Dossiers, leur fil (commentaires, historique), missions | créer, modifier ; remonter au retour | ✅ | — |
| Déclarations « en sécurité » | oui | ✅ | — |
| Stock (dépôts, articles, mouvements) | oui | ✅ | — |
| Radio : messages d'équipe, canaux, SOS | oui | ✅ | — |
| Message du central vers la radio d'un satellite | en ligne seulement | ✅ | — |
| Demandes, signalements, offres des citoyens | redescendre ; en créer sur place | 🟡 redescendent | celles **créées sur place** ne remontent pas (hors du périmètre de synchronisation) |
| Fond de carte du département | oui | ✅ PMTiles téléchargé à l'installation | — |
| **Adresses de la commune** (Base Adresse Nationale) | oui : base de l'évaluation des dégâts et des secteurs vulnérables | ❌ | elles vivent au central ; à redescendre |
| **Habitations référencées et évaluations des dégâts** | oui | ❌ | hors du périmètre de synchronisation, dans les deux sens |
| **Photos et pièces jointes** (`Document`) | oui, scellées | ❌ | une photo déposée sur le satellite **ne remonte pas** |
| Registre des personnes vulnérables | ❓ à décider | ❌ | voir § 5, décision 1 |
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
| Basculer vers le serveur du satellite (annoncé en mDNS) | — | ❌ non décidé | — | voir § 5, décision 3 |
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

## 5. Décisions à prendre

1. **Le registre des personnes vulnérables hors ligne.** Les cercles (sans identité) peuvent
   descendre sur les satellites et les téléphones sans risque. Le registre lui-même (noms,
   besoins) est la donnée la plus sensible du projet : faut-il qu'un satellite en garde une copie
   chiffrée, lisible des seules personnes habilitées, pour le jour où la commune est coupée ?
2. **L'authentification sur un satellite coupé.** À vérifier d'abord ; si elle dépend du central,
   décider comment un agent se connecte sur place.
3. **La bascule du téléphone vers le satellite** (proposée en novembre, non décidée). Sans elle,
   le mode dégradé se limite à la radio, et rien de lourd (photos, constats) ne part avant la 4G.
4. **Le seuil de fusion des biens sans adresse** (50 m proposé) et les catégories de biens.

## 6. Ordre proposé

| Lot | Contenu | Pourquoi dans cet ordre |
|---|---|---|
| 1 | Évaluation des dégâts **en ligne** dans l'application (parité avec le pointage du site) | le geste d'abord, avec le circuit de validation existant |
| 2 | **Préchargement** d'un secteur et évaluation **hors ligne** par la file | c'est l'exemple de référence |
| 3 | **Rapprochement et fusion** au central (identifiants du téléphone, propositions dans la file de validation) | sans lui, le hors ligne crée des doublons |
| 4 | Satellite : adresses, habitations, évaluations, photos, et créations citoyennes sur place **dans le périmètre de synchronisation** | ferme les trous du § 2 |
| 5 | **Bascule** du téléphone vers le satellite | donne un vrai mode dégradé |
