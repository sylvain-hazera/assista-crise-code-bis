# Application mobile

Conception et raisons : `DOSSIER-APPLICATION-INTERVENANTS.md`, à la racine du dépôt.

## Où est quoi

| Dossier | Contenu |
|---|---|
| `shared/domaine` | Modèles et règles : compte, mission, équipe, suivi en mission, dépôts citoyens, file d'attente. Aucune dépendance à Android |
| `shared/donnees` | Appels à l'API, session, file d'attente sortante, copies locales (missions, équipes, crises) |
| `shared/lien` | État du lien de terrain, trames MeshCore et Meshtastic, trame de position de seize octets |
| `androidApp` | Écrans, carte, service de suivi en mission, stockage chiffré par le Keystore |

Les modules `shared` sont en Kotlin Multiplatform, avec la JVM pour seule cible aujourd'hui :
leurs tests tournent sans téléphone ni émulateur.

## Construire

```
scripts/tester-mobile.sh
```

lance les tests puis produit l'APK de développement. Il faut un JDK complet (17 ou 21) et le
SDK Android (`platforms;android-35`, `build-tools;35.0.0`), cherchés dans `JAVA_HOME` et
`ANDROID_HOME`, sinon dans `~/.local/opt/jdk-*` et `~/Android/Sdk`.

Pour viser un serveur de développement plutôt que celui de la marque :

```
scripts/tester-mobile.sh -PurlSite=http://10.0.2.2:8000
```

La compilation de développement n'accepte le HTTP en clair que vers `localhost` et
`10.0.2.2` (la machine hôte vue de l'émulateur). Tout le reste doit être en HTTPS.

## Marques

Une marque est une saveur Gradle dans `androidApp/build.gradle.kts` : identifiant
d'application, nom, adresse du serveur. Deux existent :

| Saveur | Identifiant | Serveur | Fichier servi par le site |
|---|---|---|---|
| `reserveResilience` | `org.reserve_resilience.app` | `app.reserve-resilience.org` | `/mobile/reserve-resilience.apk` |
| `assistaCrise` | `fr.assista_crise.app` | `www.assista-crise.fr` | `/mobile/assista-crise.apk` |

Le code est le même. Ce qui change vit dans le dossier de la saveur : les images
(`androidApp/src/<saveur>/res`, à défaut celles de `src/main/res`) et la palette
(`androidApp/src/<saveur>/kotlin/.../ui/Marque.kt`). `ui/Theme.kt` ne porte que ce que les deux
applications partagent. Les deux s'installent côte à côte sur le même téléphone.

## Ce qui reste local au téléphone

Session, missions et file d'attente sont écrites dans `files/magasin`, chiffrées en
AES-256-GCM par une clé du Keystore Android. Rien n'est écrit en clair, et l'application est
exclue des sauvegardes du système.

Les polices Quicksand et Open Sans sont sous licence OFL (`androidApp/licences`).
