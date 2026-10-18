# Assista-Crise — Documentation technique

Ce document s'adresse à une personne qui **reprend le projet**. Il explique ce que fait
l'application, comment le code est organisé, comment le lancer, le tester, le surveiller et le
déployer, et quels sont les pièges et les chantiers ouverts. Les détails propres à un module
vivent dans le README de son dossier (liens en fin de document).

> Assista-Crise est un **outil d'appui** : il ne remplace jamais le Plan Communal de Sauvegarde
> d'une collectivité (voir [README.md](README.md)).

## Sommaire

1. [Le projet](#1-le-projet)
2. [Architecture](#2-architecture)
3. [Organisation du dépôt](#3-organisation-du-dépôt)
4. [Démarrer en développement](#4-démarrer-en-développement)
5. [Backend Django](#5-backend-django)
6. [Frontend Angular](#6-frontend-angular)
7. [Services annexes](#7-services-annexes)
8. [Environnements Docker](#8-environnements-docker)
9. [Monitoring](#9-monitoring)
10. [Sécurité](#10-sécurité)
11. [Tests et qualité](#11-tests-et-qualité)
12. [CI/CD et déploiement](#12-cicd-et-déploiement)
13. [Conventions de développement](#13-conventions-de-développement)
14. [Pièges connus et dépannage](#14-pièges-connus-et-dépannage)
15. [Chantiers ouverts](#15-chantiers-ouverts)
16. [Références](#16-références)

---

## 1. Le projet

Plateforme web de **gestion de crise et d'entraide** (inondations, incendies, accidents…) qui met
en relation citoyens, collectivités, secours et associations, avec une cartographie en temps réel.

### Qui l'utilise

| Rôle (`User.type`) | Usage principal |
|---|---|
| `UTIL_SIMPLE` — citoyen | demander de l'aide, proposer de l'aide, signaler une information |
| `AUT_LOCALE` — autorité locale (mairie…) | piloter la crise sur son territoire, valider des comptes |
| `SECOURS` — secours organisés, associations | intervenir, rejoindre des équipes et des missions |
| `REGULATEUR` — régulateur de crise | coordonner équipes, moyens et dossiers |
| `ADMIN` | administration de la plateforme |

Les comptes autres que citoyen sont **validés** par un administrateur ou l'autorité locale du
territoire (`enabled`).

### Fonctionnalités principales

- **Crises** : déclaration, zone géographique, cellule de crise, clôture.
- **Demandes, offres, informations** : formulaires publics géolocalisés, suivi par statut.
- **Dossiers et missions** : traitement opérationnel des demandes par des équipes.
- **Équipes, compétences, institutions, rôles opérationnels, délégations**.
- **Moyens** : matériel, points opérationnels, hébergement, registre de présence.
- **Recherche de personnes**, **référencement des dégâts** (habitations), **simulation d'inondation**.
- **Communication** : emails, messagerie Matrix/Element par équipe, réseaux maillés radio
  (MeshCore, Meshtastic) pour les zones sans réseau.
- **Satellites** : boîtiers Raspberry Pi déployés sur site, fonctionnant même sans internet.

### Glossaire

| Terme | Sens |
|---|---|
| Statuts (`Status`) | `NON_TRAITEE`, `EN_COURS`, `TRAITEE` (demandes) ; `DISPONIBLE`, `INDISPONIBLE` (offres) |
| Types de crise | `INCENDIE`, `INONDATION`, `ACCIDENT`, `CATASTROPHE_NATURELLE`, `AUTRE` |
| `Environment` | `PROD` / `DEMO` : le site de démonstration partage le même backend mais **jamais** les mêmes données de contenu (`EnvironmentScopedModel`) |
| Zone de compétence | commune / EPCI / département / région / national (`core/zone_scoping.py`) |
| Compagnon | nœud radio (MeshCore ou Meshtastic) piloté par un service-pont |
| `.113` / `.114` | machines du réseau de l'université : `.113` ancienne machine de dev (retirée le 2026-09-28), `.114` production et site de démonstration |

---

## 2. Architecture

```
                 Internet
                    │ HTTPS
              ┌─────▼─────┐
              │  ac_waf   │  ModSecurity + OWASP CRS, termine TLS   (production uniquement)
              └─────┬─────┘
              ┌─────▼─────┐  routage, rate limiting, en-têtes de sécurité, protection /media
              │   proxy   │  (Nginx, proxy/nginx.conf)
              └─┬───┬───┬─┘
       /api, /django-admin, /o …     /       matrix. auth. chat.
          ┌─────▼──┐  ┌──▼───────┐  ┌──▼──────────────────────┐
          │backend │  │ frontend │  │ synapse · mas · element │  (prod)
          │Django  │  │ Angular  │  └─────────────────────────┘
          └─┬──┬───┘  └──────────┘
            │  └──────────── mosquitto (MQTT) ◄── ponts meshtastic / meshcore
     ┌──────▼─────┐          redis + worker Celery (simulation d'inondation, prod)
     │ PostGIS    │
     └────────────┘          Monitoring : Prometheus · Alertmanager · Grafana · exporters
```

- **Backend** : Django 5 + Django REST Framework, servi par gunicorn ; PostGIS pour la
  géographie ; JWT pour l'API ; fournisseur OIDC (SSO) pour Matrix.
- **Frontend** : Angular 19 (composants standalone, lazy loading) + MapLibre GL ; en production,
  fichiers compilés servis par un Nginx dédié (`frontend/nginx.conf`, fallback SPA et cache).
- **Proxy** : passerelle unique vers tous les services ; derrière le WAF en production.
- **Celery + Redis** : calculs longs (simulation d'inondation), jamais dans une requête HTTP.

---

## 3. Organisation du dépôt

| Chemin | Contenu |
|---|---|
| `backend/` | projet Django : `config/` (settings, urls, celery), `core/` (l'application), `entrypoint.sh`, `Dockerfile` |
| `frontend/` | application Angular (`Dockerfile.dev` : `ng serve` ; `Dockerfile.prod` : build + Nginx) |
| `proxy/` | Nginx passerelle : `nginx.conf` (prod, intégré à l'image), `nginx.dev.conf` (dev) |
| `monitoring/` | images Prometheus, Alertmanager, Grafana, script du rôle PostgreSQL de monitoring |
| `mosquitto/` | configuration du broker MQTT |
| `meshtastic-bridge/`, `meshcore-bridge/` | services-ponts radio (phase de test) |
| `matrix-bridge/`, `element-web-config/` | intégration messagerie Matrix |
| `satellite/` | déploiement Raspberry Pi sur site |
| `security/` | outillage de sécurité de l'hôte (collecte des logs SSH) |
| `scripts/` | `init-secrets.sh` |
| `docker-compose*.yml` | base, dev (override), prod, antenne |
| `.gitlab-ci.yml`, `deploy_harbor.sh`, `build-prod.sh` | CI/CD et build manuel des images |

---

## 4. Démarrer en développement

**Prérequis** : Docker (avec Compose v2), Git, `openssl`.

```bash
git clone <dépôt> && cd assista-crise
./scripts/init-secrets.sh      # crée .env et secrets/ (n'écrase jamais l'existant)
docker compose up -d --build   # application + monitoring
```

| URL | Service |
|---|---|
| http://localhost | application via Nginx (point d'entrée recommandé, mêmes routes qu'en production) |
| http://localhost:4200 | serveur de dev Angular (accès direct) |
| http://localhost:8000/api/ — `/api/docs/` | API REST — documentation Swagger |
| http://localhost/django-admin/ | administration Django |
| http://localhost:8025 | MailHog : tous les emails envoyés en dev |
| http://localhost:3000 / :9090 / :9093 | Grafana (`admin`, mot de passe dans `secrets/`) / Prometheus / Alertmanager |

**Premier administrateur** : `docker compose exec backend python manage.py createsuperuser`
(ou variables `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` au démarrage).

**Commandes utiles**

```bash
docker compose logs -f backend                         # logs
docker compose exec backend python manage.py <cmd>     # commandes Django (migrate, shell…)
docker compose exec backend pytest core/test_xxx.py    # tests ciblés
docker compose --profile meshcore-test up -d           # avec le pont MeshCore de test
docker compose down                                    # arrêt (données conservées)
docker compose down -v                                 # arrêt + SUPPRESSION des données
```

- **Antenne LoRa branchée sur votre machine** : ajouter dans votre `.env`
  `COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker-compose.antenna.yml`.
- **Celery/Redis ne font pas partie de la pile de dev** : la simulation d'inondation ne
  s'exécute pas localement tant qu'ils n'y sont pas ajoutés (voir chantiers ouverts).
- Le code backend est monté dans le conteneur, mais gunicorn ne recharge pas le code
  automatiquement : `docker compose restart backend` après une modification.

---

## 5. Backend Django

### 5.1 Structure de `backend/core/`

| Fichier | Rôle |
|---|---|
| `models.py` | tous les modèles et énumérations (~150 classes, voir 5.2) |
| `views.py`, `serializers.py`, `urls.py` | API REST (ViewSets DRF + vues dédiées) |
| `permissions.py`, `zone_scoping.py`, `habitations.py` | contrôle d'accès par type de compte, par zone de compétence, référencement des dégâts |
| `middleware.py` | audit des lectures (`AuditTraceMiddleware`), pas de cache sur l'API, budget de géocodage |
| `audit.py` | journal d'audit (`AuditLog`) |
| `oidc.py`, `matrix.py` | SSO OIDC pour Synapse, correspondance utilisateur ↔ Matrix |
| `geo_lookup.py`, `geo_reference.py` | géocodage et référentiel des communes |
| `inondation.py`, `ruissellement.py`, `hydrometrie.py`, `tasks.py` | simulation d'inondation (tâche Celery) |
| `routage_mesh.py`, `sync_outbox.py` | routage MeshCore, synchronisation satellite → central |
| `imports.py`, `export.py` | import CSV/XLS (personnel, institutions, habitations), exports |
| `metrics.py` | métriques Prometheus métier (voir § 9) |
| `management/commands/` | nettoyage des crises, imports de communes, purge d'audit, synchronisation, jeux de données |
| `test_*.py` | tests pytest (≈ 115 fichiers) |

### 5.2 Domaines du modèle de données

| Domaine | Modèles principaux |
|---|---|
| Comptes et territoires | `User`, `Commune`, `Institution`, `ContactInstitution`, `Zone` |
| Crise | `Crisis`, `ImplicationInstitution`, `JournalCollectivite`, `Plan` |
| Citoyens | `Request`, `Offer`, `Information` (+ photos, types, disponibilités) |
| Opérations | `Dossier`, `Mission`, `Team`, `Competence`, `RoleOperationnel`, `PointOperationnel`, `Besoin` |
| Moyens | `MaterielCatalogue`, `MaterielPoint`, `RegistrePresence`, `AffectationLogementIntervenant` |
| Dégâts et risques | `Habitation`, `TacheSimulationInondation`, `GrilleAltimetrieCommune` |
| Personnes | `RecherchePersonne`, `DeclarationSecurite`, `Notification` |
| Communication | `CompagnonMeshCore`, `CompagnonMeshtastic`, `MessageMeshLog`, `SalonMatrixEquipe` |
| Satellites | `Satellite`, `EvenementSynchronisation`, `ConflitSynchronisation` |
| Traçabilité | `AuditLog` |

Les données de contenu héritent d'`EnvironmentScopedModel` (isolation PROD / DEMO), filtrées
automatiquement par `EnvironmentScopedViewSetMixin`.

### 5.3 API REST

Toutes les routes sont sous `/api/` (`core/urls.py`) ; documentation interactive : `/api/docs/`.

- **Ressources** (ViewSets DRF) : `crises`, `demandes`, `offres`, `informations`, `teams`,
  `dossiers`, `missions`, `besoins`, `competences`, `zones`, `plans`, `habitations`,
  `recherches-personnes`, `notifications`, `audit-logs`, `satellites`, ressources MeshCore,
  Meshtastic et Matrix…
- **Authentification** : `token/`, `token/refresh/`, `token/blacklist/` (JWT, simplejwt),
  `register/`, `activate-account/…`, `magic-login/…`, `reset-password/…`, `me/`.
- **Liens par jeton envoyés par email** : modifier ou supprimer une demande/offre/information,
  répondre à une offre, confirmer une affectation de bénévole.
- **Fonctions dédiées** : `stats/dashboard/`, `simulation-inondation/<commune>/…`, `imports/…`,
  `positions-equipes/`, `crises/<id>/cellule/`.
- Hors `/api/` : `/django-admin/`, `/o/` (fournisseur OIDC), `/accounts/login/`, `/metrics`.

### 5.4 Configuration (variables d'environnement)

| Variable | Rôle |
|---|---|
| `SECRET_KEY` | **obligatoire** hors `DEBUG=True` et tests (voir § 10) |
| `DEBUG` | `False` par défaut |
| `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASS` | base PostgreSQL (échec explicite si absentes) |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_SSL/TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | envoi d'emails |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis pour Celery |
| `OIDC_ISS_ENDPOINT`, `OIDC_RSA_PRIVATE_KEY`, `MATRIX_SERVER_NAME` | SSO Matrix |
| `INSTANCE_SATELLITE_LOCALE`, `SATELLITE_*` | instance satellite |
| `COOKIES_SECURE_OVERRIDE`, `AUDIT_LOG_RETENTION_DAYS`, `CONVENTION_SOUS_TRAITANT_*` | réglages divers |
| `PROMETHEUS_MULTIPROC_DIR` | métriques multi-workers gunicorn (fixé par compose) |

`SECRET_KEY`, `DB_PASS` et `EMAIL_HOST_PASSWORD` acceptent aussi une variante `<NOM>_FILE`
(chemin d'un secret Docker).

### 5.5 Démarrage du conteneur (`entrypoint.sh`)

`migrate` → création du superutilisateur si `DJANGO_SUPERUSER_EMAIL/PASSWORD` sont fournis →
types de demandes/offres/informations par défaut → `collectstatic` → gunicorn
(`GUNICORN_WORKERS`, 3 par défaut). L'image tourne sous l'utilisateur non-root `appuser`
(uid 10001).

### 5.6 Migrations

Les migrations sont **écrites en dev et commitées** (`makemigrations` puis revue du fichier
généré) ; seul `migrate` s'exécute au démarrage. Ne jamais générer de migration en production.

---

## 6. Frontend Angular

- `src/app/app.routes.ts` charge paresseusement deux groupes : `public/public.routes.ts`
  (accueil, carte, formulaires, suivi de dossier, connexion…) et `admin/admin.routes.ts`
  (tableau de bord, crises, dossiers, missions, équipes, institutions, matériel, satellites…).
- Les pages sont des **composants standalone** chargés avec `loadComponent` : suivre ce modèle
  pour toute nouvelle page.
- `services/` : un service par ressource d'API ; `core/guards/` : authentification, rôle admin,
  compte activé ; `auth/interceptor/` : ajout du JWT.
- `src/environments/` : `environment.ts` (dev, API sur `http://localhost:8000/api`) et
  `environment.prod.ts` (API relative `/api`, servie par le même Nginx que la page).
- Cartographie : MapLibre GL.

```bash
cd frontend && npm ci && npm start     # sans Docker
npm test                               # tests Karma
npm run build                          # build de production (dist/)
```

---

## 7. Services annexes

| Service | Rôle | Statut | Documentation |
|---|---|---|---|
| `meshtastic-bridge/` | relie l'application au réseau Meshtastic (MQTT tiers ou appareil TCP/série) | test, non déployé en prod | [README](meshtastic-bridge/README.md) |
| `meshcore-bridge/` | relie l'application à un compagnon MeshCore (série, BLE, TCP) + proxy partagé | test | [README](meshcore-bridge/README.md) |
| `matrix-bridge/` | un salon Matrix privé par équipe, relais des positions live d'Element | non vérifié sur un vrai client Element | docstring de `matrix-bridge/bridge.py` |
| `satellite/` | Raspberry Pi sur site : profil `gw` (pont radio) ou `full` (instance complète hors ligne, synchronisée avec le central) | non testé sur matériel réel | [README](satellite/README.md) |

Les services-ponts s'authentifient auprès de l'API avec un **compte de service** dédié (JWT).

---

## 8. Environnements Docker

### 8.1 Couches Compose

| Fichier | Contenu | Chargé |
|---|---|---|
| `docker-compose.yml` | base commune : services, volumes, healthchecks, profils ; **ni ports, ni builds** | toujours |
| `docker-compose.override.yml` | dev : builds, code monté, MailHog, pont MeshCore de test, ports | automatiquement |
| `docker-compose.prod.yml` | prod : images du registre, réseaux isolés, `restart` | `-f` explicite |
| `docker-compose.antenna.yml` | périphérique LoRa | via `COMPOSE_FILE` |

```bash
docker compose config                                                          # résultat fusionné (dev)
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile monitoring config   # prod
```

Règles de fusion à connaître : une valeur simple est **remplacée** ; `environment` est fusionné
par clé ; **`ports` s'additionnent** (d'où leur absence de la base) ; `volumes` sont fusionnés
par chemin dans le conteneur. Les services de monitoring ont le profil `monitoring`, activé par
`COMPOSE_PROFILES=monitoring` dans `.env` — il doit être actif pour **toutes** les commandes
(`up`, `down`, `ps`…).

### 8.2 Production

- Réseaux : `front` (proxy, frontend, backend, mosquitto, tileserver), `back`, `db` (base
  isolée : seuls `backend` et `postgres-exporter` le rejoignent), `monitoring`.
- Ports publiés : 80/443 (proxy), 1883/9001 (MQTT), Grafana sur `127.0.0.1:3000` uniquement.
- Images de base épinglées par digest dans les Dockerfiles (builds reproductibles) ; les mettre à
  jour régulièrement (`docker buildx imagetools inspect <image>` puis remplacer le `@sha256:…`).

---

## 9. Monitoring

Détails opérationnels : [monitoring/README.md](monitoring/README.md).

### 9.1 Ce qui est mesuré

| Source | Métriques | Méthode |
|---|---|---|
| Django (`/metrics`) | requêtes, statuts, latence par vue, requêtes SQL | RED |
| `core/metrics.py` | `assista_help_requests_total`, `assista_offers_total`, `assista_emails_failed_total`, `assista_requests_by_status`, `assista_offers_by_status`, `assista_active_crises` | métier |
| postgres / nginx / mosquitto exporters | état et charge de chaque service | USE |
| node-exporter, cAdvisor | hôte et conteneurs | USE |
| blackbox-exporter | sonde HTTPS de https://assista-crise.fr | boîte noire |

Gunicorn tournant avec plusieurs workers, les métriques sont agrégées via
`PROMETHEUS_MULTIPROC_DIR` (sinon chaque scrape lirait un worker au hasard).

### 9.2 Alertes (`monitoring/prometheus/alerts.yml`)

Principes : alerter sur les **symptômes** ressentis par les utilisateurs, chaque alerte doit
être actionnable, `critical` = agir maintenant, `warning` = cette semaine.

| Groupe | Alertes |
|---|---|
| Disponibilité | `SiteDown`, `InstanceDown`, `ServiceDown` (l'exporter répond mais son service est mort) |
| Application | `HighErrorRate` (avec seuil de trafic minimum), `SlowAPI`, `EmailsFailing` |
| Infrastructure | `DiskWillFillIn24h` (prédiction), `DiskAlmostFull`, `LowMemory`, `ContainerRestarting`, `DatabaseConnectionsHigh` |
| Certificats | `TLSCertExpiringSoon`, `TLSCertExpiringCritical` |
| Métier | `NoHelpRequestDuringActiveCrisis`, `UnprocessedRequestsPilingUp` |
| Méta | `Watchdog` : toujours active, transmise à healthchecks.io qui alerte quand elle **s'arrête** |

Chaque règle est couverte par `alerts_test.yml` (`promtool test rules`).

### 9.3 Notifications et visualisation

- Alertmanager : dev → MailHog ; prod → SMTP Ionos + healthchecks.io (Watchdog renvoyé chaque minute).
- Grafana : tableau de bord « Assista-Crise Overview » (santé → mission → infrastructure),
  provisionné depuis `monitoring/grafana/dashboards/` ; une modification faite dans l'interface
  n'est pas conservée.

### 9.4 Images de monitoring

Prometheus, Alertmanager et Grafana sont construits depuis `monitoring/<nom>/Dockerfile` :
image officielle + configuration, **validée pendant le build** (une règle invalide fait échouer
le build). La production n'a donc besoin d'aucun fichier de configuration sur le serveur. En
dev, l'override construit les mêmes images puis monte les fichiers par-dessus.

### 9.5 Ajouter…

- **une métrique métier** : un `Counter` / une jauge dans `core/metrics.py` (labels bornés),
  un test dans `core/test_metrics.py`, un panneau dans le dashboard JSON ;
- **une alerte** : une règle dans `alerts.yml` + un test dans `alerts_test.yml`, puis
  `docker compose build prometheus` ;
- **un service à surveiller** : son exporter dans `docker-compose.yml` (profil `monitoring`), un
  `scrape_config` dans `prometheus.yml`, une alerte sur sa métrique `*_up`.

---

## 10. Sécurité

- **Secrets** : jamais dans le code ni dans git. Identifiants applicatifs dans `.env` (modèle :
  `.env.example`), secrets du monitoring dans `secrets/` (en prod : `/etc/assista-crise/secrets`,
  hors du dépôt). Un secret commité est compromis pour toujours : il faut le **changer**.
- **`SECRET_KEY`** : la clé de repli du code est publique ; Django refuse de démarrer avec elle
  hors `DEBUG=True` et tests.
- **Conteneurs** : backend non-root (uid 10001) ; images de monitoring non-root.
- **Réseau** : WAF devant tout le trafic en production ; base isolée ; seuls 80/443 (et MQTT)
  publiés. Docker contourne UFW : un port publié sur `0.0.0.0` est joignable malgré le pare-feu.
- **Application** : rate limiting des points d'authentification (Nginx), photos et documents
  servis uniquement via des actions d'API qui vérifient les droits, HSTS, cookies sécurisés,
  `DEBUG=False` par défaut, audit des accès (`AuditLog`).
- **Monitoring** : Prometheus et Alertmanager n'ont pas d'authentification et ne sont jamais
  publiés ; Grafana écoute sur la boucle locale (tunnel SSH).
- **MQTT** : accès anonyme conservé pour l'instant (les appareils Meshtastic se connectent avec
  des identifiants propres à chaque appareil) ; activer l'authentification nécessite de créer
  un compte pour chaque client (`mosquitto_passwd`) — décision d'équipe.

---

## 11. Tests et qualité

```bash
docker compose exec backend pytest -o addopts="" --no-cov          # suite backend complète (~7 min)
docker compose exec backend pytest core/test_metrics.py             # un fichier
cd frontend && npm test                                             # frontend (Karma)
```

- Backend : pytest + pytest-django, fixtures partagées dans `backend/conftest.py`, base de test
  clonée depuis `template_postgis`. Configuration dans `backend/pytest.ini`.
- **État connu** : 15 tests échouent déjà sur `main` (implications d'institutions, URLs des
  emails, registre de présence…). La CI les tolère temporairement (`allow_failure`).
- Monitoring : `promtool test rules`, `amtool check-config` (CI et build des images).

---

## 12. CI/CD et déploiement

### 12.1 Dépôts distants

| Remote | Rôle |
|---|---|
| `origin` | dépôt principal du projet (GitHub) |
| `gitlab` | GitLab de l'université : **la CI s'y exécute** |
| `github` | fork de travail |

`origin` et `gitlab` ont des historiques distincts : une fusion entre eux demande
`--allow-unrelated-histories` et une résolution soigneuse (tous les fichiers communs sont en conflit).

### 12.2 Pipeline (`.gitlab-ci.yml`)

1. **test** (chaque push) : règles Prometheus, configs Alertmanager, fichiers Compose, tests backend.
2. **build** (branche `prod`) : images backend, frontend, proxy et monitoring, taguées par commit
   et `latest`, smoke test de l'image backend, push vers Harbor.
3. **deploy** (branche `prod`) : copie des fichiers Compose sur la VM, `pull`, `up -d`.

Variables CI (protégées et masquées) : `HARBOR_URL`, `HARBOR_PROJECT`, `HARBOR_USER`,
`HARBOR_PASSWORD`, `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY` (base64), `SSH_KNOWN_HOSTS`
(sortie de `ssh-keyscan -H <vm>`, vérifiée une fois).

### 12.3 Production réelle

- `.114` est relancée **à la main**, derrière le WAF `ac_waf` ; `docker-compose.prod.yml` sert à
  une reconstruction et doit rester cohérent avec elle.
- Images construites par la CI ou par `./deploy_harbor.sh` (build + push manuel) ;
  `./build-prod.sh` construit et lance la version de prod en local.
- Préparation d'une VM pour le monitoring : voir [monitoring/README.md](monitoring/README.md).
- Avant tout redéploiement : vérifier que `SECRET_KEY` est défini sur le serveur.
- Retour arrière : `IMAGE_TAG=<sha> docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile monitoring up -d`.

---

## 13. Conventions de développement

- Commentaires et messages de commit **en français**, phrase au présent décrivant le changement.
- Un commentaire explique **pourquoi** (décision, incident, contrainte), pas ce que fait le code.
- Ne jamais commiter `.env`, `secrets/`, `__pycache__`/`.pyc`, `node_modules`.
- Backend : nouvelle ressource = modèle + migration commitée + serializer + ViewSet enregistré
  dans `core/urls.py` + permissions + tests pytest.
- Frontend : nouvelle page = composant standalone + route `loadComponent` dans le groupe adéquat.
- Toute route ajoutée à `proxy/nginx.conf` est reportée dans `proxy/nginx.dev.conf`.
- Avant de pousser : tests ciblés, `docker compose config`, et `docker compose build` des images
  de monitoring si `monitoring/` a changé.

---

## 14. Pièges connus et dépannage

| Symptôme | Cause et solution |
|---|---|
| Un fichier monté apparaît comme un dossier appartenant à root | le fichier n'existait pas au premier `up` : Docker a créé un dossier ; le supprimer, créer le fichier, `up --force-recreate` |
| `address already in use` | un autre programme tient le port (ex. Prometheus installé via apt) : `sudo ss -tlpn 'sport = :PORT'` |
| `network … still in use` après `down` | services d'un profil inactif encore lancés : même `--profile` qu'au `up` |
| Le backend refuse de démarrer : `SECRET_KEY … n'est pas défini` | ajouter `SECRET_KEY` au `.env` (`./scripts/init-secrets.sh`) |
| `password authentication failed` après changement de secret | les mots de passe ne s'appliquent qu'à la création du volume : `ALTER USER` (voir monitoring/README.md) |
| Erreurs de schéma sur une base de dev ancienne | base créée par un autre historique de migrations : la recréer (`docker volume rm …_postgres_data`) |
| Une règle d'alerte modifiée n'est pas prise en compte | `docker compose restart prometheus` |
| Un compteur Prometheus « recule » | métriques non agrégées entre workers : vérifier `PROMETHEUS_MULTIPROC_DIR` |
| `lookup X … server misbehaving` au démarrage | course au démarrage entre conteneurs : `depends_on` |

---

## 15. Chantiers ouverts

- Corriger les 15 tests en échec puis retirer `allow_failure` de la CI.
- **Registre des images de monitoring** : la production les tire de Docker Hub
  (`stefy237/…`) alors que la CI et `deploy_harbor.sh` les poussent vers Harbor — choisir un
  registre unique.
- Ajouter Redis et un worker Celery à la pile Compose (simulation d'inondation en dev).
- Authentification MQTT (décision d'équipe, voir § 10).
- Métriques métier à venir : messages radio reçus (alerte `MeshSilent`, à partir de
  `MessageMeshLog`) et délai entre une demande et sa prise en charge.
- Logs centralisés (Loki + Grafana Alloy).
- Mettre à jour l'image Grafana (vulnérabilités signalées sur `13.0.11`) et les digests des
  images de base.
- Documents obsolètes à archiver : `DOCUMENTATION.pdf`, `Documentation_technique.pdf`,
  `IMPROVEMENTS.md`, `TEST_STRATEGY.md` (décrivent l'ancienne version du projet).

---

## 16. Références

- [README.md](README.md) — présentation, licence, démarrage rapide
- [monitoring/README.md](monitoring/README.md) — exploitation du monitoring
- [til-monitoring.md](til-monitoring.md) — cours sur l'observabilité appliqué au projet
- [satellite/README.md](satellite/README.md), [meshtastic-bridge/README.md](meshtastic-bridge/README.md),
  [meshcore-bridge/README.md](meshcore-bridge/README.md), [frontend/README.md](frontend/README.md)
- `.github/agents/assista-crise-reprise.agent.md` — méthode de reprise du projet
