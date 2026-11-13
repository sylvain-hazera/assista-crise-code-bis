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
| http://localhost:3000/grafana/ / :9090 / :9093 | Grafana (`admin`, mot de passe dans `secrets/`) / Prometheus / Alertmanager |

`init-secrets.sh` génère aussi les trois clés de chiffrement des données personnelles
(§ 10.1). **Sauvegardez votre `.env`** : sans ces clés, les données chiffrées de votre base de
dev deviennent illisibles.

**Premier administrateur** : `docker compose exec backend python manage.py createsuperuser`
(ou variables `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` au démarrage).

**Données de test**

```bash
docker compose exec backend python generate_test_data.py              # ~145 éléments, zone PROD
docker compose exec backend python generate_test_data.py --env DEMO   # idem, zone DEMO
docker compose exec backend python manage.py generate_crise_gier_pilat --total 100   # scénario DEMO complet
```

`generate_test_data.py` demande confirmation (il crée des comptes au mot de passe `test123`) ;
`generate_crise_gier_pilat` construit une crise réaliste (points opérationnels, équipes, offres,
demandes, signalements, déclarations de sécurité) et accepte `--delete` pour tout retirer.

Il enchaîne désormais `completer_affectation_auto_gier`, qui rend l'**affectation automatique**
réellement opérante et peut aussi se relancer seule sur une crise déjà générée :

```bash
docker compose exec backend python manage.py completer_affectation_auto_gier --simulation
docker compose exec backend python manage.py completer_affectation_auto_gier --intervenant "Prenom Nom"
```

La crise est retrouvée par son nom contenant « Gier » (accents et casse ignorés), parce qu'elle
est souvent renommée après génération ; `--crise "nom exact"` tranche s'il y en a plusieurs.
`--intervenant` pose aussi `User.demo_role` (`--role-demo`, REGULATEUR par défaut) : en zone de
démonstration c'est **ce** champ que lit `AuthService.getEffectiveRole`, jamais `type`, et sans
lui aucun menu ne s'ouvre. `type` n'est jamais modifié — c'est le rôle en production.

Elle pose les correspondances thème → besoin → compétence manquantes (aucun type de signalement
n'en avait), crée les `AffectationCompetence` — seule table lue par le matching, `Team.competences`
ne servant qu'à l'affichage —, déclare la zone de la crise sur chaque équipe, rend une personne
intervenante et régulatrice disponible, puis crée les dossiers des demandes et signalements qui
n'en avaient pas (le générateur les insère en `bulk_create`, donc hors `perform_create`).
`--simulation` exécute tout dans une transaction annulée ; `--sans-affectation` sur le générateur
reproduit l'état antérieur.

**Accès à la base** : `localhost:5432`, base `assista-db`, identifiants `DB_USER` / `DB_PASS`
du `.env` (DBeaver, pgAdmin…), ou `docker compose exec db psql -U admin -d assista-db`. Les
colonnes chiffrées y apparaissent illisibles (`gAAAAA…`) : pour lire ou **modifier** des
données, passer par l'admin Django (`/django-admin/`) ou `manage.py shell`. Une écriture SQL
directe dans une colonne chiffrée ou un email casse la lecture et la connexion (index aveugle
non recalculé).

**Commandes utiles**

```bash
docker compose logs -f backend                         # logs
docker compose exec backend python manage.py <cmd>     # commandes Django (migrate, shell…)
docker compose exec backend pytest core/tests/<domaine>/   # tests ciblés (§ 11.1)
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
| `routage_mesh.py`, `routage_meshtastic.py`, `sync_outbox.py` | routage MeshCore, routage Meshtastic (§ 9.5.2), synchronisation satellite → central |
| `acces_radio.py` | qui a accès au domaine radio, et à quel niveau : le droit intermédiaire « opérateur » (§ 9.5.5) |
| `decodeur_meshcore.py`, `resolution_prefixes.py` | format des trames MeshCore, et résolution d'un saut vers un nœud (portés de CoreScope) |
| `ingestion_observateurs_meshcore.py` | trames publiées par les observateurs MeshCore sur MQTT -> liaisons |
| modèle `RattachementNoeudRadio` | qui répond d'un répéteur que personne ne porte (§ 9.5.6) |
| `imports.py`, `export.py` | import CSV/XLS (personnel, institutions, habitations), exports |
| `metrics.py` | métriques Prometheus métier (voir § 9) |
| `crypto_fields.py`, `file_crypto.py` | chiffrement des colonnes et des fichiers sensibles (§ 10.1) |
| `branding.py` | marque blanche : logo, couleurs et emails selon le Host visité (`InstitutionWebDomaine`) |
| `vulnerabilites.py`, `alertes_pcs.py`, `convention_sous_traitance.py` | registre des personnes vulnérables, alertes PCS, convention RGPD |
| `logging_handlers.py` | envoi des erreurs sur Matrix (§ 5.7) |
| `management/commands/` | nettoyage des crises, imports de communes, purge d'audit, synchronisation, jeux de données |
| `tests/<domaine>/test_*.py` | tests pytest (117 fichiers en 13 domaines, voir § 11.1) |

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
| `SERVER_URL` | adresse du frontend dans les liens des emails (activation, connexion magique, réinitialisation) ; défaut `https://www.assista-crise.fr`, `http://localhost` en dev (override) |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis pour Celery |
| `OIDC_ISS_ENDPOINT`, `OIDC_RSA_PRIVATE_KEY`, `MATRIX_SERVER_NAME` | SSO Matrix |
| `FIELD_ENCRYPTION_KEY`, `FIELD_BLIND_INDEX_KEY`, `FILE_ENCRYPTION_KEY` | chiffrement des données personnelles, **sans valeur de repli** (§ 10.1) |
| `INSTANCE_SATELLITE_LOCALE`, `SATELLITE_*` | instance satellite (§ 7.3) |
| `AUDIT_LOG_RETENTION_DAYS` | conservation de l'`AuditLog` en jours (30 ; purge : `manage.py purge_audit_logs`) |
| `COOKIES_SECURE_OVERRIDE` | `False` seulement pour un SSO Matrix servi en HTTP (ancienne `.113`), jamais en prod |
| `CONVENTION_SOUS_TRAITANT_*` | identité du sous-traitant RGPD citée dans l'email de convention |
| `PROMETHEUS_MULTIPROC_DIR` | métriques multi-workers gunicorn (fixé par compose) |

`SECRET_KEY`, `DB_PASS` et `EMAIL_HOST_PASSWORD` acceptent aussi une variante `<NOM>_FILE`
(chemin d'un secret Docker). `DB_USER` et `DB_PASS` n'ont pas de valeur par défaut : l'ancien
repli `admin`/`admin` était celui de la production. Le rôle de prod (`assista_app`) n'étant pas
superuser, la base de test clone `template_postgis` (PostGIS déjà installé).

`ALLOWED_HOSTS` doit contenir chaque nom d'hôte réellement visité : `backend` (appels internes
des services-ponts) et, pour la marque blanche, le domaine du partenaire **et** son CNAME cible.

### 5.5 Isolation PROD / DEMO et zones de compétence

**PROD / DEMO.** Le site de démonstration partage le backend et le frontend, jamais les données
de contenu : ces modèles héritent d'`EnvironmentScopedModel` (champ `environment`) et sont
filtrés par `EnvironmentScopedViewSetMixin`. Le vocabulaire partagé (types, compétences,
catalogue matériel, communes) n'a pas ce champ. Les comptes sont communs aux deux zones : en
DEMO, les coordonnées réelles (email, téléphone, topologie réseau des ponts…) sont **masquées à
l'affichage** par les serializers, jamais en base. Un formulaire d'édition renvoie la valeur
masquée : les serializers l'ignorent pour ne pas écraser la vraie valeur.

**Zones de compétence** (`core/zone_scoping.py`). Chaque institution a un niveau de secteur
(commune, EPCI, département, région, national), déduit de son type ou forcé par
`secteur_override` (comptes de test uniquement : réservé au superuser en PROD). Les codes
(`commune_code`, `epci_code`, `departement_code`, `region_code`) sont **dénormalisés à
l'écriture** : sur `Institution` par `save()`, sur `Request`, `Offer` et `DeclarationSecurite`
à la création. Les lectures filtrent ainsi sans jointure géographique. `Information` n'a que
`commune_code` : les niveaux supérieurs passent par le référentiel `Commune`
(`object_in_viewer_zone_via_commune`).

**Une résolution qui échoue ne vaut pas une résolution vide** (corrigé le 10/11/2026).
`Institution.save()` recalcule les trois codes depuis `commune_code` via
`commune_secteur_codes`, qui passe par `_resolve_commune` — laquelle interroge
**`geo.api.gouv.fr`** avec un budget d'appels et une temporisation. Budget épuisé ou service
indisponible, elle rend des codes vides, et les recopier **effaçait un rattachement qu'on
connaissait**. La règle est donc : le code calculé gagne quand il existe, sinon on garde ce
qu'on a ; la commune reste la source de vérité, et un code non vide l'emporte toujours, y
compris sur une valeur posée à la main — sans quoi une institution rattachée au mauvais EPCI y
resterait.

Le symptôme était un test instable à des centaines de tests de sa cause
(`test_simulation_perimetre.py` : l'`epci_code` posé par le test était jeté par `save()`, le
périmètre tombait à « aucune », et l'assertion levait `KeyError: 'champ'`). La perte dépassait
le test : toute institution enregistrée pendant une indisponibilité du service perdait son
secteur en silence. Trois tests verrouillent la règle, dont celui qui reproduit la panne.

| Fonction | Usage |
|---|---|
| `filter_queryset_to_viewer_zone` | `get_queryset` : réduit à la zone de l'appelant, **vide** si elle est inconnue (jamais tout ouvrir par défaut) ; `resolver` pour une ressource sans code propre (ex. `Team` via son institution) |
| `object_in_viewer_zone(_via_commune)` | serializers : visibilité d'un champ, jamais bloquant |
| `widen_zone_from_request` | listes élargissables par `?echelle=` (jamais plus étroit que le niveau naturel) |

Le rôle applicatif `ADMINISTRATOR` contourne toujours ce filtrage. Ce module généralise un
filtrage que l'audit de sécurité avait trouvé absent de la plupart des vues.

**Référentiel `Commune`.** Chargé par `import_communes` (codes administratifs, population) et
complété à la demande par geo.api.gouv.fr (nom, centroïde) et Géorisques (risques). Chaque
tentative est datée (`derniere_tentative`, cooldown) : un code introuvable n'est pas
redemandé à chaque lecture. Le reverse-géocodage d'un point est mis en cache par
`PointCommune`, arrondi à 4 décimales (~11 m). En liste, aucun appel réseau.

### 5.6 Contrôle d'accès aux données

- **Localisation des personnes** : l'adresse d'une demande ou d'un signalement n'est visible
  que de la mairie, des secours de la zone et des bénévoles affectés au dossier ; celle d'une
  offre, des seuls acteurs institutionnels de la zone. Sinon, `latitude`, `longitude` et
  `location` valent `null`, et aucune donnée personnelle n'est renvoyée.
- **Liens par jeton sans compte** : `deletion_token` (désactiver), `edition_token` (modifier
  seulement), `reponse_token` (fil de messages et édition d'une offre), jetons de
  confirmation d'affectation ou d'accusé de réception PCS. Jamais exposés en lecture ; les
  serializers d'édition publique n'acceptent qu'une liste restreinte de champs.
- **Champs réservés aux actions dédiées**, toujours en lecture seule dans les serializers
  génériques : `is_active`, `type`, `demo_role`, `enabled` d'un utilisateur (un compte
  modifiant son profil ne doit pas pouvoir se donner `ADMIN`), `actif` (désactivation
  journalisée), statuts de validation, délégations d'équipe, convention RGPD, compte de
  service d'un satellite. `is_active` est le champ réellement vérifié à la connexion.
- **Champs que les services-ponts modifient par `PATCH`** (`statut`, `erreur`,
  `date_envoi`…) : ne jamais les passer en `read_only`. DRF ignore sans erreur un champ
  `read_only` reçu, et le message resterait `EN_ATTENTE` pour toujours.
- **Fichiers** : photos et documents servis par des actions `preview` / téléchargement qui
  vérifient les droits ; `proxy/nginx.conf` bloque `/media/documents/`, `/media/photos/`,
  `/media/recherches/`. Seul le préfixe des logos d'institution est public. Noms de fichiers
  stockés = UUID.
- **Comptes** : seul un administrateur authentifié crée un compte `ADMIN`. Une inscription
  autorité locale sans nom d'institution est rétrogradée en utilisateur simple. Le
  rattachement à une institution n'a lieu qu'après confirmation de l'email.
- **Crise clôturée** : plus aucun rattachement (`validate_crisis_open`) ; dépôt public
  seulement sur une crise ouverte ayant un responsable.

### 5.7 Journalisation et alertes d'erreur

Toute erreur journalisée (`logger.error` / `exception`), où qu'elle survienne (requête,
Celery, migration, commande), part sur la console, par email aux `ADMINS` et sur un salon
Matrix (`core/logging_handlers.py`) : handlers attachés au logger racine. Sans cela, en
`DEBUG=False`, Django ne journalisait rien (incident du 07/10 : email d'activation jamais
parti, sans trace). Les actions sensibles sont tracées dans `AuditLog` (`core/audit.py`).

### 5.8 Celery et simulation d'inondation

La simulation d'inondation (`core/inondation.py`, `core/ruissellement.py`, tâches dans
`core/tasks.py`) dépasse le délai de gunicorn sur une grande commune : elle tourne dans un
worker Celery (Redis), à concurrence limitée, avec un délai maximal de 10 min et une relance
des tâches interrompues (`CELERY_TASK_ACKS_LATE`). Trois calculs par commune :

| Tâche | Contenu | Borné ? |
|---|---|---|
| Paliers | grille d'altitude IGN puis zone inondée par niveau d'eau (`PalierInondationSimule`) | oui |
| Adresses | scan BAN et niveau d'eau atteignant chaque adresse (`AdresseSimuleeInondation`) | non (grandes villes) : séparé pour ne pas bloquer les paliers |
| Ruissellement | accumulation de flux (crue éclair) sur la même grille | oui |

`TacheSimulationInondation` garde l'état de la dernière tâche par (commune, environnement,
type) : pas de double lancement, et l'utilisateur peut quitter la page puis revenir. Ces
résultats sont des **hypothèses** : ne jamais écrire dans `Habitation.statut_evaluation`
(constat de terrain) depuis une simulation.

### 5.9 Démarrage du conteneur (`entrypoint.sh`)

`migrate` → création du superutilisateur si `DJANGO_SUPERUSER_EMAIL/PASSWORD` sont fournis →
types de demandes/offres/informations par défaut → `collectstatic` → gunicorn
(`GUNICORN_WORKERS`, 3 par défaut). L'image tourne sous l'utilisateur non-root `appuser`
(uid 10001).

### 5.10 Migrations

Les migrations sont **écrites en dev et commitées** (`makemigrations` puis revue du fichier
généré) ; seul `migrate` s'exécute au démarrage. Ne jamais générer de migration en production.
Modifier un `help_text` ou des `choices` produit une migration : vérifier avec
`manage.py makemigrations --check`. Les données de référence (types, institutions…) sont
créées par des migrations de données, sauf le type d'institution `mairie`, créé au premier
rattachement d'une mairie.

### 5.11 Repères sur le modèle de données

- **Statuts de validation** : un champ FK nullable `validator` / `..._valide_par` vaut « en
  attente » tant qu'il est vide. Une association n'est réputée mandatée sur une crise
  qu'après validation d'une autorité locale (`ImplicationInstitution.statut`).
- **Historiques** : plusieurs modèles ajoutent une ligne par changement plutôt que de
  modifier en place (`AffectationLogementIntervenant`, suivi de matériel, délégations
  d'équipe) ; l'état courant est la ligne la plus récente.
- **Catalogues partagés extensibles** (`Competence`, `MaterielCatalogue`, `InformationType`,
  `RisqueMajeurType`, `TypeVulnerabilite`) : toute institution ajoute une entrée réutilisable
  par toutes (`TagLikeViewSetMixin`). Regroupement `parent` sur un seul niveau, non contraint
  en base. Les types retirés sont masqués (`actif=False`), jamais supprimés.
- **Données sensibles** : registre des personnes vulnérables accessible uniquement via
  `core/vulnerabilites.py` ; **aucune donnée de santé** dans `TypeVulnerabilite` ni dans
  `DeclarationSecurite` (RGPD art. 9) : ne pas ajouter de champ médical ou de notes libres
  sans accord du porteur.
- **Messages d'erreur rendus à l'utilisateur** (`shared/utils/message-erreur.ts`) :
  `HttpErrorResponse.message` est une phrase fabriquée par Angular (« Http failure response for
  https://…/api/register/: 400 OK ») qui ne dit rien et expose une URL interne. Le message du
  serveur est dans `error.error` — toujours l'extraire avec `messageErreurServeur(err, repli)`,
  qui couvre les quatre formes du backend (chaîne brute, `{detail}`, `{error}`,
  `{champ: [messages]}`) et écarte une page HTML de passerelle en panne.
- **Prénom et nom exigés à l'inscription** (11/11/2026) : dans `UserSerializer.validate()`, à
  la **création seulement**. Les deux champs restent `required: False` au niveau champ
  (`extra_kwargs`) et c'est voulu — le même sérialiseur sert les mises à jour partielles, où
  exiger un nom ferait échouer la modification d'un numéro de téléphone. La règle appartient
  donc à la création, pas au champ, et elle est côté serveur parce que `/api/register/` est
  ouvert : une inscription sans prénom passerait par n'importe quel autre client.

  Deux surfaces étaient concernées, et chacune n'identifiait la personne que par un patronyme :

  - le **formulaire public** (`register.component.ts`) ne demandait le prénom qu'à un
    particulier ; `toggleFieldsBasedOnUserType` l'effaçait et le désactivait pour une autorité
    locale ou un service de secours. Le champ ne dépend plus du type de compte — un champ
    d'identité n'a pas de raison d'en dépendre ;
  - le **rattachement d'une habitation** avait un seul champ « Nom complet », et le compte créé
    à l'acceptation était fabriqué en coupant cette chaîne au **premier espace** : « Jean Pierre
    Dupont » donnait le prénom « Jean » et le patronyme « Pierre Dupont », en silence.
    `prenom_demandeur` est désormais un champ (migration `0246`), exigé par l'API. Les demandes
    antérieures ne sont **pas** découpées rétroactivement : couper au premier espace est
    précisément ce qui produisait l'erreur, et le figer en base la rendrait définitive. Elles
    retombent sur `RattachementHabitation.noms_pour_compte` / `identite_demandeur` /
    `salutation_demandeur`, extraits du corps de la vue pour être testables.

  **Non modifié, et c'est une décision déjà prise** : l'invitation d'un contact par une
  institution (`champsInvitationContact`, `ContactInstitutionViewSet.inviter`) garde prénom et
  nom facultatifs — on invite souvent depuis une adresse de service seule, et exiger un nom
  qu'on ne connaît pas conduit à inventer « DGS DGS ». Ce n'est pas une inscription : la
  personne ne se nomme pas elle-même, et peut compléter son profil ensuite. Conséquence à
  connaître : un compte invité sans nom reste sans nom jusqu'à ce que son titulaire le remplisse,
  l'activation ne demandant qu'un clic sur un lien.
- **Unicité du compte à l'inscription** : traitée dans `UserSerializer.validate()` et **non**
  par le validateur de champ sur `username`, retiré pour cela (`extra_kwargs`). DRF exécute les
  validateurs de champ AVANT `validate()` : tant qu'il restait, il court-circuitait tout et
  répondait « A user with that username already exists. », en anglais et sur un champ que le
  formulaire d'inscription ne montre pas. Le refus porte désormais sur `email`, en français, et
  dit quoi faire — dont **suivre le lien d'activation** pour un compte créé par invitation et
  jamais activé, cas devenu fréquent et que se réinscrire ne débloque pas.
- **Accès à la page « Membres association »** (`UserSerializer.acces_membres_association`,
  28/10/2026) : administrateur, compte rattaché à une AASC, **ou membre du bureau d'une AASC
  même rattaché ailleurs** — un agent de mairie peut être au bureau de l'association locale, et
  le critère du seul rattachement le priverait de la page dont il a la charge. C'est ce
  troisième cas qui interdit de calculer la visibilité côté client : « être au bureau » est un
  attribut du rattachement, pas du compte. Avant, l'entrée était ouverte à tout rôle
  institutionnel et la page se fermait d'elle-même, ce qui la faisait paraître **cassée** à une
  mairie plutôt qu'absente. Le sélecteur d'associations écarte par ailleurs les institutions
  `actif=False` (une fusionnée est conservée comme pierre tombale) et tout ce qui n'est pas du
  type `aasc` — comparé **sans casse** : les lignes de catalogue existent réellement en
  « AASC » et en « aasc » (constante partagée `institution_attachment.CODE_TYPE_AASC`).
- **Les trois gestes d'ajout, partout les mêmes** (chantier du 28/10/2026,
  `shared/components/common/bloc-ajout/`) : **à la main** (`+`), **par fichier**, **par
  invitation email**. Avant, les trois existaient mais dispersés — le `+` sur la page, le
  fichier sur une page d'assistant absente du menu atteignable par un seul lien contextuel,
  l'invitation sur deux destinations seulement ; aucune n'avait les trois, et *inviter une
  institution n'existait pas du tout*, de sorte qu'une mairie voisine était toujours saisie par
  un tiers qui ignore son type et son référent (cause des doublons).
  - `BlocAjoutComponent` porte les trois gestes, paramétré par URL et non par service : il sert
    sept destinations, lui passer un service par destination lui ferait connaître chacune. Le
    `+` **n'ouvre rien**, il émet `ajoutManuel` — les formulaires de saisie restent aux pages,
    qui en ont de meilleurs qu'un générique.
  - **Les champs d'invitation sont déclarés par la page hôte** (`ChampInvitation[]`) : inviter
    une institution demande un nom et un type, un contact une fonction. Un `switch` sur la
    destination aurait dû connaître la huitième.
  - **L'import se passe de l'étape de correspondance** quand les en-têtes sont reconnues
    (`imports.mapping_depuis_entetes` : libellé ou nom technique, casse et accents ignorés,
    tronqué avant une parenthèse). C'est le cas dès qu'on a téléchargé le modèle. Rien n'est
    rapproché « au plus proche » : un en-tête inconnu est laissé de côté et le refus **nomme**
    les colonnes manquantes, l'assistant en deux étapes restant le recours.
  - **Dire qu'un geste ne s'applique pas** (`invitationImpossible` / `importImpossible`) plutôt
    que le laisser manquer. Deux cas réels : un interlocuteur PCS est un service extérieur
    qu'on prévient, pas un compte à créer ; les membres d'une équipe se composent depuis
    l'annuaire, où l'import a déjà eu lieu.
  - Côté serveur, deux actions nouvelles : `InstitutionViewSet.inviter` (compte inactif avec
    `pending_institution_name`/`_type`, le destinataire crée son institution par le chemin
    d'inscription existant et en devient contact principal — aucun jeton ni modèle de plus) et
    `ContactInstitutionViewSet.inviter` (annuaire ; prénom/nom facultatifs, un compte existant
    n'est jamais recréé et un simple utilisateur est promu, jamais rétrogradé).
- **Habilitation nominative au registre des personnes vulnérables** (art. R. 121-7 du CASF,
  voir `BASE-LEGALE-REGISTRE-VULNERABLES.md`) : l'accès suppose **deux actes distincts**, et
  aucun ne vaut sans l'autre.
  1. La **désignation** par la collectivité (`HabilitationRegistreVulnerables`) : un maire, un
     adjoint ou un agent habilité désigne quelqu'un en **attestant sur l'honneur** de sa propre
     qualité (`qualite_accordant`, `attestation_accordant`). La plateforme ne peut pas vérifier
     qu'un compte est celui du maire : l'attestation est le mécanisme qui fait porter la
     responsabilité de la déclaration sur son auteur, nommément et horodatée au journal
     (code d'audit `HABILITATION_REGISTRE`).
  2. L'**engagement au secret professionnel** du désigné (`User.engagement_secret_registre_le`
     + `_version`, code d'audit `ENGAGEMENT_SECRET`), présenté en disclaimer bloquant à la
     première connexion après l'attribution des droits, puis rappelé par un bandeau permanent
     non refermable. Porté par le compte et non par l'habilitation : l'engagement suit la
     personne. La version stockée permet de **redemander la signature si le texte change** —
     un engagement pris sur un autre texte n'engage à rien.

  Trois conséquences à ne pas défaire :
  - **Appartenir à la RCSC ne donne plus accès au registre** (changement du 28/10/2026).
    `utilisateur_a_acces_rcsc` ne sert plus qu'à proposer des candidats à la désignation.
  - **Lecture et écriture ont des gardes différentes.** `filter_personnes_vulnerables_queryset`
    garde la lecture et laisse ADMINISTRATOR voir (exploitation, journalisée) ;
    `institution_accede_commune` garde l'écriture et **exclut ADMINISTRATOR** — inscrire est un
    acte de la collectivité, seule responsable de traitement, la plateforme n'étant que
    sous-traitante (RGPD art. 28).
  - **Les textes juridiques sont servis par l'API** (`mon-etat`), jamais recopiés dans le
    bundle : ce qu'on fait signer doit avoir une version et une seule origine.
  - Une habilitation **se retire avec un motif, ne se supprime pas** (`perform_destroy` refuse),
    pour pouvoir établir qui avait accès à une date donnée.
- **Demandes de mobilisation** (`DemandeMobilisation`) : jamais présentées comme une
  réquisition légale, pouvoir réservé au préfet et au maire. Le module se complète le
  11/11/2026 de trois gestes — voir le § « Module mobilisation » ci-dessous.
- **Plans** : un `Plan` regroupe équipes, points et zones existants ; son activation sur une
  crise instancie les missions modèles (`PlanMissionModele`).
- **Requêtes N+1** : les serializers mémorisent sur l'instance les valeurs utilisées par
  plusieurs champs, et s'appuient sur les `prefetch_related` des ViewSets (filtrer en Python
  une relation préchargée).
- **« Dans quelle institution est cet utilisateur » a DEUX réponses en base, et elles peuvent
  se contredire.** `ContactInstitution` est la relation faisant autorité (voir
  `_resolve_institution_or_400`, `UserSerializer.get_institution_id`), mais le scoping
  territorial lit le raccourci `User.institution`
  (`zone_scoping._institution_commune_or_400`, `_institution_secteur_or_400`, et l'import du
  personnel communal). Un compte rattaché par `ContactInstitution` **sans** que
  `User.institution` soit posé utilise donc normalement l'application, sauf les vues
  `*-vue-mairie` / `*-vue-secteur` qui lui répondent *« Aucune commune associée à votre
  institution : contactez un administrateur »* — message doublement cruel, puisque
  l'administrateur venait de le rattacher et que son geste n'y changeait rien. Observé en
  production les 25 et 26/10/2026 : 75 échecs pour un agent, sur ses quatre sessions, jusqu'à
  ce qu'il cesse de revenir.
  - **La cause** : `ContactInstitutionViewSet.perform_create` — le chemin « ajouter un
    contact » de l'administration, donc le plus utilisé — créait la ligne sans appeler
    `grant_institution_and_demo_access`. Celle-ci est le point unique qui pose
    `User.institution`, ajoute la personne à l'équipe de l'institution, lui ouvre la zone de
    démonstration et lui envoie l'accès à la messagerie d'équipe. Son commentaire affirmait
    être appelée par tous les chemins de rattachement : c'était faux, et c'est ce qui a rendu
    le trou invisible. **Tout nouveau chemin de rattachement doit l'appeler**, et
    `tests/institutions/test_contact_institution_rattachement.py` le vérifie au lieu de
    l'affirmer — y compris l'invariant « un `ContactInstitution` actif implique un
    `User.institution` renseigné ».
  - **Les comptes d'avant** : `manage.py backfill_rattachement_institution` (avec `--dry-run`
    d'abord) les reprend. Il choisit, parmi les rattachements actifs, celui dont l'institution
    est encore en service puis celui où la personne est contact principal — le rattachement
    vivant plutôt qu'un vestige. 4 comptes concernés au 27/10/2026.
  - **L'invariant est désormais tenu à l'ÉCRITURE**, dans `ContactInstitution.save()` : un
    rattachement actif pose `User.institution` quand il est vide. C'est le seul endroit par
    lequel toute création passe forcément, donc le prochain chemin de rattachement ne pourra
    plus l'oublier. Délibérément minimal — seul le raccourci est posé, sans email ni appel
    réseau ; l'accueil complet (équipe, démo, messagerie) reste dans
    `grant_institution_and_demo_access`, qui a besoin d'une requête. Et jamais de
    détournement : le raccourci n'est posé que s'il est vide, donc un profil membre de
    plusieurs collectivités garde le contexte « Vue Ma Collectivité » qu'il a choisi.
  - **Pourquoi l'invariant plutôt qu'un repli à la lecture** : une quarantaine d'endroits
    lisent `User.institution`, dont des portes de contrôle d'accès au registre des personnes
    vulnérables et à l'estimation des habitations. Les réécrire en bloc, c'est risquer
    d'élargir un accès par inadvertance ; tenir l'invariant rend tous ces lecteurs corrects
    d'un coup, sans toucher à la surface d'autorisation. Les migrations ne sont pas affectées :
    `apps.get_model` rend un modèle historique sans méthode personnalisée.
  - Les messages d'erreur territoriaux (`zone_scoping`) distinguent enfin « votre compte n'est
    rattaché à aucune collectivité » de « cette collectivité n'a pas de commune renseignée »,
    et nomment la collectivité. Le message unique précédent — « contactez un administrateur » —
    envoyait chercher la solution auprès de quelqu'un qui ne pouvait rien y faire.
- **Une commune n'a qu'une mairie : c'est le couple (commune, type) qui identifie une
  institution, pas son nom.** `find_or_create_institution_from_annuaire`
  (`institution_attachment.py`) recoupait sur le **seul nom**, et comme une même mairie porte
  des noms différents selon qui l'a enregistrée, celle déjà connue sous
  « Châteauneuf-du-Faou » a été recréée sous « Mairie - Châteauneuf-du-Faou » dès qu'un adjoint
  s'est inscrit par l'annuaire officiel. Conséquences observées sur la commune 29027 : les deux
  institutions déclarées acteur sur la même crise, deux équipes jumelles, un adjoint dont le
  compte pointait sur l'une pendant que son plan vivait sur l'autre — et une reprise manuelle
  qui a détruit au passage sa fonction, son statut de contact principal et son rôle
  opérationnel. Le recoupement se fait désormais sur `(commune_code, type)`, en se limitant aux
  institutions **en service** : une collectivité délibérément retirée ne doit pas être
  ressuscitée par l'inscription d'un inconnu. Le repli historique sur le nom exact reste, pour
  les institutions sans code commune (associations, services de l'État). Un nom déjà choisi
  n'est jamais écrasé par celui de l'annuaire, et le rattachement sous un autre nom laisse une
  trace en main courante.
- **Le code d'un `InstitutionType` est normalisé en MAJUSCULES**, et un type existant est
  réutilisé sans tenir compte de la casse. La création depuis l'annuaire le mettait en
  minuscules, d'où un catalogue où « MAIRIE » et « mairie » cohabitaient (4 institutions contre
  5 au 27/10/2026), de même pour « CG » et « cg ». Les lectures qui comptent normalisent par
  `.upper()` (`Institution.save`, `_institution_est_autorite_locale`) — **toute nouvelle
  comparaison sur `type.code` doit le faire aussi**, faute de quoi elle ignore silencieusement
  la moitié des mairies, ce qui était le cas de `backfill_zones_mon_territoire` (4 institutions
  traitées sur 9). Les doublons de casse déjà en base subsistent : ils ne gênent plus la
  création, mais une normalisation rétroactive reste à faire.
- **Fusionner deux doublons** : `manage.py fusionner_institutions --garder <id> --absorber <id>`,
  **toujours avec `--a-blanc` d'abord** et après sauvegarde de la base. La commande repointe
  comptes, rattachements, équipes, plans, implications, rôles et demandes ; écarte les doublons
  stricts **vides** et refuse d'écarter ce qui porte du travail humain (un risque dont l'état
  des lieux est renseigné reste sur l'absorbée, et c'est dit à l'écran) ; puis désactive et
  renomme l'absorbée au lieu de la supprimer. Deux pièges qu'elle contourne, et qui valent pour
  toute opération du même genre : `Institution.save()` appelle
  `_assurer_zone_mon_territoire`, qui **recrée** la Zone « Mon territoire » de l'institution
  qu'on vide (d'où un `update()` et non un `save()` pour la pierre tombale) ; et
  `uq_contact_principal_institution` n'autorise qu'un contact principal par institution, donc
  le drapeau ne peut pas voyager tel quel.

### 5.12 ter Portée de lecture des contacts d'institution

`ContactInstitution` porte des personnes nommées avec leur email et leur fonction, et
`ContactInstitutionSerializer` expose `fields = "__all__"`. Jusqu'au 28/10/2026 le ViewSet
n'avait **aucune** `permission_classes` — donc le défaut `IsAuthenticated` — et son queryset ne
filtrait que par environnement : tout compte authentifié, y compris un citoyen venu déclarer un
dégât, pouvait lister les contacts de toutes les institutions de la plateforme. Les cinq pages
qui consomment cet endpoint tiraient d'ailleurs la table entière pour n'afficher qu'une
institution à la fois.

**Plus grave encore, les écritures l'étaient aussi** : `get_object()` passant par
`get_queryset()`, n'importe quel compte authentifié pouvait promouvoir, désactiver ou supprimer
le rattachement de n'importe qui dans n'importe quelle institution — se faire contact principal
d'une mairie, par exemple. Un test préexistant passait précisément parce que c'était ouvert.

Quatre cercles, du plus large au plus étroit :

| Qui | Voit |
|---|---|
| Administrateur | tout — il arbitre les rattachements et débloque une institution dont le bureau a perdu ses accès |
| Rôle institutionnel **en zone DEMO** | tout, coordonnées masquées par le serializer |
| Rôle institutionnel **avec `?institution=<id>`** | les contacts de celle-là |
| Tout le monde | ses rattachements, et ceux des institutions dont il est membre actif |

La distinction qui porte tout : **la question ciblée reste permise, la liste en vrac
disparaît.** C'est elle qui préserve le seul besoin réellement inter-institutions — déclarer
une institution actrice sur une crise et désigner son responsable, ce qui suppose de voir ses
contacts sans en être membre (`crises.component`, `acteurDirectContacts`). Un test vérifie
qu'un compte non institutionnel n'obtient rien, **même** en ajoutant le paramètre d'URL : sans
cela la restriction se contournerait d'un `?institution=`.

L'exemption **DEMO** reprend celle d'`InstitutionViewSet` (qui lève sa restriction de zone dans
cette zone, voir `TestInstitutionAndContactVisibleAcrossEnvironmentsInDemo`) : une vraie
institution doit rester utilisable pour une démonstration hors du périmètre du compte, et ses
contacts avec elle. Acceptable parce que le serializer masque les coordonnées en DEMO, et
parce que la zone de démonstration n'est accessible qu'aux comptes institutionnels (`demo_role`
n'est jamais posé sur un compte citoyen). La fuite réelle était en PROD.

Côté frontend, deux pages ont changé de façon de faire plutôt que de capacité : la page
Institutions demande les contacts à l'ouverture du détail d'une institution, la page Crises les
demande au moment où l'on choisit l'institution à déclarer actrice. `plan-modal` et le
formulaire public de déclaration sont inchangés — ils filtraient déjà sur leurs propres
rattachements, et deux tests de non-régression reproduisent leurs filtres côté client pour que
le cadrage ne leur retire rien.

### 5.12 bis Associations agréées de sécurité civile (AASC)

Premier partenaire en marque blanche : « Réserve Résilience - Casques Jaunes », semée par la
migration 0199 avec son branding et ses deux hostnames (`cj.assista-crise.fr` et
`app.reserve-resilience.org`, pointé en CNAME par le partenaire). Portée nationale, donc pas de
`commune_code`.

- **On rejoint une AASC, on ne la fabrique pas en la nommant.** `attach_secours_user_to_institution`
  faisait un `get_or_create` sur le nom saisi à l'inscription : un bénévole tapant « Casques
  jaunes » au lieu de « Réserve Résilience - Casques Jaunes » créait une seconde association et
  s'y retrouvait « Créateur », contact principal **et** responsable. Or une AASC est une
  association *agréée* : son existence sur la plateforme est un acte administratif, jamais
  l'effet d'une faute de frappe. `trouver_aasc` compare sur un nom normalisé (casse, accents,
  espaces) et **ne crée rien** ; sans correspondance, les `pending_*` sont conservés pour un
  rattachement manuel, comme pour une RCSC dont la mairie n'est pas encore enregistrée.
- **Un membre tout juste accepté est `INTERVENANT`.** Le défaut d'`assign_default_institution_role`
  est « RESPONSABLE si l'institution n'a aucune affectation, REGULATEUR sinon » : les deux sont
  absurdes pour quelqu'un dont la candidature vient d'être acceptée, et le niveau se déduisait
  du hasard de l'ordre d'inscription. C'est au bureau d'élever ce niveau quand la personne est
  formée.
- **`ContactInstitution.membre_bureau`** porte la gouvernance associative : administrer les
  membres, prendre en charge une candidature, valider les étapes d'un recrutement. Porté par le
  **rattachement** et non par le compte, délibérément — on est au bureau d'UNE association, la
  même personne peut être simple membre ailleurs, et les cinq `UserRole` sont globaux. Ce n'est
  pas non plus un `RoleOperationnel` : ceux-là servent l'opérationnel de crise.
- **Le bureau valide ses propres candidats, où qu'ils habitent**
  (`_est_bureau_de_laasc_demandee`). `approve_account` bornait une autorité locale aux comptes
  de son propre code postal, ce qui rendait le recrutement impossible dès le deuxième village —
  or une AASC recrute à l'échelle d'un département. L'élargissement est limité à un cas : la
  candidature à une AASC nommément déclarée, dont le validateur est au bureau. Le contrôle
  territorial des mairies est inchangé, et un test le vérifie.

Reste à faire, dans cet ordre : le circuit de recrutement (demande à rejoindre, étapes validées
par le bureau, lien d'invitation), la section RH (annuaire, qualifications avec échéances,
adhésion sans cotisation, date d'aptitude), puis les disponibilités à 15 jours pour les
mobilisations. Les qualifications par personne avec échéance n'existent PAS aujourd'hui :
`Competence` n'a pas de date et `AffectationCompetence` lie une compétence à une équipe sur une
crise, pas à une personne. Les disponibilités, elles, ont déjà leur socle
(`DisponibiliteOperationnelle`, pendue à `AffectationRoleOperationnel`).

#### Bénévoles d'association : ni agents, ni citoyens anonymes

Arbitrage du 11/11/2026, après le constat que les membres des Casques Jaunes étaient « bancals »
entre trois catégories. Le diagnostic : **trois choses différentes étaient dites dans un seul
champ global**. `importer_personnel_communal` écrivait `AUT_LOCALE` — un pouvoir sur toute la
plateforme — pour exprimer « il est membre d'une association ».

| Ce qu'on veut dire | Où ça vit |
|---|---|
| ce que je peux faire **sur la plateforme** | `User.type` → `UTIL_SIMPLE` pour un bénévole |
| à quelle **association** j'appartiens | `ContactInstitution` |
| **où** j'interviens | l'équipe départementale |
| mon **niveau** dans l'association | `Team.membres_encadrement` |

`importer_benevoles_association` (`core/imports.py`) est **distinct** d'`importer_personnel_communal`,
et pas un paramètre de plus : type de compte, rôle opérationnel, accès DEMO et équipe de
destination diffèrent tous les quatre. Un compte déjà institutionnel n'est **jamais** rétrogradé
— un agent de mairie peut aussi être bénévole.

**La promotion suit la désignation** : marquer quelqu'un encadrement le passe en `SECOURS`
(encadrer, c'est gérer les autres), tracé en main courante. Jamais de rétrogradation en sens
inverse : le retirer de l'encadrement ne lui retire pas son type, qu'il peut détenir pour une
autre raison.

#### Qui voit quels comptes

`core/visibilite_membres.py`. **Corrige un trou** : `UserViewSet` servait `User.objects.all()` à
tout acteur institutionnel ; le filtre `?institution=` existait mais était **facultatif**, et
huit écrans appelaient la liste sans lui. Une mairie quelconque voyait tous les comptes de la
plateforme.

Quatre règles, de la plus large à la plus étroite :

1. **administrateur** : tout — c'est lui qui débloque une institution dont le bureau a perdu ses
   accès ;
2. **bureau d'une institution** : tous ses membres — lui cacher une partie de son propre fichier
   rendrait la page Membres inutilisable ;
3. **encadrement d'une équipe** : cette équipe et **toutes celles en dessous**. Un coordinateur
   régional voit ses départements, le national voit tout le monde, la Gironde ne voit pas la
   Haute-Savoie ;
4. **acteur institutionnel d'une institution sans hiérarchie** (une mairie) : ses collègues.
   Sans cette règle, cloisonner par hiérarchie ferait disparaître les collègues d'un agent dont
   l'institution n'a aucune équipe à échelon.

Et toujours **son propre compte** : se masquer à soi-même ne protège personne.

Appliqué à `list` **et** à `retrieve` : restreindre la liste en laissant la fiche accessible par
son identifiant ne cloisonnerait rien, l'identifiant se devinant dans n'importe quelle réponse
qui mentionne un utilisateur. La descente de l'arbre se fait en Python sur **une** requête, avec
un ensemble de vus contre les cycles.

#### Envoi au nom de l'institution : email Brevo, SMS

`ConfigurationEnvoiInstitution` + `core/envoi_brevo.py` + `core/envoi_institution.py`
(migration `0248`), onglet **Envois** de la fiche institution.

Lève la limite inscrite dans `core/branding.py` depuis l'origine : « compte SMTP unique
Assista-Crise en v1, `reply_to` est le seul levier de personnalisation de l'adresse pour
l'instant ». Une institution qui fournit sa clé Brevo envoie depuis **son** adresse, et
Assista-Crise n'apparaît plus dans le message.

Le point d'insertion est `send_branded_mail`, parce que c'est la seule fonction qui connaît
l'institution. Conséquence voulue : **tous** les emails de marque blanche y passent, y compris
le cycle de vie des comptes (activation, mot de passe oublié) — choix explicite du 11/11/2026,
puisque le mail d'activation est le **premier** que voit un bénévole.

Contrat Brevo relevé sur leur documentation le 11/11/2026 : `POST
https://api.brevo.com/v3/smtp/email`, clé dans l'en-tête **`api-key`** (et non
`Authorization: Bearer`, qui renvoie 401), corps `sender {name, email}` / `to` / `subject` /
`textContent`, succès **201** avec `messageId`. Deux zones d'ombre, traitées défensivement :
leur documentation **ne liste que le 400** (aucune entrée 401/403) et **ne dit pas** quelle
erreur revient pour un expéditeur non vérifié. Tout statut hors 2xx est donc un échec nommé,
avec le message de Brevo remonté **intact** — c'est lui qui distingue une clé révoquée d'un
quota dépassé ou d'un domaine non vérifié.

**Le repli est volontaire et partiel.** Si l'API échoue, le message part quand même par le SMTP
Assista-Crise **en gardant le texte de l'institution** : sa signature, son Reply-To, son nom
dans le corps. Seule l'adresse `From` retombe sur Assista-Crise. C'est une fuite de marque
assumée, préférée à un message qui ne part pas (arbitrage de Sylvain). Elle n'est jamais
silencieuse : journalisée en main courante avec le message du fournisseur, et horodatée sur la
configuration, que l'onglet affiche.

Distinction de journalisation qui compte : une clé révoquée passe par `logger.warning` (c'est un
problème de configuration **chez le partenaire**), un bug de notre côté par `logger.exception`,
qui déclenche l'alerte technique. Confondre les deux noierait les vraies pannes.

Quatre décisions sur le stockage :

- **modèle séparé d'`Institution`**, pas des champs de plus. Le bloc de marque blanche sur
  `Institution` porte en commentaire « en clair : informations publiques », et
  `InstitutionSerializer` est servi largement. Un modèle à part garantit que la clé ne voyage
  jamais par défaut — le projet a déjà payé cette leçon sur cinq endpoints de secrets mesh, d'où
  `EstComptePont` ;
- **clés chiffrées au repos** (`EncryptedTextField`), vérifié par un test **en SQL brut** et non
  par l'ORM : seule façon de constater ce qu'un `pg_dump` contiendrait ;
- **jamais relues par l'API.** On ne sert que `*_cle_api_renseignee`, pas même un fragment :
  quatre caractères réduisent déjà le travail de qui la cherche. Une clé perdue se régénère chez
  le fournisseur ;
- **réservé au bureau** (`ContactInstitution.membre_bureau`), pas à tout contact actif : confier
  une clé qui permet d'envoyer **au nom** de l'association est un acte de gouvernance, du même
  ordre que d'administrer ses membres.

Côté interface, un champ de clé laissé vide signifie **inchangée** et non effacée — sans cette
distinction, ouvrir l'onglet et enregistrer effacerait la clé en place. L'effacement est un
geste explicite.

Deux fuites de marque corrigées au passage, trouvées en traçant les chemins d'envoi : l'accusé
« compte en attente de validation » et le mail de refus de compte signaient « L'équipe
Assista-Crise » **en dur**, hors de tout branding, par `send_mail_logged` direct.

**SMS : la couche est construite, l'adaptateur Mobimel ne l'est pas.** `core/envoi_sms.py` est un
registre de fournisseurs, de la même forme que celui des canaux d'alerte PCS — ajouter un
opérateur = une fonction + une entrée, sans migration (`fournisseur_sms` est une chaîne libre).
Mobimel y est **déclaré et marqué non implémenté** : l'opérateur existe, mais aucune
documentation publique de son API n'a pu être trouvée (ni endpoint, ni paramètres, ni forme
d'authentification). Un adaptateur écrit sur des suppositions enverrait des identifiants à une
URL inventée. Ce qu'il faut pour l'écrire est listé dans la docstring de `_envoyer_mobimel`, y
compris le **format du numéro** — c'est le point le plus souvent faux : un opérateur qui attend
`33612345678` et reçoit `+33612345678` accepte l'appel et ne livre rien.

#### Relecture avant envoi, et modèles de messages

`core/modeles_messages.py` (registre), `core/brouillons_envoi.py` (capture), `BrouillonEnvoi` +
`ModeleMessage` (migration `0249`), onglet **Modèles de messages** de la fiche institution, et
page **Messages à relire**.

Trois besoins d'un seul mécanisme (demande du 11/11/2026) : une fenêtre de relecture avant
envoi, des placeholders plutôt que des valeurs, et des textes qu'une institution réécrit.

**Aucun des 48 points d'envoi n'a été modifié**, et c'est le cœur de la conception. La capture se
fait dans `send_branded_mail` et la décision se déduit de la requête :

> un utilisateur authentifié, et **aucun destinataire n'est son adresse** → il écrit à un tiers

C'est la traduction du critère retenu après avoir sorti la liste réelle des 48 envois : « un
humain agit » ne suffisait pas, puisqu'une inscription est une action humaine. Le critère utile
est **« le message part-il vers quelqu'un d'autre ? »**. Les trois conséquences tombent d'elles-
mêmes :

| Famille | Exemples | Comportement |
|---|---|---|
| l'acteur écrit à un **tiers** (~25) | valider/refuser un compte, clôturer un dossier, inviter, réinitialiser le mot de passe **d'un autre** | capturé en brouillon, fenêtre de relecture |
| l'acteur est le **destinataire** | inscription, mot de passe oublié, accusé de dépôt | part directement — un éditeur montrerait à quelqu'un le mail qu'il reçoit, avec son propre lien dedans |
| **aucun humain** (4) | `notifier_administrateurs`, SOS mesh, passerelle muette, infrastructure DEMO | part directement, `request=None` |

**L'INVARIANT : un placeholder de lien n'est jamais résolu ailleurs qu'à l'instant de l'envoi.**
Onze points d'envoi utilisent `build_magic_link`, et un lien magique est un **porteur
d'identité** — qui l'a peut agir comme la personne, 7 jours. Le cas qui le prouve :
`UserViewSet.send_password_reset`, où un administrateur déclenche une réinitialisation **pour
quelqu'un d'autre** ; lui afficher ce lien lui donnerait la main sur ce compte.

Le masquage est fait **par valeur, pas par motif** : `build_magic_link` déclare chaque lien
produit sur la requête (`_liens_magiques`, même motif qu'`audit_log`), et on remplace exactement
ces chaînes par `[LIEN_1]`, `[LIEN_2]`… La correspondance est gardée **chiffrée** côté serveur et
n'est jamais servie par l'API. Reconnaître par motif d'URL laisserait passer la première forme à
laquelle on n'aurait pas pensé. Un test structurel vérifie que les quatre actions **et** la
variante `?next=` se déclarent toutes ; les liens sont remplacés du plus long au plus court,
parce qu'un lien peut être le préfixe d'un autre.

**L'interface est prévenue par un en-tête de réponse** (`X-Brouillons-Envoi`) qu'un intercepteur
Angular lit : aucun des 25 endpoints ne change de contrat, et tout envoi futur est couvert
automatiquement. `CORS_EXPOSE_HEADERS` est renseigné — sans lui l'en-tête arrive mais reste
invisible au JavaScript : la requête réussit et la fonctionnalité ne marche pas, sans qu'aucune
erreur n'apparaisse. La fenêtre est montée **une fois** dans la coquille de l'application, pas
par page.

**L'action a déjà eu lieu.** Le compte est validé, le dossier est clôturé ; seul le message
attend. D'où trois dispositions : `manage.py expedier_brouillons_oublies` envoie au-delà de
**24 h** avec le statut `EXPEDIE_AUTO` — distinct d'`ENVOYE`, pour mesurer si la relecture sert
ou si elle est systématiquement oubliée ; l'abandon exige un **motif**, pour savoir plus tard
pourquoi personne n'a été prévenu ; et la page « Messages à relire » retrouve ce qui a été
manqué (onglet fermé, « Plus tard », message produit par un collègue).

Le catalogue compte **16 messages, 15 personnalisables**. Les envois internes et techniques ne le
sont pas : ils vont aux administrateurs de la plateforme, et les laisser réécrire permettrait de
casser le texte d'une alerte de panne.

Quatre détails qui ont chacun coûté un aller-retour :

- **crochets littéraux doublés** : `[[PCS]]` rend `[PCS]`. Le sujet de l'alerte PCS commence par
  ce préfixe, sur lequel des filtres de boîte mail peuvent porter. `rendre()` le laissait intact
  seulement parce qu'aucune valeur n'était fournie pour « PCS » — le jour où un placeholder de ce
  nom existerait, le sujet changeait en silence. L'échappement **prime** sur la résolution d'un
  lien, y compris à l'envoi ;
- **contrôle de cohérence du catalogue** : tout placeholder employé doit être déclaré (sinon il
  partirait en clair dans le mail) **et** tout placeholder déclaré doit être employé (sinon
  l'écran réclame une valeur qui ne sert à rien). C'est ce contrôle qui a trouvé le `[PCS]` ;
- **un placeholder sans valeur est laissé tel quel**, jamais remplacé par du vide : « Bonjour
  [PRENOM] » se remarque et se corrige, « Bonjour  » passe inaperçu ;
- **compteur de segments SMS**, recalculé à la frappe : la facturation est au segment, et un
  texte de 161 caractères coûte deux fois celui de 160. Au-delà du premier segment, chacun ne
  porte plus que 153 caractères utiles (en-tête de concaténation).

Côté personnalisation, un champ identique au défaut est stocké **vide** : le texte suit alors les
évolutions de l'original au lieu d'être figé. Et `actif = false` revient au défaut **sans perdre**
la version réécrite.

**Reste à faire** : les 25 envois utilisent encore leurs textes en dur. La fenêtre de relecture
fonctionne sur tous — elle capture le corps déjà composé — mais la personnalisation par
institution ne s'applique qu'aux appels migrés vers `resoudre_modele`. À faire par lots : 37
extractions de f-strings en un seul commit est exactement là où vit la casse silencieuse.

#### Arborescence de coordination territoriale

`echelon` + `territoire_code` + `territoire_libelle` sur `Team` (migration `0247`), plus
`manage.py creer_arborescence_coordination --institution "<nom>"`. Conçu et validé le
28/10/2026, écrit le 11/11/2026 pour les Casques Jaunes.

`Team.equipe_parente` existait déjà (arbre de profondeur libre) mais `Team` n'avait **aucun
territoire** : rien ne permettait donc de trier les équipes département → région → zone →
national, ni de retrouver « l'équipe de l'Isère ». Les antennes restent des **équipes** et non
des institutions filles (décision antérieure : `Institution` n'a aucune hiérarchie).

    Coordination Nationale                              1
      └─ Coordination Zone de Défense « X »             10   (7 métropole + 3 outre-mer)
           └─ Coordination Régionale « X »              18   (13 métropole + 5 DROM)
                └─ Coordination Départementale « XX »   96   (métropole seulement)
                                                       ───
                                                       125 équipes

Cinq points à ne pas redécouvrir :

- **`core/zones_defense.py` est recopiée à la main, et elle se vérifie.** Il n'existe pas d'API
  publique stable servant la découpe en zones de défense, fixée par le décret du
  10 décembre 2015. `verifier_coherence()` est appelée **avant toute écriture** et par un test :
  aucun département dans deux régions, aucune région dans deux zones, et 96 départements de
  métropole (Corse comptée pour deux). C'est ce recoupement qui a servi à établir la table — les
  comptes officiels par zone tombent juste (Nord 1 région / 5 départements, Est 2/18, Ouest 4/20,
  Sud 3/21).
- **Un code de département n'est pas un entier** : `2A` et `2B`. Traiter la table comme numérique
  casse sur la Corse.
- **Les DROM s'arrêtent à l'échelon régional.** Leur territoire est à la fois région et
  département ; empiler deux équipes pour un seul territoire créerait deux salons pour les
  mêmes personnes.
- **Une équipe départementale renseigne AUSSI `departements`.** `territoire_code` dit ce que
  l'équipe *représente* ; `departements` est ce que lit le matching d'intervention existant.
  Oublier le second rendrait l'équipe invisible au moteur d'affectation.
- **La commande ne provisionne AUCUN salon Matrix** : 127 équipes feraient 254 salons, presque
  tous vides et tous affichés dans Element. Un salon se crée quand l'équipe a des membres.

Elle est **idempotente** et retrouve chaque équipe par `(institution, échelon, territoire)`,
jamais par son nom — un libellé d'affichage n'a aucune raison d'être stable, et s'en servir de
clé créerait un doublon au premier renommage.

**`--institution` se compare sans accents ni casse** (`nom_comparable`, rendue publique pour
cela — c'est le rattrapage que `trouver_aasc` faisait déjà). Les accents sont mutilés en route
par certains clients SSH, et la commande était alors impossible à lancer pour une institution
qui s'appelle « Réserve Résilience ». La correspondance reste **exacte une fois normalisée** :
jamais un rapprochement approximatif, et une ambiguïté est une erreur plutôt qu'un choix
arbitraire — écrire 125 équipes dans la mauvaise institution ne se défait pas d'un geste.

#### Encadrement d'une équipe

`Team.membres_encadrement`, défini depuis la page de l'équipe
(`TeamViewSet.definir_encadrement`). Il pilote la composition du salon Matrix « Encadrement »
(§ 7.1).

**Par équipe et non par personne** : la même personne peut encadrer son département et n'être
qu'intervenante ailleurs. Ni `Team.leader` ni `Team.regulateur` (une seule personne chacun) ni
`AffectationRoleOperationnel` (par **institution**) ne pouvaient le porter.

Action dédiée plutôt qu'un champ inscriptible par `PATCH`, pour deux garanties qu'un `PATCH` ne
donne pas : **un encadrant doit être membre de l'équipe** — l'encadrement est une qualité au sein
de l'équipe, pas une appartenance de plus, et désigner quelqu'un d'extérieur est refusé
explicitement plutôt que filtré en silence — et le changement est **journalisé**, parce qu'il
décide de qui lit un salon. L'appel remplace la liste entière (`set`), donc il est idempotent et
un retrait ne demande pas d'action séparée ; en revanche un corps **sans** `membres_encadrement`
est refusé, pour que « je n'ai rien envoyé » ne soit jamais lu comme « retire tout ».

#### Enrôlement d'un bénévole, de l'import à sa fiche

Déroulé validé le 11/11/2026, de bout en bout :

1. `importer_benevoles_association` crée le compte (`UTIL_SIMPLE`, inactif), le rattachement
   (`ContactInstitution`), la fiche (`FicheBenevole`), et place la personne dans l'équipe
   départementale **déduite du géocodage** ;
2. elle reçoit `BENEVOLE_ACTIVATION` — un modèle **distinct** de celui des comptes
   institutionnels (`send_benevole_account_email`). Deux raisons, aucune cosmétique : le texte
   des comptes institutionnels annonce un « compte institutionnel » et un « rattachement à
   votre institution », où un bénévole ne reconnaît rien de sa situation ; et son lien
   n'emmenait **nulle part**, alors qu'il reste ici l'essentiel à faire. Le lien porte donc
   `?next=/ma-fiche-benevole`, honoré par `ActivateAccountComponent` — **restreint aux chemins
   internes**, sinon un lien d'activation qui circule par email devient une redirection ouverte
   avec la caution du domaine ;
3. elle arrive sur `/ma-fiche-benevole` : relecture de ce que l'import a saisi, dépôt des
   justificatifs, et mot de passe **facultatif**. Le lien magique continue de fonctionner — en
   imposer un juste après le premier clic serait une friction au pire moment.

**Le département vient du géocodage, pas du code postal.** `core/departements.py` n'est qu'un
repli, et il le **signale** : un préfixe postal se trompe sur la Corse (20xxx → 2A ou 2B), sur
l'outre-mer (trois chiffres) et sur tout fichier passé par un tableur, qui mange le zéro
initial. Changer d'adresse peut donc changer d'équipe départementale : l'écran l'annonce **avant**
l'enregistrement (`adresseModifiee`), pour que ce ne soit pas découvert après coup.

**Le secteur est en lecture seule** (`commune_code`, `departement_code`…). Le laisser saisir
permettrait de se déclarer dans un département où l'on n'habite pas, donc de rejoindre une
équipe qui n'est pas la sienne.

Une fiche de bénévole est **une ressource comme les autres** (demande de Sylvain : « c'est juste
une ressource particulière comme membre de l'asso ») : même forme qu'`Offer` et `Habitation` —
`adresse` chiffrée, `location` PointField, `ban_id`, et les quatre codes de secteur
dénormalisés par `commune_secteur_codes`.

#### Ce que la fiche porte, et ce qu'elle ne porte pas

`FicheBenevole` ne porte **aucune disponibilité** : son champ s'appelle
`frequence_engagement` (migration `0254`, un `RenameField`) et dit un volume annuel —
« occasionnelle », « régulière », « fréquente », les libellés du formulaire d'adhésion du
partenaire.

Ce n'est pas une disponibilité, et la différence est de nature, pas de précision : « environ
10 jours par an » ne dit **rien** du 5 novembre. On ne peut donc pas la convertir en
déclarations datées sans inventer des dates, et elle ne peut pas servir à armer une garde. Elle
sert à autre chose, qui compte aussi : dimensionner l'effectif mobilisable sur l'année, et
savoir à qui l'on peut demander souvent. Elle est conservée **à côté** du moteur plutôt que
fondue dedans, et jamais lue par la grille — un test le vérifie.

Elle ne conditionne pas non plus `est_complete` : une fiche est exploitable dès qu'on sait
joindre la personne et où elle est.

**Dette de sécurité corrigée au passage sur l'ancien modèle à la journée**
(`DisponibiliteOperationnelle`, toujours exposé mais plus utilisé par les membres) : le ViewSet
servait `objects.all()` sans `permission_classes` ni filtrage. Tout compte connecté lisait les
disponibilités de la plateforme entière et surtout **écrivait celles de n'importe qui** —
`prendre_permanence` et `quitter_permanence` appelaient `get_object()` sur une table non
filtrée. On pouvait déclarer un inconnu indisponible la veille d'une garde. Lecture cloisonnée
comme les comptes, écriture plus étroite encore : le titulaire, le bureau, ou l'encadrement
d'une de ses équipes.

**L'import crée aussi l'affectation opérationnelle** (`INTERVENANT`, comme le circuit de
recrutement à l'acceptation) : la voie « import » ne doit pas produire un membre d'une autre
nature que la voie « candidature ». Toujours pas de `REFERENT`, qui est un niveau de
responsabilité.

#### Le bénévole est une ressource, et le moteur de disponibilité est celui à créneaux

Deux corrections du 11/11/2026, qui n'en font qu'une : Sylvain demande un seul moteur de
disponibilité, et c'est celui des personnes ressources — « celui qui est appelé quand on
constitue une équipe ».

**Le moteur, c'est `DisponibiliteOffre`** : une ligne par `(offre, date, créneau)`, quatre
créneaux par jour (`Creneau` : matin, midi, soir, nuit), et **« pas de ligne = indisponible »**.
C'est ce que lit le planning de `/admin/teams` — « les disponibilités des offres dont le membre
est l'auteur » — et ce que remplit le formulaire public « proposer mon aide » depuis l'origine.

Une première version de l'écran bénévole avait écrit dans `DisponibiliteOperationnelle` : une
déclaration **à la journée**, accrochée à `AffectationRoleOperationnel`, que seule la grille de
l'association lisait. C'était un second moteur, et le défaut n'était pas cosmétique : la grille
pouvait afficher « disponible » là où la constitution d'équipe ne voyait rien. La journée est
aussi la mauvaise unité — quelqu'un de libre le matin et pris l'après-midi est une situation
ordinaire, et une déclaration à la journée force à répondre « indisponible », perdant une
demi-journée d'effectif à chaque fois.

**Le moteur est clé sur `Offer`, donc un bénévole doit avoir une offre.** C'est
`fiches_benevoles.ressource_du_benevole()` : une offre de type « Bénévolat », dont le membre est
l'auteur, créée à l'import et réalignée à chaque enregistrement de fiche (position, secteur,
identité — sinon quelqu'un qui corrige son nom resterait cherchable sous l'ancien). Retrouvée
par `(author, institution, type)` et jamais par son titre : un libellé d'affichage n'a aucune
raison d'être stable.

Conséquence voulue, et c'est la réponse à l'autre question : **un bénévole devient une vraie
ressource**, trouvable par les régulateurs de son association comme n'importe quelle offre.

#### Offres internes : `Offer` n'était pas cloisonné du tout

Ce qui précède était impossible sans ça. `Offer` est servi par un `OfferViewSet` en `AllowAny`,
sa liste alimente la carte publique et la recherche, et le modèle ne portait **ni institution ni
visibilité**. Importer un fichier d'adhérents aurait publié l'annuaire de l'association —
l'inverse exact de la consigne « seule la réserve résilience a le droit de les voir comme
ressource ».

`Offer.visibilite` (`PUBLIQUE` / `INTERNE`) + `Offer.institution`, migration `0255`, et
`core/visibilite_offres.py` comme pendant de `visibilite_membres.py`. Une offre `INTERNE` n'est
servie qu'aux membres actifs de son institution, à son auteur, et aux administrateurs.

**Le défaut est permissif, et c'est délibéré** : toutes les lignes existantes restent
`PUBLIQUE`. Ce champ ne peut donc pas *réduire* par accident ce qui était déjà visible ; il
ouvre la possibilité de fermer.

Cinq points servent des offres à un client, et le filtre est appliqué aux cinq — la liste est
dans les tests, parce qu'une nouvelle vue qui sert des offres sans passer par là est un oubli
que seul un test attrapera :

| Où | Pourquoi ça compte |
|---|---|
| `OfferViewSet.get_queryset` | la carte publique et la recherche ; appliqué **avant** tout aiguillage par action, cette vue étant anonyme |
| tableau de bord (`_base_querysets`) | un compteur « 412 bénévoles » renseigne déjà sur l'effectif d'une association, sans qu'aucune fiche ne fuite |
| candidats à un point | on ne recrute pas dans l'annuaire d'une autre association |
| logement des intervenants | même filtre, par cohérence |
| synchronisation satellite | un satellite sert le public de son territoire ; rien ne l'autorise à détenir cet annuaire |

Deux garde-fous de modèle : `visibilite` est **indexé** (il entre dans le filtre de toute
lecture, sur la table la plus volumineuse du projet), et `clean()` refuse un `INTERNE` sans
institution — il ne serait visible de personne, et on chercherait longtemps pourquoi un bénévole
« n'apparaît pas ».

`Offer.title` reste en clair (champ de recherche et de tri) : le titre d'une ressource bénévole
est donc « Bénévole — Prénom N. », **nom abrégé**. Y écrire l'état civil complet sortirait en
clair ce que `first_name_offer` / `last_name_offer` chiffrent juste à côté.

#### La grille de l'association, en créneaux

`DisponibiliteOperationnelleViewSet.grille` lit les mêmes lignes que la constitution d'équipe :
quinze jours × quatre créneaux (choix de Sylvain ; les écrans citoyens plus anciens restent à
huit jours et ne sont pas touchés).

Ce moteur n'a que **deux états** par créneau, et il ne faut pas en inventer un troisième : il ne
sait pas stocker « non renseigné ». Ce qui restait juste dans l'ancienne grille — distinguer un
silence d'un refus, pour savoir qui relancer — est donc porté autrement, par `a_declare` :
en base, une grille vierge et une grille entièrement décochée sont identiques, et seul ce
drapeau les sépare.

**L'orientation des trois grilles est la même, et ce n'est pas un détail de goût** (demande de
Sylvain du 11/11/2026 : « 1 colonne = 1 jour, 4 lignes = les 4 créneaux… c'est tellement plus
lisible ») : **une colonne par jour, les quatre créneaux empilés**, matin en haut. C'est
l'orientation que le modal de recrutement (`dispo-mini`) utilise depuis l'origine, donc celle que
l'encadrement a déjà sous les yeux au moment où il constitue une équipe. Deux orientations pour
la même information obligeraient à relire l'en-tête à chaque écran — et une journée se lit mieux
comme un bloc vertical qu'étalée sur quatre colonnes.

La première version faisait l'inverse (une ligne par jour) et, sur la grille de l'association,
produisait **soixante colonnes d'une case** : illisible.

Côté écran bénévole (`/ma-fiche-benevole`, onglet « Mes disponibilités »), la colonne des
créneaux reste collée à gauche pendant le défilement horizontal — seize colonnes ne tiennent pas
sur un téléphone, et sans ça on ne sait plus quelle ligne on lit. Un geste « toute la journée »
par colonne et un « tout cocher » sur quinze jours : soixante cases à cocher une par une,
personne ne le fait, et une grille que personne ne remplit ne sert pas à armer une garde. Le
« tout cocher » enchaîne les jours **séquentiellement** : quinze requêtes simultanées sur le même
jeu de lignes, c'est quinze occasions de conflit pour un gain invisible.

La lettre dans chaque case (`M` / `Mi` / `S` / `N`) porte l'information autant que la couleur :
la grille reste lisible en niveaux de gris et pour un daltonien, et elle dit **lequel** des
quatre créneaux on lit. « Mi » prend deux lettres parce que « M » désignerait aussi bien matin
que midi.

#### Justificatifs de qualification : déposés par le membre, validés par sa hiérarchie

`QualificationMembre.justificatif` + `statut` (`DECLAREE` / `VERIFIEE` / `REFUSEE`), migration
`0253`. Permis, diplômes, attestations de formation.

**« Déclarée » n'est pas « vérifiée », et le mot compte** : tant que l'encadrement ne s'est pas
prononcé, une qualification est une affirmation de son titulaire. L'interface le montre au bord
gauche de chaque ligne, des deux côtés — celui du membre et celui du manager.

**L'accès aux PIÈCES est plus étroit que l'accès aux comptes** (`peut_voir_justificatifs`) :
soi-même, le bureau, ou l'encadrement d'une équipe à laquelle le titulaire appartient — ou d'une
équipe au-dessus. Un simple collègue est refusé, alors qu'il **voit** le compte : un diplôme
n'est pas un annuaire.

Protection du fichier, les quatre mêmes garde-fous que les autres pièces jointes sensibles :
`get_encrypted_file_storage`, `secure_document_path` (préfixe `documents/`, bloqué par nginx),
`validate_identity_document_file`, et **jamais d'URL `/media/`** — le fichier ne sort que par une
action dédiée, après contrôle des droits, avec journalisation du succès **et** du refus. Côté
Angular il est donc chargé en **blob** : un `<a href>` ne porterait pas l'en-tête
d'authentification, et le navigateur afficherait une page de refus.

**Un refus exige un motif**, qui est lu par le membre. Sans lui, il redépose la même pièce sans
savoir ce qui n'allait pas. Redéposer remet le titre à instruire : c'est la seule façon de
répondre à un refus.

#### Politique de conservation : ce qu'on annonce est ce qu'on fait

`core/conservation_pieces.py` (la table) et `core/pieces_conformite.py` (ce qui l'exécute),
migration `0267`. Demande du 13/11/2026 : afficher le tableau, le texte de loi applicable et
le pourquoi **sur la page de dépôt et sur la page de validation**, et appliquer la règle —
« pour le permis, la destruction du fichier une fois validé, et une destruction à 30 jours
s'il n'est pas validé ».

**La table est une donnée du logiciel, pas un texte recopié dans deux gabarits.** C'est elle
qui décide de détruire le fichier ; l'écran l'affiche, il ne la redit pas. Deux copies
finiraient par diverger, et c'est l'écran qui aurait tort : il promettrait une destruction qui
n'aurait pas lieu, ce qui est pire que ne rien promettre. Servie par
`GET /api/conservation-pieces/`, et attachée à chaque titre du catalogue (`conservation`) pour
que la règle puisse être annoncée **au moment du choix du titre**.

Trois régimes, portés par `Qualification.categorie_piece` :

| Régime | Ce qui reste | Exemples |
|---|---|---|
| `VERIFIER_DETRUIRE` | la trace (qui, quand, valable jusqu'au), jamais la copie ni le numéro | pièce d'identité, permis, titre de séjour, justificatif de domicile |
| `CONSERVER_ENGAGEMENT` | la pièce, le temps de l'engagement + la prescription | PSE1/2, formation continue, certificat médical |
| `DUREE_LEGALE` | la pièce, pour la durée imposée par un texte | RIB et pièces comptables (10 ans, art. L123-22 c. com.) |

Quatre règles tiennent l'ensemble :

- **La trace survit au fichier.** `piece_detruite_le` distingue « aucune pièce déposée » de
  « vérifiée, puis détruite comme prévu » — deux états que le seul booléen `a_justificatif`
  confondait. Sans cette trace, personne n'oserait détruire : il ne resterait plus rien pour
  montrer que le contrôle a eu lieu.
- **La destruction suit la décision dans la même requête**, validation comme refus. La
  différer à une tâche de nuit laisserait une fenêtre pendant laquelle la politique affichée
  serait fausse.
- **Trente jours sans décision, et le fichier part** (`purger_pieces_non_validees`, simulation
  par défaut, rappel à J-7). La LIGNE survit : supprimer tout ferait perdre au membre la date
  et l'organisme qu'il avait saisis, une double peine pour une négligence qui n'est pas la
  sienne.
- **Une catégorie inconnue ne détruit rien.** Une entrée de catalogue créée par une
  institution retombe sur `SECOURISME` : se tromper fait garder une pièce de trop, jamais
  perdre une pièce qu'il fallait.

**`PieceIdentiteReserve` était l'exception, et c'était un défaut.** Le permis d'un candidat à
une réserve y était conservé indéfiniment : aucun état de validation, aucune suppression, la
seule date portée étant celle du dépôt — l'inverse exact de la politique, sur la pièce qui en
est l'exemple même. Il porte désormais le même cycle (`verifier` / `refuser`, `valable_jusqu_au`
relevé au contrôle, images détruites dans la foulée) et une liste `a-instruire` : une politique
de destruction qui dépend d'une validation que personne ne peut déclencher ne s'applique
jamais.

Les durées marquées `ferme` citent un article et sont opposables ; les autres sont
**recommandées** et alignées sur les délais de prescription (art. 2224 et 2226 du code civil).
L'écran le dit — présenter une recommandation comme une obligation est une faute symétrique de
l'inverse. Le registre des traitements reste à valider par le DPO de l'association.

**Régler le catalogue, et corriger une pièce mal rangée.** Deux ajouts du 13/11/2026 sans
lesquels la politique s'affiche sans jamais s'appliquer :

- Onglet **Catalogue des titres** de `/admin/membres-association` : la catégorie de
  conservation se règle par entrée du catalogue, avec la durée et le texte applicable en
  regard. L'écran compte et signale les titres restés sur le défaut — tant qu'un permis y
  reste, sa copie ne sera jamais détruite, et personne ne s'en apercevrait. Le serveur refuse
  une catégorie inconnue (`validate_categorie_piece`) : le repli silencieux existe pour les
  entrées antérieures à cette table, pas pour couvrir une faute de frappe au moment où l'on
  décide du sort d'un fichier.
- Action **`requalifier`** sur `QualificationMembre`, proposée à côté du bouton « Valider » :
  « si le bénévole se plante et met permis dans diplôme, le management doit pouvoir modifier
  cela ». Le titre décide du régime, donc corriger **avant** de valider est la seule façon
  d'appliquer la bonne règle — d'où la correction posée là où la décision se prend, et non
  dans un écran d'édition séparé. Le statut retombe à `DECLAREE` (on se prononce sur le titre
  corrigé), une pièce déjà vérifiée n'est plus requalifiable (son fichier peut avoir été
  détruit, la déplacer sous un régime conservateur ferait croire à une pièce qu'on n'a plus),
  et le doublon interdit par la contrainte `(personne, titre, environnement)` est annoncé en
  409 plutôt que rendu en erreur de base de données.

#### Section départementale : où arrive un bénévole qui adhère

`core/rattachement_departemental.py`. Une « section départementale » n'est pas un concept de
plus : c'est une `Team` d'échelon `DEPARTEMENTAL` dont `territoire_code` porte le code INSEE du
département. Le rattachement est posé dans `grant_institution_and_demo_access` — le passage
obligé de **tous** les chemins de rattachement, et non dans l'un d'eux, pour ne pas reproduire
le trou où « ajouter un contact » n'y passait pas.

Pourquoi un défaut plutôt qu'une question : un bénévole qui s'inscrit ne connaît pas
l'organigramme, et le lui demander produit soit un choix au hasard, soit un champ vide. Or
quelqu'un rattaché à rien n'est dans aucun salon, ne reçoit aucune campagne ciblée par
territoire et n'apparaît sur aucune grille — il a adhéré pour rien. Le département vient du
**géocodage** et non du code postal (la Corse partage `20xxx`, l'outre-mer demande trois
chiffres).

Ce n'est pas une assignation : l'encadrement déplace qui il veut, et un déménagement retire de
l'ancienne section (`retirer_les_autres=True`) — rester mobilisable à 700 km et figurer dans
deux salons départementaux serait pire que ne pas être rattaché du tout. Sans section dans le
département, rien n'est inventé : la personne reste dans l'équipe de tête.

#### Les salons naissent avec l'équipe, et le salon d'annonces

`matrix.provisionner_salons_equipe`, appelé par `TeamViewSet.perform_create`,
`creer_avec_membres` et `creer_equipe_fille`. Les deux salons (Intervenants, Encadrement)
existent dès la création : c'était un second geste depuis la fiche de l'équipe, que personne ne
faisait. L'**inscription** des membres n'a rien demandé de plus — le pont resynchronise la
composition en continu, donc quelqu'un qui rejoint l'équipe demain y entre tout seul.

`TypeSalonInstitution.ANNONCES` (migration `0268`) est une **diffusion**, pas un troisième
salon de discussion : tous les membres de l'association le reçoivent — y compris ceux
qu'aucune équipe active ne mobilise, ce qui le distingue de « Bénévoles mobilisés » — et seul
le bureau (`ContactInstitution.membre_bureau`) y publie. Techniquement : `events_default: 50`
posé à la création du salon, et niveau 50 accordé aux seuls rédacteurs que Django désigne
(`SalonMatrixInstitutionSerializer.get_redacteurs`), reposé à chaque cycle — un ancien
trésorier ne doit pas garder le droit d'écrire à toute l'association. Le pont ne relit et ne
republie que si les niveaux ont changé : republier un état identique toutes les 30 s est ce
qui avait saturé Synapse le 22/10 avec les noms d'affichage.

Le contrôle est **répété côté web** (`_est_membre_bureau`) parce que le relais de chat écrit
avec le compte du bot, qui est administrateur du salon : sans ce garde-fou, passer par
l'interface contournerait la restriction posée dans Element.

Pourquoi un salon à part plutôt qu'une consigne dans le salon des bénévoles : une annonce qui
compte doit être lisible sans remonter trente messages de coordination, et une consigne de
politesse ne tient pas en situation — c'est au salon de garantir le silence, pas aux gens. La
diffusion ne remplace pas la conversation, elle la décharge.

#### L'arborescence repliable et sa pastille

Onglet **Équipes et justificatifs** de `/admin/membres-association`. Le serveur sert une liste
**plate** d'équipes ; la hiérarchie est dans `equipe_parente` et l'arbre est reconstruit côté
client.

Trois choix qui tiennent à l'échelle réelle (125 équipes pour les Casques Jaunes) :

- **la page s'ouvre refermée.** 125 équipes dépliées d'office ouvrent sur un mur. Un bouton
  « ouvrir ce qui attend » déplie les seules branches qui mènent à une pièce en attente — c'est
  le geste que cherche le manager ;
- **la pastille d'une branche compte tout ce qui est en dessous** (`aVerifierTotal`). Ne compter
  que l'équipe elle-même laisserait une branche repliée masquer ce qui attend dedans, ce qui est
  exactement le défaut qu'une pastille est censée corriger. Le compteur vient de
  `qualifications-membres/a-verifier/` et est **rechargé après chaque décision** : un décompte
  tenu localement finirait par mentir ;
- **un cycle dans `equipe_parente` ne doit pas figer la page**, et une équipe dont le parent est
  absent (autre institution, ou désactivé) devient racine plutôt que de disparaître sans que
  rien ne le dise. Les deux sont tenus par un test.

#### Module mobilisation : prévisualiser, extraire, vérifier au QR

Trois demandes de Sylvain du 11/11/2026, sur un module qui existait déjà
(`DemandeMobilisation`, `core/attestation_mobilisation.py`, page
`/admin/demandes-mobilisation`). Elles comblent chacune un manque précis.

**Prévisualisation** (`GET /api/demandes-mobilisation/<id>/attestation/`). Il n'existait que
`envoyer-attestation`, qui expédie : la seule façon de voir le document était donc de se
l'envoyer à soi-même, ou de l'envoyer au destinataire pour s'apercevoir après coup qu'une ligne
était fausse. `Content-Disposition: inline` — le navigateur l'affiche au lieu de le déposer dans
les téléchargements, c'est toute la différence entre une prévisualisation et un fichier de plus.
Côté Angular, chargée en **blob** : la route exige l'en-tête d'authentification, qu'un
`<a href>` n'enverrait pas. Disponible aussi sur une demande **révoquée** : on regarde aussi ce
qui a été émis.

Rien n'est stocké, comme avant : le PDF est reconstruit à chaque appel depuis les données
actuelles, statut inclus. Un PDF mis en cache afficherait « active » après une révocation.

**Extraction** (`GET /api/demandes-mobilisation/extraction/?crise=…&institution=…`), en CSV à
séparateur `;` — ces fichiers s'ouvrent dans un Excel configuré en français, où un CSV à la
virgule arrive sur une seule colonne. Dix-huit colonnes : référence, autorité, émetteur,
destinataire et son type, immatriculation, point de rendez-vous avec adresse et GPS, équipe,
mission, motif, statut, date de révocation, et **le lien de vérification** de chaque ligne —
plutôt que le jeton nu, parce que collé dans un navigateur il donne le statut à jour, ce qu'un
CSV ne saura jamais dire.

Deux points qui comptent : `crise` est **obligatoire** (un extrait « de toutes les crises » est
un vidage de base, pas un document de retour d'expérience), et le filtre `institution`
s'applique **par-dessus** le cloisonnement de `get_queryset` — passer l'identifiant d'une
institution dont on n'est pas membre ne sort rien. Tracé en main courante avec
`exposition=EXPORT`, qui distingue une consultation d'une sortie de données hors plateforme.

**Vérification au QR : le QR pointe vers l'APPLICATION, et le verdict a deux niveaux.**

Le QR imprimait `/api/verifier-mobilisation/<jeton>/`, une page HTML servie par Django et faite
pour un gendarme sans compte. Il pointe depuis le 11/11/2026 vers
`/verifier-mobilisation/<jeton>` — une route Angular, donc hors `/api/`. Proposition de
Sylvain, et c'est la bonne : « l'appareil photo lit l'URL, renvoie sur le site, réutilise
l'authentification en place ». C'est ce qui donne la vérification complète **sur iPhone**, où
le navigateur ne sait pas décoder un QR : l'appareil photo natif ouvre l'URL, l'application
retrouve la session, sans décodeur et sans rien installer.

`verdict_mobilisation(demande, complet)` produit **les deux sorties** — la page HTML publique et
le JSON de l'application. Une seule fonction, délibérément : deux listes de champs écrites
séparément finiraient par diverger, et celle qui se tromperait serait la publique, c'est-à-dire
la fuite.

| | Connecté | Anonyme |
|---|---|---|
| valide / révoquée / inconnue, référence, autorité, crise, nature, dates | ✓ | ✓ |
| **destinataire** | ✓ | retiré |
| **lieu de rendez-vous** | ✓ | retiré |

**Ce resserrage corrige un défaut réel** : la page publique affichait le nom du destinataire et
le lieu, donc un QR ramassé par terre disait qui avait été mobilisé et où.

L'endpoint reste `AllowAny` plutôt que fermé, et c'est un arbitrage explicite : une autorité
extérieure doit pouvoir constater qu'un document n'est pas faux — elle lit le nom sur
l'attestation qu'elle tient. Le fermer entièrement obligerait d'ailleurs à réécrire le texte
légal du PDF, qui annonce un document « vérifiable via le QR code ». La barre posée est **être
authentifié sur le site**, pas « avoir un lien avec cette demande » : l'authentification lève le
masquage, le jeton reste l'autorisation.

**La route Angular n'a pas de garde d'authentification**, et ce n'est pas un oubli : une garde
renverrait un contrôleur extérieur vers une page de connexion qu'il ne peut pas franchir, alors
que le serveur sait lui répondre. C'est le serveur qui décide du niveau de détail — une garde
côté navigateur ne protège rien.

**Les attestations déjà émises portent l'ancienne adresse imprimée**, donc la route Django reste
servie. Elle rend le verdict réduit et affiche un lien « Vous êtes membre ? Ouvrir le détail
dans l'application → » : un geste de plus pour les PDF déjà dans les poches, rien de cassé.

Le rendu du verdict est mutualisé entre le scanner intégré et la page ouverte par le QR
(`VerdictMobilisationComponent`), pour la même raison que la fonction côté serveur. Jamais le
téléphone ni l'email de la cible, dans aucun des deux niveaux : ce sont des données de contact,
et le jeton n'est pas une autorisation de les lire.

Un jeton inconnu rend **200 avec `valide: false` et `connue: false`**, jamais 404 : le scanner
doit distinguer « ce QR n'est pas des nôtres » d'une panne réseau, et un 404 se confond avec une
erreur de route côté client. L'écran distingue d'ailleurs trois verdicts — valide, révoquée,
inconnue — et un quatrième état qui n'est pas un verdict : « serveur injoignable, ne concluez
rien de cet échec ».

**Le scanner intégré utilise `BarcodeDetector`, l'API du navigateur, et aucune
bibliothèque.** Cette API existe sur Chrome et Edge, **pas sur Safari ni iOS** — ce qui aurait
été une vraie limite si le scanner était le seul chemin. Il ne l'est pas, et c'est pourquoi le
QR pointe vers l'application : **sur iPhone, l'appareil photo natif fait le travail**, ouvre la
page et réutilise la session. Le scanner reste utile pour contrôler plusieurs personnes à la
suite sans ressortir l'appareil photo à chaque fois. Embarquer un décodeur JavaScript aurait
couvert l'iPhone dans le scanner lui-même, au prix d'une dépendance de plus dans un projet qui
n'en a aucune de ce genre — et sans rien apporter que le chemin natif ne donne déjà.

La saisie manuelle de la référence reste ouverte à tous. `jetonDepuisTexte` accepte
donc l'URL complète comme le jeton nu, et **refuse** ce qui n'a rien à voir — un QR de carte de
visite ne doit pas partir en requête, et l'écran doit dire « ce code n'est pas une attestation »
plutôt que « introuvable », qui laisserait croire à une attestation périmée.

La caméra est arrêtée à la fermeture **et** à la destruction du composant : une diode qui reste
allumée après fermeture est le genre de détail qui fait désinstaller une application. Et une
image par 400 ms plutôt qu'en continu — un QR tenu à la main n'a pas besoin de 60 images par
seconde, et décoder sans répit chauffe le téléphone pour rien.

**Le QR code est passé de 26 à 45 mm** (`COTE_QR_MM`), soit 73 % de côté en plus et trois fois
la surface, à la demande de Sylvain : « plus gros pour être plus facilement lisible sans
modifier profondément la mise en page ». La mise en page ne bouge pas — la zone 2 offre
95 × 125,5 mm utiles, et les flowables qui suivent se replacent d'eux-mêmes, ce qui est tout
l'intérêt d'un `Frame` platypus plutôt que de coordonnées absolues. Au-delà, on perdrait le
texte légal en bas de zone : 45 mm est le réglage, pas un maximum théorique.

Le motif lui-même est devenu plus tolérant au même encombrement : correction d'erreur au
**niveau Q** (25 % de redondance au lieu des 7 % par défaut) parce que ce document est plié en
quatre, glissé dans une poche et ressorti froissé ; et marge réduite de 4 à 2 modules, les deux
modules récupérés allant au motif.

#### Campagnes de disponibilité : solliciter en masse, sur critères

Demande de Sylvain du 11/11/2026. Le point qui commande toute la conception est celui-ci :
« **Date de la période demandée — et pas seulement un texte libre dans le mail** — pour le faire
rentrer en bdd pour constituer les équipes en avance. »

Modèles (migration `0256`) : `CampagneDisponibilite`, `CibleCampagne`, `RotationCampagne`,
`AffectationRotation`. Page `/admin/campagnes-disponibilite`, dans la rubrique **Mon
association**.

**Aucun de ces modèles ne stocke de disponibilité.** Les réponses vont dans
`DisponibiliteOffre`, le moteur unique que lit la constitution d'équipe. Une campagne est un
moyen de faire remplir ce moteur, jamais une source parallèle — c'est la leçon du double moteur
corrigé le même jour.

**Le ciblage ne réinvente rien** (`core/ciblage_benevoles.py`), et c'est ce qui le rend court :

| Critère | D'où il vient |
|---|---|
| compétences | `Offer.competences`, porté par la ressource du bénévole |
| permis, diplômes | `QualificationMembre.qualification`, et ils se **cumulent** |
| « à jour » | `statut=VERIFIEE` + `date_expiration` + `ContactInstitution.aptitude_valide_jusquau` |
| commune / département / région | les codes dénormalisés de la ressource |
| zone de défense | `core/zones_defense.py` |
| X km de la crise | PostGIS, `Distance` sur `Crisis.location` |
| branche de l'arborescence | `Team.equipe_parente`, descendu par `visibilite_membres` |

Trois pièges, chacun tenu par un test :

- **Un critère inapplicable est une ERREUR** (`CritereInapplicable`), jamais un silence.
  Demander « à 30 km de la crise » sans crise rattachée ne doit pas rendre tout le monde : on
  écrirait à 400 personnes en croyant en viser 30, et ça ne se défait pas.
- **Les titres se cumulent par un COMPTE distinct**, pas par des `filter()` enchaînés : deux
  `filter()` sur la même relation inverse se satisfont de deux lignes différentes, donc
  quelqu'un qui a le permis deux fois passerait pour quelqu'un qui a le permis **et** le PSE1 —
  et partirait sans le titre requis.
- **`departements_de_zone` rend des couples `(code, libellé)`**, pas des codes. Les passer à un
  `__in` ne lève pas, ne filtre rien, et rend zéro ligne. Rencontré en écrivant le module.

Les **compétences sont un « ou »**, les **titres un « et »** : demander « électricien ET
infirmier » ne décrit personne, alors qu'un permis C n'est pas interchangeable avec un PSE1.

**Trois temps, et pas un bouton.** Composer (motif typé, période, texte) → `apercu`, qui fige la
liste et rend le **nombre** sans écrire à personne → envoyer. « 87 bénévoles retenus » est la
seule chose qui permette de s'apercevoir qu'un critère ne filtre pas ce qu'on croyait.

**L'envoi passe par `send_modele_mail`** (modèle `CAMPAGNE_DISPONIBILITE`), donc par la
relecture avant envoi et ses **lots** : un texte générique validé **une fois** pour 87
destinataires, chacun repersonnalisé à l'envoi. Écrire un second chemin d'envoi aurait fait
exactement ce que la fenêtre de relecture existe pour empêcher.

Le lien du message est un lien magique avec `next=/ma-fiche-benevole?campagne=<id>` : la grille
s'ouvre **sur la période demandée**, avec le motif rappelé. Sans ce paramètre, le bénévole
arriverait sur ses quinze prochains jours et répondrait à une autre question. Le `next` est
restreint aux chemins internes dans `MagicLoginComponent` comme dans `ActivateAccountComponent` :
un lien qui vaut identité pendant sept jours et circule par email ne doit pas pouvoir servir de
redirection ouverte.

**Répondre, c'est remplir sa grille.** Il n'y a pas de bouton « j'ai répondu » : un geste de
confirmation oublié ferait relancer quelqu'un qui a fait ce qu'on lui demandait. Et **zéro
créneau est une réponse** — « je ne suis pas disponible » n'est pas un silence ; `relancer` ne
touche donc que les `CONTACTE`.

**Qui peut lancer** : le bureau pour toute l'association, l'encadrement pour **sa** branche.
Sinon la coordination nationale est le seul goulot pour une crise départementale, et une
sollicitation qui doit partir dans l'heure attend une validation à Paris. Un encadrant ne peut
pas lancer une campagne sans équipe : elle viserait des gens dont il n'a pas la charge.

#### Tours de garde : la règle de répartition

`core/rotations_campagne.py`. **C'est une option explicite** (`tours_de_garde`, migration
`0258`, demande du 12/11/2026), décochée par défaut : le défaut va vers le moins d'effet pour une
option qui propose d'affecter des gens, et beaucoup de campagnes ne veulent que recueillir des
disponibilités — « qui peut venir la semaine prochaine ? » n'appelle aucun tour de garde. La
première version s'en remettait à `effectif_cible = 0`, c'est-à-dire une décision d'organisation
portée par un nombre laissé à zéro, que personne ne lit comme telle dans un formulaire.

Trois conséquences : le sérialiseur **refuse** `tours_de_garde` sans effectif (on n'arme pas une
garde avec zéro personne par créneau, et laisser passer promettrait dans le message une
organisation jamais produite) ; l'action `rotations` répond 400 quand l'option est fermée plutôt
qu'un bilan vide, qu'on prendrait pour « aucun volontaire disponible » — deux situations
opposées ; et **désactiver l'option supprime les tours existants**, parce qu'une grille de garde
orpheline que plus rien n'alimente est pire qu'aucune grille : quelqu'un la lira un jour en
croyant qu'elle vaut encore.

Quand l'option est active, la période est découpée par `duree_rotation_jours` (la dernière
tranche peut être plus courte — refuser le dernier jour laisserait un trou de garde), et chaque
`(tour, créneau)` cherche `effectif_cible` personnes.

La règle est ordonnée, et chaque niveau répond à une objection :

1. **seulement ceux qui se sont déclarés** sur ce créneau — une garde armée avec quelqu'un qui
   n'a rien promis n'est pas armée ;
2. **le moins de jours déjà posés**, avec `repos_min_jours` entre deux tours : c'est la raison
   d'être des rotations, sans quoi le planificateur reprendrait les mêmes du premier au dernier
   jour ;
3. **le moins de créneaux déjà posés**, pour l'équité ;
4. **le plus proche de la crise**, quand la campagne en nomme une ;
5. **l'ordre alphabétique**, pour que deux exécutions donnent le même plan — un planificateur
   qui rebrasse les noms à chaque recalcul ne se relit pas.

Deux garde-fous qui rendent la génération automatique acceptable :

- **tout sort en `PROPOSEE`.** Le calcul ignore les trajets réels, les brouilles et ce qui s'est
  dit au téléphone ; l'encadrement confirme. Une régénération **garde les `CONFIRMEE`**, sinon
  chaque recalcul détruirait les décisions prises.
- **le sous-effectif est dit**, nommément (`manques`). Une grille qui paraît complète parce
  qu'on a caché les trous est pire que pas de grille.

Chaque proposition porte son `motif` en clair (« disponible, 3 jours déjà posés, à 12 km de la
crise ») : une proposition qu'on ne peut pas expliquer ne se relit pas, elle se subit.

#### Inscription d'un bénévole : la case « membre » est cochée par défaut

Demande du 12/11/2026. La case n'apparaît **que** sur un site de marque blanche ayant sa propre
réserve (`afficherCaseReserve`, qui lit `Branding.reserve_active`) : jamais sur le site
généraliste, où la pré-cocher serait indéfendable. Qui s'inscrit sur `cj.assista-crise.fr` vient
de l'association ; lui faire cocher une case pour dire ce qu'il est venu faire est un obstacle
de plus au pire moment.

**Une case pré-cochée demande en retour d'être explicite sur ce qu'elle engage** — sans quoi
c'est un consentement arraché par défaut. D'où l'avertissement sous la case, qui dit quatre
choses : ce n'est pas une adhésion automatique (l'association décide) ; quelles données lui
deviennent visibles et pour quoi ; qu'on peut décocher et garder un compte citoyen ; et comment
revenir sur ce choix.

Ce dernier point est volontairement formulé « il suffit de le demander à l'association » et
**non** « depuis vos paramètres » : la page des paramètres affiche l'état de la candidature mais
n'offre aucun retrait. Promettre un bouton qui n'existe pas aurait été pire que de ne rien
promettre. Un retrait en libre-service reste à faire si on le veut.

#### La rubrique « Mon association » dans le menu

Demande du 11/11/2026 : « ramener tout ce qui est association dans une rubrique association ».
Nouveau cadre `association` dans `GROUPES_NAV`, entre « Préparation » et « Communications », qui
porte **Membres** et **Campagnes de disponibilité**. Elles étaient dispersées dans
« Préparation », entre les sites sensibles et les personnes vulnérables — un président
d'association devait les y chercher parmi des écrans de collectivité qui ne le concernent pas.

Le cadre entier disparaît pour une mairie sans rien de spécial à écrire : toutes ses entrées
portent `visibilite: 'membres-association'`, et le menu masque déjà un cadre dont aucune entrée
n'est visible.

#### L'arborescence des équipes : deux cadres par équipe, fiches, recherche et affectation

Demande du 12/11/2026. L'onglet « Équipes et justificatifs » montrait un nom par membre et rien
d'autre. Il montre désormais, par équipe, **deux cadres dépliables** et, par personne, **une
fiche** — plus la recherche, le tri et la sélection multiple qui permettent de composer une
équipe terrain sans quitter l'arbre.

**Les deux cadres, et pourquoi ce découpage.** Le premier porte les **cadres de l'équipe**
(`Team.membres_encadrement`, plus le chef et le régulateur) ; le second, le **niveau en
dessous** — pour une équipe de coordination, les cadres des équipes rattachées, parce que c'est
ainsi qu'on lit une chaîne de commandement ; pour une équipe départementale, qui n'a rien
dessous, ses intervenants. Une équipe qui a des sous-équipes **et** des équipiers en propre
montre les deux : les taire les ferait disparaître de l'écran.

Le rôle d'une personne dans une équipe (`CHEF`, `REGULATEUR`, `CADRE`, `INTERVENANT`) est
**calculé par le serveur** (`annuaire_association._roles_dans_les_equipes`) et non redéduit côté
navigateur : la même personne est cadre ici et intervenante là, et un rôle recomposé à partir de
listes d'identifiants recopiées finit par diverger de ce que le serveur retient.

**Un seul appel pour l'annuaire enrichi.** `GET /api/contacts-institutions/annuaire-association/`
assemble ce qui vivait dans cinq tables : rattachement (fonction, statut, bureau), compte
(courriel, téléphone), fiche bénévole (commune, métier), ressource (`Offer.competences`) et
`DisponibiliteOffre` pour savoir qui a déclaré ses créneaux. Les mêmes sources que
`core/ciblage_benevoles.py`, délibérément : une personne trouvée par une recherche dans l'arbre
doit être exactement celle qu'une campagne ciblerait.

**Deux cercles de lecture.** La page est ouverte à tout membre d'une AASC, pas seulement à son
bureau (`membresAssociationGuard`). Téléphone, commune et métier sont donc réservés au bureau et
aux administrateurs, comme `ContactInstitutionSerializer.CHAMPS_SUIVI_ASSOCIATIF` le fait déjà
pour l'aptitude. Ils sont **absents** de la réponse sinon, jamais rendus à `null` : afficher
« — » affirmerait qu'il n'y a pas de téléphone, alors qu'on n'a pas le droit de le savoir. Le
drapeau `coordonnees_visibles` dit laquelle des deux réponses l'écran est en train de lire, et
celui-ci écrit la phrase plutôt que de laisser un tiret.

**L'affectation en masse passe par `POST /api/teams/<id>/ajouter-membres/`, jamais par un
`PATCH member_ids`.** Un PATCH envoie la liste entière telle que ce navigateur la connaissait :
deux régulateurs qui affectent en même temps, et le second efface les ajouts du premier sans que
personne ne le voie. L'action ajoute, donc l'ordre des appels n'a plus d'importance. Elle
n'accepte que des personnes **rattachées activement à l'institution de l'équipe** (sinon elle
serait un moyen détourné d'ajouter n'importe quel compte à n'importe quelle équipe), refuse
nommément un membre sorti, et **rend ses refus** : une affectation partielle présentée comme un
succès fait partir une équipe incomplète en croyant l'avoir au complet. La mission est posée
dans la foulée (`_definir_mission`), parce qu'une équipe n'a qu'une mission active.

Piège rencontré en écrivant l'action, attrapé par un test : filtrer les rattachements sur
`actif=True` faisait disparaître le membre sorti **avant** qu'on puisse dire pourquoi il était
refusé — sortir quelqu'un désactive son rattachement. L'appelant lisait « n'est pas membre de
cette institution » d'une personne qu'il voyait dans l'annuaire.

**La recherche porte sur tous les critères** — nom, fonction, rôle, commune, métier,
compétences, coordonnées quand on y a droit — plus des filtres structurés (rôle, compétence,
bureau, sans disponibilité déclarée, titre périmé, sans fiche ressource) et cinq tris. Filtres et
cadres sont recalculés dans `recalculerLesVues()` et non dans le gabarit : avec 125 équipes,
trier et filtrer dans une expression de template se refait à chaque cycle de détection de
changements.

#### La grille de disponibilités : deux fenêtres, et des créneaux qu'on pointe

`GET /api/disponibilites-operationnelles/grille/` (construite dans
`core/grille_disponibilites.py`) sert la mobilisation de l'onglet « Disponibilités » de
`/admin/membres-association`. Les cases viennent de `DisponibiliteOffre`, le **moteur unique** —
quatre créneaux par jour portés par la ressource du bénévole, les mêmes lignes que lit la
constitution d'équipe. Sa règle est « pas de ligne = indisponible » ; `a_declare` est le seul
signal qui sépare le silence du refus.

**Deux fenêtres, et la seconde est l'ajout du 12/11/2026.** Par défaut, les quinze prochains
jours (`jours`, plafonné à 31). Avec `?campagne=<id>`, la période de cette campagne —
souvent bien plus loin devant. Les réponses à une campagne étaient écrites en base, lues par le
planificateur de tours de garde, et **invisibles sur l'écran qui sert à mobiliser**. Trois
conséquences, toutes voulues :

- les créneaux servis deviennent ceux que la campagne a réellement posés
  (`creneaux_effectifs`). Interroger sur quatre quand elle n'en demandait qu'un ferait lire
  comme des refus trois colonnes auxquelles personne n'a été invité à répondre ;
- `a_declare` tient compte de l'état de la cible : **zéro créneau déclaré par quelqu'un qui a
  répondu n'est pas un silence**, c'est un « je ne suis pas disponible » ;
- un membre **non ciblé** porte `cible: null` — on ne lui a rien demandé, ce n'est pas un
  silencieux non plus.

Une période plus longue que `PLAFOND_JOURS_CAMPAGNE` (92 jours) est coupée, et la réponse le
**dit** (`tronquee`).

**Les cases sont cliquables** : cliquer une case prend la personne *sur ce créneau*, geste repris
du recrutement depuis un point opérationnel. Ce que les créneaux pointés deviennent dépend du
contexte, et l'écran ne le cache pas :

| Contexte | Ce qui est écrit |
|---|---|
| Grille ouverte sur une campagne **avec tours de garde** | `AffectationRotation` en `CONFIRMEE` — un humain a choisi, ce n'est pas une proposition du planificateur |
| Campagne sans tours de garde, ou hors campagne | Rien : **aucune table ne stocke « cette équipe tient le soir du 14 »**. Les créneaux restent au journal d'audit, et la barre d'affectation le dit |

Limite à connaître : la maille d'un tour de garde est la **rotation**, pas le jour. Pointer le
soir du 14 et celui du 15 dans la même rotation produit UNE affectation, pas deux — l'unicité
porte sur `(rotation, utilisateur, créneau)`.

**Deux cibles pour une sélection** : `POST /api/teams/<id>/ajouter-membres/` (équipe existante,
elle **ajoute** et ne remplace pas) et `POST /api/teams/creer-avec-membres/` (équipe neuve).
Cette seconde action existe plutôt que le `POST /teams/` ordinaire parce que celui-ci exige un
*type* de compte institutionnel — un membre du bureau d'une association est souvent
`UTIL_SIMPLE` — et parce qu'il accepte `members` sans vérifier le rattachement. Ici, c'est la
qualité qui compte (bureau de cette association, voir `recrutement_association.peut_instruire`),
la sélection passe par le même tri que l'affectation, et **les refus sont nommés**. Une équipe
dont tous les membres seraient refusés n'est pas créée : une coquille vide dans l'arborescence
ne se nettoie jamais.

#### Le planning d'équipe (`core/planning_equipe.py`)

`CreneauEquipe` répond à la question que personne ne savait poser avant le 12/11/2026 : **qui
tient le soir du 14 pour cette équipe ?** Page `/admin/planning-equipes`, API
`creneaux-equipe`.

**Quatre tables parlent de créneaux, et chacune répond à autre chose.** Les confondre était
l'erreur à éviter :

| Table | Question |
|---|---|
| `DisponibiliteOffre` | quand cette personne **peut** venir — une déclaration du bénévole, jamais une affectation |
| `AffectationRotation` | qui arme ce **tour de garde** de cette campagne — maille rotation, pas jour |
| `DisponibilitePointEquipe` | qui tient ce **point opérationnel** |
| `CreneauEquipe` | qui tient ce **créneau pour cette équipe** |

Pointer un créneau dans la grille de l'association écrit donc **les deux** quand une campagne
est ouverte : la rotation pour le planificateur de la campagne, la ligne de planning pour
l'équipe. Ce ne sont pas des doublons, ce sont deux questions posées par deux écrans.

**Deux écarts signalés, jamais bloqués** — et un refus :

- **double engagement** : la même personne attendue par une autre équipe au même créneau. Pas
  refusé (il existe des cas réels : deux équipes du même site, un passage d'un poste à
  l'autre), mais **nommé** — qui, quand, quelle équipe. « 3 conflits » n'a jamais permis à
  personne de décider ;
- **hors disponibilité déclarée** : la personne n'a pas coché ce créneau. Un chef d'équipe a le
  droit d'appeler ; l'interdire supposerait que la grille déclarée est exhaustive ;
- **pas membre de l'équipe** : refusé, lui. Un planning qui affecte des gens hors de l'équipe
  ne décrit plus rien.

`pointer` est **idempotent** : la clé est `(équipe, personne, jour, créneau)`, deux clics ne
font pas deux présents. Et l'effectif d'un créneau **ne compte ni les annulés ni les absents** —
c'est la seule définition qui rende le chiffre utilisable, compter une ligne annulée ferait
croire une garde armée.

#### Suivi du relogement des familles (`core/relogement.py`)

Pendant de « Logement intervenants », pour les sinistrés : page `/admin/relogement-familles`,
API `dossiers-relogement`. Demandé le 12/11/2026, avec le bilan qui va avec.

**Deux tables et non une.** Un foyer sinistré passe presque toujours par plusieurs solutions
successives — gymnase la première nuit, hôtel la semaine suivante, logement communal pour six
mois, puis un bail. `DossierRelogement` porte le foyer ; `SolutionRelogement` est une ligne par
hébergement. Écrire tout cela dans une seule ligne mise à jour en place détruirait l'historique,
or c'est précisément ce que le rapport demande : « tant de familles relogées **de manière
pérenne** » suppose de distinguer le provisoire de ce qui a tenu.

| Notion | Valeurs |
|---|---|
| `TypeSolutionRelogement` | urgence, temporaire, **intermédiaire**, définitive |
| `TitreOccupation` | centre, hôtel, proches, prêt, convention, bail, retour au domicile |
| `StatutDossierRelogement` | en recherche, hébergée, relogée, retour au domicile, clos sans suite |

L'intermédiaire existe pour de vrai (un logement communal prêté six mois pendant que l'assurance
instruit) et le compter comme définitif ferait annoncer des familles relogées qui seront à la rue
au printemps.

**Ce que le serveur tient, et que l'écran ne refait pas :** `ajouter-solution` clôt
automatiquement l'hébergement en cours (un foyer ne dort pas à deux endroits, et deux lignes
ouvertes le compteraient deux fois) et met à jour le statut du dossier ; `synthese` calcule le
bilan **sur toute la crise**, pas sur les lignes affichées — un total recompté côté navigateur
changerait avec les filtres, et deux personnes annonceraient deux chiffres en réunion. La page
en tire un point de situation en texte, prêt à coller.

Trois chiffres passent devant le tableau : **foyers sans solution** (des gens qui dorment on ne
sait où ce soir), **termes dépassés** sans sortie enregistrée (le plus urgent : personne ne sait
où en est cette famille) et **termes à moins de 30 jours**.

**Rien en clair** : nom du référent, coordonnées, notes d'accompagnement, adresse d'hébergement
et contact de l'hébergeur sont en `EncryptedTextField` — ce sont les données les plus sensibles
du produit, des personnes sinistrées nommées avec l'endroit où elles dorment. La lecture est
réservée aux acteurs institutionnels dont l'institution suit le dossier ou a une équipe sur la
crise, et chaque ouverture de fiche est tracée.

#### Hébergement et interventions : des entrées de menu qui expliquent leur vide

« Mes interventions » et « Hébergement » sont visibles de **tous** dans le menu, y compris d'un
compte qui n'est dans aucune équipe. La page affiche alors un encart qui dit ce qu'elle fait, que
ce n'est ni une panne ni un refus, et à qui demander le rattachement. Les masquer laissait croire
que la fonction n'existe pas et ne donnait aucun moyen de savoir ce qu'il faut pour y accéder.
`/hebergement` est le même composant que `/mon-equipe/<id>/hebergement` : sans équipe dans l'URL,
il demande laquelle, ou explique pourquoi il n'y a rien.

Sur cette page, **l'œil d'une fiche (offre comme demande) va chercher la fiche au serveur**, et
ce n'est pas un détail d'implémentation : les listes d'annonces arrivent sans email ni téléphone
(voir § 10, « coordonnées retirées des listes »), et c'est l'ouverture de la fiche qui est tracée
objet par objet. Afficher l'objet déjà chargé par la liste montrerait une fiche sans contact et
contournerait la trace.

#### Qui crée une institution, et comment une institution en aide une autre

Deux décisions du 12/11/2026, prises après une revue d'accès demandée par Sylvain (« je veux
éviter les fuites de données »).

**Créer une institution, c'est créer SOUS la sienne** (`core/creation_institution.py`,
`Institution.institution_parente`, migration 0261). Jusque-là, tout compte institutionnel
créait des institutions flottantes, au même rang qu'une mairie du référentiel national — d'où
les « Mairie debug test » restées dans la liste. Le besoin légitime existe pourtant, et il a
deux visages : une collectivité crée ses satellites (CCAS, CIAS, médiathèque, régie), une
association crée ses échelons (un comité départemental sous l'association nationale). Dans les
deux cas la fille n'existe que sous sa mère. **On ne retire pas le droit de créer, on retire le
droit de créer à côté.**

- la mère est posée d'office depuis le rattachement de l'appelant, et **une valeur envoyée par
  le client est ignorée** — sinon la règle ne vaudrait rien ;
- les types du référentiel national (mairie, EPCI, préfecture, SDIS, gendarmerie, conseils)
  sont fermés, avec un message qui invite à signaler l'institution manquante ;
- le rattachement **ne se déplace pas** depuis le formulaire : il dit qui répond de la fille ;
- l'**import en masse**, qui crée sans mère, passe aux administrateurs seuls ;
- un administrateur reste libre : c'est lui qui tient le référentiel national.

**Proposer son aide à une institution en crise** (`core/entraide_institutions.py`). Le
mécanisme existait — une institution se déclare acteur, et si elle n'est pas une collectivité
sa déclaration attend l'accord d'un régulateur, mandat exigé d'une association qui n'intervient
pas sur délégation. Les crises sont publiques et leur liste n'est pas filtrée par zone,
« pour permettre à une institution de candidater n'importe où ». Deux choses manquaient :

| Endpoint | Ce qu'il apporte |
|---|---|
| `POST /api/crises/<id>/proposer-aide/` | Un geste : les besoins sur lesquels on peut intervenir, un message libre. Proposer deux fois renvoie 409 **en disant où en est la première** — une institution impatiente inonderait sinon la collectivité le jour où elle en a le moins le temps |
| `GET /api/crises/<id>/referents/` | À qui parler : les institutions engagées, **collectivités en tête** puisque ce sont elles qui acceptent |

`referents` répond **sans ouvrir l'annuaire** : coordonnées de l'ORGANISATION (celles du papier
à en-tête) et **nom** du responsable désigné, jamais ses coordonnées personnelles — on demande
la bonne personne au standard, comme au téléphone. Une déclaration encore en attente n'y figure
pas : elle ferait appeler quelqu'un qui n'a rien accepté. Les deux actions sont réservées aux
comptes institutionnels : une crise est publique, savoir qui la gère et comment le joindre ne
l'est pas.

**Au menu**, « Conflits de synchronisation » et « Correspondances » sont passés en `sysadmin`,
URL comprise — leurs données étaient déjà cloisonnées, mais les laisser dans le menu d'un
bureau associatif donnait l'impression d'un accès plus large. « Institutions » **reste ouvert**
à tout compte institutionnel, volontairement : c'est par cette page qu'une association
configure ses envois, et sa liste est déjà bornée à « chez moi + ma zone ».

#### L'équipe naît avec l'institution fille, et une notification porte sa fiche

**Créer une institution fille crée son équipe** (`creation_institution.creer_equipe_fille`),
rattachée à l'équipe de tête de la mère. Une institution est une entité administrative : elle
ne reçoit pas de campagne, ne porte pas de mission, n'entre pas dans la constitution d'équipe —
c'est l'ÉQUIPE qui le fait. La médiathèque créée par la mairie peut ainsi être sollicitée pour
animer un centre d'accueil.

**Celui qui crée n'en est pas membre d'office** : un DSI crée l'équipe de la médiathèque sans en
faire partie. La réponse de création porte `equipe_creee`, et l'écran propose aussitôt d'y
**entrer** (`POST /api/teams/<id>/rejoindre/`) ou d'y **inviter ses membres par email**
(`contacts-institutions/inviter/`, qui accepte désormais `equipe`). Les deux reposent sur
`gere_institution` : une mère agit pour ses filles, la réciproque est fausse.

**Une notification peut porter une fiche** (`Notification.details`, `lien`, `lien_libelle`,
migration 0262). Le résumé dit qu'il s'est passé quelque chose ; la fiche dit *qui, quand, quoi,
comment*, et un bouton mène plus loin. Premier usage : une institution propose son renfort sur
une crise — et **les deux cas notifient** désormais, alors que seule une déclaration en attente
prévenait quelqu'un : une collectivité voisine qui engage ses moyens ne se découvrait qu'en
ouvrant la crise. ⚠ `details` n'est pas chiffré : noms d'institutions, dates, libellés — jamais
une donnée personnelle. `lien` est toujours relatif, et l'écran refuse d'en suivre un autre.

#### Les atouts : être force de proposition (`core/atouts.py`)

Inspiré des quatorze besoins fondamentaux de Virginia Henderson, sur une idée de Sylvain, ancien
infirmier. « Vous avez une médiathèque ? → divertissements. Une cantine scolaire ? → repas. Une
salle omnisports ? → centre d'accueil. Des vestiaires avec douche ? → hygiène. »

Trois partis pris, qui font tout l'intérêt de la chose :

- on part de ce que l'institution **possède**, jamais de ce qui lui manque. La question est
  « avez-vous… ? » ; une commune de trois cents habitants coche deux cases sans que rien ne lui
  dise qu'elle en a raté onze ;
- **rien de ce qui relève du soin** : respirer, la douleur, c'est le métier des secours. Un test
  le tient ;
- cocher **n'engage à rien** : cela dit qu'il existe une cuisine et à qui en parler.

`Institution.atouts` (migration 0263) porte les clés ; le catalogue est **en code**, parce que
c'est un vocabulaire éditorial pesé, pas un référentiel que chacun enrichit. Les référents d'une
crise affichent ce que chacun peut apporter (`peut_apporter`).

#### La main courante ne se trompe plus de crise

`tracabilite.perimetre_de` prenait l'`id` de toute réponse d'une action de `CrisisViewSet` pour
celui d'une crise. `proposer-aide` rend une implication : une ligne de main courante partait
avec une clé étrangère vers une crise inexistante. On ne retient plus que les identifiants qui
**sont** des crises ; à défaut, celle que la réponse désigne.

#### Les numéros de téléphone sont enregistrés en E.164 (`core/telephone.py`)

`+262692123456` : indicatif pays, numéro national sans son zéro, rien d'autre. C'est la seule
écriture qu'acceptent sans discuter Brevo, Twilio, OVH ou Orange Contact Everyone ; chacun a
ensuite sa manie (Brevo veut le même numéro **sans** le `+`), et `pour_fournisseur` s'en
charge au moment d'appeler l'API, pas au moment d'enregistrer.

**Pourquoi un format d'ENREGISTREMENT et pas seulement une conversion à l'envoi.** Trois
raisons, découvertes dans cet ordre :

1. **l'outre-mer n'est pas en +33.** Un portable réunionnais saisi « 0692 12 34 56 » et
   converti par la règle naïve « 0 → 33 » part vers un numéro métropolitain qui n'est pas le
   sien. Le projet a un satellite à La Réunion : l'erreur serait restée invisible jusqu'au
   jour où il aurait fallu joindre quelqu'un ;
2. en base, « 0692… » ne dit pas s'il s'agit d'un numéro réunionnais ou d'une faute de
   saisie — l'information de pays était perdue à la saisie et devinée trop tard ;
3. un numéro **étranger** (un renfort belge, un prestataire suisse) n'avait aucune façon
   correcte d'être saisi.

La normalisation est posée dans `save()` (`User.phone_number`,
`InterlocuteurAlertePCS.telephone`) et non dans les sérialiseurs, pour couvrir aussi les
imports de fichiers et les scripts. **Ce qui n'est pas reconnu est conservé tel quel** : une
saisie du genre « voir le standard » peut être le seul moyen de joindre quelqu'un, et
l'écraser par une interprétation hasardeuse serait pire que de la laisser.

La reprise de l'existant se fait par `manage.py normaliser_telephones`, **à blanc par
défaut** : ces colonnes sont chiffrées, une réécriture en masse ne se relit pas par un
`SELECT` pour vérifier après coup.

#### Brevo : SMS par la même clé, et suivi des crédits (`core/credits_brevo.py`)

Vérifié contre l'API réelle le 12/11/2026, sans rien envoyer : `POST /v3/transactionalSMS/send`
accepte la clé `xkeysib-` des emails (corps vide → 400 « Sender name is missing »), et
`GET /v3/account` rend `plan: [{credits, creditsType, endDate}]`.

**Une seule clé.** `ConfigurationEnvoiInstitution.cle_sms_effective` : avec Brevo, un champ SMS
vide signifie « la même que les emails » — et l'écran ne montre même plus le champ quand Brevo
est choisi, un champ vide à côté d'un fournisseur configuré se lisant comme un oubli. La redemander ferait saisir deux fois le même secret,
et une régénération n'en mettrait qu'un à jour. Le nom d'expéditeur est ramené à onze
caractères alphanumériques (« Réserve Résilience - Casques Jaunes » → `ReserveResi`) et les
numéros au format international, faute de quoi Brevo refuse au moment où l'on en a besoin.

**L'API rend le RESTANT, pas le quota.** On garde donc le plus haut niveau vu sur la période
(`brevo_credits_email_reference`) pour dessiner une jauge, et le seuil d'alerte se règle en
**nombre de crédits**, pas en pourcentage : « il reste 500 emails » se comprend sans calcul.
Relevé après chaque envoi réussi et à l'ouverture de l'onglet « Envois », espacé d'une
demi-heure — un appel par email doublerait le trafic vers leur API pour une donnée qui bouge
lentement. `?rafraichir=1` force.

**L'alerte ne part JAMAIS par Brevo** : prévenir que le compte est à sec en l'utilisant, c'est
scier la branche. Elle part par le SMTP de la plateforme vers `brevo_admin_email` — la personne
qui gère l'abonnement, souvent pas celle qui envoie — et le bureau la voit en notification.
**Une alerte par niveau** (`BAS`, puis `EPUISE`), remise à zéro au rechargement : sans cette
mémoire, chaque envoi sous le seuil renverrait un message et l'alerte deviendrait du bruit.

Enfin, `restant: null` veut dire inconnu, et **inconnu n'est pas zéro** : un plan sans plafond
lisible ne déclenche rien.

#### Par quel canal part une campagne, et ce que ça coûte (`core/canaux_campagne.py`)

Demande du 13/11/2026 : « compte tenu des coûts, on doit avoir la possibilité de choisir entre
brevo mail / brevo sms / mobimel / Matrix avec un rappel des coûts / solde restant ».

**Le coût est un critère de choix, pas une note de bas de page.** Écrire à quatre cents
bénévoles vaut quelques centimes par email et plusieurs dizaines d'euros par SMS. La décision
se prend donc au moment de composer, et l'aperçu (`POST /api/campagnes-disponibilite/<id>/apercu/`)
rend, pour chacun des quatre canaux : combien de personnes il atteint, **combien il laisse de
côté**, ce qu'il consomme, ce qu'il reste, et si ça suffit. Le choix se fait **après** le
comptage — on ne chiffre pas un envoi sans savoir à combien de personnes il part.

Quatre règles tiennent l'écran :

- **Zéro n'est pas gratuit.** Les tarifs (`cout_unitaire_email`, `cout_unitaire_sms`,
  `cout_unitaire_sms_mobimel`, en centimes) sont **déclarés par l'institution** : ils dépendent
  de son contrat et nous ne les connaissons pas. Non renseigné → « coût inconnu », jamais
  « 0 € ». Un total à zéro ferait partir quatre cents SMS sans y penser, et le total global est
  `null` dès qu'un tarif manque — un total partiel sous-estime la dépense, ce qui est la pire
  des erreurs ici.
- **Matrix est gratuit ET partiel.** Il ne joint que les membres d'une équipe de l'institution
  dont le salon est réellement provisionné (`SalonMatrixEquipe.room_id`), et le chiffre annoncé
  est une **estimation haute** : être membre d'un salon ne garantit pas s'être connecté à la
  messagerie, et le vérifier demanderait un appel réseau par bénévole. Le dire est le seul
  moyen que « gratuit » ne soit pas un piège.
- **Un solde insuffisant prévient, il ne bloque pas.** Partir quand même sur les cent premiers
  est une décision de l'association. `credits_suffisants: null` = solde inconnu, et l'écran ne
  dit alors jamais « suffisant ».
- **Email seul par défaut** (`CampagneDisponibilite.canaux` vide → `canaux_effectifs ==
  ['BREVO_EMAIL']`) : une campagne créée avant ce choix ne doit pas se mettre à envoyer des
  SMS, et un défaut qui engage des dizaines d'euros n'est pas un défaut.

Brevo et Mobimel ne sont jamais proposés ensemble : une institution a **un** fournisseur SMS à
la fois, et proposer l'autre ferait cocher un canal qui n'enverrait rien. `envoyer_campagne`
route ensuite par canal et rend un décompte `par_canal` ; une personne qu'aucun canal retenu ne
peut joindre est comptée en échec, visible dans le suivi.

### 5.12 Sites sensibles et open data (`core/opendata/`)

Les enjeux du territoire d'une commune (`SiteSensible` : écoles, structures de soins, sites
industriels, élevages, équipements recevant du public) sont pré-alimentés depuis des bases
publiques nationales, puis validés un à un par la commune. Page `/admin/sites-sensibles`.

| Source | Connecteur | Accès | Filtrage |
|---|---|---|---|
| Annuaire de l'éducation (MENJ) | `opendata/ecoles.py` | API Opendatasoft (`exports` au-delà d'une page) | `code_commune`, ou `code_departement` / `code_region` |
| FINESS (Agence du numérique en santé) | `opendata/finess.py` | fichier JSON national quotidien (~50 Mo compressés) | aucun : lecture en flot, filtrage local sur `cogCommune` |
| Installations classées et élevages (Géorisques) | `opendata/icpe.py` | API REST paginée | `code_insee`, ou `departement` / `region` |
| Équipements sportifs (ministère des Sports) | `opendata/equipements.py` | API Opendatasoft (`exports` au-delà d'une page) | `insee`, ou `dep_code` / `reg_code` |
| Annuaire des entreprises (SIRENE / INSEE) | `opendata/sirene.py` | API « Recherche d'entreprises » (DINUM), sans clé | `code_commune` / `departement` / `region` + `activite_principale` (par thème) |

Règles qui structurent le paquet :

- **Proposer, jamais décider.** Tout import dépose en `StatutSiteSensible.PROPOSE` ; seul un
  agent passe une ligne en `RETENU` ou `ECARTE`. Ces bases se trompent et vieillissent (FINESS
  conserve des pharmacies radiées en 2009, le recensement des équipements sportifs classe des
  écluses en « installation sportive »). Même posture que
  `RisqueCommunalViewSet.suggestions_georisques`, mais persistée : plusieurs dizaines de sites
  par commune, relus sur plusieurs séances.
- **Une fiche par établissement, partagée par les collectivités du territoire.** C'est la règle
  structurante : `SiteSensible` est la fiche (nom, adresse, coordonnées, attributs, corrections
  comprises), `SuiviSiteSensible` est ce qu'UNE collectivité en fait (décision, commentaire,
  convention, point opérationnel), une ligne par (fiche, institution). Conséquences voulues :
  - **Le bénéfice va dans les deux sens.** Si la mairie importe son collège, le département le
    trouve ; si le département l'importe, la mairie le trouve. Avant cette séparation, chacun
    avait sa copie et deux inventaires du même territoire divergeaient tranquillement.
  - **Les corrections circulent.** Une adresse redressée par un agent communal sert au
    département, et réciproquement. C'est aussi pourquoi la garde contre l'écrasement au
    ré-import est passée de la décision à `corrige_le` / `corrige_par` : la décision n'est plus
    sur la fiche, elle ne peut plus servir d'indice.
  - **Chacun garde sa décision.** Un collège est retenu au plan du département et peut être
    écarté de celui de la commune, qui n'en a pas la charge. Le filtre « à vérifier » signifie
    « je n'ai pas encore statué », pas « personne n'a statué » — l'absence de suivi EST l'état à
    vérifier, d'où l'absence de ligne créée à l'import. `decisions_autres` expose ce que les
    voisins ont tranché, pour éviter de refaire leur travail.
  - **Les conventions et les points opérationnels ne se partagent pas** : une convention lie une
    collectivité précise à une entreprise précise, et commune et département peuvent chacun
    ouvrir leur centre d'accueil sur le même bâtiment.
  - **La visibilité devient territoriale** (`get_queryset`) : une mairie voit les fiches de sa
    commune, un conseil départemental celles de son département. Plus de filtre par institution
    propriétaire, qui était précisément la cause des doublons.
  - **Supprimer retire la fiche de SON plan**, pas de celui des autres (`perform_destroy`) : le
    suivi part, la fiche reste si une autre collectivité la suit — ou si elle vient d'une base
    publique, auquel cas la détruire ne servirait à rien puisqu'elle reviendrait au prochain
    import.
- **Une collectivité ne valide pas un territoire, elle valide sa compétence**
  (`EchelonCompetence` sur chaque ligne). Mesuré sur le Finistère : 852 établissements
  scolaires, dont **75 collèges publics** relèvent du conseil départemental, 374 écoles
  publiques des communes et 40 lycées publics de la région. Un inventaire qui mélange les trois
  annonce 852 lignes « à vérifier » qu'aucun agent départemental ne relira.
  - L'échelon est **déduit de la source** quand elle le dit : l'annuaire de l'éducation porte
    `type_etablissement` et `statut_public_prive`, ce qui suffit (école → commune, collège →
    département, lycée → région, privé sous contrat → `PRIVE` car son bâtiment n'est la charge
    d'aucune collectivité, service administratif → `ETAT`). Les autres sources ne permettent pas
    de conclure — Géorisques dit qui exploite et non qui a la charge, le recensement des
    équipements sportifs ne nomme pas le propriétaire, FINESS ne dit pas qui finance — elles
    déposent donc `INDETERMINE` plutôt que de deviner.
  - Le compteur « à relire » est borné à la compétence **seulement pour une collectivité
    supra-communale**. Pour une mairie, tout ce qui est sur sa commune la concerne, installations
    classées et commerces compris : la borner à l'échelon « commune » masquerait l'essentiel de
    son plan. `a_relire_tous_echelons` reste exposé — rien n'est caché, c'est le compteur qui est
    cadré.
  - Le filtre de la page suit la même règle, et la recherche ne filtre jamais par échelon : ce
    qui ne relève pas de la collectivité doit rester **retrouvable**, c'était l'exigence.
- **Le périmètre d'import est choisi, borné par le niveau de la collectivité** (`perimetre` sur
  l'action `importer` : commune / epci / departement / region). On restreint, on n'élargit
  jamais — même règle que `SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION`, qui donne déjà « departement »
  à un `CG` et « region » à un `CR`. Le défaut de la page est le périmètre **le plus étroit**
  autorisé, jamais le plus large : l'inverse a produit un recensement de 21 648 fiches sur
  3 313 communes d'un seul clic depuis un compte de niveau régional. Trois sources ont un filtre
  de secteur natif, ce qui évite 277 appels : Géorisques (`departement`), SIRENE (`departement`,
  `region`) et l'annuaire de l'éducation (`code_departement`, à zéro-compléter sur trois
  caractères). FINESS lit de toute façon son flux national en entier. Seul l'EPCI passe par un
  `IN` sur ses codes commune, aucun jeu ne le portant.
- **Les sources plafonnent le nombre de résultats qu'elles servent, et certaines ne le disent
  pas.** C'est la contrainte la plus dangereuse du paquet, parce qu'elle produit un inventaire
  qui a l'air complet. Mesuré en direct le 27/10/2026 :
  | Source | Plafond réel | Conséquence |
  |---|---|---|
  | Portails Opendatasoft, endpoint `records` | `offset + limit ≤ 10000`, refus 400 explicite | 7 344 des 17 344 équipements sportifs de Nouvelle-Aquitaine hors d'atteinte |
  | Portails Opendatasoft, endpoint `exports` | **aucun** | 17 344 enregistrements en un appel, 10 s |
  | Géorisques | aucun constaté (148 pages servies pour une région) | pagination complète |
  | Annuaire des entreprises | `page × per_page ≤ 10000`, **et `total_results` lui-même plafonné à 10 000** | le thème « élevages » annonce 10 000 pour la Nouvelle-Aquitaine, là où ses 12 départements en comptent **48 499** |

  Trois réponses, dans cet ordre d'importance :
  1. **Découper le périmètre** (`sites_sensibles.tranches`) : une région est interrogée
     département par département. C'est le seul remède réel — un plafond de pagination ne
     s'écoule pas avec le temps, étaler les appels n'y change rien, l'offset 10 100 est refusé
     aussi patiemment qu'on le demande. Un département n'est pas redécoupé : il reste sous les
     plafonds de toutes les sources (le plus gros thème SIRENE mesuré y atteint 8 462). FINESS
     est explicitement exclu du découpage (`SOURCES_SANS_DECOUPAGE`) : son flux national est lu
     en entier quel que soit le périmètre, le découper en douze téléchargerait douze fois les
     mêmes 50 Mo.
  2. **Passer par `exports` sur Opendatasoft** dès que le jeu dépasse une page, avec un `select`
     restreint aux champs du mapper (`ecoles.CHAMPS`, `equipements.CHAMPS`) : l'export régional
     de l'annuaire de l'éducation passe de 14 Mo à 1 Mo, celui des équipements sportifs de 22 Mo
     à 5 Mo. Un comptage préalable (`_compter_ods`) choisit l'endpoint et **refuse** un jeu
     aberrant plutôt que de le charger en mémoire : un total national annoncé signifie que le
     filtre territorial n'a pas été pris en compte.
  3. **Dire ce qui manque** (`opendata.base.Collecte`, champ `tronque`, remonté dans
     `ImportOpenData.resultat["incomplet"]` et affiché en permanence sur la page). Un
     recensement incomplet qui se croit complet est plus dangereux qu'une absence de
     recensement : on bâtit un plan de sauvegarde dessus et on ne cherche pas ce qu'on croit
     déjà avoir. À l'échelle départementale, un recensement thématique SIRENE est un
     **échantillon**, et la page le dit.
- **Les appels sont espacés, et tout ce qui dépasse la commune part en tâche de fond.** Aucune
  des API branchées ici ne publie de limite de débit ; on s'en impose donc une
  (`PAUSE_ENTRE_APPELS`, `PAUSE_ENTRE_TRANCHES`) plutôt que d'enchaîner au rythme que le réseau
  permet — ce sont des services publics gratuits et sans quota. `fetch_json` réessaie sur un
  refus temporaire (429, 502-504) en respectant `Retry-After` : un 429 est une demande de
  ralentir, pas une panne. Côté durée, `lancer_import` délègue à Celery dès que le périmètre
  dépasse la commune, et plus seulement pour FINESS et SIRENE : le seul export des équipements
  sportifs d'une région prend 10 s, et tenir la requête HTTP ouverte immobiliserait un worker
  gunicorn pour un écran figé. Deux budgets de temps emboîtés, et l'ordre compte : l'import
  s'arrête LUI-MÊME (`BUDGET_SECONDES`, 15 min) en consignant ce qui manque, bien avant que
  Celery ne le tue (30 min). Une tâche tuée par Celery ne consigne rien et laisse « recherche en
  cours » affiché indéfiniment — exactement ce qui a été observé en production.
- **L'avancement vit en base, pas dans le navigateur** (`ImportOpenData.resultat` :
  `tranches_faites`, `tranches_total`, `tranche_en_cours`). L'agent doit pouvoir quitter la page,
  changer d'appareil ou revenir le lendemain et retrouver où en est son recensement — même
  raisonnement que `TacheSimulationInondation`. Une tranche qui échoue ne perd pas les
  précédentes, déjà enregistrées, et le statut reste `TERMINEE` tant qu'une tranche a rendu
  quelque chose : afficher onze tranches de données utiles en « injoignable » reviendrait à les
  cacher.
- **Les plafonds internes suivent le niveau** (`PLAFONDS`, `sirene.MAX_PAR_THEME`), sans quoi un
  plafond communal de 500 tronquerait les 852 établissements d'un département. Quand l'un d'eux
  mord, il se signale à l'agent et pas seulement au journal.
- **Chaque site porte SA commune**, pas celle de l'institution qui importe : évident mais faux
  jusqu'ici, et bloquant dès le premier import départemental. Pour Géorisques, c'est `codeInsee`
  qui fait foi et **pas** le libellé `commune`, qui est sale — un établissement bien situé dans
  le Finistère y est étiqueté « Pleudihen-sur-Rance », commune des Côtes-d'Armor.
- **Les thèmes SIRENE sont plus fins que les catégories.** À l'échelle d'un département, un
  « moyens et travaux » unique rend 3 270 établissements dans le Finistère — inexploitable —
  alors que « transport de voyageurs » en rend 57, et ce sont précisément ces 57 autocaristes qui
  constituent le levier d'évacuation d'un conseil départemental. Le thème porte donc sa catégorie
  (`sirene.THEMES`), et la catégorie reste large pour que les filtres restent lisibles.
- **Les animaux captifs comptent, et pas seulement les cheptels d'élevage.** La protection des
  animaux est une mission du plan de sauvegarde, et un animal en captivité est intégralement
  dépendant de ses soigneurs : une évacuation, un feu qui approche ou une coupure électrique
  longue ne lui laissent aucune autonomie. Deux chemins, volontairement complémentaires :
  - **Géorisques, rubrique ICPE 2140** (« présentation au public d'animaux d'espèces non
    domestiques ») attrape les parcs classés. Vérifié en direct : 8 établissements pour le
    Loir-et-Cher et la Dordogne réunis — Beauval, l'aquarium du Périgord noir, la réserve
    zoologique de Calviac, le parc animalier du Thot. Attention au piège : ces enregistrements
    portent `industrie: true` et un code NAF « 91 », qui les rangeraient avec les usines. C'est
    la **rubrique** qui tranche, et elle l'emporte — un zoo sort en `ELEVAGE`, avec la nature de
    la rubrique lisible sur la ligne, seul indice de dimensionnement puisque Géorisques ne donne
    pas d'effectif animal sur cette rubrique.
  - **SIRENE, thème `PARCS_ANIMALIERS`** (NAF 91.04Z) complète par le bas, exactement comme pour
    les élevages : les fermes pédagogiques, petits aquariums, refuges et volières sous les
    seuils du classement n'apparaissaient nulle part. Mesuré : 1 040 en France, 32 en Dordogne,
    17 dans le Finistère. Ce code mélange trois choses — zoos, parcs botaniques, associations de
    protection de la nature — et il est rangé en `ELEVAGE` quand même : un parc botanique mal
    classé se corrige d'un clic, un zoo absent de la liste des animaux est un trou dans le plan.
    Le libellé NAF est affiché pour rendre l'arbitrage évident. Thème `ressource` autant
    qu'`enjeu` : un parc animalier est souvent le seul endroit d'un département où des gens
    savent contenir, soigner et transporter un animal de deux tonnes.
  - Écarté après mesure : le NAF 96.09Z, qui héberge officiellement les services aux animaux de
    compagnie, rend 1 151 établissements en Dordogne en mêlant tatoueurs, photomatons et sites
    de rencontre pour deux pensions canines. Inexploitable comme thème.
- **Un établissement ne produit qu'une ligne, même connu de plusieurs sources.** Le SIRET est la
  seule clé commune (Géorisques le donne sur les 27 ICPE de Châteauneuf-du-Faou, SIRENE en fait
  son identifiant) et **15 des 25 installations classées de cette commune sont aussi des
  établissements SIRENE** : sans rapprochement, l'agent relirait quinze fermes deux fois et le
  plan les compterait double. `_fusionner` verse ce que la seconde source sait dans la ligne
  existante — le cheptel de Géorisques et le code d'activité de SIRENE cohabitent — sans jamais
  rien retirer. Trois conséquences voulues : le nom vu par l'autre source est *proposé*
  (`nom_autre_source`) et non imposé, parce que renommer n'est pas le travail d'un import ; un
  rôle révélé par une source s'ajoute (une ferme « enjeu » pour Géorisques est aussi un moyen
  d'action pour SIRENE) ; et si une source identifie une **personne physique**, la ligne entière
  bascule en masquée, y compris quand le registre d'origine publie l'adresse — sinon le même
  exploitant serait masqué d'un côté et exposé de l'autre.
- **Une ressource recensée n'est pas une ressource acquise : seule une convention engage.** D'où
  les champs `convention_existe` / `convention_numero` / `convention_date_signature` /
  `convention_echeance` et le document joint. Le fichier est chiffré au repos
  (`core/file_crypto.py`, même dispositif que les pièces d'identité de la réserve : préfixe
  `documents/` bloqué par nginx, jamais d'URL `/media/`), `write_only` au serializer, et servi
  par l'action `telecharger-convention` qui écrit une ligne de main courante. `convention_echeance`
  n'était pas demandée : une convention périmée sur laquelle on compte est pire qu'une absence de
  convention, l'écran affiche donc « convention expirée ». Déclarer une convention est tracé mais
  **n'inscrit pas** l'agent dans `valide_par` : ce champ veut dire « a statué sur le sort du
  site », pas « a touché la ligne ».
- **Un ré-import n'écrase jamais le travail d'un agent** (`core/sites_sensibles.py`) : le nom
  corrigé, l'adresse, l'effectif, le commentaire et la décision lui appartiennent ; la source ne
  rafraîchit que ses propres `attributs`, complète les champs encore vides et reclasse les lignes
  que personne n'a relues (statut `PROPOSE` et aucun validateur). Ce dernier point est ce qui
  permet à une amélioration du classement — la sortie des élevages, par exemple — d'atteindre
  les communes qui avaient déjà importé : il leur suffit de relancer la recherche. La clé de
  rapprochement est `(institution, source, source_id, environment)`, `source_id` étant
  l'identifiant stable de la source (UAI, n° FINESS, code AIOT, n° d'installation).
- **FINESS seul est asynchrone** (`importer_sites_sensibles_task`) : son flux national ne tient
  pas dans une requête HTTP. `ImportOpenData` porte l'état par (institution, source,
  environnement), comme `TacheSimulationInondation` pour l'inondation — l'agent peut quitter la
  page. L'ancienne extraction CSV de FINESS n'est plus mise à jour depuis l'été 2026 : ne jamais
  y revenir, l'URL du flux est résolue dynamiquement via l'API data.gouv.
- **Licence.** Les quatre sources sont sous Licence Ouverte (Etalab) : réutilisation libre avec
  mention de la source et de sa date, affichée en pied de page. OpenStreetMap est
  volontairement exclu malgré sa richesse sur les salles des fêtes : sa licence ODbL impose le
  partage à l'identique des bases dérivées.
- **Les élevages ont leur catégorie** (`CategorieSiteSensible.ELEVAGE`), bien qu'ils sortent de
  la même API que les usines : la protection des animaux est une mission possible du plan de
  sauvegarde, et un cheptel ne se planifie pas comme une usine (évacuation en bétaillères,
  abreuvement, ventilation des bâtiments à l'arrêt lors d'une coupure longue). Le connecteur
  remonte les espèces et l'effectif autorisé, lu dans les rubriques ICPE (« 56 000 volailles »,
  « 1 232 animaux-équivalents porcs ») : c'est le seul ordre de grandeur public. La détection
  cumule quatre signaux, car aucun ne suffit : rubrique animale (2101 bovins, 2102 porcs,
  2111 volailles, 2140 espèces non domestiques, 3660 élevage intensif IED… ou libellé explicite),
  indicateurs `bovins`/`porcs`/`volailles` de Géorisques — souvent à faux sur des élevages que la
  rubrique désigne noir sur blanc —, code NAF en `01`, et enfin la forme juridique (GAEC, EARL,
  SCEA, réservées par la loi à l'agriculture). Sans ce dernier repli, la moitié des élevages
  d'une commune rurale arrivait en « site industriel » : Géorisques ne détaille pas les rubriques
  des établissements simplement déclarés (« Autres régimes ») et y laisse le code NAF vide. Pour
  la même raison, le filtre sur le régime `Non ICPE` cède devant une exploitation : une ferme
  repassée sous les seuils garde ses animaux. Un même bâtiment portant deux rubriques (50 000
  volailles autorisées puis enregistrées), le connecteur remonte les deux lignes brutes et c'est
  l'affichage qui dédoublonne — sinon la page annoncerait 100 000 animaux.
- **Un site est un enjeu, une ressource, ou les deux** (`est_enjeu` / `est_ressource`). Deux
  booléens et non une catégorie, parce que les cas qui comptent sont les deux à la fois : un
  camping, c'est 200 personnes à évacuer et 200 lits ; une ferme, c'est un cheptel à sauver et un
  tracteur avec une cuve. En crise, « qui est menacé ? » et « avec quoi j'agis ? » sont deux
  questions posées à deux moments différents — une seule liste n'y répond pas. Le connecteur
  pré-positionne, l'agent corrige. À ne pas confondre avec une `Offer` : une ressource recensée
  n'est **pas** une offre reçue, personne ne s'est engagé.
- **SIRENE est thématique, les quatre autres non.** C'est la seule source qui donne les *moyens
  d'action* (cars, bétaillères, engins, cuisines collectives, lits) et les exploitations sous les
  seuils ICPE — mais son volume s'inverse avec la taille de la commune : 105 établissements à
  Châteauneuf-du-Faou pour les thèmes par défaut, **3 409 à Bordeaux**. La commune choisit donc
  ses thèmes (`categories` sur l'action `importer`), et le bouton « Rechercher dans les bases
  publiques » ne la déclenche pas. Elle est asynchrone pour la même raison que FINESS : jusqu'à
  onze thèmes paginés 25 par 25.
- **SIRENE enregistre une existence juridique, pas une activité physique** : les 152 « élevages »
  de Bordeaux sont à 85 % des personnes physiques domiciliées en centre-ville, code NAF agricole
  et zéro animal. Une raison de plus pour que tout arrive en `PROPOSE`.
- **RGPD.** Les adresses sont chiffrées sans exception (§ 10.1) : une liste d'enjeux communaux
  contient forcément des adresses de personnes, puisque 61 % des élevages de Châteauneuf sont
  des exploitants en nom propre — et qu'on ne peut pas les écarter sans perdre la majorité des
  fermes. Les lignes marquées `personne_physique` (nature juridique SIRENE 1000) sont donc
  traitées à part :
  - l'adresse et les coordonnées **ne sortent pas** de la liste (`to_representation`), seul
    `adresse_masquee` signale qu'il y a quelque chose à demander ;
  - elles s'obtiennent par l'action `devoiler`, un appel serveur et non une bascule d'affichage
    — sinon la donnée serait déjà dans le navigateur et la trace mentirait. Chaque appel écrit
    une ligne de main courante en `exposition=FICHE`, donc « qui a vu cette fiche » reste
    interrogeable, comme pour une `PersonneVulnerable` ;
  - `creer-point` les **refuse** : un `PointOperationnel` est montré aux habitants sur la carte
    publique, le recopier y publierait un domicile. C'est la sortie par laquelle tout le
    dispositif se viderait ;
  - `statut_diffusion` (droit d'opposition INSEE) est respecté à la collecte ;
  - le thème « accueil du jeune enfant » est **décoché par défaut** : en commune rurale il
    ramène surtout des assistantes maternelles, donc des noms de personnes à leur domicile. Il
    existe (c'est un enjeu réel pour une évacuation), il ne s'active pas tout seul.
- Un site retenu peut devenir un `PointOperationnel` (action `creer-point`), nom, adresse et
  coordonnées comprises — ce qui évite les centres d'accueil sans adresse, inutilisables par un
  habitant cherchant où aller.

---

## 6. Frontend Angular

- `src/app/app.routes.ts` charge paresseusement deux groupes : `public/public.routes.ts`
  (accueil, carte, formulaires, suivi de dossier, connexion…) et `admin/admin.routes.ts`
  (tableau de bord, crises, dossiers, missions, équipes, institutions, matériel, satellites…).
- Les pages sont des **composants standalone** chargés avec `loadComponent` : chacune a son
  propre paquet JS, téléchargé à la première visite (page admin typique : quelques Ko à
  25 Ko compressés). Suivre ce modèle pour toute nouvelle page ; `component:` est réservé aux
  layouts et à `acces-refuse`. Pas de `PreloadAllModules` : le préchargement ignore les gardes
  `canActivate` et ferait télécharger tout le code admin aux visiteurs publics.
- `services/` : un service par ressource d'API ; `core/guards/` : authentification, rôle admin,
  compte activé ; `auth/interceptor/` : ajout du JWT.
- `src/environments/` : `environment.ts` (dev, API sur `http://localhost:8000/api`) et
  `environment.prod.ts` (API relative `/api`, servie par le même Nginx que la page).
- Cartographie : MapLibre GL.

**Où placer un composant** :

| Dossier | Contenu | Règle |
|---|---|---|
| `admin/<page>/`, `public/<page>/`, `pages/<page>/` | les **pages** : un composant par route | un sous-composant propre à une page reste dans son dossier (ex. `admin/teams/equipe-messagerie-mesh/`) |
| `layouts/<nom>-layout/` | les **coquilles** : composant de route parent avec le `<router-outlet>` et l'habillage | le layout assemble ses morceaux, placés dans son propre dossier (`public-layout/` : en-tête, pied de page, popup de géolocalisation ; `admin-layout/` : menu, cloche, § 6.4) |
| `shared/components/` | les **briques réutilisées** par plusieurs pages ou layouts (cartes, modales, sélecteurs) | seulement à partir de deux utilisateurs ; sinon, près de l'unique utilisateur |

```bash
cd frontend && npm ci && npm start     # sans Docker
npm test                               # tests Karma
npm run build                          # build de production (dist/)
```

Outils partagés (`shared/utils/`) : `pollWhileVisible` (rafraîchissement périodique suspendu
quand l'onglet est en arrière-plan, sans requêtes qui se chevauchent : à utiliser plutôt qu'un
`setInterval`), `crisis-zone-secteurs.util.ts` (zone de crise composée de communes et
départements), `contact-obfusque.util.ts` (coordonnées masquées aux robots).

### 6.1 Rôles, zone DEMO et gardes

`AuthService` garde la session (JWT d'accès + refresh, utilisateur) dans `localStorage`. Le
refresh token tourne à chaque rafraîchissement (`ROTATE_REFRESH_TOKENS`) : le nouveau doit être
stocké, l'ancien est blacklisté. La déconnexion révoque le refresh côté serveur (best-effort),
puis vide toujours la session locale.

Deux notions de rôle coexistent, à ne pas confondre :

| Méthode | Base | Sert à |
|---|---|---|
| `isAdmin()`, `isSysAdmin()` | rôle **PROD réel** (`type`) | décisions de confidentialité (ex. flou des positions sur la carte publique), page Utilisateurs : ne s'élargissent jamais avec un accès démo |
| `getEffectiveRole()` | `demo_role` en zone DEMO, `type` en PROD (miroir de `get_effective_role` côté backend) | ce qui peut charger **maintenant** : menu latéral, sélecteurs d'institution |

- **Zone active.** `getEnvironment()` (PROD par défaut) part dans l'en-tête `X-Environment` de
  chaque requête (intercepteur `auth/interceptor/auth.ts`). Changer de zone recharge la page
  entière : toutes les données repartent sous le bon environnement. La bascule n'apparaît,
  dans l'en-tête public, que si un admin a donné un `demo_role` au compte.
- **Gardes** (`core/guards/`) : `authGuard` (connecté), `adminGuard` (un compte n'ayant qu'un
  accès démo n'entre dans `/admin` qu'en zone DEMO), `sysAdminGuard` (admin PROD réel),
  `institutionalEffectiveGuard` (rôle effectif institutionnel, sinon page « droits
  insuffisants » dans l'admin), `accountValidationGuard` (admin ou mairie), `zonesGuard`
  (collectivités territoriales) et `vulnerabilitesGuard` (champ serveur
  `acces_registre_vulnerables`, non recalculable côté client).
- **Profil périmé.** `getCurrentUser()` relit le cache posé à la connexion. Les gardes et la
  mise en page admin rafraîchissent le profil (`/api/auth/me/`) : sans cela, un droit accordé
  après la connexion resterait invisible jusqu'à la reconnexion.
- Le frontend masque ou désactive ce que le backend refuserait, mais **le contrôle réel est
  toujours côté serveur**. La page Utilisateurs masque en plus les coordonnées en zone DEMO
  (le serializer le fait déjà), pour ne pas dépendre d'une seule couche.
- **Suivi de position permanent** (`SuiviPositionPermanentService`) : traçage continu d'un
  intervenant, indépendant de Matrix (Element limite le partage en direct à 8 h). Il est
  actif par défaut pour tout compte connecté, sauf refus mémorisé dans `localStorage` (toggle
  de l'en-tête admin ou de `/settings`). L'invite de géolocalisation du navigateur reste le
  vrai garde-fou. Il ne fonctionne que tant que l'application est ouverte. À distinguer de
  `GeolocationService.reportPositionIfInstitutional` (capture ponctuelle, institutionnels).

### 6.2 Flux métier à connaître

- **Formulaire d'offre** (`propose-help-form`). Une soumission peut contenir plusieurs lignes,
  chacune devenant une `Offer` :
  - `presencePhysique` : imposé par le type (Soins, Soutien, Bénévolat : la personne elle-même ;
    hébergement prêté : jamais présente) ou à préciser pour les types ambigus (transport,
    matériel, vivres). Les compétences, disponibilités et qualifications (déclarées une seule
    fois) ne sont reportées que sur les offres avec présence ;
  - la ligne « Engins agricoles / chantiers / spéciaux » est une **passerelle** : elle ne
    devient jamais une offre, chaque engin coché dessous devient la sienne, avec une seule
    confirmation réglementaire pour le lot ;
  - catalogue matériel partagé (`MaterielCatalogue`) : un matériel « Autre » saisi une fois
    est ensuite proposé à tous ;
  - plusieurs validateurs dépendent d'un autre contrôle (`type`, `transportType`) : Angular ne
    les réévalue pas seul, d'où les abonnements à `valueChanges` dans `addOffer()` ;
  - un nom d'organisation pose un `groupe_id` commun (dépôt groupé), repris par l'affichage
    des ressources et le pré-remplissage du nom d'équipe.
- **Demandes** (`request-help-form`) : un besoin Hébergement porte sur une **zone** (communes +
  rayon), pas une adresse ; `commune_code` est conservé pour le rapprochement géographique.
- **Affecter une demande à une équipe** passe toujours par l'action backend dédiée
  (`assign_team` ou la validation groupée de la fiche équipe) : création du dossier,
  notification du régulateur, email au demandeur. Dans la fiche équipe, cocher une demande ne
  fait aucun appel réseau : seul « Valider la sélection » applique, en un appel.
- **`Team.assigned_crises` est distinct de la mission active** (`Mission.crise`) et des points
  liés. Lier un point ou définir une mission ne rattache pas la crise à l'équipe ; or le
  recrutement, les ressources mobilisées et le matching hébergement lisent ce champ. Il faut
  appeler `assigner-crise` explicitement (fiche équipe, assistant de démarrage).
- **Candidats** (membres, responsables, délégataires) : toujours scopés sur l'institution de
  l'objet édité (équipe, point) et ses institutions liées, **jamais sur l'institution du
  compte connecté**, même pour un admin.
- **Page Signalements** (`reporting`) : pagination, recherche, tri et filtres **côté serveur**
  ; jamais la table entière en mémoire. Exceptions côté client, sur la page affichée : le tri
  par contact (champ chiffré, non triable en SQL) et le filtre par nom de commune. L'onglet
  « Tout » n'est qu'un aperçu (1re page de chaque type) ; « Tout sélectionner » et l'export CSV
  portent sur la page affichée. Les modes « picker » (`?pickForTeamId=`, `?pickForPoint=`)
  servent à ajouter des offres à une équipe ou au stock d'un point.
- **Assistant de démarrage de crise** (`crise-demarrage`) : points stratégiques, équipes, puis
  récapitulatif. Une équipe créée ici passe par `nouvelle_equipe_nom` sur le point (implication
  de l'institution, notification, journalisation) et reçoit en silence la zone du territoire
  de la crise. L'ensemble peut être enregistré comme `Plan`, réactivable sur une prochaine
  crise.
  - **Les trois défauts doivent désigner trois lieux distincts.** Le centre de regroupement
    des moyens était prérempli sur « Salle des fêtes », comme le centre d'accueil des
    populations juste au-dessus : deux communes l'ont accepté tel quel, mettant sinistrés et
    dépôt de matériel dans la même salle. Il propose désormais « Centre technique municipal »
    en premier. Un défaut qui se contredit lui-même est accepté sans être lu.
  - **Un même lieu pour deux rôles est signalé, jamais refusé** (`lieuxEnDoublon`) : dans une
    petite commune, la mairie est souvent à la fois cellule de crise et point de regroupement.
    L'avertissement est là pour que ce soit un choix et non un défaut subi, et la comparaison
    ignore casse et accents.
  - **L'assistant reprend ce qui existe déjà au lieu de le recréer**
    (`reconcilierAvecLExistant`). Il repartait de ses trois étapes vierges à chaque ouverture :
    un adjoint l'a lancé trois fois sur la même crise en deux minutes le 26/10/2026, et le
    troisième passage a reproduit à l'identique le premier — trois points en doublon exact
    (même crise, même nom, même type), sans aucun avertissement et sans que rien ne lui montre
    que son premier passage avait abouti, ce qui est probablement pourquoi il a recommencé.
    Désormais les points de la crise sont chargés à l'ouverture, appariés par type, affichés en
    lecture seule et marqués `cree` : ils traversent les étapes suivantes (affectation
    d'équipe, récapitulatif) comme s'ils venaient d'être posés, puisqu'on revient dans
    l'assistant pour COMPLÉTER et non pour tout refaire. Une ligne ajoutée qui redésigne un
    point existant (même nom, même type) est signalée sans être refusée : deux bâtiments
    homonymes dans deux communes d'une crise intercommunale sont parfaitement possibles.
  - Pas de test automatisé sur cette logique : le projet n'a pas de harnais de test de
    composant (seuls quelques `*.spec.ts` de services existent, et le frontend ne se construit
    que dans Docker, par `ng build`). La vérification passe par la compilation — qui type-vérifie
    aussi les gabarits — et par la présence des identifiants dans le bundle produit.
- **Un centre peut être préparé AVANT toute crise** (`PointOperationnel.crise` est nullable).
  C'est le travail normal de préparation d'un plan de sauvegarde : on repère la salle des fêtes
  à froid, on la rattache à une crise le jour où on l'ouvre. Trois conséquences à tenir
  ensemble :
  - `PointModalComponent` demande explicitement **« pour une crise en cours »** ou **« à
    l'avance, pour réutilisation »** (`rattachement`). La crise était auparavant *obligatoire*
    à la création hors contexte de crise — exactement à l'envers : dans une crise, son
    identifiant est déjà fourni ; hors crise, on se voyait imposer d'en choisir une.
  - La page Centres les liste dans son onglet **« Centres prévus »**
    (`?crise__isnull=true`), et la colonne Crise affiche « Préparé à l'avance » plutôt qu'un
    tiret, qui les faisait passer pour une donnée manquante. **Le rattachement à une crise est
    le geste d'ouverture** : c'est par là qu'un centre prévu entre en service, sans copie.
  - **`carte_publique` les exclut.** Un centre préparé n'est pas un centre ouvert, et c'est la
    seule information de la plateforme sur laquelle un habitant se déplace physiquement :
    l'y annoncer l'enverrait vers une salle que personne n'a ouverte — pire qu'un centre fermé,
    où il trouverait au moins une porte close et une affiche. `crise` étant en `CASCADE`, un
    point sans crise n'est jamais le résidu d'une crise supprimée : l'absence de crise signifie
    bien « préparé », sans ambiguïté, et aucun champ supplémentaire n'est nécessaire.
- **Membres association** (`membres-association`) : annuaire, recrutement, qualifications et
  disponibilités d'une association agréée de sécurité civile, en quatre onglets. Quatre vues du
  même effectif plutôt que quatre pages — un président qui instruit une candidature a besoin de
  voir dans la foulée ce que la personne apporte et quand elle est libre.
  - **La page se ferme d'elle-même** à qui n'est au bureau d'aucune association, et le dit
    plutôt que d'afficher un écran vide. Pas de garde de route dédiée : « être au bureau » est
    un attribut du **rattachement** (`ContactInstitution.membre_bureau`), pas un rôle de
    compte, donc invérifiable depuis le menu. Le serveur l'impose de son côté ; cette page ne
    fait que ne pas proposer ce qui serait refusé.
  - **Une disponibilité a trois états**, et le troisième compte autant que les deux autres :
    disponible, indisponible, **non renseigné**. Une case vide n'est pas un refus, c'est un
    silence — et la grille en affiche le total par jour, ligne « Sans réponse », pour qu'on
    sache qui relancer. Compter les silences comme des refus, ou comme des présences, donne un
    effectif imaginaire.
  - **Une qualification périmée s'affiche à côté du nom**, pas dans un sous-menu : un PSE1
    expiré vaut un PSE1 absent, et on ne le découvre pas le jour du départ. Même traitement
    pour l'aptitude échue, et les échéances à moins de 30 jours passent en orange.
  - **Sortir un membre retire ses accès** (règle tenue au modèle) : l'écran le dit explicitement
    au moment du changement, sinon le bureau croit n'avoir modifié qu'une étiquette.
  - L'échéance d'une qualification est préremplie depuis `Qualification.validite_mois`, en
    **proposition** : c'est la date portée par l'attestation réelle qui fait foi, jamais notre
    calcul. Et les décisions (titre périmé ou non) viennent du serveur — l'horloge d'un poste
    client est réglable.
- **Éléments désactivés** : équipes, offres, demandes et signalements ne sont jamais supprimés
  mais désactivés ; le backend les masque, `?actif=all` les fait réapparaître pour les
  réactiver.
- **Photos** : les champs `photo` sont `write_only` ; l'aperçu passe par l'action `/preview/`,
  qui renvoie un blob converti en object URL (un 403 laisse simplement la vignette vide).

### 6.3 Cartographie (MapLibre)

**MapLibre exige WebGL, et son absence n'est pas théorique** : accélération matérielle
désactivée, poste ancien, pilote en panne, politique d'entreprise. `MapComponent` et
`ZoneMapComponent` instanciaient la carte sans garde, si bien que l'exception traversait
`ngAfterViewInit` et que **la page entière** ne s'affichait plus — pas seulement la carte. Sur
une plateforme de crise consultée depuis le premier ordinateur disponible, c'est un écran blanc
au mauvais moment. Les deux composants attrapent désormais l'échec et affichent un message qui
dit quoi faire ; le reste de la page continue de fonctionner, et le tracé de zone reste
possible par la liste des communes.

Le drapeau est posé au tour suivant (`Promise.resolve().then(...)`) et non immédiatement : on
est dans `ngAfterViewInit`, où écrire directement déclenche `NG0100`.

- Trois composants : `MapComponent` (carte générale, clustering), `MinimapComponent` (point en
  lecture seule) et `ZoneMapComponent` (dessin de polygone avec TerraDraw, émis en WKT).
- **Pièges MapLibre** : la taille du canvas est fixée à l'initialisation (un `ResizeObserver`
  appelle `resize()`, puis recadre si besoin) ; l'événement `load` n'est pas rejoué pour un
  écouteur ajouté après coup (`runWhenMapReady` teste `isStyleLoaded()`) ; les propriétés
  tableau/objet d'une source GeoJSON sont sérialisées en chaîne JSON.
- Demandes, offres et signalements partagent une source clusterisée : les masquer retire leurs
  features de la source, sinon les clusters les compteraient encore.
- **Calques chargés à la demande** : l'annuaire de bénévoles (jusqu'à ~1 300 fiches pour un
  secteur régional) n'est chargé qu'à la première activation (performance, minimisation des
  données de position). Même motif sur la carte radio, pour les liaisons et la couverture.
- **Les calques radio ont quitté cette carte le 10/11/2026** pour `/admin/carte-radio` (§ 9.5.4) :
  relais déclarés, passerelles, répéteurs entendus, liaisons mesurées, couverture calculée. Il
  n'en reste que les positions de nœuds personnels des intervenants, et le panneau porte un lien
  vers la carte radio — sans quoi les calques retirés auraient eu l'air d'avoir disparu.
- Les positions de nœuds personnels MeshCore/Meshtastic n'apparaissent que pendant une mission
  `EN_COURS` (règle appliquée par le serveur). Pour un visiteur non institutionnel, les
  positions des demandes, offres et signalements sont légèrement bruitées.

### 6.4 Mise en page et menu de l'administration

```
layouts/admin-layout/
├── admin-layout.component.*     coquille : grille, affichage mobile, fonds semi-transparents,
│                                rafraîchissement du profil, <router-outlet>
├── admin-nav.config.ts          entrées et cadres du menu : données pures
├── admin-sidebar/               menu latéral : cadres repliables, filtrage par visibilité
└── admin-header/                logo, bannière démo, suivi de position, bascule PROD/DEMO,
    │                            thème clair/sombre, affichage du menu, menu utilisateur
    └── admin-notifications/     cloche : polling, liste, notifications navigateur
```

**Ajouter une page au menu = ajouter une entrée dans `admin-nav.config.ts`** (icône, libellé,
route, cadre, `visibilite`) ; sinon elle n'est atteignable que par son URL. Les entrées
`permanent` sont toujours en haut ; les autres sont rangées dans des cadres repliables groupés
**par moment d'usage** dans le cycle d'une crise (crise en cours, post-critique, préparation),
sauf deux cadres transversaux (Communications / Radio, Administration). L'état replié est une
préférence locale (`localStorage`).

`visibilite` décide qui voit l'entrée : `institutionnel` (défaut, rôle effectif, § 6.1),
`tous` (ex. « Mes interventions », route publique pour un chef d'équipe non institutionnel),
`sysadmin`, `validation-comptes`, `autorite-locale`, `registre-vulnerables`,
`membres-association`, `radio` (§ 9.5.5). Masquer une entrée ne protège rien : la route doit
avoir la garde correspondante. Un test de la spec de `admin-sidebar` vérifie que chaque entrée
`/admin/...` pointe vers une route existante et que cette route porte la garde associée à sa
`visibilite`.

**Sous-cadres (second niveau).** `SOUS_GROUPES_NAV` + `NavItem.sousGroupe` ajoutent un niveau de
repli *à l'intérieur* d'un cadre ; une entrée sans `sousGroupe` reste affichée directement dans
le cadre, **avant** les sous-cadres. Le seul usage à ce jour est le cadre Radio, qui porte un
sous-cadre MeshCore et un sous-cadre Meshtastic : deux protocoles sans rien en commun, dont les
sept écrans à plat se lisaient comme une liste de doublons. Un sous-cadre sans entrée visible
n'est pas rendu, et le mode réduit (icônes seules) affiche tout à plat — on ne peut pas replier
sans libellé. L'état est une préférence locale séparée
(`admin-sidebar-sous-groupes-ouverts`) : mélanger les deux objets rendrait le typage faux dès
qu'un sous-cadre porterait le nom d'un cadre. Trois tests de la spec verrouillent l'invariant
qui casse en silence : une entrée dont le `groupe` ne correspond pas au cadre de son sous-cadre
disparaît du menu.

La cloche interroge un résumé léger toutes les 20 s (`pollWhileVisible`) et ne recharge la
liste que s'il a changé. L'en-tête arbitre ses deux listes déroulantes (notifications, menu
utilisateur : une seule ouverte à la fois) et signale au layout qu'une liste est ouverte
(`menusOuvertsChange`). Le layout affiche alors le fond semi-transparent et, au clic, appelle
`fermerMenus()` de l'en-tête. Ce fond reste dans le layout : placé dans l'en-tête (`sticky`,
z-index 999), il recouvrirait les boutons de l'en-tête lui-même.

Styles : ce qui place un bloc dans la grille (`grid-area`, position fixe sur mobile) reste dans
`admin-layout.component.scss`, car il s'applique à la balise du composant enfant ; l'intérieur
de chaque bloc est stylé dans le composant lui-même (encapsulation Angular). Le mode réduit
passe par la classe `collapsed` posée sur `<app-admin-sidebar>` (`:host(.collapsed)`), la zone
DEMO par `demo-mode` sur `<app-admin-header>`.

**Menu latéral ajustable (grand écran, > 768 px).** Trois états, pilotés par le layout
(`etatSidebar`) : `etendue` (largeur libre de 200 à 420 px), `reduite` (icônes seules, 70 px),
`fermee` (masqué, `inert`). La largeur de la colonne passe par la variable CSS
`--sidebar-largeur` posée sur la grille ; le contenu principal suit donc le menu.
- Poignée sur le bord droit du menu (`role="separator"`) : glisser change la largeur ; sous
  150 px le menu passe en icônes seules, sous 40 px il se ferme ; double-clic = largeur par
  défaut ; au clavier, flèches et Entrée. Pendant le glissement (`.redimensionnement`), pas
  d'animation et pas de sélection de texte ; le pointeur est capté (`setPointerCapture`) pour
  ne pas être perdu au-dessus d'une iframe (Grafana).
- Bouton de l'en-tête : masquer / réafficher le menu (retour à l'état précédent). Bouton du
  bas du menu : icônes seules / libellés.
- Les libellés se tronquent (« … ») quand le menu rétrécit ; en mode réduit, les icônes
  glissent vers le centre (padding animé) au lieu de sauter.
- État, largeur et état avant fermeture sont une préférence locale (`localStorage`,
  `admin-sidebar-affichage`). Sur mobile, rien ne change : menu en tiroir.

### 6.5 Simulation d'inondation (page)

Outil de planification, pas une prévision (calculs au § 5.8). La page lance la simulation des
paliers dès qu'une commune est choisie, puis l'interroge par polling jusqu'à
`statut !== 'EN_COURS'`. L'état vit côté serveur : revenir sur la page reprend où l'on en
était (la dernière commune est mémorisée en `localStorage`). Le chargement des adresses BAN
reste un geste explicite, car il peut être long ou échouer sur une grande ville. Le curseur ne
fait aucun appel réseau : couleurs data-driven (`setPaintProperty`) et `setData` sur des
données déjà chargées. Deux modes superposables : crue de rivière et ruissellement (grille de
carrés à la taille réelle des cellules). Le niveau mesuré (Hub'Eau) et la vigilance
(Vigicrues) ne sont que des repères.

### 6.5.1 Géolocalisation : une seule invite, et seulement sur un geste

Règle du projet depuis le 07/11/2026 : **l'invite de permission de géolocalisation ne part que
d'un geste explicite de l'utilisateur**, pour une fonctionnalité qu'il vient de demander.

Pourquoi c'est une règle et pas une préférence : sur iOS, un refus est **définitif pour tout le
site** — Safari ne repropose jamais l'invite, et il faut passer par les Réglages du téléphone.
Deux appels la déclenchaient depuis `ngOnInit`, sans geste : le champ d'adresse des formulaires
publics et la carte, tous deux pour un usage purement opportuniste (trier les suggestions
d'adresse, recentrer la vue). L'utilisateur voyait donc l'invite surgir au chargement d'une page,
la refusait — réaction normale devant une demande qu'il n'a pas sollicitée — et **tous les usages
légitimes suivants échouaient ensuite définitivement**, y compris un signalement de terrain
géolocalisé. Signalé comme « Safari bloque la géoloc ».

Trois mécanismes :

- `GeolocationService.positionSansInvite()` pour tout usage opportuniste : rend la position si
  elle est déjà connue ou déjà autorisée (`navigator.permissions`), sinon `null`, **sans jamais
  inviter**. Sans l'API Permissions (Safari < 16) on s'abstient : impossible de savoir si l'appel
  inviterait, et c'est l'invite non sollicitée qu'on veut éviter.
- `requestLocation()` reste pour les appels déclenchés par un geste, avec des réglages tenables
  sur iOS : délai de 20 s (le premier point GPS y demande couramment plus de dix secondes) et
  acceptation d'un point de moins d'une minute, au lieu d'exiger une mesure neuve.
- Sur la carte, un **bouton « ma position »** (`maplibregl.GeolocateControl`) remplace le
  recentrage automatique : l'invite part d'un clic, ce qui est le contexte qu'exige Safari, et
  l'utilisateur sait pourquoi on la lui demande. `trackUserLocation: false` — un point à la
  demande, jamais un suivi continu, qui a son propre dispositif explicite.

En cas de refus sur iOS, le message dit **où** rétablir l'autorisation : sans cela, l'utilisateur
conclut que l'application est cassée.

Le **suivi de position permanent** suivait la même mauvaise pente, par un autre chemin :
`SuiviPositionPermanentService` était « actif par défaut, sauf refus mémorisé », en comptant sur
l'invite du navigateur comme garde-fou. `AppComponent.ngOnInit` appelait donc `watchPosition` à
**chaque chargement de page et pour tout visiteur**, connecté ou non, site public compris. C'est
le chemin le plus visible, et il avait été manqué lors du premier correctif. Désormais il faut un
**consentement explicite** (`suiviPositionPermanentConsenti`, posé par le bouton de l'en-tête ou
des paramètres) ; les comptes antérieurs ne reprennent le suivi que si la permission est **déjà
accordée**, ce qui n'invite jamais. Désactiver retire le consentement et pas seulement le suivi,
sinon le prochain chargement le relancerait.

Enfin, les lectures/écritures de préférence passent par un accès protégé : `localStorage`
**lève** en navigation privée Safari ou avec le blocage total des cookies, et comme ce service est
appelé depuis `ngOnInit`, l'exception empêchait l'initialisation de toute l'application pour une
simple préférence.

**Limite connue, et elle est structurelle** : l'instance locale d'un satellite est servie en
**HTTP** sur le réseau local (`http://<IP du satellite>/`, voir `satellite/nginx-satellite.conf`).
`window.isSecureContext` y vaut donc **faux**, et tous les navigateurs — Safari comme les autres —
refusent la géolocalisation, sans même afficher d'invite. Aucun code ne peut contourner cela :
dans ce mode, « ma position », le suivi d'intervenant et le géomarquage des photos sont
indisponibles. C'est précisément le scénario du satellite (téléphones sur site, sans internet),
donc la limite compte. La lever demanderait un certificat TLS sur le satellite et l'installation
de son autorité sur les téléphones — pas fait, pas décidé.

### 6.5.2 Création d'une zone : la carte suit la commune saisie

`ZoneMapComponent` accepte `[communesGeojson]` (contours en calque de référence sous l'outil de
dessin) et `[cadrerSur]` (ajustement aux limites d'une géométrie). `[cadrerSur]` et non
`[center]`/`[zoom]` : un niveau de zoom fixe cadre mal une commune, qui peut faire deux kilomètres
comme quarante. Le calcul gère le MultiPolygon — une commune insulaire ou discontinue en est un,
et ne lire que `coordinates[0]` cadrerait sur un seul morceau.

La modale de création de zone ne passait **ni l'un ni l'autre** : saisir une commune laissait donc
la carte sur la France entière, et on dessinait une zone à main levée sur un fond sans limites
administratives (bug signalé le 07/11/2026). Elle charge maintenant le contour officiel de chaque
commune ajoutée (`getCommuneContour`, mis en cache par code INSEE), cadre sur la dernière saisie,
et affiche l'ensemble en calque. Si l'API géo ne répond pas, seule l'aide visuelle manque : la
zone reste créable.

### 6.6 Thème clair / sombre

`ThemeService` (`services/theme.service.ts`) pose `data-theme="clair|sombre"` et
`color-scheme` sur `<html>`. Préférence `clair`, `sombre` ou `systeme` (défaut : suit
`prefers-color-scheme`, y compris quand le système bascule pendant la session), mémorisée en
`localStorage` (`theme`). Bouton soleil/lune dans les deux en-têtes (admin et public).

**Principe : le mode clair ne change pas.** Les couleurs des composants s'écrivent
`var(--ac-…, <couleur d'origine>)`. Les variables `--ac-*` ne sont définies que sous
`html[data-theme='sombre']` (`styles.scss`, « Thème ») : en clair, la valeur de repli
s'applique, au pixel près.

| Variables | Rôle en sombre |
|---|---|
| `--ac-bg`, `--ac-surface`, `--ac-surface-2`, `--ac-surface-3` | page, cartes, fonds discrets/survols (sous les cartes), pastilles (au-dessus) |
| `--ac-text`, `--ac-text-muted`, `--ac-text-subtle` | texte principal, secondaire, discret |
| `--ac-border`, `--ac-border-strong` | bordures |
| `--ac-<famille>-bg/-text/-border` (`red`, `orange`, `amber`, `green`, `teal`, `blue`, `indigo`, `purple`, `pink`) | badges, alertes, encadrés teintés : fond opaque teinté, texte clair |

**Écrire un nouveau style** : utiliser directement ces variables avec la couleur claire en
repli, par exemple `color: var(--ac-text-muted, #6b7280);`. Les couleurs franches (boutons,
dégradés, texte blanc sur un bouton) restent telles quelles. Une couleur qui doit être la même
dans les deux thèmes (texte sur le fond orange du mode démo) se marque `// theme: fixe`.

**Conversion des feuilles existantes** : `frontend/scripts/convertir-couleurs-theme.py`
(`--dry-run` pour simuler, `--annuler` pour revenir aux couleurs d'origine). Il classe chaque
couleur selon la propriété (fond, texte, bordure, `stroke`/`fill` SVG) et sa nature (gris,
teinte pâle, texte de couleur trop sombre pour un fond sombre) ; il laisse le texte d'un bloc
dont le fond reste clair. Idempotent : à relancer après l'ajout de pages écrites avec des
couleurs en dur.

#### 6.6.1 Marque blanche et contraste

Une institution choisit sa couleur primaire en la regardant sur un fond blanc. Rien ne
garantit qu'elle reste lisible sur `--ac-surface` (`#1c1f26`), ni que du blanc passe dessus.
Le bleu Assista-Crise lui-même ne tient pas : **3.19:1 sur le fond sombre**, sous le seuil AA
de 4.5:1. Le problème n'est donc pas théorique et ne concerne pas que les marques blanches.

Plutôt que de valider chaque branding à la main — impossible, une institution change sa
couleur quand elle veut — `BrandingService` dérive au runtime des couleurs sûres via
`services/contraste.ts` (luminance et rapport de contraste WCAG 2.1), et **les recalcule à
chaque bascule de thème** :

| Variable | Usage |
|---|---|
| `--brand-primary`, `--brand-secondary` | la couleur de la marque, brute : **aplats uniquement** (boutons pleins, badges) |
| `--brand-primary-lisible`, `--brand-secondary-lisible` | **tout texte, icône, lien ou bordure fine** posé sur une surface — contraste ≥ 4.5:1 garanti dans les deux thèmes |
| `--brand-on-primary`, `--brand-on-secondary` | le texte posé **sur** un aplat de marque : blanc ou encre (`#111827`) selon la luminance de la marque |

L'ajustement conserve teinte et saturation et ne déplace que la luminosité, par pas de 1 %,
jusqu'au premier palier conforme : la couleur reste reconnaissable comme celle de la marque.
Il ne bascule jamais vers le blanc ou le noir purs, qui l'effaceraient. Une couleur déjà
conforme est renvoyée inchangée.

**Écrire un nouveau style avec la couleur de marque** :

```scss
// Texte, icône, lien, bordure fine
color: var(--brand-primary-lisible, var(--brand-primary));
// Aplat + son texte
background: var(--brand-primary); color: var(--brand-on-primary, #fff);
```

Les valeurs de repli de `styles.scss` ne servent qu'au tout premier rendu, avant le passage
de `BrandingService` ; elles sont écrasées au runtime par la couleur ajustée de l'institution.
`contraste.spec.ts` vérifie qu'un échantillon de marques plausibles (dont des cas extrêmes :
or, cyan, noir, blanc) atteint AA sur les deux fonds.

Limites connues : les couleurs écrites dans les templates (`style="…"`) ou dans le TypeScript
ne sont pas converties ; le fond de carte MapLibre reste clair. Grafana suit le thème
(`theme=dark` dans l'URL de l'iframe, § 9.3.1). Le budget d'erreur `anyComponentStyle`
d'`angular.json` est passé de 24 à 28 ko : la conversion ajoute ~7 % à chaque feuille, ce qui
faisait dépasser `teams.component.scss`.

---

## 7. Services annexes

| Service | Rôle | Statut | Documentation |
|---|---|---|---|
| `meshtastic-bridge/` | relie l'application au réseau Meshtastic (MQTT tiers ou appareil TCP/série) | test, non déployé en prod | [README](meshtastic-bridge/README.md) |
| `meshcore-bridge/` | relie l'application à un compagnon MeshCore (série, BLE, TCP) + proxy partagé | test | [README](meshcore-bridge/README.md) |
| `matrix-bridge/` | un salon Matrix privé par équipe, relais des positions live d'Element | non vérifié sur un vrai client Element | [README](matrix-bridge/README.md) |
| `satellite/` | Raspberry Pi sur site : profil `gw` (pont radio) ou `full` (instance complète hors ligne, synchronisée avec le central) | non testé sur matériel réel | [README](satellite/README.md) |

Les services-ponts s'authentifient auprès de l'API avec un **compte de service** dédié (JWT)
et appellent `http://backend:8000/`. Ils n'exposent aucun port : ils **interrogent
périodiquement** des files en base (`MessageMeshLog`, `CommandeMeshCore`,
`MessageMeshtasticLog`…) puis rapportent le résultat par `PATCH`.

### 7.1 Matrix (messagerie)

- **SSO** : Django est fournisseur OIDC (`django-oauth-toolkit`, `core/oidc.py`) ; on se
  connecte à Element avec son compte Assista-Crise, sans compte Matrix séparé. La clé
  `OIDC_RSA_PRIVATE_KEY` est passée sur une ligne (`\n` littéraux, contrainte des
  `--env-file` Docker). `OIDC_ISS_ENDPOINT` est **fixe** : Synapse appelle `/o/token/` via
  `backend:8000`, et l'émetteur déduit du Host ne correspondrait pas à celui qu'il attend.
- **Identifiants Matrix** déterministes (`core/matrix.py`) : `MATRIX_SERVER_NAME` doit être
  identique dans Django, `matrix-bridge` et la config Synapse. Ne jamais pré-créer un compte
  Matrix via l'API d'administration (erreur « Localpart not available » au premier SSO).
- **Salons** : **deux par équipe** (`SalonMatrixEquipe`, activés à la demande) et deux
  par institution (`PERMANENTS` pour le personnel, `BENEVOLES` pour les membres de ses équipes
  actives). `matrix-bridge` les crée puis **resynchronise les membres en continu** depuis
  l'API ; le salon de la cellule de crise n'expulse personne (pas de membres formels).

  Les deux salons d'équipe (11/11/2026, migration `0247` — c'était un `OneToOneField`, une
  équipe n'avait qu'un salon) :

  | Salon | Qui s'y trouve |
  |---|---|
  | `INTERVENANTS` | toute l'équipe, **encadrement compris** — un encadrant absent du salon de terrain de sa propre équipe ne voit pas ce qui s'y dit |
  | `ENCADREMENT` | l'encadrement de l'équipe **et celui de ses équipes filles directes**, un seul niveau |

  **La remontée s'arrête à « n-1 »** (arbitrage du 11/11/2026). Le salon d'une Coordination
  Régionale réunit l'encadrement régional et les coordinateurs départementaux, et s'arrête là :
  chaque échelon parle à celui immédiatement en dessous.

  La remontée récursive avait d'abord été écrite, puis écartée : elle faisait du salon
  d'encadrement national la réunion de **tous** les encadrants de France, ce qui n'est plus un
  salon de commandement mais une liste de diffusion. À n-1, un encadrant départemental est dans
  exactement deux salons d'encadrement — le sien et celui de sa région.

  Conséquence à connaître : **rien ne relie deux échelons non adjacents.** Le national ne joint
  pas un coordinateur départemental par un salon ; il passe par la zone, qui passe par la région.
  C'est la chaîne de commandement, et c'est ce qui est voulu.

  Effet secondaire bienvenu : un seul niveau ne peut pas boucler, donc aucun garde anti-cycle
  n'est nécessaire — la version récursive en demandait un pour ne pas tourner indéfiniment dans
  le pont si un cycle était introduit à la main dans `equipe_parente`.

  Le salon `INTERVENANTS` **ne remonte pas du tout** : celui du national contiendrait sinon tous
  les bénévoles de France.

  La migration donne le type `INTERVENANTS` aux salons existants, et c'est le seul choix qui ne
  détruise rien — l'unique salon d'une équipe était déjà celui de l'équipe entière. Il garde son
  `room_id`, son historique Synapse et ses membres ; aucun salon n'est recréé. Le pont met le
  type dans le **nom** du salon : deux salons homonymes dans Element sont indiscernables, et on
  écrit alors à l'encadrement en croyant parler à l'équipe.
- **Deux FQDN sur un seul Synapse** (11/11/2026) : le proxy sert déjà
  `matrix.reserve-resilience.org`, `auth.*` et `chat.*` vers les mêmes conteneurs, avec un
  certificat partenaire séparé (`proxy/waf-partenaires-tls.conf`). Trois niveaux à ne pas
  confondre :

  | Niveau | Personnalisable ? |
  |---|---|
  | **Point d'entrée** (l'adresse saisie dans Element X) | **oui** — `Institution.matrix_hostname` |
  | **Découverte client** (`/.well-known/matrix/client`) | **oui** — servi par hôte dans nginx |
  | **`server_name` de Synapse** (le suffixe des identifiants) | **non** |

  `MATRIX_SERVER_NAME` servait à deux choses confondues — former les identifiants
  (`core/matrix.py:matrix_user_id`) **et** indiquer l'adresse à taper dans le mail d'enrôlement.
  Seule la seconde devient per-institution ; un test (`test_l_identifiant_matrix_ne_change_PAS`)
  garde la frontière. Synapse n'a qu'un seul `server_name`, inscrit dans chaque identifiant
  d'utilisateur et de salon : les comptes restent `@…:matrix.assista-crise.fr`, et le changer
  casserait toutes les identités et tous les salons existants.

  Synapse génère `/.well-known/matrix/client` depuis son `public_baseurl` **unique** : un membre
  qui saisissait l'adresse du partenaire était aussitôt renvoyé sur celle de la plateforme.
  Nginx répond donc avant le `proxy_pass`, avec le `$host` réellement visité.

  **L'`issuer` OIDC y reste celui de la plateforme, et c'est mesuré, pas supposé** : MAS renvoie
  `issuer: https://auth.assista-crise.fr/` **quel que soit le Host** (vérifié en forçant
  l'en-tête `Host` sur les deux domaines). Annoncer l'émetteur du partenaire créerait une
  non-concordance que tout client OIDC strict refuse — cela casserait la connexion Matrix pour
  **tout le monde**, pas seulement pour le partenaire. Le domaine partenaire sur
  l'authentification demanderait de reconfigurer l'émetteur de MAS, ce qui invaliderait les
  sessions existantes. Reste donc une seule apparition d'« assista-crise » pour un bénévole : la
  page de connexion.

  `nginx.conf` est **copié dans l'image**, pas monté : toute modification exige
  `docker compose build proxy && up -d proxy`, un `nginx -s reload` ne la voit pas.
- **Positions live** Element (MSC3489) : enregistrées par le pont dans
  `HistoriquePositionUtilisateur` pour rejouer un trajet. Distinct de `DernierePositionUtilisateur`,
  capturée par le frontend seulement quand le navigateur a déjà la position (jamais de
  traçage continu).
- Les erreurs applicatives sont aussi envoyées sur un salon Matrix (§ 5.7).

### 7.2 Réseaux maillés radio (MeshCore, Meshtastic)

- **MeshCore** : un *companion* (`CompagnonMeshCore`) sert de passerelle, piloté par
  `meshcore-bridge` (série, BLE ou TCP, plus un proxy qui partage l'appareil avec d'autres
  clients). Les nœuds de terrain sont associés aux comptes par clé publique
  (`NoeudMeshUtilisateur`) ; le répertoire de contacts et les répéteurs sont synchronisés
  automatiquement par le pont.
- **Cloisonnement** : un DM est rattaché à l'équipe de l'expéditeur au moment de la réception ;
  seuls son leader et son régulateur le lisent (administrer un companion ne donne pas accès
  aux messages). Chaque équipe peut avoir un **canal privé** dont la clé est distribuée par
  DM ; une rotation de clé libère l'ancien slot après 48 h. Les canaux publics `#nom` ont une
  clé dérivée du nom (`sha256(nom)[:16]`) ; le canal « Public » d'usine est reconnu
  automatiquement. Les canaux captés mais inconnus sont signalés (`CanalMeshCoreDetecte`).
- **Routage** (`core/routage_mesh.py`) : sans companion imposé, l'API choisit celui qui
  connaît le chemin le plus court vers le destinataire, puis par étiquette régionale
  communautaire (ex. « fr-naq », sans existence dans le protocole).
- **Meshtastic** : soit un nœud **logiciel** relayé par un broker MQTT tiers (Gaulix :
  racine de topic `Traitement/msh/EU_868`, chiffrement réimplémenté dans
  `meshtastic-bridge/crypto.py`), soit un appareil réel en TCP (port 4403) ou USB. Gaulix ne
  relaie de façon fiable que le **clair** : le chiffrement reste désactivé par companion tant
  que `chiffrement_supporte` n'est pas coché. Les clés privées et PSK ne sont jamais renvoyées
  par l'API.
- **Urgences** : un message entrant contenant un mot-clé SOS, ou arrivé sur un canal
  d'urgence (ex. `Fr_EMCOM`), crée une `AlerteMeshSOS` et notifie les administrateurs, sans
  jamais créer de demande automatiquement.
- **Alertes sismiques** : `verifier_alertes_sismiques` (cron) diffuse les séismes du catalogue
  BCSF-Rénass proches de chaque institution abonnée (magnitude ≥ 3.5 par défaut, réglable) et
  sur `Fr_EMCOM` ; `SeismeDiffuse` évite les doublons (réglages : `ConfigurationAlerteSismique`).
- Traceroute (`TracerouteMeshCore`) et batterie du companion servent au diagnostic.

### 7.3 Satellites (Raspberry Pi sur site)

- **Profils** : `gw` (pont et proxy radio locaux) ou `full` (instance Assista-Crise complète,
  utilisable sans internet). Le satellite initie **toujours** la connexion vers le central :
  aucun port entrant à ouvrir sur le site.
- **Enrôlement** : un acteur institutionnel génère un jeton court à usage unique, saisi à
  l'installation ; le satellite apparaît `EN_ATTENTE`. Un administrateur le **valide**, ce qui
  crée son compte de service (identifiants affichés une seule fois). Le satellite s'authentifie
  ensuite en JWT, comme les ponts.
- **État** Actif / Inactif / Perdu, dérivé à la lecture de `dernier_contact` (mis à jour par
  tout appel authentifié) et des seuils `SATELLITE_SEUIL_INACTIF_MINUTES` (15) et
  `SATELLITE_SEUIL_PERDU_MINUTES` (120). Supervision : communes limitrophes approximées par
  distance de centroïdes (`SATELLITE_SUPERVISION_RAYON_LIMITROPHE_KM`).
- **Synchronisation satellite → central** (`core/sync_outbox.py`, profil `full`) : avec
  `INSTANCE_SATELLITE_LOCALE=True` (jamais sur le central), chaque écriture locale d'un modèle
  synchronisé (dossiers et leur fil, déclarations de sécurité, missions, messages mesh) crée un
  `EvenementSynchronisation`. La commande `synchroniser_sortant` les pousse dans l'ordre toutes
  les `SATELLITE_SYNC_SORTANT_INTERVALLE_S` secondes. Les demandes, offres et signalements des
  citoyens ne sont jamais synchronisés (ils arrivent par internet). Un objet modifié des deux
  côtés (`version_de_base` dépassée) crée un `ConflitSynchronisation`, **jamais résolu
  automatiquement**. L'auteur apparent côté central est le compte du satellite ; l'auteur
  local réel est conservé dans l'événement.

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

- Réseaux : `front` (proxy, frontend, backend, mosquitto), `back`, `db` (base
  isolée : seuls `backend` et `postgres-exporter` le rejoignent), `monitoring`.
- Ports publiés : 80/443 (proxy), 1883 (MQTT) **sur la seule IP du LAN `172.16.1.114`** et non
  sur `0.0.0.0` (§ 10.2), Grafana sur `127.0.0.1:3000` uniquement.
- Images de base épinglées par digest dans les Dockerfiles (builds reproductibles) ; les mettre à
  jour régulièrement (`docker buildx imagetools inspect <image>` puis remplacer le `@sha256:…`).

---

## 9. Monitoring

Détails opérationnels : [monitoring/README.md](monitoring/README.md).

### 9.1 Ce qui est mesuré

| Source | Métriques | Méthode |
|---|---|---|
| Django (`/metrics`) | requêtes, statuts, latence par vue, requêtes SQL | RED |
| `core/metrics.py` | `assista_help_requests_total`, `assista_offers_total`, `assista_institutions_created_total`, `assista_emails_failed_total`, `assista_requests_by_status`, `assista_offers_by_status`, `assista_active_crises`, `assista_accounts_pending_validation`, `assista_oldest_pending_account_age_seconds` — label `environment` (PROD/DEMO) sur les métriques métier | métier |
| postgres / nginx / mosquitto exporters | état et charge de chaque service | USE |
| node-exporter, cAdvisor | hôte et conteneurs | USE |
| blackbox-exporter | sonde HTTPS de `www.assista-crise.fr`, atteinte par l'IP locale + SNI (§ 9.6) | boîte noire |

Gunicorn tournant avec plusieurs workers, les métriques sont agrégées via
`PROMETHEUS_MULTIPROC_DIR` (sinon chaque scrape lirait un worker au hasard), activé par défaut
par le `CMD` de l'image (`/tmp/prometheus-multiproc`, vidé au démarrage).

### 9.2 Alertes (`monitoring/prometheus/alerts.yml`)

Principes : alerter sur les **symptômes** ressentis par les utilisateurs, chaque alerte doit
être actionnable, `critical` = agir maintenant, `warning` = cette semaine.

| Groupe | Alertes |
|---|---|
| Disponibilité | `SiteDown`, `InstanceDown`, `ServiceDown` (l'exporter répond mais son service est mort) |
| Application | `HighErrorRate` (avec seuil de trafic minimum), `SlowAPI`, `EmailsFailing` |
| Infrastructure | `DiskWillFillIn24h` (prédiction), `DiskAlmostFull`, `LowMemory`, `ContainerRestarting`, `DatabaseConnectionsHigh` |
| Certificats | `TLSCertExpiringSoon`, `TLSCertExpiringCritical` |
| Métier (PROD uniquement) | `NoHelpRequestDuringActiveCrisis`, `UnprocessedRequestsPilingUp`, `AccountWaitingForValidation` (> 24 h) |
| Réseau radio | `MeshCompagnonSilencieux`, `MeshPlusAucunCompagnon` (critique : plateforme coupée de la radio), `MeshInfrastructureBatterieFaible` |
| Méta | `Watchdog` : toujours active, transmise à healthchecks.io qui alerte quand elle **s'arrête** |

Chaque règle est couverte par `alerts_test.yml` (`promtool test rules`).

### 9.3 Notifications et visualisation

- Alertmanager : dev → MailHog ; prod → SMTP Ionos + healthchecks.io (Watchdog renvoyé chaque minute).
- Grafana : six tableaux provisionnés depuis `monitoring/grafana/dashboards/`, reliés par
  le tag `assista` :

  | Onglet de l'admin | uid | Contenu |
  |---|---|---|
  | Vue complète | `assista-overview` | santé → mission → infrastructure |
  | Santé du site | `assista-sante` | disponibilité, erreurs 5xx, latence, certificat, alertes |
  | Métriques métier | `assista-metier` | crises actives, demandes, offres, emails en échec |
  | Infrastructure | `assista-infra` | conteneurs, VM, PostgreSQL, MQTT |
  | Réseau radio | `assista-mesh` | passerelles actives, silence maximal, infrastructure entendue, batteries faibles |
  | WAF | `assista-waf` | refus 403, détections OWASP CRS, types d'attaque, IP, trafic par code HTTP |
  | Fail2ban | `assista-fail2ban` | bans et détections par jail |

  Les onglets WAF et Fail2ban lisent **Loki** (.114 uniquement, `docker-compose.114.yml`) :
  Alloy (`monitoring/alloy/config.alloy`) y envoie l'audit ModSecurity, le journal d'accès du
  WAF et le journal de fail2ban, réduits à des champs choisis (jamais les en-têtes
  Authorization/Cookie ni les corps de requête ; jetons des URL masqués). Rétention 90 jours
  (`monitoring/loki/loki.yml`). Ailleurs, ces deux onglets restent vides.

  Les conteneurs du profil monitoring portent le label `assista.role=monitoring` (ancre
  `x-monitoring` de `docker-compose.yml`), que cAdvisor expose en `container_label_assista_role`.
  Les panneaux par conteneur filtrent sur `container_label_assista_role!="$monitoring"` : la
  variable `monitoring` vaut `monitoring` (masquer, par défaut) ou `aucun` (afficher). Le
  frontend ne choisit que cette valeur (`&var-monitoring=`), jamais la requête PromQL.

  Une modification faite dans l'interface n'est pas conservée. Pour modifier un tableau : le
  modifier en local, *Export → Export as JSON* en **JSON classique** (pas « v2 resource »), sans
  « Export for sharing externally » (sinon `${DS_…}` que le provisioning ne résout pas), puis
  `"id": null`, `uid` inchangé (le frontend construit l'URL avec) et source de données
  `{"type":"prometheus","uid":"prometheus"}`.

### 9.3.1 Grafana dans l'administration (`/admin/monitoring`)

```
Angular (sysadmin)  ── POST /api/monitoring/grafana-token/ ──▶  Django (core/grafana.py)
                    ◀── jeton RS256, 1 h, sub/role seulement ──  rôle réel ADMIN, sinon 403
<iframe src="/grafana/d/<uid>/?kiosk&auth_token=…">  ──▶  nginx /grafana/  ──▶  Grafana [auth.jwt]
                                                          vérifie avec la clé publique (secret)
```

- **Pas de second mot de passe** : Grafana vérifie la signature avec `grafana_jwt_public.pem`
  et crée l'utilisateur (`assista-<id>`, rôle *Viewer*). Il ne pose pas de session : son
  interface renvoie le jeton à chaque requête, d'où la durée d'1 h et le renouvellement par le
  composant 5 min avant expiration.
- **Le jeton passe dans l'URL** : aucune donnée personnelle dedans, et nginx le remplace par
  `MASQUE` dans ses journaux (`log_format masque`, URL et Referer).
- **Clés** : `scripts/init-secrets.sh` génère la paire. Privée → `GRAFANA_JWT_PRIVATE_KEY` du
  backend (PEM sur une ligne) ; absente, le point d'API répond 503 et le reste du site marche.
- **nginx** résout `grafana` à chaque requête (`resolver 127.0.0.11` + variable) : sans le
  profil monitoring, seul `/grafana/` répond 502, le proxy démarre quand même.
- **Accès de secours** (site ou backend en panne) : Grafana ne dépend que de Prometheus.
  `ssh -L 3000:localhost:3000 <utilisateur>@<vm>` puis http://localhost:3000/grafana/login,
  compte local `admin`.

### 9.4 Images de monitoring

Prometheus, Alertmanager et Grafana sont construits depuis `monitoring/<nom>/Dockerfile` :
image officielle + configuration, **validée pendant le build** (une règle invalide fait échouer
le build). En dev, l'override construit les mêmes images puis monte les fichiers par-dessus.

Deux exceptions sur **.114**, qui monte des fichiers par-dessus l'image : `prometheus.114.yml`
(depuis le dépôt) et `alertmanager.114.yml` (depuis `~/.config/assista-crise/monitoring/`, parce
qu'il contient les vrais destinataires, qui n'ont rien à faire dans git). Ce sont des montages de
**fichier**, pas de dossier : éditer le fichier en crée un nouvel inode et le conteneur continue
de lire l'ancien. Un `SIGHUP` ne suffit donc pas, il faut **recréer le conteneur**
(`docker compose -f docker-compose.114.yml up -d --no-deps <service>`) — et valider la
configuration dans un conteneur jetable monté sur le dossier, pas avec le `promtool`/`amtool` du
conteneur en service, qui lit l'ancien fichier et validerait la version d'avant.

### 9.5 Ajouter…

- **une métrique métier** : un `Counter` / une jauge dans `core/metrics.py` (labels bornés),
  un test dans `core/tests/plateforme/test_metrics.py`, un panneau dans le dashboard JSON ;
- **une alerte** : une règle dans `alerts.yml` + un test dans `alerts_test.yml`, puis
  `docker compose build prometheus` ;
- **un service à surveiller** : son exporter dans `docker-compose.yml` (profil `monitoring`), un
  `scrape_config` dans `prometheus.yml`, une alerte sur sa métrique `*_up`.

### 9.5.1 Diagnostic des liaisons radio

`core/analyse_liaisons.py`, porté de `asymetrie.js` de `carte-live-meshtastic` (GPL-3.0, avec
l'autorisation de l'auteur). Exposé par `GET /api/contacts-meshtastic/analyse-liaisons/` et affiché
sur **`/admin/diagnostic-radio`** (cadre « Communications / Radio »).

La page affiche chaque conclusion **avec ce qui permet de la juger** — origine de la preuve
(passerelle ou voisinage), nombre d'observations, et si la puissance d'émission était connue. Ce
n'est pas de l'ornement : une conclusion non corrigée en puissance est marquée « non corrigé »
plutôt que présentée comme un fait, parce que désigner un relais comme sourd envoie quelqu'un sur
un point haut. Le calcul relit une semaine d'observations : il se déclenche au chargement et sur
bouton, jamais en boucle.

Quatre diagnostics : **liaisons à sens unique** (« B entend A, mais A n'entend jamais B »),
**liaisons déséquilibrées** (plus de 10 dB d'écart entre les deux sens), **nœuds inaudibles**
(entendent leurs voisins, mais personne ne les entend — antenne en réception seulement, ou
émission en panne) et **relais sourds** (écart médian de SNR anormal : le nœud entend nettement
moins bien qu'on ne l'entend).

Ce qui a de la valeur dans ce portage, ce ne sont pas les formules mais les **précautions**, sans
lesquelles l'analyse produirait des diagnostics faux et crédibles — désigner un relais comme sourd
envoie quelqu'un sur un point haut :

- on ne conclut « à sens unique » que pour un nœud qui **rapporte** ce qu'il entend (passerelle
  MQTT ou rapport de voisinage) : un saut de traceroute ne le prouve pas, et un relais muet ferait
  passer pour unilatéral tout ce qu'il entend sans le dire ;
- un rapport de voisinage Meshtastic est **plafonné à 10 voisins** : liste pleine, une absence ne
  prouve rien ;
- au moins **3 observations** : un paquet isolé peut être un rebond ;
- au-delà de **120 km**, c'est une erreur de position, pas une liaison directe ;
- relais sourd : **médiane** sur au moins deux voisins dont une mesure réciproque — une mesure
  isolée peut venir du partenaire, pas du nœud examiné.

### 9.5.2 Routage Meshtastic : par où joindre un nœud

`core/routage_meshtastic.py`, exposé par `GET /api/contacts-meshtastic/routage/` et affiché dans
le tableau « Nœuds détectés » de **`/admin/meshtastic-companions`**. Équivalent Meshtastic de
`routage_mesh.py` (MeshCore), dont il reprend le principe : jamais un choix opaque, le résultat
porte toujours une `raison` lisible, affichée telle quelle.

**Deux questions, et il ne faut pas les confondre.** « Quelle passerelle a entendu ce nœud ? » est
une observation : une passerelle MQTT a reçu un de ses paquets *sans relais intermédiaire*
(`hop_start == hop_limit`, voir `_observer_liaison_rf` dans le pont). « Par où l'atteindre ? » ne
s'en déduit pas, pour trois raisons :

- **le broker cloisonne** : il faut émettre par le companion qui a vu le nœud
  (`ContactMeshtastic.compagnon`, le plus récent quand plusieurs l'ont vu) ; publier sur un autre
  broker, c'est publier dans un autre réseau ;
- **la passerelle qui entend n'est pas forcément la nôtre** : sur un broker partagé (Gaulix) la
  plupart appartiennent à des tiers. On voit alors le nœud sans maîtriser le dernier saut — la
  descente dépend du `downlink_enabled` de cette passerelle, qu'on ne peut pas lire chez
  quelqu'un d'autre. Le tableau distingue donc les passerelles « à nous » des autres (trait
  pointillé) ;
- **une liaison est orientée** : « elle l'entend » n'implique pas « il l'entend ». Chaque saut
  porte `retour_prouve` ; un chemin dont le retour n'est pas observé sert à écouter, pas
  forcément à parler.

Le nombre de sauts est la conclusion la plus actionnable : `hop_limit` vaut **3 par défaut**
(maximum 7) et décroît à chaque relais. Un nœud à 4 sauts est hors d'atteinte sans relever cette
limite, et le paquet est abandonné en route **sans erreur** pour l'émetteur. Un relais unique sur
le chemin est signalé comme point de panne unique.

Un `null` en nombre de sauts signifie « aucune passerelle ne l'a entendu en 7 jours », pas « à
zéro saut » : ces nœuds sont affichés « hors de portée » et restent en dernier dans les deux sens
de tri (voir `shared/utils/table-tri-filtre.ts`). Un saut de traceroute compte comme chemin — il
prouve un saut radio direct — mais son récepteur n'est **pas** compté comme passerelle : un relais
traversé ne publie pas forcément sur MQTT.

Non fait, et c'est un choix : l'envoi d'un DM Meshtastic exige toujours un `compagnon` explicite.
Le routage *renseigne* l'opérateur, il ne sélectionne pas encore le companion à sa place comme le
fait MeshCore — se tromper enverrait le message sur le mauvais broker, où il n'arriverait jamais.

### 9.5.3 Tri et filtrage des tableaux

`frontend/src/app/shared/utils/table-tri-filtre.ts` et les deux composants
`th[appThTri]` / `th[appThFiltre]` (`shared/components/common/table-tri/`). Sélecteurs
d'**attribut** sur `th` : un élément `<app-…>` placé dans un `<tr>` est sorti du tableau par le
navigateur et la mise en page est détruite.

Trois décisions verrouillées par des tests :

- **les valeurs inconnues restent en dernier dans les deux sens** — un `null` trié comme valeur
  minimale ferait passer « jamais entendu » pour « le plus récent » ;
- **comparaison insensible à la casse et aux accents** : en français, filtrer « elysee » doit
  trouver « Élysée », et `<` sur des chaînes place les lettres accentuées après `z` ;
- **le tri porte sur la valeur, le filtre sur le texte affiché** : une date se trie
  chronologiquement mais se filtre comme elle est lue ; un booléen se filtre en tapant « oui ».

Filtres de colonne et recherche globale se **cumulent** (ET). Le clic sur un en-tête fait
croissant → décroissant → ordre du serveur, qui a souvent un sens.

**Correction de puissance** (06/11/2026) : la puissance d'émission vient désormais d'une lecture de
configuration à distance (§ 9.5.2) et alimente `ConfigurationNoeudMeshtastic`. L'écart de SNR est
alors corrigé de la différence de puissance, qui est exactement ce que l'équation dit :
`SNR(b entend a) − SNR(a entend b) = (Ptx a − Ptx b) + (bruit a − bruit b)`. Trois règles :

- la correction n'est appliquée que si la puissance est connue **des deux côtés** — une
  demi-correction serait pire que pas de correction ;
- le résultat porte `puissance_connue` **globalement, par relais sourd et par mesure** : une
  conclusion corrigée et une conclusion non corrigée ne valent pas la même chose, et l'interface
  doit les distinguer ;
- `tx_power = 0` ne veut **pas** dire 0 dBm : le firmware applique alors le maximum autorisé pour
  la région, c'est donc une puissance inconnue, traitée comme absente. La confondre avec 0 dBm
  inventerait un écart de 20 dB qui n'existe pas.

Tant qu'aucun nœud n'a été interrogé, la correction reste nulle et la détection de relais sourd
plus bruyante que la sienne : un nœud qui émet plus fort que ses voisins peut passer pour sourd.
La métrique `assista_mesh_noeuds_puissance_connue` dit où on en est.

Côté pont (`meshtastic-bridge/bridge.py`) : une liaison `RF` n'est enregistrée que si la passerelle
a entendu l'émetteur **directement** (`hop_start == hop_limit`). `rx_snr` est mesuré sur le dernier
saut : sur un paquet relayé il ne dit rien de la liaison d'origine, et l'enregistrer fabriquerait
une liaison directe inexistante. L'observation est faite **avant** toute tentative de
déchiffrement, ce qui cartographie aussi les canaux dont on n'a pas la clé.

### 9.5.2 Administration à distance des nœuds Meshtastic

`/admin/meshtastic-administration`. Modèle `TacheAdminMeshtastic`, exécution dans
`meshtastic-bridge/admin_meshtastic.py`, API `/api/taches-admin-meshtastic/`.

Lire ou modifier la configuration d'un nœud **par la radio** (portnum `ADMIN_APP`, protobuf
`AdminMessage`). Opérations : lire la configuration LoRa (puissance, région, preset, sauts), lire
firmware et modèle, lire la configuration de l'appareil, lire le nom, définir la puissance
d'émission, redémarrer.

**Ce qui conditionne tout, lu dans le firmware** (`AdminModule::handleReceivedProtobuf`, le
06/11/2026 ; la documentation Meshtastic ne le dit pas) : un message d'administration venant d'un
autre nœud n'est accepté que dans deux cas.

1. Il est **chiffré par clé publique** et la clé publique de l'émetteur figure dans l'une des
   **trois** fentes `config.security.admin_key` du nœud cible (comparaison sur 32 octets). Sinon :
   `ADMIN_PUBLIC_KEY_UNAUTHORIZED`.
2. Il arrive sur un **canal nommé « admin »** avec `admin_channel_enabled`, sans aucune
   vérification de clé. **Cette voie n'est jamais utilisée ici** : elle donnerait l'administration
   de tous les nœuds à quiconque possède la PSK de ce canal, qui est partagée par construction.
   D'où `channelIndex=0` forcé dans le pont, au lieu du `_getAdminChannelIndex()` de la lib
   officielle — qui basculerait sur cette voie faible dès qu'un canal « admin » existe.

Conséquence pratique : **administrer un nœud suppose d'avoir posé la clé publique de l'appareil
passerelle dans son `security.admin_key`**, une fois, avec l'application Meshtastic officielle, en
le tenant en main. Ce n'est pas une lacune du code : c'est la seule chose qui empêche n'importe qui
de reconfigurer vos relais par radio. La clé à recopier est affichée en haut de la page
(`CompagnonMeshtastic.cle_publique_appareil_hex`, rapportée par le pont à chaque connexion). Elle
n'a rien à voir avec `x25519_public_key_hex`, qui est l'identité **logicielle** du mode MQTT : le
firmware compare la clé de l'émetteur **radio**, c'est-à-dire l'appareil.

**Seule exception, et point de départ conseillé** : la passerelle elle-même. Le firmware traite le
message comme venant du téléphone (`mp.from == 0`) et n'exige ni clé d'administration ni clé de
session. C'est par là qu'il faut commencer pour vérifier que la chaîne fonctionne.

**Clé de session** : les lectures en sont dispensées (`messageIsRequest`), les écritures l'exigent
(`checkPassKey`). C'est un jeton de 8 octets qu'un nœud glisse dans toute réponse de lecture,
valable 300 s et **renouvelé dès qu'une réponse est construite plus de 150 s après la précédente**.
Le pont construit donc son message d'écriture (ce qui, pour une puissance, relit la configuration
et rapporte une clé au passage), puis écrit ; sur `ADMIN_BAD_SESSION_KEY` il oublie la clé, relit
et réessaie **une** fois. Le jeton n'est pas lié au demandeur : il vaut pour qui le détient.

**Publication JSON du MQTT** (demande du 07/11/2026 : « le MQTT de La Réunion doit avoir JSON
activé »). Deux opérations : `LIRE_CONFIG_MQTT` et `DEFINIR_MQTT_JSON`. Le nœud publie alors, **en
plus** des trames chiffrées sur `<racine>/2/e/#`, une version **décodée en clair** sur
`<racine>/2/json/#`. Quatre points à connaître :

- **Sans effet sur ce pont**, qui ne s'abonne qu'à `<racine>/2/e/#` (`bridge.py`) : le JSON ne lui
  arrive pas et ne peut donc pas perturber son décodage protobuf. Il sert aux outils tiers du site
  (Node-RED, Home Assistant, un tableau de bord local).
- **La liste de droits du satellite l'autorise déjà** : `satellite/mosquitto-config/acl` donne
  `readwrite msh/EU_868/#`, ce qui couvre `2/json/#` comme `2/e/#`. Resserrer cette ligne sur
  `2/e/#` couperait la publication JSON **sans aucun message d'erreur**.
- **Le broker voit le texte en clair.** Acceptable sur un broker de site, authentifié et publié
  sur la seule IP du LAN ; à ne jamais activer vers un broker tiers. À noter avec la règle « rien
  en clair » : le broker du satellite a `persistence true`, donc un abonné durable hors ligne
  ferait écrire des messages en file — en clair — dans `/mosquitto/data`. Le pont n'ouvre pas de
  session durable (paho, `clean_session` par défaut), mais c'est à savoir avant d'ajouter un
  abonné.
- **`set_module_config.mqtt` remplace tout le bloc** côté firmware, exactement comme
  `set_config.lora` : l'opération relit la configuration et la renvoie entière avec le seul
  `json_enabled` modifié. N'envoyer que ce champ effacerait l'adresse du broker, son compte et son
  mot de passe — le nœud perdrait son uplink, et il faudrait aller le rebrancher en USB. Un test
  le verrouille. La lecture, elle, ne remonte **jamais** le mot de passe du broker, seulement le
  fait qu'il soit défini : la réponse d'une tâche est journalisée.

**Réglages de configuration** (09/11/2026) : `LIRE_REGLAGES` et `DEFINIR_REGLAGES` couvrent cinq
sections — appareil (rôle, mode de rediffusion, annonce d'identité), radio LoRa (région, preset,
nombre de sauts, puissance, émission, gain RX, remontée MQTT, **fréquence imposée, numéro de
canal, décalage de fréquence et rapport cyclique** — voir « Réglages sous contrainte
réglementaire » plus bas), position (diffusion, position fixe, GPS), module **Voisinage** et
module **Télémétrie**. `DEFINIR_NOM` renomme le nœud.

La liste blanche des champs, avec leurs types et bornes, vit dans `core/mesh_reglages.py` et est
**servie** à l'interface par `GET /api/taches-admin-meshtastic/reglages/` : les bornes sont des
contraintes du firmware, les recopier dans le frontend garantirait qu'elles divergent. Le serveur
revalide à la création, et le pont revalide les deux minima de temps d'antenne — un pont peut
tourner contre un Django plus ancien.

Trois choses à savoir, chacune verrouillée par un test :

- **Seuls les réglages explicitement cochés sont envoyés.** `set_config` et `set_module_config`
  remplacent **tout le bloc** côté firmware : le pont relit la section, applique les seuls champs
  demandés, et renvoie l'ensemble. Envoyer un champ non voulu l'écraserait — sur la section LoRa
  cela effacerait la région, et **un nœud sans région ne transmet plus du tout**. Même piège que
  pour la puissance et le JSON MQTT ; c'est le piège central de toute l'opération.
- **Le module Voisinage est ce qui rend le diagnostic des liaisons voyant.** Sans lui, un nœud ne
  dit jamais qui il entend, et l'analyse d'asymétrie (§ 9.5.1) ne voit que ce que les passerelles
  reçoivent — jamais ce que les relais entendent. Son intervalle est au minimum de **4 h** :
  limite du firmware, pas une préférence, un rapport de voisinage étant volumineux.
- **Les noms se mesurent en OCTETS** : 39 pour le nom long, **4** pour le nom court. Quatre
  lettres accentuées en font huit, un emoji en consomme quatre à lui seul. Compter les caractères
  laisserait le firmware tronquer en silence.

#### Réglages sous contrainte réglementaire

**Politique inversée le 09/11/2026, à la demande de l'exploitant.** `override_frequency`,
`channel_num`, `frequency_offset`, `override_duty_cycle`, les trente-quatre régions du firmware et
la puissance au-delà de 27 dBm étaient refusés par principe. Ils sont désormais **modifiables,
avec un avertissement adapté à la zone**. Son argument, et il est juste : *« 868 MHz n'est
peut-être pas la même plage en France et à La Réunion »*. Trancher à sa place l'empêchait de faire
ce que sa situation autorise.

Ce qui est verrouillé n'est donc plus l'interdiction, mais le fait que l'acte soit **délibéré et
traçable** : ces champs portent `reglementaire=True`, leur écriture exige
`confirmation_reglementaire: true`, et la confirmation est écrite **en clair et en tête** du
commentaire d'audit (`[CONFIRMATION REGLEMENTAIRE donnee par le demandeur]`) — enfouie dans le
dictionnaire de paramètres, elle serait introuvable le jour où la question est posée. Ce n'est pas
un garde-fou technique : rien n'empêche techniquement une valeur illégale. C'est une chaîne de
responsabilité, nominative et horodatée.

**L'avertissement dit la vérité du firmware avant d'invoquer la loi**, parce qu'un texte identique
partout n'est pas lu. Chaque région porte le sien, construit depuis `TABLE_REGIONS_FIRMWARE` —
les macros `RDEF` de `src/mesh/RadioInterface.cpp`, lues le 09/11/2026 ; la documentation publique
ne donne pas ces valeurs. Quatre constats non évidents en sont ressortis :

- **EU_868 chez Meshtastic, c'est 869,4-869,65 MHz, 27 dBm, rapport cyclique 10** — une tranche de
  250 kHz, pas toute la bande SRD. Avec 250 kHz de largeur de bande, elle ne contient qu'**un seul
  créneau**.
- **Le limiteur de rapport cyclique du firmware est déjà deux fois plus strict que la règle.**
  `AirTime::isTxAllowedAirUtil()` s'arrête à la **moitié** du rapport cyclique de la région
  (`polite_duty_cycle_percent = 50`), soit **5 % effectifs** en EU_868, mesurés sur une fenêtre
  glissante d'une heure en soixante paniers d'une minute. Cocher `override_duty_cycle` ne « revient
  pas à la limite légale » : cela **supprime toute limite côté appareil**.
- **Le plafond de puissance n'est pas une garantie.** `applyModemConfig()` et `limitPower()` ne
  ramènent la puissance au plafond de la région que si le propriétaire n'est **pas** marqué
  « licencié » (`devicestate.owner.is_licensed`). Annoncer un garde-fou qui n'en est pas un serait
  pire que de ne rien annoncer.
- **Sept régions du protobuf n'ont aucune entrée dans la table du firmware** (`EU_866`, `EU_874`,
  `EU_917`, `EU_N_868`, `ITU1_2M`, `ITU2_2M`, `ITU3_2M`) : les poser peut laisser le nœud **muet**,
  et il faudra l'appareil en main. Les trois `ITU*_2M` sont de surcroît des bandes du **service
  amateur** — licence obligatoire, et le service amateur interdit le trafic pour le compte de
  tiers, donc l'usage opérationnel.

Le cadre français, lui, est rappelé sans être inventé : vérifié le 09/11/2026, le TNRBF de l'ANFR
s'applique en outre-mer **« sous réserve de dispositions particulières »**, regroupées dans son
chapitre 7. Aucune condition propre à La Réunion pour 863-870 MHz n'a été trouvée dans cette
recherche — ce qui ne veut pas dire qu'il n'y en a pas, mais qu'il faut la vérifier au chapitre 7
et dans la table SRD de l'ANFR, à défaut auprès du délégué régional. Le texte est servi une seule
fois par le catalogue (`avertissement_france`) ; le recopier dans le frontend garantirait qu'il
divergerait.

Deux plafonds de puissance, une seule règle : jusqu'à `PUISSANCE_MAX_DBM` (27 dBm, 500 mW) la
demande passe seule ; au-delà et jusqu'à `PUISSANCE_MAX_ABSOLUE_DBM` (36 dBm, plafond de la région
la plus permissive du firmware) elle exige la confirmation. Le pont, lui, borne à 36 dBm sans
rejuger la conformité : **il ne sait pas qui demande**, il ne peut donc pas porter cette règle.

**Ce qui reste non proposé, et pourquoi** :

- `bandwidth`, `spread_factor`, `coding_rate` (réglages radio manuels, actifs seulement avec
  `use_preset=False`). Refus de **deviner**, pas refus de principe : vérifié le 09/11/2026 dans
  `applyModemConfig()`, `bandwidth` ne stocke pas des kHz mais un **code** converti par
  `bwCodeToKHz()`, dont la table est dans un fichier non lu ; et dans la branche sans preset,
  `spread_factor` et `coding_rate` sont recopiés **sans aucun contrôle de bornes**. Une valeur
  fausse ne rend pas le nœud illégal, elle le rend invisible pour tout le réseau — et personne ne
  saura pourquoi. À exposer le jour où la table des codes aura été lue.
- `packet_signature_policy` (authentification des paquets, à traiter avec le propriétaire du
  réseau), la quasi-totalité du module Télémétrie (capteurs d'environnement, qualité d'air,
  santé : rien n'en est utilisé ici, et trente champs inutiles n'ajoutent que de la surface
  d'erreur), les GPIO de la section position (une mauvaise broche rend le GPS muet et seul
  quelqu'un qui a l'appareil en main peut corriger).
- `factory_reset`, `nodedb_reset`, `shutdown` et `set_channel`. Un répéteur est souvent sur un
  point haut : une extinction ou une réinitialisation à distance se paie d'un déplacement.
  `set_channel` demanderait en plus de transporter une PSK de canal jusqu'à l'appareil, ce que ce
  chemin ne fait pas.

À noter que `tx_enabled` n'est pas réglementé mais porte quand même un avertissement : le mettre à
faux coupe le seul chemin par lequel on pourrait rallumer le nœud. C'est le réglage le plus
irréversible de la page, et il n'a rien d'illégal.

**Transport** : seules les passerelles **TCP ou série** administrent, parce que c'est le firmware
de l'appareil qui chiffre le message. L'API refuse d'emblée une tâche posée sur un companion MQTT,
avec la raison — plutôt que de la laisser échouer silencieusement 30 s plus tard.

**Droits** (révisés le 10/11/2026, § 9.5.5) : les lectures sont ouvertes à qui a un accès radio
(acteur institutionnel ou opérateur) — relever une puissance n'est pas un acte matériel, et c'est
la seule façon pour un porteur de savoir ce que son nœud fait. Les **écritures exigent la zone
PROD et le droit sur le nœud visé** : son propre nœud pour un opérateur, n'importe lequel pour un
administrateur, **la passerelle pour lui seul**. Le rôle administrateur reste pris au sens réel —
un `demo_role` prêté pour une démonstration ne reconfigure pas un relais, et une tâche DEMO
n'aurait aucun exécutant. Pas de `PATCH` ni de `DELETE` sur la file : le pont rapporte par une
action dédiée qui décide seule du statut, sinon on pourrait maquiller une opération faite sur un
relais.

**Réessais** : le compteur s'incrémente à la **prise**, pas au rapport, et une tâche laissée
`EN_COURS` plus de 300 s est rendue à la file — un pont qui meurt en pleine opération ne doit ni la
bloquer pour toujours, ni pouvoir la reprendre sans fin. Trois tentatives, puis `ECHEC` avec son
dernier message, jamais supprimée. Alerte `MeshTachesAdminEnEchec`, et trois panneaux dans
l'onglet « Réseau radio » : opérations en échec, nœuds à puissance connue, file par état. Le
second est celui à regarder : tant qu'il est bas, le diagnostic des liaisons (§ 9.5.1) reste non
corrigé.

**Chiffrement au repos** : `TacheAdminMeshtastic.reponse` est chiffrée — une configuration lue peut
contenir la PSK WiFi de l'appareil (`config.network`) ou des clés de canal.
`ConfigurationNoeudMeshtastic` ne l'est pas : ce sont des caractéristiques radio, aucune donnée
personnelle, et `puissance_emission_dbm` doit rester comparable en SQL pour l'analyse (§ 9.5.1).
Un nom de nœud lu par `LIRE_PROPRIETAIRE` reste dans la réponse chiffrée et n'alimente aucune table
en clair.

**Tests du pont** : `meshtastic-bridge/test_admin_meshtastic.py`, en `unittest` (l'image du pont
n'embarque pas pytest). À lancer dans l'image du pont :

```
docker run --rm -v "$PWD/meshtastic-bridge":/src -w /src \
  --entrypoint python assista-crise-meshtastic-bridge:prod -m unittest test_admin_meshtastic
```

#### Trois défauts d'ingestion trouvés dans les journaux du pont (10/11/2026)

Relever les journaux du pont en service a montré **1 348 paquets MQTT abandonnés**. Cinq
défauts, tous silencieux, et ce qu'ils coûtaient :

1. **`HasField("hop_start")` sur un scalaire proto3** (1 201 fois). `hop_start` n'a pas de
   présence (vérifié sur la lib déployée :
   `MeshPacket.DESCRIPTOR.fields_by_name['hop_start'].has_presence is False`), donc `HasField`
   lève `ValueError`. Comme `_observer_liaison_rf` est appelée **en tête** de `on_message`,
   l'exception faisait abandonner le paquet **entier** : ni message, ni position, ni contact, ni
   liaison. Aucune liaison RF n'a donc jamais pu être enregistrée. Seuls les paquets dont la
   passerelle est l'émetteur lui-même y échappaient — ils sortent à la garde précédente — ce qui
   explique que le pont *paraissait* fonctionner. Le défaut absent valait déjà 0, qui signifie
   exactement « firmware qui ne renseigne pas ce champ » : la garde se réduit à `if not
   paquet.hop_start`.
2. **Message de canal en clair sur un canal inconnu** (14 fois). Il était journalisé avec
   `canal: null`, que l'API refuse — 400 avec trace. La branche *chiffrée* avait déjà la garde
   « canal qu'on ne connaît pas : rien à faire pour nous », la branche *en clair* ne l'avait pas.
3. **`DecodeError` « Wire format was corrupt »** (149 fois). Déchiffré avec notre PSK mais le
   résultat n'est pas un `Data` : quelqu'un d'autre utilise le même **nom** de canal avec une
   autre clé. C'est du bruit normal sur un broker partagé, pas une erreur de chez nous — une
   trace complète par paquet enterrait les vraies erreurs. Descendu en `debug`.

4. **Un abonnement REFUSÉ par le broker était totalement silencieux** : le pont n'avait aucun
   `on_subscribe`. Il journalisait « Connecté au broker », rapportait l'état `CONNECTE`, et plus
   rien n'arrivait jamais — indiscernable d'un réseau calme. Or un refus d'ACL est le cas
   **normal** sur un broker communautaire, dont le compte n'a souvent le droit de lire qu'un
   préfixe précis : le broker de La Réunion répond `SUBACK 128` à un abonnement sur `#`. Le pont
   lit désormais le SUBACK, nomme le topic refusé et sa raison, et rapporte le companion en
   `ERREUR` au lieu de le laisser affiché « connecté » (`echec_abonnement`, extraite du rappel
   pour être testable — les rappels paho sont des fonctions imbriquées).

`bridge.py` n'avait **aucun** test, et c'est ce qui a laissé passer le premier défaut :
`meshtastic-bridge/test_bridge.py` en ajoute seize, qui construisent de **vrais**
messages protobuf et de vrais codes de retour paho. Un faux objet avec un `HasField` complaisant aurait laissé passer exactement ce
défaut-là.

5. **Un companion connecté, abonné et muet restait indiscernable d'un réseau calme.** Un
   contact exige de savoir déchiffrer ; une liaison exige que le paquet ait été relayé par une
   passerelle *autre* que son émetteur. Un réseau réel mais fermé à nos clés et un réseau vide
   produisaient donc les mêmes journaux : rien. `CompteursReception` +
   `boucle_statistiques_reception` publient une ligne par fenêtre de dix minutes, **y compris à
   zéro** — et c'est le zéro qui est l'information, journalisé en avertissement :
   `[<nom>] AUCUN paquet reçu en 10 min sur <topic>`. Sinon : combien reçus, combien sur un
   canal inconnu, combien indéchiffrables.

Le topic d'abonnement est désormais journalisé à la connexion (`<racine>/2/e/#`) : c'est la
seule chose qui permette de vérifier le paramétrage d'une passerelle sans lire la base — une
racine fausse donne une connexion parfaitement réussie et zéro paquet, indiscernable d'un réseau
calme.

#### Paramètres du réseau citoyen de La Réunion (relevés le 10/11/2026)

Source : <https://www.meteor-oi.re/index.php/projets/reseau-lora-citoyen-mesh-la-reunion/utiliser-le-reseau/>.
Recopiés ici parce qu'ils conditionnent le paramétrage d'un `CompagnonMeshtastic` et qu'une
valeur fausse donne un silence indiscernable d'un réseau calme.

| | Valeur |
|---|---|
| Broker | `mqtt-mt.meteor-oi.re`, sans TLS |
| **Racine de topic** | **`msh/EU_868`** (donc abonnement `msh/EU_868/2/e/#`) |
| Canaux | 0 `Fr_Balise`, 1 `Fr_EMCOM`, 2 `Fr_BlaBla` |
| Relayés vers MQTT | `Fr_Balise` et `Fr_EMCOM` seulement — `Fr_BlaBla` a uplink **et** downlink désactivés |
| LoRa | EU_868, preset **LongModerate** (la page écrit « ne pas mettre LongFast »), fréquence forcée **869,4625 MHz**, slot 1, 27 dBm, `hop_limit` 7 à titre temporaire |
| Rôle | CLIENT, réémission LOCAL_ONLY |
| Sortie JSON | demandée ; « sans effet pour les puces nRF52 (T114) » |
| Compte | `lora974-P<numéro>`, envoyé par courriel ; identifiants supplémentaires par MeshForge (« devenir passerelle MQTT ») |

Deux conséquences pour ce projet :

- **les PSK des canaux ne sont pas publiées** : elles viennent du QR code officiel de Gaulix.
  Sans elles, le pont reçoit les paquets sans pouvoir les décoder — mais enregistre quand même
  les **liaisons RF**, qui s'observent sur l'enveloppe, avant tout déchiffrement. C'est
  précisément ce que le défaut `hop_start` empêchait ;
- `Fr_BlaBla` porte le même nom sur Gaulix et à La Réunion (canaux français communs, même QR
  code). Le nom d'un canal ne permet donc **pas** d'attribuer un message à un broker ; ce qui
  les distingue ici est que La Réunion n'en fait pas d'uplink. D'où la journalisation du nom du
  companion sur chaque message.

La fréquence recommandée (869,4625 MHz) tombe dans la tranche `EU_868` du firmware
(869,4-869,65 MHz, § 9.5.2) et la puissance recommandée (27 dBm) est exactement le plafond de
cette région. Ce n'est pas une source réglementaire — c'est une page communautaire — mais c'est
un indice de plus que la bande utilisée outre-mer est la même qu'en métropole, question laissée
ouverte faute de disposition particulière trouvée dans le TNRBF.

#### Publication JSON du MQTT : ce que ça fait, et ce que ça ne fait pas

`DEFINIR_MQTT_JSON` fait publier au nœud, **en plus** des trames chiffrées sur `<racine>/2/e/#`,
une version décodée en clair sur `<racine>/2/json/#`. Deux conséquences :

- **ce pont ne s'en sert pas** : il ne s'abonne qu'à `2/e/#` et décode le protobuf lui-même.
  Activer le JSON ne change donc rien pour Assista-Crise ; c'est utile aux outils tiers
  (Node-RED, Home Assistant, un tableau de bord local) ;
- **le broker voit le texte en clair.** Acceptable sur un broker de site authentifié et publié
  sur la seule IP du LAN ; à éviter sur un broker tiers.

C'est un réglage **du nœud**, poussé par la radio — pas un champ de la déclaration d'une
passerelle, et c'est pourquoi il n'apparaît pas dans ce formulaire.

#### MeshCore : l'administration est à portée, et l'analyse a une référence

Relevé le 10/11/2026, et il corrige ce que ce document disait avant.

**L'administration à distance MeshCore n'est pas un protocole à reverse-engineerer.** La
bibliothèque `meshcore` que le pont utilise déjà expose 104 méthodes, dont `send_login`,
`send_cmd`, `send_statusreq`, `req_status`, `req_telemetry`, `req_neighbours`, `req_regions`,
`req_acl`, `reboot`, `send_advert`, `send_trace`, `send_path_discovery`.

Quatre constats lus dans le firmware (`meshcore-dev/MeshCore`), pas dans de la documentation :

1. **Le firmware interdit lui-même à distance** (garde `sender_timestamp == 0`,
   `src/helpers/CommonCLI.cpp`) : `erase` (l. 280), **`set freq`** (l. 607, donc le changement de
   fréquence *permanent*), `set prv.key` (l. 711, « from serial command line only »), et
   `log`/`stats-*` (l. 472-479). Le scénario qui a dicté toute notre prudence côté Meshtastic —
   un nœud rendu muet et injoignable — est donc **déjà fermé**.
2. **`tempradio <freq> <bw> <sf> <cr> <timeout_minutes>`** (l. 252-266) applique des paramètres
   radio **temporairement**, avec un délai obligatoire, bornes vérifiées par le firmware
   (freq 150-2500 MHz, bw 7-500 kHz, sf 5-12, cr 5-8). C'est l'essai radio qui se rattrape tout
   seul, et c'est ce qui manquait sur Meshtastic : toute modification radio doit passer par là
   d'abord.
3. **Deux niveaux d'authentification** (`examples/simple_repeater/MyMesh.cpp:92-104`) : mot de
   passe vide → vérification de l'**ACL** ; sinon comparaison au mot de passe administrateur
   puis invité. Voir § 9.5.6 pour ce que ça donne côté réclamation.
4. **La commande `password` réaffiche le nouveau mot de passe dans sa réponse** (l. 272,
   commentaire du firmware : « echo back just to let admin know for sure!! »). La réponse d'une
   tâche doit donc être chiffrée au repos, comme `TacheAdminMeshtastic.reponse`.

**À exclure de la liste blanche**, pour les mêmes raisons que `factory_reset` et `set_channel`
côté Meshtastic : `poweroff`, `shutdown`, `start ota` (un déplacement), `set prv.key` /
`set public.key` (changent l'identité du nœud), `password` / `set guest.password` (transportent
un secret et le réaffichent).

**Pour l'analyse : CoreScope** (<https://github.com/Kpa-clawbot/CoreScope>, GPL-3.0, compatible
avec notre AGPL-3.0 comme `carte-live-meshtastic`). Même décision : on ne le déploie pas, on
porte ses algorithmes. Ce qu'il a et qu'on ne trouve pas ailleurs : un décodeur de trames
MeshCore complet (`cmd/ingestor/decoder.go`, 1 237 lignes, avec ses références au firmware), la
validation de signature Ed25519 des adverts, et surtout le **modèle de confiance des préfixes de
hash** — un saut de chemin MeshCore est un hash tronqué de clé publique
(`hash_size = (pathByte>>6)+1`, souvent **1 octet, soit 256 valeurs**), donc les collisions sont
inévitables au-delà d'une vingtaine de nœuds. C'est l'équivalent MeshCore de notre garde
`hop_start == hop_limit` : ce qui décide si une liaison affichée est réelle.

Son API de lecture est ouverte (~45 endpoints, la clé ne garde que l'administratif), et
**`POST /api/decode`** accepte une trame brute : c'est un oracle de référence pour valider le
portage du décodeur, sans toucher à aucune donnée tierce.

Si un import depuis une instance publique est envisagé : **répéteurs et rooms seulement**. Un
companion est l'appareil personnel de quelqu'un et sa position est souvent son domicile — c'est
le même filtrage que la carte applique déjà à `ContactMeshCore`, pour la même raison. La
convention `🚫` par laquelle un opérateur demande à ne pas être affiché doit être honorée, et
les données appartiennent à l'exploitant de l'instance, pas à la licence du code.

#### La file d'administration MeshCore

`TacheAdminMeshCore`, API `/api/taches-admin-meshcore/`, exécution dans
`meshcore-bridge/admin_meshcore.py`. Jumelle de la file Meshtastic, et **volontairement
identique dans sa mécanique** : prise avec verrou, réessai compté à la prise, pas de `PATCH` ni
de `DELETE`, réponse chiffrée au repos. Deux mécaniques différentes pour le même besoin ne
feraient que diverger.

| Type | Ce que le pont appelle | Écriture |
|---|---|---|
| `VERIFIER_ACCES` | `send_login_sync` (mot de passe) ou `req_status_sync` (ACL) | — c'est la preuve |
| `LIRE_STATUT` / `LIRE_VOISINS` / `LIRE_REGIONS` / `LIRE_TELEMETRIE` | `req_*_sync` | non |
| `RADIO_TEMPORAIRE` | `send_cmd` → `tempradio f bw sf cr minutes` | oui |
| `DEFINIR_REGLAGE` | `send_cmd` → `set <clé> <valeur>` | oui |
| `ANNONCER` / `REDEMARRER` | `send_cmd` → `advert` / `reboot` | oui |

**Une écriture exige une preuve de contrôle faite** (§ 9.5.6) et la zone PROD.
`VERIFIER_ACCES` est l'exception évidente — c'est elle qui fait la preuve — et reste réservée à
qui peut modifier le rattachement. Les lectures sont ouvertes à tout accès radio : relever un
statut ou une liste de voisins n'est pas un acte matériel, et `LIRE_VOISINS` est l'entrée de
`analyse_liaisons.py` pour MeshCore.

**Ce qui est refusé, et pourquoi** : `prv.key` et `public.key` (changent l'identité du nœud),
`password` et `guest.password` (transportent un secret que le firmware **réaffiche dans sa
réponse**). Le motif du refus est renvoyé en clair — un refus sans motif se contourne par une
autre voie au lieu d'être compris. `poweroff`, `shutdown` et `start ota` sont simplement absents
du catalogue : un répéteur est souvent sur un point haut.

**`tempradio` est la voie recommandée pour tout ce qui touche la radio.** Son délai de retour
est obligatoire et strictement positif, vérifié **deux fois** — par l'API et par le pont. Ce
n'est pas de la redondance inutile : c'est la garde qui fait qu'un essai raté se rattrape tout
seul, et elle ne doit dépendre d'aucun appelant. Les bornes recopiées dans le serializer sont
celles du firmware (`CommonCLI.cpp` l. 261), citées pour qu'on sache d'où elles viennent ; elles
évitent un aller-retour radio de trois minutes pour se faire répondre « Error, invalid params ».

**Le mot de passe du répéteur voyage avec la tâche**, servi par `prendre` au seul pont qui vient
de la verrouiller pour son companion. Le laisser le chercher lui-même l'obligerait à lire tous
les rattachements, donc ceux des autres institutions.

**La session est rouverte à chaque opération**, jamais mémorisée : une session MeshCore expire,
le pont peut redémarrer entre deux tâches, et une session qu'on croit ouverte produit un échec
silencieux bien plus coûteux qu'une connexion de trop.

#### Le voisinage MeshCore, et ce qu'une absence prouve

`LIRE_VOISINS` est l'opération la plus utile de la file : elle donne la carte des liaisons sans
attendre le décodeur de trames. Son résultat est rangé par `_enregistrer_voisinage` en
`LiaisonMeshCore` (liaisons orientées) et `ReleveVoisinageMeshCore` (un relevé par répéteur,
remplacé à chaque lecture).

La forme de la réponse vient du **parseur de la bibliothèque** (`meshcore/reader.py`, branche
`BinaryReqType.NEIGHBOURS`), et non d'une supposition :

```
{neighbours_count, results_count, pubkey_prefix_length,
 neighbours: [{pubkey, secs_ago, snr}]}
```

Trois points qui comptent :

- **le sens.** `neighbours` est ce que le répéteur ENTEND : il est donc le **récepteur** de
  chaque liaison, le voisin en est l'émetteur. L'inverser retournerait toutes les conclusions
  de l'analyse d'asymétrie ;
- **l'émetteur n'est connu que par un préfixe** de `pubkey_prefix_length` octets, 4 par défaut —
  pas les 32 de la clé. On le stocke tel quel **avec sa longueur** : deux préfixes de longueurs
  différentes ne se comparent pas, et fabriquer une clé complète à partir d'un préfixe
  fabriquerait une liaison qui n'existe pas. C'est le même problème que celui que CoreScope
  traite par désambiguïsation (§ ci-dessus), rencontré ici avant même le décodeur ;
- **la complétude est CONNUE.** `neighbours_count` est le total chez le répéteur,
  `results_count` ce que contient la page. C'est une différence nette avec Meshtastic, dont le
  rapport de voisinage est plafonné à 10 **sans le dire** — là-bas une absence ne prouve jamais
  rien, ici elle peut prouver quelque chose quand `ReleveVoisinageMeshCore.complet` est vrai.

Le meilleur SNR observé est retenu, comme côté Meshtastic : une mesure basse peut venir d'une
interférence passagère, la meilleure dit ce dont la liaison est capable.

Une réponse d'une forme inattendue n'enregistre **rien** plutôt que d'enregistrer au mieux :
une liaison fausse envoie quelqu'un sur un point haut.

#### L'écran

`/admin/meshcore-administration`, dans le sous-cadre MeshCore du menu. Trois gestes dans
l'ordre où ils se font : réclamer, prouver, opérer. La page refuse une écriture **avant le
clic** quand la preuve n'est pas faite, plutôt que de la laisser découvrir par un 403 trois
minutes plus tard, et chaque opération affiche ce qu'elle coûte en cas d'erreur.

**Tests** : `backend/core/tests/mesh/test_acces_radio.py` (111),
`meshcore-bridge/test_admin_meshcore.py` (18, avec un faux companion) et
`meshcore-administration.component.spec.ts` (10).

#### Deux protocoles, un seul raisonnement d'analyse

`analyse_liaisons.py` portait six précautions écrites pour Meshtastic. Les dupliquer pour
MeshCore aurait garanti qu'une des deux copies finisse par en perdre une : le module a donc été
**extrait** (10/11/2026). Le cœur (`_analyser`) ne connaît que des identités opaques ; ce qui
dépend du protocole vit dans une *source* (`_SourceMeshtastic`, `_SourceMeshCore`). Les 25 tests
d'origine passent sans modification — c'est ce qui prouve que l'extraction est fidèle.

Deux choses seulement diffèrent entre les protocoles, et la source les porte :

| | Meshtastic | MeshCore |
|---|---|---|
| Identité | entier 32 bits (`node_num`) | clé publique Ed25519 (`pubkey`) |
| Une absence prouve-t-elle quelque chose ? | **jamais au-delà de 10 voisins** : le rapport est plafonné sans le dire | **oui quand le relevé est complet** (`neighbours_count` annoncé) |

Le second point est un gain net pour MeshCore : là où l'analyse Meshtastic doit s'abstenir dès
qu'un nœud déclare 10 voisins, elle peut conclure ici sur un décompte.

`analyser_meshcore()` rend en plus `liaisons_ecartees` : un diagnostic calculé sur une partie
des liaisons seulement doit le dire. Les liaisons dont le préfixe d'émetteur est **ambigu** ou
**inconnu** sont écartées — conclure « à sens unique » sans savoir de qui l'on parle reviendrait
à inventer une liaison, et une liaison fausse envoie quelqu'un sur un point haut. Endpoint :
`GET /api/contacts-meshcore/analyse-liaisons/`.

#### Décodage des trames MeshCore

`core/decodeur_meshcore.py`, porté de CoreScope (commit `1577b57d`, 09/11/2026). Format :

```
octet 0      en-tête : bits 1-0 route, 5-2 charge, 7-6 version
[4 octets]   codes de transport, sur les routes TRANSPORT_* seulement
1 octet      chemin : bits 7-6 (taille de hash − 1), bits 5-0 nombre de sauts
n octets     les sauts
reste        la charge (184 octets au plus)
```

Faits vérifiés dans le firmware, pas dans une documentation :

- **un « hash » de chemin est un PRÉFIXE de la clé publique**, pas un condensé. Le firmware
  l'écrit : « hash is just prefix of pub_key » (`src/Identity.h:20`). Chercher un SHA-256
  n'aurait rien donné ;
- **`taille_hash == 4` est réservée** et refusée quel que soit le nombre de sauts
  (`src/Packet.cpp:13-18`) : un `0xC0` sur le fil est par définition malformé ;
- bornes `MAX_PATH_SIZE = 64` et `MAX_PACKET_PAYLOAD = 184` (`src/MeshCore.h:19,21`) ;
- un advert est `clé (32) + horodatage (4 LE) + signature Ed25519 (64) + données`, et la
  signature porte sur `clé + horodatage + données`. Les positions sont des entiers **signés**
  au millionième de degré — les lire en non signé placerait tout l'hémisphère sud en Sibérie ;
- un canal se déchiffre avec `SHA-256(nom)[:16]`, un MAC HMAC-SHA256 **tronqué à 2 octets** sur
  un secret de `clé + 16 octets nuls`, en **AES-128-ECB**. Rater l'un des trois fait échouer en
  silence.

Le décodeur **lève** plutôt que de décoder au mieux : une trame à moitié comprise produit des
liaisons et des positions fausses. Les charges exotiques (MULTIPART imbriqué, CONTROL/DISCOVER,
RAW_CUSTOM) sont reconnues par leur type et rendues brutes — CoreScope y traite des cas repérés
au fil de ses propres incidents, que nous ne pouvons pas rejouer.

#### Résoudre un saut vers un nœud, et savoir quand on ne peut pas

`core/resolution_prefixes.py`, porté de `docs/HASH-PREFIX-DISAMBIGUATION.md` de CoreScope.

Un préfixe d'un octet n'a que **256 valeurs** : au-delà d'une vingtaine de nœuds les collisions
sont certaines, et CoreScope a mesuré sur un réseau réel que **56 % des sauts observés** portent
un préfixe d'un seul octet. Un saut mal résolu ne donne pas une donnée floue : il donne un trait
faux sur la carte.

Trois certitudes, qui ne valent pas la même chose :

- **`unique`** — un seul nœud connu porte ce préfixe. C'est une résolution ;
- **`deduit`** — plusieurs candidats, départagés par la géographie en deux passes (avant, puis
  arrière pour ce qui reste — sans la seconde, un chemin dont le premier saut est ambigu ne se
  résoudrait jamais). **C'est une hypothèse** : bonne pour tracer un itinéraire, jamais comme
  preuve de topologie ;
- **`ambigu` / `inconnu`** — on ne tranche pas.

Un saut à plus de 200 km de ses deux voisins résolus est marqué `invraisemblable` (distinct du
seuil de 120 km de `analyse_liaisons`, qui juge une portée RF et non la cohérence d'un
itinéraire). Seul `unique` alimente le diagnostic. Le seuil de confiance
(`MIN_OCTETS_HASH_DEFAUT = 1`) reprend leur défaut et leur raisonnement : exiger 2 d'emblée
ferait disparaître la moitié du graphe sans que rien ne l'explique à l'écran.

#### MeshCore n'a pas de MQTT, et ce que ça implique

Constaté sur du matériel réel le 10/11/2026, puis vérifié dans le firmware — cela **corrige** ce
que ce document envisageait (« ingestion MQTT MeshCore ») :

- **un companion n'a pas de CLI de configuration.** Le jeu `get`/`set` (`bridge.*`,
  `tempradio`, `role`…) vient de `src/helpers/CommonCLI.cpp`, inclus par les seuls firmwares
  d'infrastructure : `simple_repeater`, `simple_room_server`, `simple_sensor`. Le firmware
  companion n'en reprend que des structures (`examples/companion_radio/NodePrefs.h:126`,
  « COPIED from CommonCLI (for now) ») et répond `ERR_CODE_UNSUPPORTED_CMD`
  (`examples/companion_radio/MyMesh.cpp:135`) à tout `get`. **La file d'administration vise donc
  les répéteurs, et c'est le bon périmètre** ;
- **MeshCore n'a aucun module MQTT.** Pas d'équivalent du module MQTT de Meshtastic. Le plus
  proche, `bridge.*`, n'existe que sur le firmware répéteur et c'est un pont de **paquets**
  entre segments de maillage (`bridge.sendPacket`, « bridge needs WiFi radio »,
  `simple_repeater/MyMesh.cpp:1337`), pas un client MQTT ;
- **donc ce qui publie sur `meshcore/<iata>/<pubkey>/…` chez CoreScope n'est pas le firmware,
  c'est un *observateur*** : un logiciel attaché à un nœud, qui republie ce qu'il entend.
  Autrement dit **notre pont est déjà un observateur**. Rejoindre cet écosystème consisterait à
  publier, pas à ingérer — et c'est un choix d'exposition, pas une fonction manquante.

#### Ingestion des observateurs MeshCore

C'est la source de trames qui manquait au décodeur. Un **observateur** est un répéteur ou un
room server dont le firmware a reçu un client MQTT — pas MeshCore : vérifié, le firmware
officiel n'a aucun `mqtt`. Les binaires `heltec_v4_repeater_observer_mqtt` et
`heltec_v4_room_server_observer_mqtt` (v1.16) sont des forks du répéteur.

**Le contrat**, établi des deux côtés — gabarits de topic relevés dans les chaînes du binaire,
forme de la charge lue dans `cmd/ingestor/db.go:2546` de CoreScope :

```
meshcore/<iata>/<cle_observateur>/packets   {"raw": "<trame hex>", "SNR": .., "RSSI": ..,
                                             "origin": .., "timestamp": ..}
meshcore/<iata>/<cle_observateur>/raw       la trame brute
meshcore/<iata>/<cle_observateur>/status    {"battery_mv":.., "noise_floor":.., "last_snr":..,
                                             "recv":.., "flood_tx":.., "rx_air_secs":..}
meshcore/<iata>/<cle_observateur>/neighbors
```

Le champ `raw` ferme la boucle : c'est exactement l'entrée de `decodeur_meshcore.decoder_paquet`.

Seize clés de configuration côté firmware observateur : `mqtt.server`, `port`, `username`,
`password`, `iata`, `origin`, `owner`, `email`, `interval`, plus quatre interrupteurs par flux
(`mqtt.raw`, `mqtt.packets`, `mqtt.status`, `mqtt.tx`). Deux serveurs sont intégrés par défaut
(`mqtt.analyzer.eu`, `mqtt.analyzer.us`, authentification par jeton JWT) ; un broker privé se
déclare à la place.

**Chez nous** : `SourceObservateurMeshCore` (un broker par ligne, identifiants chiffrés, filtre
d'abonnement), `/api/sources-observateurs-meshcore/` (déclaration réservée à l'administrateur
réel — engager une connexion sortante permanente est un acte d'exploitation), et
`manage.py ingerer_observateurs_meshcore`, processus long qui s'abonne, décode et écrit.

Trois décisions :

- **une commande Django, pas une boucle du pont.** L'ingestion ne concerne pas notre companion :
  elle consomme un broker tiers et écrit des liaisons. Passer par le pont imposerait un
  aller-retour HTTP **par paquet** vers l'API — des centaines par minute sur un broker régional ;
- **une liaison n'est tirée que d'un ADVERT**, et seulement si sa **signature Ed25519 est
  valide**. Hors advert, l'en-tête MeshCore ne porte aucun expéditeur (il est dans la charge
  chiffrée) : en déduire une liaison supposerait de savoir qui a émis. Et un advert non signé
  peut porter la clé d'autrui, ce qui attribuerait la liaison au mauvais nœud. Gain au passage :
  l'émetteur d'un advert est une clé **complète**, donc ces liaisons échappent au problème
  d'ambiguïté des préfixes ;
- **l'horodatage de l'observateur n'est pas utilisé.** CoreScope l'a appris à ses frais (leur
  ticket #1370 : des observateurs à l'horloge fausse estampillaient 18 h 42 une réception réelle
  de 1 h 42). On garde l'heure d'ingestion.

Le filtre d'abonnement est validé à l'enregistrement (racine `meshcore/`, joker obligatoire) et
le SUBACK est lu : un abonnement refusé passe la source en `ERREUR` au lieu de la laisser
affichée « connectée ». Même garde que celle ajoutée au pont Meshtastic le même jour, pour la
même raison.

**Pas encore fait** : la comparaison systématique avec `POST /api/decode` d'une instance
CoreScope, qui servirait d'oracle sur de vraies trames.
`CommandeMeshCore` reste par ailleurs la file du companion LOCAL (`ADVERT`, `FLOOD_ADVERT`) :
elle ne pilote pas un relais distant, et ces deux files ne se recouvrent pas.

#### Cartographie du réseau MeshCore public

`manage.py importer_cartographie_meshcore --instance <url>` importe les répéteurs et room
servers d'une instance CoreScope (`GET /api/nodes`) dans `NoeudPublicMeshCore`. L'instance de
référence au 11/11/2026 est `meshstats.serveurperso.in` : 2436 répéteurs, 129 rooms,
707 companions, 5 capteurs.

Ce n'est pas notre réseau et nous ne l'administrons pas : c'est le **voisinage radio**, ce qui
existe autour d'une commune et sur quoi on peut compter — ou pas. Affiché sur
`/admin/carte-radio`, calque « Réseau public », chargé à la première activation.

Quatre décisions :

- **les companions ne sont pas importés** (`ROLES = ("repeater", "room")`). Un companion est
  l'appareil personnel de quelqu'un, et sa position est très souvent son domicile. L'instance
  les sert ; nous n'en republions aucun. Un test verrouille cette liste, parce que « avoir plus
  de points sur la carte » est une tentation permanente ;
- **un nom préfixé 🚫 est un refus d'affichage**, honoré de notre côté aussi. CoreScope les
  retire déjà de ses réponses ; on le refait, pour qu'une instance mal configurée ne nous fasse
  pas republier ce que son opérateur a demandé à cacher ;
- **les scores sont repris, pas recalculés.** `coverage_score`, `redundancy_score`,
  `bridge_score`, `usefulness_score` viennent d'un volume d'observations que nous n'avons pas.
  C'est de la couverture **constatée** : elle ne remplace pas le calcul de relief de
  `core/relief_radio.py`, qui répond à la question inverse (« jusqu'où porterait un site qu'on
  n'a pas encore installé ? ») ;
- **la taille de préfixe est importée et affichée.** Elle décide de ce qu'on peut conclure des
  chemins d'un nœud : à un octet — 308 nœuds sur les 1809 qui annoncent une taille, soit 17 % —
  un préfixe n'a que 256 valeurs et les sauts de ce nœud ne prouvent aucune topologie (voir
  `core/resolution_prefixes.py`). Une carte qui la cache laisse croire le contraire.

Deux pièges relevés en écrivant l'import :

- la pagination suit **`has_more`**, et non `total` : l'instance renvoie dans `total` la taille
  de la **page**. S'y fier aurait arrêté l'import à 200 nœuds, sans rien dire ;
- l'en-tête `User-Agent` est générique. C'est le service de quelqu'un d'autre : il n'a pas à
  savoir quelle commune regarde sa carte.

L'import est idempotent (`update_or_create` sur instance + clé + environnement) et ne supprime
rien : un nœud que l'instance ne sert plus garde sa dernière date vue. `--compter` dit ce qu'un
import contiendrait sans rien écrire. Le résumé servi par
`/api/noeuds-publics-meshcore/resume/` est affiché à côté de la carte, parce qu'une carte sans
sa provenance ni sa date se lit comme un fait.

### 9.5.3 Planification radio sur le relief

`core/relief_radio.py`, porté de `carte-live/src/relief.js` de `carte-live-meshtastic` (GPL-3.0,
avec l'autorisation de l'auteur). Page **`/admin/couverture-radio`**, API
`/api/couvertures-radio/` et `/api/calibrations-radio/`.

Deux outils de nature différente :

- **bilan de liaison** (`analyser-liaison`) : *est-ce que ça passe entre ces deux points ?*
  Synchrone — un profil de terrain au pas de 100 m, soit un ou deux lots d'altimétrie, quelques
  secondes. C'est l'outil du quotidien, celui qu'on consulte avant de monter sur un toit.
- **couverture d'un site** (`calculer`) : *jusqu'où porte ce site ?* Balayage radial, mis en file
  (Celery) parce qu'un site neuf demande quelques milliers d'interrogations d'altimétrie. Le site
  n'a pas besoin d'exister : on évalue un point candidat avant d'y installer quoi que ce soit.

**Le modèle** (constantes et formules reprises telles quelles) : terre équivalente `k = 4/3`
(sans quoi toute liaison de plus d'une quinzaine de kilomètres serait déclarée bloquée à tort),
affaiblissement en espace libre, plancher de bruit `-174 + 10·log10(BW) + 6`, seuil de
démodulation par facteur d'étalement, et diffraction par lame de couteau (UIT-R P.526).

Deux résultats contre-intuitifs, tous deux verrouillés par un test parce qu'ils *paraissent* être
des bogues :

1. **Un terrain parfaitement plat coûte déjà 4 à 6 dB.** À la rasance (`v = 0`) la perte de
   diffraction vaut 6 dB, pas zéro — c'est le résultat exact de la recommandation. Un modèle qui
   annoncerait 0 dB serait optimiste sur toutes les liaisons longues.
2. **L'obstacle déterminant n'est pas le plus haut.** `v = h·√(2D/(λ·d₁·d₂))` dépend autant de la
   *position* de l'obstacle que de sa hauteur : le rayon de Fresnel se resserre près des
   extrémités, donc à hauteur égale au-dessus de la visée, un relief modeste proche d'un nœud
   pénalise plus qu'une colline au milieu. Trier par hauteur — ou par angle de site, comme le mode
   rapide de son module — désigne parfois le mauvais obstacle, avec cette conséquence absurde :
   monter l'antenne pouvait faire *diminuer* la couverture calculée.

**La calibration est ce qui sépare une prévision d'une illustration.** Un bilan théorique se
trompe de 10 à 20 dB en milieu réel (végétation, bâti, antennes désadaptées). `calibrer()` compare
le modèle aux liaisons **réellement mesurées** (`LiaisonMeshtastic`, § 9.5.1) et retient la
**médiane** de l'écart — pas la moyenne, qu'une seule liaison aberrante suffirait à fausser.
Trois précautions reprises de son implémentation : fenêtre de distance 1-80 km, rejet des liaisons
confortables des deux côtés (le SNR d'un module LoRa plafonne vers +10 dB et n'apprend plus rien),
et minimum de cinq liaisons. Le résultat est borné à [4, 30] dB : au-delà, c'est autre chose qu'un
environnement (position fausse, antenne débranchée) et une correction aussi grosse masquerait le
vrai problème. Tant qu'aucune calibration n'a conclu, `calibre` reste faux et l'interface annonce
une **indication de relief, pas une prévision**.

**Ce qui n'est pas porté, et pourquoi.** Son module télécharge le modèle numérique de terrain IGN
RGE ALTI par dalles et le garde sur disque, ce qui lui permet 1080 rayons au pas de 250 m sur tout
un département, et au-dessus un plan de couverture départemental (`planDepartement`, `planBudget`,
`simuler`, `optimiserRelais`). Assista-Crise réutilise son client altimétrique existant — l'API
REST `data.geopf.fr` de `core/inondation.py`, avec sa limite de 2,5 requêtes/s, sa reprise sur 429
et son parallélisme — plutôt que de rapatrier des gigaoctets de dalles. Conséquence directe et
assumée : la couverture se calcule **par site** et non en raster départemental. C'est ce dont une
commune a besoin ; le plan départemental reste chez lui.

**Cache d'altitude** : `PointAltitude`, clé arrondie à 1e-4 degré (~11 m). Le relief ne change
pas, donc une ligne n'est jamais à rafraîchir, et c'est ce cache qui rend un **recalcul** quasi
gratuit là où la première passe prend une minute. Volontairement **non cloisonné PROD/DEMO** : le
relief est le même dans les deux zones, comme les grilles d'inondation.

**Deux détails d'honnêteté du rendu** :

- l'API rend des **points** et non un contour : une couverture radio est trouée (vallées masquées,
  crêtes qui portent loin), et un contour convexe déclarerait couvert tout ce qu'il englobe — c'est
  l'erreur qui envoie une équipe dans une zone d'ombre en croyant qu'elle a la radio ;
- `points_sans_altitude` est exposé : au-delà de 10 % de trous le calcul **échoue** plutôt que de
  rendre une couverture sous-estimée sans le dire, et en dessous l'interface affiche l'avertissement.

### 9.5.4 Deux cartes : la carte de crise et la carte radio

Jusqu'au 10/11/2026, `/admin/carte` portait six calques radio en plus des calques de crise. Ils
en sont partis, sauf un. Le découpage n'est pas esthétique, il suit la question posée :

| Carte | Question | Calques mesh |
|---|---|---|
| `/admin/carte` | *où en est la crise ?* | **seulement** les positions des intervenants en mission portant leur nœud personnel (`NoeudMeshUtilisateur`, `NoeudUtilisateurMeshtastic`, via `positions_en_mission`) |
| `/admin/carte-radio` | *dans quel état est le réseau radio ?* | passerelles, relais déclarés, répéteurs entendus, nœuds Meshtastic détectés, liaisons mesurées, couverture calculée |

Les positions des intervenants restent sur la carte de crise parce qu'elles appartiennent à la
**conduite d'opération** : on les lit à côté des demandes, des centres et des équipes, pas à
côté d'un bilan de liaison. Tout le reste appartient à l'**exploitation du réseau**.

Le panneau de calques de la carte de crise porte un lien explicite vers la carte radio. Sans
lui, les calques retirés auraient simplement eu l'air d'avoir disparu.

`CarteRadioComponent` reprend les cinq pièges de `MapComponent` (§ 6.3) : garde WebGL (sinon
l'exception du constructeur traverse `ngAfterViewInit` et c'est la **page** qui reste blanche),
`before` explicite pour que les traits de liaison passent **sous** les points, garde `getLayer()`
avant tout `before` ou changement de visibilité, couleurs lisibles **sur fond clair seulement**
(le fond ne suit pas le mode sombre), et chargement différé des deux calques coûteux (liaisons
mesurées, couverture). Les compteurs affichés par calque ne sont pas décoratifs : une carte vide
ne dit pas si elle est vide parce qu'il n'y a rien, ou parce que le chargement a échoué — les
erreurs de chargement sont donc affichées, calque par calque.

### 9.5.5 Qui a accès à la radio : le droit intermédiaire

`core/acces_radio.py`, modèle `DemandeAccesRadio`, page **`/admin/radio`**, API
`/api/demandes-acces-radio/`. Garde Angular `radioGuard`, visibilité de menu `radio`, champs
servis `acces_radio` et `niveau_acces_radio` (`UserSerializer`).

**Le problème corrigé.** Avant le 10/11/2026, les écrans radio étaient ouverts à tout acteur
institutionnel et toute écriture sur un nœud exigeait le rôle ADMINISTRATOR réel. Les deux
extrémités étaient fausses : une commune sans aucun matériel radio voyait huit pages qui ne
pouvaient rien lui dire, et le bénévole qui porte un nœud ne pouvait pas régler son propre
appareil.

**Trois niveaux** (`NiveauAccesRadio`), et ce qui les sépare est **qui subit l'erreur** :

| Niveau | Lecture du réseau, simulations | Écriture sur son matériel et celui de son institution (passerelle comprise) | Écriture sur le matériel d'autrui |
|---|---|---|---|
| `AUCUN` | non | non | non |
| `OPERATEUR` | oui | oui | non |
| `ADMINISTRATEUR` | oui | oui | oui |

**L'écriture suit la PROPRIÉTÉ du matériel, pas le grade** (`peut_administrer_noeud`, précisé le
10/11/2026 à la demande explicite de l'exploitant). Trois périmètres, un seul principe — on
répond du matériel dont on est responsable :

1. ses propres nœuds personnels ;
2. le matériel de son institution : les nœuds de ses membres, et **les passerelles qu'elle a
   déployées**. Une passerelle est de la responsabilité de l'institution qui est allée la poser
   et qui ira la rechercher si un réglage la rend muette ; faire dépendre son réglage d'un
   administrateur de plateforme n'ajoutait aucune sécurité — il ne sait pas où elle est ;
3. `ADMINISTRATEUR` écrit partout. C'est le **recours** : une institution qui a perdu la main
   sur son matériel, ou une passerelle sans institution renseignée, dont personne ne répond.

**`ADMINISTRATEUR` n'est jamais la réponse à « je veux administrer ma passerelle »** (garde-fou
posé le 10/11/2026 : *« l'administrateur d'une passerelle est admin de SA passerelle et de SES
nœuds »*). L'exploitant d'une passerelle en est administrateur **par le rattachement de ce
matériel à son institution**, au niveau opérateur — pas par un droit réseau. Trois mesures le
font tenir :

- l'action `instruire` **refuse** d'accorder `ADMINISTRATEUR` sans `confirmation_portee_reseau`,
  et le message de refus explique la bonne manœuvre (rattacher, puis `OPERATEUR`) ;
- l'interface propose **toujours `OPERATEUR` par défaut**, même sur une demande
  d'administration complète : pré-remplir le niveau demandé rendait possible d'accorder le
  réseau entier d'un seul clic ;
- le journal d'audit porte `[PORTEE RESEAU ENTIER]` en clair, pour qu'on puisse répondre un jour
  à « qui pouvait toucher au matériel d'autrui ? ».

Côté demandeur, choisir « administration complète » affiche que ce n'est probablement pas ce
qu'il lui faut.

`node_num_cible` vide désigne **la passerelle qui exécutera la tâche** : le droit se lit alors
sur `compagnon.institution`, et non sur un node_num. Sans companion, la réponse est non — une
écriture sur « la passerelle » sans savoir laquelle n'est pas vérifiable.

**Ce qui ouvre le droit**, dans l'ordre où `niveau_acces_radio` l'évalue :

1. rôle ADMINISTRATOR **réel** → `ADMINISTRATEUR` (pas le rôle effectif : un `demo_role` prêté
   le temps d'une démonstration ne donne pas la main sur du matériel qui émet) ;
2. une `DemandeAccesRadio` accordée au niveau `ADMINISTRATEUR` ;
3. **posséder un nœud personnel actif**, ou **appartenir à une institution qui exploite du
   matériel radio** — une passerelle active, ou le nœud d'un de ses membres → `OPERATEUR`.
   C'est le point important : le droit vient du matériel avant de venir d'une décision, et
   personne n'a à demander l'autorisation de régler son propre appareil. Le nœud compte autant
   que la passerelle : une commune dont trois agents portent un nœud *a* un réseau radio, même
   sans passerelle ;
4. sinon, le niveau accordé par une demande (`OPERATEUR`), ou `AUCUN`.

Le calcul ne porte que sur les données de la zone **PROD** : la démonstration ne contient aucun
matériel réel, et un nœud de démonstration qui ouvrirait le droit donnerait la main sur les
vrais appareils.

**Deux conséquences d'exploitation à connaître** :

- une passerelle dont le champ `institution` est **vide** n'ouvre aucun droit et n'appartient à
  personne au sens de ce module — « quelqu'un, quelque part, a une passerelle » n'est pas un
  titre à administrer un réseau. Renseigner l'institution des companions existants est donc ce
  qui donne à une collectivité la main sur son propre matériel, menu compris ; à défaut, seul
  l'administrateur de la plateforme peut la régler ;
- `canEnterAdminArea()` admet désormais `acces_radio`, sans quoi un porteur de nœud non
  institutionnel n'entrerait pas dans `/admin` du tout. Il n'y gagne rien d'autre : chaque
  autre page garde sa propre garde et le renvoie vers `/admin/acces-refuse`.

**Ce que l'erreur coûte**, et qui est la raison pour laquelle le périmètre est étroit : une
région ou un rapport cyclique faux rend un nœud muet, et **le nœud qui n'émet plus ne peut plus
recevoir l'ordre inverse** — il faut aller le chercher à la main, souvent sur un point haut.
C'est aussi pourquoi `mon-acces` rend un `perimetre_ecriture` **rédigé par le serveur** : la
règle est déjà difficile à tenir à un endroit, la recopier dans l'interface garantirait qu'elle
divergerait, et une interface qui promet une écriture refusée se découvre par un 403.

**La porte d'entrée.** « Accueil radio » est la seule entrée du cadre Radio en `visibilite:
'tous'`, et `/admin/radio` la seule route radio sans `radioGuard` : c'est elle qui dit ce qu'il
faut (un nœud, ou une passerelle), affiche **à quel titre** le droit est ouvert quand il l'est
— donc ce qu'on perdrait en désactivant son nœud — et porte le formulaire de demande.
`radioGuard` y renvoie au lieu de `/admin/acces-refuse` : « refusé » est exact et inutile, la
personne a besoin de savoir ce qui lui manque. Même raisonnement que « Habilitations registre »
(§ 5.11) : masquer la page supprimerait la porte d'entrée du dispositif.

**La demande et le droit sont une seule ligne**, parce que le droit EST la demande instruite.
Rien n'est supprimé : un droit retiré passe en `RETIREE` avec son motif, de sorte que « qui
avait ce droit en novembre ? » reste une question à laquelle on peut répondre. La décision passe
par l'action `instruire` (administrateur **réel** seulement), jamais par un PATCH — sinon un
demandeur s'accorderait le droit en modifiant son propre statut. `niveau_accorde` peut être
inférieur au niveau demandé : c'est une décision, pas un refus, et il est **obligatoire** à
l'octroi (jamais déduit du niveau demandé en silence).

**Permission serveur** : `PeutAccederRadio` (`core/permissions.py`) remplace
`IsInstitutionalActor` sur les endpoints radio en lecture (contacts, traceroutes, liaisons,
configurations, couvertures, calibrations) et sur la file d'administration. C'est un
**élargissement** : l'acteur institutionnel garde son accès, l'opérateur radio non institutionnel
l'obtient. Le filtrage de ce que chacun voit reste celui des endpoints (zone, institution,
secrets réservés aux ponts par `EstComptePont`, § 10.2).

**`acces_radio` n'est calculé que pour le compte de la requête**, et vaut `null` pour les
autres : le calcul coûte quatre requêtes et `UserSerializer` sert aussi la liste de
`/admin/utilisateurs`, où ce serait un N+1 pour une information dont cette page ne fait rien. La
vue administrative des droits est `/api/demandes-acces-radio/`.

### 9.5.6 Rattacher un répéteur : « ce nœud est à nous »

`RattachementNoeudRadio`, API `/api/rattachements-noeuds-radio/`, colonne « Responsable » du
tableau des nœuds détectés de `/admin/meshtastic-companions`.

Trou laissé par la règle de propriété (§ 9.5.5) et comblé le 10/11/2026 : **un répéteur n'est le
nœud personnel de personne**, donc il n'était réglable que par un administrateur de la
plateforme — alors que c'est la commune qui est allée l'installer.

**Pourquoi un modèle de plus, et pas un champ sur `NoeudUtilisateurMeshtastic`** : celui-là
répond à une autre question. Il dit « ce nœud EST cette personne », et c'est de lui que le pont
tire l'expéditeur d'un message reçu. Y rendre `utilisateur` facultatif pour loger un répéteur
aurait fait porter deux sens au même champ et cassé la résolution d'expéditeur. Ici on ne dit
pas qui est le nœud, on dit **qui en répond**.

Une cible et une seule : une institution **ou** un compte (contrainte en base pour « au moins
une », validation du serializer pour « pas les deux »). Le compte sert au radioamateur qui a
posé un répéteur chez lui et n'a aucune institution.

**Ce n'est pas réservé aux administrateurs**, et c'est délibéré : un administrateur de
plateforme ne sait pas à qui appartient quoi. Trois choses empêchent de s'approprier le matériel
d'autrui :

1. **on ne rattache qu'à soi** ou à une de ses propres institutions (`_verifier_cible`), et on
   ne détache que ce dont on répond — sinon on libérerait le nœud d'un autre pour se
   l'attribuer, et l'unicité ne protégerait plus rien ;
2. **`node_num` est unique** : un nœud déjà rattaché ne l'est pas deux fois, le conflit est
   visible et s'arbitre au lieu de se régler au dernier arrivé ;
3. **le firmware reste le dernier mot.** Écrire exige que la clé publique de la passerelle
   figure dans `security.admin_key` du nœud, ce qui suppose de l'avoir eu en main. Un
   rattachement abusif permet d'essayer, pas de reconfigurer : l'appareil refuse.

Poule et œuf assumé : sans aucun matériel on n'a pas accès au domaine radio, donc pas même de
quoi s'y rattacher un premier nœud. `/admin/radio` est la porte d'entrée — un administrateur
rattache, ou accorde le droit.

#### Rattacher SON nœud : la liste de découverte ne peut pas être derrière le droit radio

Les nœuds personnels existent des deux côtés et de façon symétrique, et c'est l'utilisateur
lui-même qui se les rattache depuis `/parametres`, onglet Radio :

| Protocole | Modèle | Clé | Endpoints |
|---|---|---|---|
| MeshCore | `NoeudMeshUtilisateur` | `pubkey_hex` (Ed25519) | `/api/noeuds-meshcore/` : `candidats`, `mes-noeuds`, `reclamer`, `liberer`, `messageables`, `positions-en-mission` |
| Meshtastic | `NoeudUtilisateurMeshtastic` | `node_num` | `/api/noeuds-meshtastic/` : idem, `messageables` en moins (le choix du destinataire passe par l'endpoint d'équipe) |

C'est ce rattachement qui fait qu'un message venu du mesh est attribué à une personne
(`MessageMeshLog.expediteur`, résolu par ces deux modèles) et que les équipes peuvent discuter
par radio **à travers l'application**. Il ne faut donc pas confondre ces companions-là avec ceux
de la cartographie publique ci-dessus, qui sont les appareils d'inconnus sur une instance tierce
et ne sont **jamais** importés.

**Correction du 11/11/2026.** Le passage des endpoints radio derrière `PeutAccederRadio` avait
créé un cercle : porter un nœud actif est ce qui OUVRE le droit radio
(`core/acces_radio.py`), mais trouver la clé de son nœud demandait `/api/contacts-meshcore/`,
désormais réservé au domaine radio. Un utilisateur qui venait de brancher un boîtier devait donc
recopier **64 caractères hexadécimaux** à la main — et une faute de frappe rattache un nœud qui
n'est pas le sien.

D'où `candidats` sur les **vues de rattachement**, et non un assouplissement de
`ContactMeshCoreViewSet` :

- **ouvert à tout compte connecté** (`IsAuthenticated`), parce que c'est la porte d'entrée du
  droit et qu'une porte ne peut pas être derrière la serrure qu'elle ouvre ;
- **charge minimale** : clé ou `node_num`, nom annoncé, date de dernière écoute, et deux
  drapeaux. Ni position, ni batterie, ni voisinage — la position d'un companion est très souvent
  un domicile, et reconnaître « c'est le mien » n'en a aucun besoin. C'est le prix de
  l'ouverture, et c'est pour cela que l'action ne réutilise pas le sérialiseur complet ;
- **companions seulement** côté MeshCore. Un répéteur est une infrastructure dont d'autres
  dépendent : il passe par `RattachementNoeudRadio` et sa preuve (section suivante), jamais par
  une liste à cocher ;
- **`deja_associe` sans nommer le titulaire**, et `a_moi` distingué : savoir qu'une clé est prise
  suffit à comprendre pourquoi on ne peut pas la réclamer ; dire par qui révélerait quel appareil
  appartient à quelle personne. « Pris » et « pris par vous » n'appellent d'ailleurs pas la même
  action — le second se libère ;
- **une ligne par clé**, la plus récemment entendue : un même appareil est vu par plusieurs
  passerelles, et le proposer deux fois dans une liste de choix est une invitation à se tromper.

La saisie manuelle reste disponible et le restera : un appareil qu'aucune de nos passerelles n'a
jamais entendu n'est dans aucune liste. Côté Meshtastic, l'identifiant est affiché sous la forme
`!a1b2c3d4` — celle que l'appareil montre lui-même — alors que l'API attend l'entier.

#### Réclamer un répéteur MeshCore : la preuve remplace la déclaration

Ajouté le 10/11/2026, et c'est une **différence de nature** avec Meshtastic.

Sur Meshtastic, un rattachement est une déclaration que seul le firmware démentira : la clé
publique de la passerelle doit figurer dans `security.admin_key` du nœud, ce qu'on ne peut ni
lire ni vérifier à distance. Sur MeshCore, les deux moyens d'administrer un répéteur sont
**vérifiables** — ils viennent du firmware, `examples/simple_repeater/MyMesh.cpp:92-104` : un
mot de passe vide fait vérifier que l'émetteur figure dans l'**ACL** du répéteur, sinon le mot
de passe est comparé à celui de l'administrateur puis à celui de l'invité.

Réclamer un répéteur, c'est donc remplir un formulaire avec l'un des deux moyens
(`MoyenAdminRadio`) :

| Moyen | Ce qu'on fournit | Comment ça se vérifie |
|---|---|---|
| `MOT_DE_PASSE` | le mot de passe d'administration du répéteur | `send_login` |
| `ACL` | rien — la clé publique de notre companion est déjà dans son ACL | `req_status` |
| `AUCUN` | cas Meshtastic : l'autorisation est sur l'appareil | invérifiable à distance |

`statut_preuve` porte le résultat, et **un rattachement MeshCore non vérifié n'ouvre aucune
écriture** (`peut_administrer_noeud_meshcore`). Ce n'est pas un excès de prudence : contrairement
à Meshtastic, il n'y a ici **aucun filet côté firmware** — quiconque a le mot de passe peut
écrire. La vérification n'est donc pas un confort, c'est la condition.

Trois conséquences de conception :

- **une identité et une seule** par ligne : `node_num` (Meshtastic, entier 32 bits) ou
  `pubkey_hex` (MeshCore, Ed25519). Aucun champ commun n'existe, et en fabriquer un casserait la
  jointure avec `NoeudUtilisateurMeshtastic` d'un côté et `ContactMeshCore` de l'autre.
  Contrainte en base, plus l'unicité conditionnelle de chacun des deux ;
- **le mot de passe est stocké chiffré** (`EncryptedTextField`, `write_only`). Il faut le stocker
  parce qu'une tâche d'administration est exécutée par le pont des minutes plus tard, parfois
  après un réessai : demander le mot de passe à chaque opération supposerait un humain présent
  au moment de l'exécution. Un test vérifie **en SQL brut** qu'il n'est pas en clair ;
- **le companion est obligatoire** dès qu'un moyen est déclaré : c'est lui qui ouvre la session,
  et c'est *sa* clé publique que l'ACL doit contenir. Il doit appartenir à l'institution du
  demandeur, sinon on emprunterait la passerelle d'autrui pour ouvrir une session en son nom.

**Pas encore fait** : la tâche de vérification elle-même (l'équivalent MeshCore de
`TacheAdminMeshtastic`). Tant qu'elle n'existe pas, `statut_preuve` reste `NON_VERIFIE` et les
écritures MeshCore sont refusées — le défaut sûr.

Meshtastic : les répéteurs déclarés à la main portent par ailleurs déjà une institution
(`RelaisMeshCore.institution`), qui reste le chemin pour un relais qu'on ne compte pas
administrer.

**Tests** : `backend/core/tests/mesh/test_acces_radio.py` (63), plus deux tests de
`test_administration_meshtastic.py` qui disaient l'inverse avant le 10/11/2026 (toute écriture
exigeait le rôle ADMIN réel) et portent le changement dans leur docstring, la spec de
`admin-sidebar`, `radio.component.spec.ts` et `carte-radio.component.spec.ts`.

### 9.6 Angles morts de la supervision

Trois garde-fous posés le 06/11/2026, après un incident où `ac_prometheus` est resté arrêté
**2 j 8 h sans que rien ne le signale** — 2 j 8 h de métriques définitivement perdues.

**1. La pile de supervision redémarre toujours** — `restart: always`, ancre
`x-service-supervision` de `docker-compose.114.yml`, pour les dix services de supervision.
`unless-stopped` ne relance jamais un conteneur arrêté à la main, *même au redémarrage suivant de
la machine* : Prometheus avait reçu un SIGTERM 1 min 37 avant le reboot de mise à jour du noyau,
Docker l'a donc compté comme un arrêt manuel, et les 26 autres conteneurs sont remontés sans lui.
Les services applicatifs gardent `unless-stopped` — leur panne se voit immédiatement, un arrêt
volontaire doit y rester volontaire. Celle de la supervision ne se voit pas : c'est précisément le
service chargé de prévenir qui manque.

**2. Le dead man's switch est câblé** — receveur `deadmans-switch`. Aucune alerte interne ne peut
signaler l'absence de Prometheus, puisque c'est lui qui les évalue : seule une surveillance
**externe** du battement en est capable. Côté healthchecks.io, régler **période 5 min, grâce
15 min** — le défaut est d'un jour, qui retarderait l'alerte d'autant ; on est alors prévenu dans
les 20 min. L'URL de ping est un secret (qui la connaît peut envoyer de faux battements et faire
taire le dispositif) : elle vit dans `healthchecks_url.txt`, lue via `/run/secrets`, jamais dans
git. Droits `644` et non `600` comme les autres secrets montés : le processus tourne en
`nobody`(65534) alors que le fichier appartient à l'uid 1000 — la barrière est le dossier parent,
en `drwx------`. Le ping ne transporte que `alertname=Watchdog`, `severity=none`, `environment` et
un résumé fixe : aucune donnée personnelle ne part chez ce tiers.

**3. La sonde HTTPS est déterministe** — et ne mesure pas ce qu'on croit. Elle cible l'**IP
locale**, le nom passant par le paramètre `hostname` du prober http, qui fixe l'en-tête Host *et*
le SNI TLS (sans quoi la sonde échoue : un certificat ne vaut pas pour une IP). Sonder le nom la
rendait instable : l'apex résout vers l'IP locale par le DNS interne mais vers l'IP publique par
un résolveur public, et la box ne fait pas de retour en épingle — un TCP de la machine vers sa
propre IP publique expire, alors que la même connexion vers l'IP locale aboutit instantanément.
Chaque bascule de résolveur produisait donc un faux `SiteDown`, de sévérité *critical*, pendant
que le WAF servait des centaines de requêtes. Cause de la bascule : la machine était bi-raccordée
(Ethernet et WiFi tous deux en `+DefaultRoute`) avec des vues DNS contradictoires, `9.9.9.9`
figurant en second serveur sur le lien Ethernet ; `systemd-resolved` interrogeait les deux en
parallèle et gardait la première réponse. Ce repli a été retiré le 06/11/2026, la résolution est
redevenue cohérente — mais la sonde n'en dépend plus de toute façon.

> **Ce que la sonde ne voit pas.** Elle valide TLS, le certificat, le WAF, le proxy et le
> frontend — pas la box, pas la redirection de port, pas le FAI. Hébergée sur la machine du site,
> elle ne *peut pas* mesurer ce que vivent les visiteurs : soit elle résout en interne et ne teste
> que le chemin interne, soit elle résout en public et exige un hairpinning indisponible. Une
> vraie disponibilité externe demande un point d'observation **hors du réseau** — par exemple un
> cron sur une machine tierce qui ne pingue un second check healthchecks.io que si le site
> répond.

---

## 10. Sécurité

### 10.1 Chiffrement des données personnelles

Les colonnes contenant des données personnelles (demandeurs, bénévoles, signalements,
personnes recherchées, déclarations de sécurité, interlocuteurs PCS, messages mesh, adresses des
enjeux communaux, emails et téléphones des comptes…) sont chiffrées **par l'application**
(`core/crypto_fields.py`) : un accès au disque, un `pg_dump` ou une requête SQL ne lit que du
texte chiffré. La règle ne souffre pas d'exception « parce que c'est un établissement » : une
liste d'enjeux finit toujours par contenir l'adresse d'une personne (voir § 5.12).

Depuis le 06/11/2026 (migration `0230`), le même chiffrement couvre aussi des **secrets** qui ne
sont pas des données personnelles, parce que la règle « rien en clair » vaut pour eux aussi : clés
partagées des canaux MeshCore (`CanalMeshCore.cle_partagee_hex`), PSK des canaux Meshtastic
(`CanalMeshtastic.psk_hex`), mot de passe du broker MQTT et clé privée X25519
(`CompagnonMeshtastic`). Ils n'étaient protégés que par `write_only` côté serializer, donc
lisibles dans un `pg_dump`.

| Clé | Algorithme | Usage |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | Fernet (réversible) | `EncryptedTextField`, `EncryptedEmailField`, `EncryptedJSONField` |
| `FIELD_BLIND_INDEX_KEY` | HMAC-SHA256 (irréversible) | index aveugles `*_bidx` : recherche **exacte** sur un email chiffré |
| `FILE_ENCRYPTION_KEY` | Fernet | fichiers très sensibles (pièces d'identité, conventions signées, `core/file_crypto.py`) |

- Trois clés distinctes : jamais la même clé pour deux usages. **Aucune valeur de repli** :
  sans clé, Django refuse de lire ou d'écrire le champ. Changer ou perdre une clé rend les
  données illisibles ; une rotation demande de tout rechiffrer (`MultiFernet`).
- Fernet inclut un nonce aléatoire : deux valeurs identiques ont des chiffrés différents. Les
  contraintes d'unicité et les recherches passent donc par l'index aveugle (`email_bidx`
  unique ; d'où `auth.E003` désactivé), recalculé par `save()` sur valeur normalisée
  (espaces, casse). Aucune recherche partielle (`icontains`) n'est possible sur un champ
  chiffré.
- Une valeur lue non chiffrée est renvoyée telle quelle (lignes antérieures au chiffrement).
- **Conséquence à ne jamais oublier : plus aucun `filter()` SQL ne peut porter sur une colonne
  chiffrée**, et l'échec est *silencieux* — la requête ne lève pas, elle ne renvoie simplement
  jamais rien. Chiffrer un champ oblige donc à relire tous ses usages. Deux l'ont imposé en
  `0230`, tous deux comparant à `CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT` et passés en comparaison
  Python (tables minuscules, coût nul) : `verifier_alertes_sismiques._diffuser_emcom_meshcore`,
  où l'échec aurait **arrêté la diffusion des alertes sismiques**, et la garde anti-doublon de
  `CompagnonMeshCoreViewSet.signaler_canaux_detectes`, où il aurait recréé le canal « Public » à
  chaque appel. `core/tests/securite/test_chiffrement_secrets_mesh.py` verrouille les deux, et
  prouve le chiffrement au repos en lisant la colonne en **SQL brut** — un test écrit avec l'ORM
  passerait même sur une colonne en clair, puisque l'ORM déchiffre à la lecture.
- Un `search_fields` de l'admin Django sur un champ chiffré ne trouve rien non plus, pour la même
  raison : `NoeudMeshUtilisateurAdmin` cherche sur `nom_noeud`, chiffré — recherche inopérante,
  antérieure à `0230`.
- **Hors périmètre** : géométries (PostGIS doit les lire), `AuditLog`, informations
  publiques d'une institution (nom, marque blanche). La géométrie étant inchiffrable, un objet
  qui désigne une personne n'en porte pas : les coordonnées d'un domicile vont dans un
  `EncryptedJSONField` et `location` reste nul (`SiteSensible.donnees_personnelles`).
- En dev, `init-secrets.sh` génère les clés dans `.env`. En production, elles sont injectées
  hors du dépôt (`backend.env` sur la machine) : elles doivent être **sauvegardées ailleurs
  que sur le serveur**.

### 10.1.1 Anonymisation de la zone DEMO

Tout le **contenu** est cloisonné par `EnvironmentScopedModel` : une page de démonstration ne lit
que des lignes DEMO, engendrées par Faker (`generate_crise_gier_pilat`, `generate_benevoles_*`).
**`User`, lui, est partagé** entre les deux zones : un compte, un rôle PROD, un `demo_role`. Toute
page qui nomme une personne nomme donc un compte **réel**, même en démonstration.

Les adresses et téléphones étaient masqués depuis longtemps (`mask_email`, `mask_phone`), mais
**les noms ne l'étaient nulle part** : une soixantaine de `f"{u.first_name} {u.last_name}"`
dispersés dans `serializers.py` et `views.py` les composaient à la main. Plusieurs vues rendaient
en plus l'adresse ou le téléphone en clair (fiche « personne », supervision inter-collectivités,
main courante, habilitations au registre, invitations d'association). Constaté par l'exploitant le
07/11/2026.

**Point de passage unique** : `core/permissions.py:nom_affichable(user, request)`. En zone DEMO il
rend un **pseudonyme stable** (`pseudonyme()` : prénom tiré d'une liste fixe + `Démo-XXXX`, dérivé
de l'identifiant). Stable, pour qu'un scénario de démonstration reste suivable d'un écran à
l'autre ; dérivé de l'identifiant et non du nom, pour que deux homonymes restent distincts et
qu'on ne puisse pas remonter au nom réel. Le patronyme factice est toujours `Démo-XXXX` : on ne
fabrique pas un faux nom de famille crédible, qui pourrait être pris pour une vraie personne.

Trois règles qui expliquent la forme du code :

- **Aucun repli interne sur l'email.** La fonction remplace exactement
  `f"{u.first_name} {u.last_name}".strip()` et rend une chaîne vide pour un compte sans nom : les
  appelants gardent leur propre `or u.email`, inchangé en production. En DEMO le pseudonyme est
  toujours non vide, donc ce repli ne s'applique jamais et aucune adresse ne fuit par là. Un repli
  interne aurait fait apparaître des emails là où le code renvoyait délibérément `None`.
- **Jamais dans le contenu d'un email.** Un message envoyé à une vraie personne doit porter son
  vrai nom. Les `send_mail` de `views.py` lisent donc `first_name`/`last_name` en direct. Là où un
  même texte alimentait **à la fois** une notification affichée et un email (créneau bénévole à
  valider, candidature à la réserve), les deux textes ont été séparés : pseudonyme à l'écran, vrai
  nom dans la boîte.
- **Son propre nom reste en clair.** Se masquer à soi-même ne protège personne et rend la zone de
  démonstration incompréhensible.

Deux lectures directes restent assumées et **déclarées** : la main courante (un journal d'audit ne
doit pas mentir ; sa consultation globale est réservée au super-admin) et la réplication des
comptes vers le Django local d'un satellite (un email pseudonymisé y rendrait la connexion
impossible).

**Garde structurel** : `core/tests/plateforme/test_anonymisation_demo.py` relit `serializers.py` et
`views.py` et **échoue** sur toute lecture directe de `first_name` non déclarée par un commentaire
`# nom-reel-assume: <raison>`. Sans lui, la prochaine vue qui composerait un nom à la main
réintroduirait la fuite en silence — c'est exactement ce qui s'était produit.
- `SECRET_KEY` signe les JWT, les liens magiques et de réinitialisation : la changer
  déconnecte tout le monde et invalide les liens envoyés (rotation douce :
  `SECRET_KEY_FALLBACKS`). Elle ne chiffre aucune donnée.

### 10.2 Règles générales

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
- **MQTT** : authentifié partout depuis le 06/11/2026. En dev,
  `mosquitto/config/mosquitto.dev.conf` (comptes `exporter` et `dev`, mots de passe dans `.env`).
  Sur **.114**, `mosquitto/config/mosquitto.114.conf` : `allow_anonymous false`, **liste de
  droits** (`acl_file`, un compte par usage et par site — voir `mosquitto/config/acl.114`), et
  surtout **le port 1883 est publié sur la seule IP du LAN** (`172.16.1.114`), jamais sur
  `0.0.0.0` : Docker contourne UFW, et un port publié sur `0.0.0.0` serait joignable depuis
  Internet malgré le pare-feu. Seuls les nœuds radio du réseau local y accèdent ; aucune
  redirection sur la box, pas de listener TLS. Le fichier de mots de passe haché est reconstruit
  ni versionné. **Les comptes s'administrent depuis `/admin/comptes-mqtt`** (administrateurs au
  rôle PROD réel) : Django est la source de vérité, réécrit `passwd` et `acl` dans le volume
  partagé `ac_mqtt_comptes`, et une boucle dans le conteneur du broker déclenche un rechargement
  de configuration dans les dix secondes — sans couper les autres comptes. Au premier démarrage,
  avant que Django n'ait rien écrit, le broker s'amorce depuis ses propres secrets : sa
  disponibilité ne dépend **jamais** de l'application. Le greffon « dynamic security » de
  Mosquitto a été écarté pour cette raison précise (il exige un broker en fonctionnement pour
  créer un compte), d'où la réimplémentation de son format de mot de passe dans
  `core/mqtt_comptes.py`, figée par un vecteur de référence en test. Procédure pour ajouter une
  passerelle : [mosquitto/README.md](mosquitto/README.md).

  *Auparavant, l'accès de production était anonyme sur un port publié sur toutes les interfaces :
  n'importe qui pouvant joindre la machine pouvait lire et publier.*

- **Secrets mesh exposés par l'API** : les endpoints qui livrent un secret radio **en clair**
  sont réservés aux comptes de service des ponts depuis le 07/11/2026
  (`core/permissions.py:EstComptePont`). Il y en a cinq :
  `compagnons-meshtastic/actifs-avec-identifiants/` (mot de passe MQTT **et** clé privée X25519),
  `compagnons-meshtastic/{id}/avec-cle-privee/`, `canaux-meshtastic/avec-cle/` (PSK),
  `compagnons-meshcore/{id}/canaux-a-provisionner/` et `.../canaux-pour-decodage-logiciel/`
  (clés de canal MeshCore).

  Trois familles d'appelants, et pas une de plus : un compte marqué `compte_service_pont`, le
  compte de service d'un **satellite approuvé** (autorisé d'office par son enrôlement), et un
  administrateur au sens du rôle **réel** — pas le rôle effectif, un `demo_role=ADMIN` prêté le
  temps d'une démonstration ne donne pas les clés du réseau radio.

  Le marquage est volontairement **hors API** — un compte qui lit tous les secrets radio ne doit
  pas pouvoir être fabriqué par une requête HTTP :

  ```
  docker exec ac_backend python manage.py marquer_compte_pont <email-du-pont>
  docker exec ac_backend python manage.py marquer_compte_pont --lister
  ```

  **À faire au déploiement** : sans ce marquage, les ponts reçoivent 403 et le relais radio
  s'arrête (ils réessaient, donc l'interruption s'arrête d'elle-même dès le marquage fait).
  `--lister` avertit explicitement quand aucun compte n'est autorisé.

  *Auparavant, `get_permissions` ne restreignait que create/update/destroy et laissait tout le
  reste sur `IsAuthenticated` : **n'importe quel compte citoyen inscrit** pouvait lire le mot de
  passe MQTT du broker de l'institution, les clés privées de ses companions et les PSK de ses
  canaux — donc se faire passer pour une passerelle et déchiffrer son trafic radio.*

---

## 11. Tests et qualité

```bash
docker compose exec backend pytest -o addopts="" --no-cov                    # suite backend complète (~7 min)
docker compose exec backend pytest -o addopts="" --no-cov core/tests/mesh/   # un domaine
docker compose exec backend pytest core/tests/plateforme/test_metrics.py     # un fichier
docker compose exec backend pytest core/tests/mesh/test_meshcore.py -k canal # tests dont le nom contient « canal »
scripts/tester-frontend.sh                                                   # frontend (Karma, conteneur jetable)
scripts/tester-frontend.sh --couverture                                      # idem + rapport de couverture
```

- Frontend : Karma + Jasmine, exécutés dans un conteneur jetable
  (`frontend/Dockerfile.test`). **Le projet avait 68 fichiers de test inexécutables** jusqu'au
  28/10/2026 : `angular.json` ne référençait pas `karma.conf.js`, donc le lanceur
  `ChromeHeadlessCI` n'était pas enregistré et la suite ne démarrait pas du tout — personne
  n'avait donc jamais vu que 29 de ces tests échouaient. `npm test` en local ne marche pas
  davantage : il n'y a pas de `node_modules`, le frontend n'est construit que par Docker.
  - **Un socle partagé** : `src/app/testing/test-providers.ts` fournit HTTP (avec le
    contrôleur de test), un routeur vide et une `ActivatedRoute` factice. Trois lignes
    répétées dans 68 fichiers deviendraient trois lignes à changer dans 68 fichiers le jour où
    un fournisseur s'ajoute.
  - **Pas de seuil de couverture** dans `karma.conf.js`, et c'est délibéré : en poser un à
    50 % alors que la couverture réelle est de quelques pourcents rendrait la commande
    inutilisable dès le premier jour, donc personne ne la lancerait. Un plancher se décide
    quand la couverture est significative, et se relève par cliquet.
  - **WebGL** : Chromium sans GPU ne crée pas de contexte, même avec SwiftShader. Les
    composants de carte ne doivent donc pas instancier MapLibre sans garde — ce que le harnais
    a révélé, et qui était une vraie fragilité (voir § 6.3).
- Backend : pytest + pytest-django, fixtures partagées dans `backend/conftest.py` (valables
  pour tous les sous-dossiers), base de test clonée depuis `template_postgis`. Configuration
  dans `backend/pytest.ini` (`testpaths = core`, fichiers `test_*.py`) ; les tests sont exclus
  de la couverture par `backend/.coveragerc`.

### 11.1 Organisation des tests backend

Les tests sont rangés par **domaine fonctionnel** sous `backend/core/tests/` :

| Dossier | Ce qu'on y teste |
|---|---|
| `comptes/` | inscription, activation, connexion, mots de passe, validation et désactivation des comptes |
| `securite/` | confidentialité (localisation, photos), isolation PROD/DEMO et masquage, permissions transverses, **chiffrement**, correctifs d'audit de sécurité |
| `audit/` | main courante (`AuditLog`) : journalisation, consultation, export |
| `crises/` | crises (déclaration, zone, clôture, export), implication des institutions, plans, demandes de mobilisation |
| `citoyens/` | demandes, offres, signalements, déclarations de sécurité, types et photos |
| `dossiers/` | dossiers et missions : création, affectation, suivi, priorité, clôture |
| `equipes/` | équipes : membres, compétences, délégations, hiérarchie, ressources, positions, rôles opérationnels |
| `institutions/` | institutions, contacts, imports, rattachement des comptes, convention RGPD, journal de bord, registre des personnes vulnérables |
| `zones/` | zones de compétence, vues mairie et secteur, résolution des communes, référentiel géographique |
| `moyens/` | points opérationnels, matériel et stock, registre de présence, affectation de bénévoles |
| `mesh/` | MeshCore, Meshtastic, routage radio, alertes sismiques |
| `satellites/` | enrôlement, supervision et synchronisation des satellites |
| `plateforme/` | transverse : API générique, performances (N+1), métriques, tableau de bord, emails, notifications, catalogues partagés |

**Où placer un nouveau test ?**

1. Ajouter le test au **fichier existant** qui couvre déjà cette fonctionnalité, s'il y en a un.
2. Sinon, créer `test_<sujet>.py` dans le dossier du **domaine de la fonctionnalité testée**
   (le modèle ou le ViewSet principal concerné), pas de celui où le bug a été remarqué.
3. Si la règle testée est **transverse** (confidentialité, isolation PROD/DEMO, chiffrement,
   permissions), le ranger dans `securite/`, même si l'exemple porte sur une demande ou une
   équipe. Ce qui touche plusieurs domaines sans être une règle de sécurité va dans
   `plateforme/`.
4. Nouveau domaine (aucun dossier ne convient, et au moins quelques fichiers à venir) : créer
   le dossier **avec un `__init__.py`**, puis l'ajouter à ce tableau.

Règles techniques :

- Chaque dossier contient un `__init__.py` : les modules s'appellent
  `core.tests.<domaine>.test_<sujet>`, ce qui autorise deux fichiers de même nom dans deux
  domaines. Sans `__init__.py`, pytest échoue sur ces doublons.
- Une fixture utile à plusieurs domaines va dans `backend/conftest.py` ; une fixture propre à
  un domaine peut aller dans un `conftest.py` de son dossier.
- Pour réutiliser une constante d'un autre fichier de test, importer le chemin complet
  (`from core.tests.citoyens.test_requests import REQUEST_PAYLOAD`) ; si elle sert souvent,
  la déplacer plutôt dans une fixture de `conftest.py`.
- Ne pas recréer `core/tests.py` : il masquerait le package `core/tests/`.
- **État connu** (18/10/2026) : 1463 réussis, 5 ignorés, **1 échec** déjà présent sur `main`
  (`institutions/test_institutions.py::TestContactInstitutionPrincipalUniqueness`). La CI le
  tolère temporairement (`allow_failure`). Les clés de chiffrement doivent être définies pour
  lancer les tests : sans elles, une quinzaine de tests échouent (emails, implications…).
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

- `.114` est décrite par **`docker-compose.114.yml`** (source de vérité depuis le 19/10/2026 :
  tous les conteneurs, monitoring compris, nommés `ac_<service>`, images locales
  `assista-crise-<service>:prod`, réseaux/volumes/secrets existants en `external`).
  Déployer : `scripts/114/deployer.sh <service>...` (build + recréation + reload du proxy).
  Migration initiale depuis les anciens `docker run` : `scripts/114/migrer-vers-compose.sh`
  (retour arrière : `scripts/114/annuler-migration-compose.sh`). Monitoring :
  `scripts/114/preparer-monitoring.sh` (secrets + rôle PostgreSQL `monitoring`), Grafana sur
  http://172.16.1.114:3000 (LAN). `docker-compose.prod.yml` sert à une reconstruction from
  scratch et doit rester cohérent avec lui.
- Images construites par la CI ou par `./deploy_harbor.sh` (build + push manuel) ;
  `./build-prod.sh` construit et lance la version de prod en local.
- Préparation d'une VM pour le monitoring : voir [monitoring/README.md](monitoring/README.md).
- Avant tout redéploiement : vérifier que `SECRET_KEY` est défini sur le serveur.
- Retour arrière : `IMAGE_TAG=<sha> docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile monitoring up -d`.

---

## 13. Conventions de développement

### 13.0 bis « Mon espace » : deux rôles, pas neuf onglets

Réorganisation du 13/11/2026, à la demande de Sylvain : *« un bénévole ou un bénéficiaire
devrait arriver sur cette page certes, mais avec 2 secteurs : le secteur bénéficiaire avec le
suivi de ses demandes / démarches ; le secteur bénévole, avec ses offres, ses missions en
cours, le récap du passé, ses documents justificatifs »*.

`/settings` servait **neuf onglets de même poids**, nommés par le modèle de données
(« Offres », « Besoins », « Crises », « Mon dossier ») et non par ce que la personne vient y
faire. Or ce sont **deux rôles différents** — demander de l'aide, et en donner — qu'une même
personne porte souvent tous les deux. À plat, retrouver l'un ou l'autre oblige à relire la
liste entière.

Ce qui change, et uniquement côté interface — **rien n'a été ajouté au serveur, tout était
déjà servi** :

- **La page s'appelle « Mon espace »**, et non « Paramètres du compte » : ce n'est pas un
  écran de réglages, c'est la page d'accueil d'un bénévole comme d'un bénéficiaire.
- **Trois groupes d'onglets, avec leur intitulé visible** : « J'ai besoin d'aide », « Je donne
  un coup de main », « Mon compte ». Sans l'intitulé, le regroupement n'existerait que dans la
  tête de celui qui l'a écrit. Les groupes sont **toujours affichés, même vides** : quelqu'un
  qui n'a jamais rien demandé doit pouvoir le faire.
- **Une vue d'ensemble à l'arrivée** (`activeTab = 'apercu'`), qui ne répète pas les tableaux
  mais dit, pour chaque rôle, ce qui attend quelque chose. Personne n'ouvre son espace pour
  relire son adresse email.
- **Les compteurs ne comptent que ce qui appelle une action.** Un compteur qui additionne les
  dossiers terminés annonce « 14 » à quelqu'un qui n'a rien à faire.

**La séparation qui compte** : `/dossiers/` rend à la fois les dossiers ouverts **pour** la
personne et ceux confiés à une **équipe dont elle fait partie**. Les confondre afficherait à un
bénévole « vos démarches » en parlant des gens qu'il aide. D'où `mesDemarches` / `mesMissions`,
départagés par `equipe` ∈ `mesEquipes()` — c'est le seul point du travail qui puisse tromper
quelqu'un, et c'est celui que les tests tiennent.

**Deux libellés de menu corrigés**, qui envoyaient au mauvais endroit :

| Avant | Où ça menait | Après |
|---|---|---|
| « Mon compte » | `/admin/dashboard`, la gestion de crise | « Tableau de bord de crise » |
| « Paramètres », en dernier | `/settings` | « Mon espace », en premier et pour tout le monde |

**Où l'on atterrit depuis le menu, et ce que chaque secteur contient vraiment.** Deuxième
passe le même jour, après essai :

- **« Mon espace » figure dans le menu latéral mobile**, en tête des raccourcis. Il n'était que
  dans le menu du compte — lui-même hors de l'écran sur un téléphone étroit — alors que c'est
  la porte d'entrée de tout ce qui suit : les raccourcis qui le suivent ne font qu'ouvrir ses
  onglets.
- **`/mes-equipes`** remplace le lien « Mon équipe », qui pointait sur `/mon-equipe/<première
  trouvée>`. On appartient souvent à plusieurs équipes : sa section départementale, celle de sa
  commune, et l'équipe d'intervention constituée pour la crise en cours. La page les groupe en
  **équipes d'intervention** (en haut) et **équipes permanentes** (en bas).
  *Ce qui fait une équipe « d'intervention » est un ÉTAT, pas une nature* : mission en cours,
  engagement démarré, ou crise assignée. Une section départementale engagée remonte donc en
  haut le temps de l'engagement — la page répond à « où suis-je attendu aujourd'hui », pas à
  « comment l'association est-elle organisée ». La même règle est appliquée à l'identique dans
  l'onglet « Mes équipes » de Mon espace, pour que les deux écrans ne se contredisent pas.
- **Un chat Matrix dans la vue d'une équipe** (`/mon-equipe/:id`), via le composant générique
  `app-matrix-salon-chat` déjà utilisé par la cellule de crise. Les messages transitent par le
  compte du bot côté serveur — jamais un jeton Matrix dans le navigateur — et qui installe
  Element un jour retrouve la même conversation. Tant que `room_id` est vide, l'écran explique
  l'attente au lieu d'afficher un chat qui répondrait 409.
- **« Mes missions » et « Mes équipes » sont de vrais onglets** du secteur bénévole, et non des
  liens : partir sur une autre page pour savoir ce qu'on a à faire, c'est perdre le fil de son
  espace. L'écran de terrain complet (photos, priorités, réordonnancement) reste
  `/mes-interventions`.
- **« Mes documents » dans « Mon compte »**, par un composant partagé
  `app-mes-justificatifs` — le même que celui de « Ma fiche de bénévole ». Deux copies
  auraient divergé au premier correctif, et ce formulaire décide de la destruction d'un
  fichier : ce n'est pas un endroit où se permettre deux vérités. Il montre d'abord **ce qui
  attend une action** (refus à corriger, titre sans pièce), puis le **tableau de suivi**
  (document, déposé le, fin de validité, statut, œil), enfin le formulaire de dépôt — mettre
  le formulaire en premier obligerait à faire défiler pour savoir s'il y a quelque chose à
  faire.

  **L'onglet n'est conditionné à rien.** Première version réservée aux adhérents d'association
  (`est_benevole_association`) : elle disparaissait donc pour tous les autres, y compris le
  compte qui l'avait demandée. Une pièce justificative est rattachée à la **personne** — pas à
  une association — et quelqu'un qui propose son aide sans adhérer a un permis à faire
  vérifier comme les autres.

  **Le catalogue était vide en production**, constaté le 13/11/2026 : la liste « Type de
  document » ne proposait donc rien, et personne ne pouvait déposer quoi que ce soit — un
  écran parfaitement fonctionnel et parfaitement inutilisable.
  `manage.py initialiser_catalogue_qualifications`, appelé par `entrypoint.sh`, pose un socle
  de 21 titres **avec leur régime de conservation déjà réglé** : sans cette catégorie, tout
  resterait sur le défaut prudent et une photo de permis ne serait jamais détruite. Idempotent,
  et il ne défait **jamais** un reclassement fait à la main — revenir sur la décision d'une
  association à chaque redémarrage du conteneur serait incompréhensible pour elle.

  **Le statut est une phrase, pas un mot.** `VERIFIEE` ne dit rien du sort du FICHIER, et
  c'est pourtant la question qu'on se pose en revenant : *est-ce que mon permis est encore
  quelque part ?* Deux documents au même statut ont connu deux sorts opposés selon leur
  régime de conservation. La colonne rend donc « Validé — la copie a été détruite, comme prévu
  pour ce type de document » ou « Validé — vous pouvez le reconsulter », et l'œil n'apparaît
  que si la pièce existe encore : une icône qui ouvrirait une erreur serait pire que pas
  d'icône, et une pièce disparue sans explication passe pour un bug.

**Correctif de sécurité trouvé en chemin.** Depuis que chaque équipe porte **deux** salons
(Intervenants / Encadrement), trois endroits prenaient
`SalonMatrixEquipe.objects.filter(equipe=...).first()` — sans `Meta.ordering` sur le modèle, le
tirage était réellement arbitraire, et un simple membre pouvait se retrouver dans le salon de
commandement de son équipe et y écrire. Le type est désormais explicite
(`type=TypeSalonEquipe.INTERVENANTS`) dans `salon_matrix_messages`, `salon_matrix_reagir` et la
cellule de crise.

**Les variables de thème qui n'existent pas sont pires qu'une couleur en dur.** Corrigé le
13/11/2026 sur les sept feuilles écrites ce jour-là. La convention du § 6.6 est d'écrire
`var(--ac-…, <couleur du mode clair>)`, les `--ac-*` n'étant définies **que** sous
`html[data-theme='sombre']`. Un nom inventé — `--ac-surface-alt`, `--ac-primary`,
`--ac-danger`, `--ac-success`, `--ac-warning` n'existent pas — résout donc **toujours** vers
le repli clair, y compris en mode sombre : d'où des pavés clairs portant du texte gris pâle,
illisibles. Les seuls noms disponibles sont `--ac-surface` / `-2` / `-3`, `--ac-text` /
`-muted` / `-subtle`, `--ac-border` / `-strong`, les triplets `--ac-<couleur>-bg` / `-text` /
`-border`, et `--brand-primary-lisible` (la seule définie dans les deux thèmes).

**Sur smartphone, la barre d'onglets est une liste.** Première version corrigée le jour même,
après essai sur un Android de 412 px : les règles existantes masquaient le libellé
(`.tab-text { display: none }`) pour faire tenir les onglets sur une bande horizontale, ce qui
donnait, avec dix entrées groupées, une rangée de pictogrammes de 24 px — ni visables ni
compréhensibles. Sous 768 px, les onglets passent donc en **colonne**, mots en entier, lignes
d'au moins 44 px, et **un seul groupe déplié à la fois** (`groupeOuvert`) : dix lignes empilées
feraient six cents pixels de navigation avant le premier contenu. Le groupe suit toujours
l'onglet actif — un onglet actif dans un groupe fermé serait invisible, sans rien pour le
retrouver — et un en-tête de groupe **ouvre sans refermer**, pour la même raison.

Dans l'en-tête, `Menu d'administration` portait `white-space: nowrap` : sur un écran étroit le
pavé poussait le bouton de compte hors de l'écran, et « Mon espace » devenait littéralement
inatteignable. Il passe sur deux lignes sous 768 px, et `.header-right` ne se comprime plus —
le bouton de compte et le hamburger sont les deux seules portes de sortie de l'écran.

Enfin, « Les crises » est devenu **« Les crises que j'ai déclarées »** : le filtre est
`author_email`, donc parler de crises « qui me concernent » aurait été faux. Et
`/ma-fiche-benevole` accepte désormais `?onglet=justificatifs`, pour que le lien du secteur
bénévole arrive sur les pièces et non sur le formulaire d'identité — un lien qui dépose les
gens à côté de ce qu'il annonce est un lien raté.

### 13.0 Les textes de l'interface s'adressent à celui qui les lit

Règle posée le 12/11/2026, après un constat sans appel : beaucoup de textes d'écran, d'emails
et de documents étaient écrits **comme on écrit à celui qui a commandé la fonctionnalité** —
on y justifiait une décision de conception, on citait un chemin d'URL, on dramatisait pour
convaincre. Ce n'est pas la bonne personne. Celui qui lit est un bénévole, un agent, un
sinistré, et il veut savoir quoi faire.

**Ce qui ne change pas** : on explique. Le projet assume des écrans qui enseignent leur propre
métier, et cette habitude est bonne — un outil de crise sert à des gens qui l'ouvrent deux fois
par an, parfois en urgence, souvent sans formation.

**Ce qui change, c'est à qui l'on parle.** Sept règles :

1. **Vouvoyer, et s'adresser au lecteur.** « Vous pouvez… », « Renseignez… », « Cette page vous
   montre… ». Jamais « on », qui désigne l'équipe qui construit l'outil.
2. **Dire quoi faire, pas pourquoi on l'a codé ainsi.** « Renseignez la date de fin prévue :
   c'est elle qui permet de vous prévenir avant la fin de l'hébergement » — et non « sans
   elle, le calcul du terme est impossible ».
3. **Aucun terme d'implémentation** : table, base, serveur, API, endpoint, null, chiffré au
   repos, sérialisation. Le lecteur ne sait pas ce qu'est une table, et ne devrait pas avoir à
   le savoir pour remplir un formulaire.
4. **Aucun chemin d'URL ni nom de fichier** dans un texte visible. On nomme l'écran
   (« le planning de l'équipe »), pas sa route.
5. **Pas de dramatisation.** « Personne ne sait où ils dorment ce soir » est une phrase de
   réunion, pas d'écran. « Aucun hébergement n'est enregistré pour eux. À traiter en
   priorité. » dit la même chose et respecte le lecteur, qui connaît son métier.
6. **Pas de participe passé genré** quand le destinataire est inconnu : « Vous faites
   désormais partie de l'équipe » plutôt que « Vous avez été ajouté ».
7. **Un refus ou un vide s'explique et donne la suite.** Ce qui vaut pour les erreurs vaut
   pour les pages vides : dire ce que la page fait, pourquoi elle est vide pour ce compte, et
   à qui s'adresser.

Cela vaut pour **les écrans, les emails (`core/modeles_messages.py`) et les documents produits**
(attestations, exports). Et particulièrement en marque blanche : un bénévole des Casques Jaunes
lit « Réserve Résilience », jamais « Assista-Crise » (voir `core/branding.py`).

Le **commentaire de code**, lui, garde l'autre registre : il s'adresse au prochain développeur,
explique le pourquoi, les pièges et les décisions. Les deux registres coexistent dans le même
fichier — le texte entre balises parle à l'utilisateur, le commentaire au mainteneur.

- Commentaires et messages de commit **en français**, phrase au présent décrivant le changement.
- Un commentaire explique **pourquoi** (contrainte, piège, raison d'un choix), en une ou deux
  lignes ; pas ce que fait le code, ni l'historique (dates, conversations, incidents : git et
  ce document s'en chargent). Une explication d'architecture qui dépasse un fichier va dans ce
  document, et le code y renvoie (« voir DOCUMENTATION.md, § x »).
- Ne jamais commiter `.env`, `secrets/`, `__pycache__`/`.pyc`, `node_modules`.
- Backend : nouvelle ressource = modèle + migration commitée + serializer + ViewSet enregistré
  dans `core/urls.py` + permissions + tests pytest dans le bon dossier de domaine
  (`core/tests/<domaine>/`, règle de choix au § 11.1).
- Frontend : nouvelle page = composant standalone + route `loadComponent` dans le groupe adéquat
  + entrée dans `admin-nav.config.ts` (§ 6.4) ; rafraîchissement périodique via `pollWhileVisible`.
- Pas de code mort laissé en commentaire (ancienne implémentation, CSS désactivé) : git le garde.
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
| `container ac_db is unhealthy`, `pg_isready: too many command-line arguments` | `.env` absent ou sans `DB_USER` : relancer `./scripts/init-secrets.sh`, puis aligner le mot de passe du rôle existant (`ALTER USER … PASSWORD`) sur le nouveau `DB_PASS` |
| `ImproperlyConfigured: FIELD_ENCRYPTION_KEY n'est pas configurée` | clés de chiffrement absentes du `.env` : `./scripts/init-secrets.sh` puis `docker compose up -d backend` |
| Valeurs `gAAAAA…` dans un client SQL | colonnes chiffrées, c'est normal : lire et modifier via l'admin Django (§ 4) |
| Un utilisateur ne peut plus se connecter après une modification SQL de son email | l'index aveugle `email_bidx` n'a pas été recalculé : refaire la modification via Django |
| `InstitutionType matching query does not exist` (`mairie`) sur une base neuve | type créé au premier rattachement d'une mairie ; les générateurs le créent eux-mêmes |
| `password authentication failed` après changement de secret | les mots de passe ne s'appliquent qu'à la création du volume : `ALTER USER` (voir monitoring/README.md) |
| Erreurs de schéma sur une base de dev ancienne | base créée par un autre historique de migrations : la recréer (`docker volume rm …_postgres_data`) |
| Une règle d'alerte modifiée n'est pas prise en compte | `docker compose restart prometheus` |
| Un compteur Prometheus « recule » | métriques non agrégées entre workers : vérifier `PROMETHEUS_MULTIPROC_DIR` |
| « Impossible de contacter le serveur » à la connexion en dev, alors que l'API répond | requête bloquée par CORS (console du navigateur) : en dev le front appelle `localhost:8000` depuis une autre origine. L'origine doit figurer dans `CORS_ALLOWED_ORIGINS` et tout en-tête ajouté par l'intercepteur (ex. `X-Environment`) dans `CORS_ALLOW_HEADERS` (`config/settings.py`) ; en prod, même origine, pas de CORS |
| Un lien reçu par email en dev ouvre le site de production (« Lien invalide ou expiré ») | `SERVER_URL` non défini : il vaut l'adresse de prod par défaut (défini à `http://localhost` dans l'override) |
| `manage.py changepassword <email>` : `user … does not exist` | la commande compare l'email en clair à la colonne chiffrée. Utiliser le shell : `User.objects.get(email_bidx=blind_index('<email>'))` puis `set_password()` et `save()` |
| `tsc` local : `Cannot find module 'terra-draw'` | `node_modules` du poste plus ancien que `package.json` : `cd frontend && npm ci` (l'image Docker l'installe déjà) |
| `lookup X … server misbehaving` au démarrage | course au démarrage entre conteneurs : `depends_on` |

---

## 15. Chantiers ouverts

- Corriger le dernier test en échec puis retirer `allow_failure` de la CI.
- **Clés de chiffrement en production** : documenter leur injection et vérifier qu'elles
  sont sauvegardées hors de la machine (sans elles, les données personnelles sont perdues).
- Commentaires historiques encore longs dans `views.py` et les ponts : les réduire selon les
  conventions (§ 13), en coordination avec les auteurs (conflits). Le frontend est fait
  pour ses plus gros fichiers.
- Frontend : `services/api.service.ts` n'est plus importé nulle part : à supprimer.
- **Registre des images de monitoring** : la production les tire de Docker Hub
  (`stefy237/…`) alors que la CI et `deploy_harbor.sh` les poussent vers Harbor — choisir un
  registre unique.
- Ajouter Redis et un worker Celery à la pile Compose (simulation d'inondation en dev).
- **Recenser les passerelles radio** et leur créer un compte MQTT chacune : le broker de .114 est
  authentifié avec liste de droits depuis le 06/11/2026 (§ 10.2), mais un seul compte de
  passerelle (`passerelle1`) existe pour l'instant. Un compte par site, pour que révoquer un site
  n'oblige pas à reconfigurer les autres.
- Métriques métier à venir : messages radio reçus (alerte `MeshSilent`, à partir de
  `MessageMeshLog`) et délai entre une demande et sa prise en charge.
- Logs centralisés (Loki + Grafana Alloy) : en place sur .114 pour le WAF et fail2ban (20/10/2026) ;
  restent les journaux applicatifs (backend, Celery, Synapse).
- Mettre à jour l'image Grafana (vulnérabilités signalées sur `13.0.11`) et les digests des
  images de base.
- Documents obsolètes à archiver : `DOCUMENTATION.pdf`, `Documentation_technique.pdf`,
  `IMPROVEMENTS.md`, `TEST_STRATEGY.md` (décrivent l'ancienne version du projet).

---

## 16. Références

- [README.md](README.md) — présentation, licence, démarrage rapide
- [monitoring/README.md](monitoring/README.md) — exploitation du monitoring
- [til-monitoring.md](til-monitoring.md) — cours sur l'observabilité appliqué au projet
- [backend/README.md](backend/README.md) — point d'entrée dans le code backend, commandes de gestion
- READMEs des modules : [frontend](frontend/README.md), [proxy](proxy/README.md),
  [satellite](satellite/README.md), [meshtastic-bridge](meshtastic-bridge/README.md),
  [meshcore-bridge](meshcore-bridge/README.md), [matrix-bridge](matrix-bridge/README.md),
  [mosquitto](mosquitto/README.md), [security](security/README.md)
- `.github/agents/assista-crise-reprise.agent.md` — méthode de reprise du projet
