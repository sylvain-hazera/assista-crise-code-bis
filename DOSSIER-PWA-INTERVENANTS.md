# L'application des intervenants sur iPhone, en application web (PWA) — dossier de projet

Demande de Sylvain du 20/11/2026 : « prévoir la version intervenants pour Apple en PWA ».

Pourquoi une PWA : l'application iOS native est en attente (pas de Mac, compte Apple à ouvrir au
nom de Réserve Résilience, compilation par un service macOS distant). Une PWA s'installe depuis
Safari (« Partager » → « Sur l'écran d'accueil »), sans App Store ni Mac, et se met à jour avec
le site. Elle sert aussi aux Android sans l'APK.

État relevé le 20/11/2026 : le site n'est pas installable (ni manifeste, ni service worker, ni
icône Apple) ; il a déjà des pages d'intervenant (`mes-equipes`, `mon-equipe/:id`,
`mes-interventions`, `mon-releve`, `ma-fiche-benevole`), une file d'attente chiffrée dans le
navigateur (`services/file-attente-chiffree.ts`, AES-GCM, clé non extractible) et un suivi de
position (`suivi-position-permanent.service.ts`). Le serveur n'envoie pas de notification web
(aucune clé VAPID, aucun abonnement).

## 1. Ce que Safari permet en 2026 (iOS 26)

| Capacité | iPhone, application installée | Source |
|---|---|---|
| S'ouvrir en plein écran, comme une application | ✅ (par défaut depuis iOS 26) | WebKit, Safari 26 |
| Notifications (Web Push) | ✅ depuis iOS 16.4, **une fois installée** et après un geste de la personne ; toujours visibles, sans image ni bouton | WebKit |
| Écran maintenu allumé (Wake Lock) | ✅ depuis Safari 18.4 | WebKit |
| Caméra (photos, QR code), position au premier plan | ✅ | — |
| Stockage hors ligne (IndexedDB, cache du service worker), chiffrement (WebCrypto) | ✅ | — |
| Envoi différé en arrière-plan (Background Sync) | ❌ : la file part quand l'application est ouverte | firt.dev |
| Position **en arrière-plan** (application fermée, écran éteint) | ❌ à ma connaissance ; aucune source fiable — à vérifier sur un appareil | — |
| Bluetooth (Web Bluetooth), NFC, série | ❌ | firt.dev |
| Connexion TCP à une radio | ❌ : un navigateur n'ouvre pas de prise TCP ; et une page en HTTPS ne peut pas appeler une radio en HTTP sur le réseau local | — |
| Alerte « critique » qui sonne en mode silencieux | ❌ (réservé aux applications natives autorisées par Apple) | — |

## 2. Fonction par fonction : application Android → PWA iPhone

| Fonction (écran Android) | PWA iPhone | Remarque |
|---|---|---|
| Connexion, inscription, mon compte | ✅ | pages du site |
| Missions, engagements, interventions | ✅ | à regrouper sous un espace « terrain » adapté au téléphone |
| Équipes et messagerie | ✅ en ligne ; hors ligne : messages mis en file | |
| Carte | ✅ | même carte que le site |
| Dépôt citoyen, aide, fiche bénévole, disponibilités | ✅ | pages existantes |
| Notifications et alertes | ✅ par Web Push, **à construire côté serveur** ; pas d'alerte critique | |
| Dossiers, photos scellées | ✅ | empreinte, heure et lieu calculés dans le navigateur |
| Évaluation des dégâts à pied | ✅ en ligne ; secteur embarqué hors ligne : ✅ (IndexedDB chiffré) | même API que l'application (`tournee`, `constat`, `secteur`) |
| Lecture des QR codes de mobilisation | ✅ | caméra et bibliothèque de lecture (Safari n'a pas `BarcodeDetector`) |
| Suivi de position en mission | ⚠️ **seulement application ouverte**, écran maintenu allumé | la limite la plus gênante ; le dire à l'écran |
| Hors ligne | ⚠️ ce qui est saisi attend et part **à la prochaine ouverture** avec réseau | pas d'envoi en arrière-plan |
| Radio MeshCore / Meshtastic (Bluetooth ou TCP) | ❌ | reste propre à Android ; sur iPhone, sans réseau, les messages attendent |
| Bascule vers un satellite | ⚠️ le satellite est une autre adresse : une seconde installation | à documenter |
| Mise à jour | ✅ automatique : le service worker prévient « Nouvelle version — recharger » | équivalent de la boîte demandée pour l'APK |

## 3. Lots proposés

| Lot | Contenu | Essais |
|---|---|---|
| **1. Installable** | Manifeste par marque (nom, icônes, couleurs selon le domaine, comme `core/branding.py`), icône Apple, balises `apple-mobile-web-app-*`, service worker Angular (coquille et images mises en cache, `/api/` jamais en cache), page « Installer l'application sur iPhone » et bandeau discret sur iPhone, annonce « nouvelle version disponible » | build de production, manifeste par domaine, rien de `/api/` dans le cache |
| **2. Espace terrain** | Une entrée `/terrain` pensée pour le téléphone : missions et engagements, équipes et messagerie, carte, dossiers, compte ; en reprenant les pages existantes | Karma, gardes, menu |
| **3. Hors ligne** | Missions, équipes et dossiers gardés dans IndexedDB **chiffré** ; la file chiffrée existante généralisée (messages, constats, photos) avec identifiants tirés sur le téléphone ; envoi à l'ouverture et au retour du réseau ; indicateur en ligne / hors ligne | idempotence, chiffrement, coupure simulée |
| **4. Notifications** | Web Push : clé VAPID en secret Docker, abonnement par appareil (adresse d'envoi chiffrée, empreinte pour retrouver), envoi par le même chemin que les notifications Android, désabonnement à la déconnexion | envoi simulé, rien en clair en base |
| **5. Terrain** | Suivi de position au premier plan avec écran allumé ; photos scellées ; lecture des QR codes ; évaluation des dégâts (tournée, replacer, constat, nouveau point, secteur embarqué) | logique partagée testée sans appareil |

Ordre conseillé : 1 et 2 d'abord (une application installable et utilisable en ligne, rapide à
livrer), puis 4 (les notifications sont ce qu'un intervenant attend le plus), puis 3 et 5.

## 4. Règles du projet qui s'appliquent

- **Rien en clair** : tout ce qui est gardé sur le téléphone est chiffré (clé non extractible,
  comme `file-attente-chiffree.ts`) ; l'adresse d'envoi Web Push est une donnée personnelle,
  chiffrée en base avec empreinte.
- **Aucun service tiers** : le service worker et la lecture des QR codes sont servis par le site ;
  les notifications passent par le service de notifications d'Apple, comme pour toute application
  iOS (c'est le seul chemin), et ne portent qu'un titre et un lien, pas de donnée sensible.
- Nouvelle page d'administration éventuelle : dans le menu latéral.

## 5. À décider

1. **L'adresse** : `/terrain` sur le site de chaque marque (proposé), ou un sous-domaine.
2. **Le premier lot à livrer** : lots 1 et 2 (proposé), ou directement jusqu'aux notifications.
3. **Un iPhone pour essayer** : rien de ce qui touche à iOS ne se vérifie ici ; il faudra un
   appareil (installation, notifications, caméra, position, hors ligne).
4. **Le suivi de position** : sur iPhone, seulement application ouverte. Acceptable pour les
   intervenants, ou faut-il garder l'application native en ligne de mire pour ce point ?

Sources : [WebKit — Safari 26.0](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/),
[firt.dev — iOS PWA Compatibility](https://firt.dev/notes/pwa-ios/),
[MagicBell — PWA iOS Limitations](https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide).
