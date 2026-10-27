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
| `routage_mesh.py`, `sync_outbox.py` | routage MeshCore, synchronisation satellite → central |
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
- **Demandes de mobilisation** (`DemandeMobilisation`) : jamais présentées comme une
  réquisition légale, pouvoir réservé au préfet et au maire.
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
  - Reste à faire : le scoping territorial devrait passer par `ContactInstitution` comme le
    reste de l'application, au lieu de dépendre d'un raccourci qu'il faut penser à poser.
- **Deux institutions peuvent désigner la même collectivité**, et c'est la création qui en est
  responsable : `find_or_create_institution_from_annuaire`
  (`institution_attachment.py`) fait son `get_or_create` sur le **seul nom**, sans recouper le
  code commune ni le type. Une mairie déjà enregistrée sous un nom court
  (« Châteauneuf-du-Faou ») est donc recréée dès qu'un agent s'inscrit par l'annuaire officiel,
  qui la nomme autrement (« Mairie - Châteauneuf-du-Faou »). Conséquences observées sur la
  commune 29027 : les deux institutions déclarées acteur sur la même crise, deux équipes
  jumelles, et un adjoint dont le compte pointait sur l'une pendant que son plan vivait sur
  l'autre. La même fonction crée aussi son `InstitutionType` avec un code **en minuscules**
  (`.lower()`), d'où un catalogue où « MAIRIE » et « mairie » coexistent (4 institutions contre
  5 au 27/10/2026). Les lectures qui comptent normalisent par `.upper()`
  (`Institution.save`, `_institution_est_autorite_locale`) — **toute nouvelle comparaison sur
  `type.code` doit le faire aussi**, faute de quoi elle ignore silencieusement la moitié des
  mairies, ce qui était le cas de `backfill_zones_mon_territoire` (4 institutions traitées sur
  9).
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
- **Éléments désactivés** : équipes, offres, demandes et signalements ne sont jamais supprimés
  mais désactivés ; le backend les masque, `?actif=all` les fait réapparaître pour les
  réactiver.
- **Photos** : les champs `photo` sont `write_only` ; l'aperçu passe par l'action `/preview/`,
  qui renvoie un blob converti en object URL (un 403 laisse simplement la vignette vide).

### 6.3 Cartographie (MapLibre)

- Trois composants : `MapComponent` (carte générale, clustering), `MinimapComponent` (point en
  lecture seule) et `ZoneMapComponent` (dessin de polygone avec TerraDraw, émis en WKT).
- **Pièges MapLibre** : la taille du canvas est fixée à l'initialisation (un `ResizeObserver`
  appelle `resize()`, puis recadre si besoin) ; l'événement `load` n'est pas rejoué pour un
  écouteur ajouté après coup (`runWhenMapReady` teste `isStyleLoaded()`) ; les propriétés
  tableau/objet d'une source GeoJSON sont sérialisées en chaîne JSON.
- Demandes, offres et signalements partagent une source clusterisée : les masquer retire leurs
  features de la source, sinon les clusters les compteraient encore.
- **Calques chargés à la demande** : l'annuaire de bénévoles (jusqu'à ~1 300 fiches pour un
  secteur régional) et les relais MeshCore ne sont chargés qu'à la première activation
  (performance, minimisation des données de position).
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
    │                            menu utilisateur
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
`sysadmin`, `validation-comptes`, `autorite-locale`, `registre-vulnerables`. Masquer une entrée
ne protège rien : la route doit avoir la garde correspondante. Un test de la spec de
`admin-sidebar` vérifie que chaque entrée `/admin/...` pointe vers une route existante et que
cette route porte la garde associée à sa `visibilite`.

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
- **Salons** : un salon privé par équipe (`SalonMatrixEquipe`, activé à la demande) et deux
  par institution (`PERMANENTS` pour le personnel, `BENEVOLES` pour les membres de ses équipes
  actives). `matrix-bridge` les crée puis **resynchronise les membres en continu** depuis
  l'API ; le salon de la cellule de crise n'expulse personne (pas de membres formels).
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
- Ports publiés : 80/443 (proxy), 1883 (MQTT), Grafana sur `127.0.0.1:3000` uniquement.
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
| blackbox-exporter | sonde HTTPS de https://assista-crise.fr | boîte noire |

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
le build). La production n'a donc besoin d'aucun fichier de configuration sur le serveur. En
dev, l'override construit les mêmes images puis monte les fichiers par-dessus.

### 9.5 Ajouter…

- **une métrique métier** : un `Counter` / une jauge dans `core/metrics.py` (labels bornés),
  un test dans `core/tests/plateforme/test_metrics.py`, un panneau dans le dashboard JSON ;
- **une alerte** : une règle dans `alerts.yml` + un test dans `alerts_test.yml`, puis
  `docker compose build prometheus` ;
- **un service à surveiller** : son exporter dans `docker-compose.yml` (profil `monitoring`), un
  `scrape_config` dans `prometheus.yml`, une alerte sur sa métrique `*_up`.

---

## 10. Sécurité

### 10.1 Chiffrement des données personnelles

Les colonnes contenant des données personnelles (demandeurs, bénévoles, signalements,
personnes recherchées, déclarations de sécurité, interlocuteurs PCS, messages mesh, adresses des
enjeux communaux, emails et téléphones des comptes…) sont chiffrées **par l'application**
(`core/crypto_fields.py`) : un accès au disque, un `pg_dump` ou une requête SQL ne lit que du
texte chiffré. La règle ne souffre pas d'exception « parce que c'est un établissement » : une
liste d'enjeux finit toujours par contenir l'adresse d'une personne (voir § 5.12).

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
- **Hors périmètre** : géométries (PostGIS doit les lire), `AuditLog`, informations
  publiques d'une institution (nom, marque blanche). La géométrie étant inchiffrable, un objet
  qui désigne une personne n'en porte pas : les coordonnées d'un domicile vont dans un
  `EncryptedJSONField` et `location` reste nul (`SiteSensible.donnees_personnelles`).
- En dev, `init-secrets.sh` génère les clés dans `.env`. En production, elles sont injectées
  hors du dépôt (`backend.env` sur la machine) : elles doivent être **sauvegardées ailleurs
  que sur le serveur**.
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
- **MQTT** : authentifié **en dev** (`mosquitto/config/mosquitto.dev.conf`, comptes `exporter`
  et `dev` dont les mots de passe sont dans `.env`). En production, l'accès reste **anonyme**
  sur le port 1883 publié : n'importe qui peut lire ou publier sur le broker. L'activer exige un
  compte pour chaque appareil et pont radio — décision d'équipe, procédure dans
  [mosquitto/README.md](mosquitto/README.md).

---

## 11. Tests et qualité

```bash
docker compose exec backend pytest -o addopts="" --no-cov                    # suite backend complète (~7 min)
docker compose exec backend pytest -o addopts="" --no-cov core/tests/mesh/   # un domaine
docker compose exec backend pytest core/tests/plateforme/test_metrics.py     # un fichier
docker compose exec backend pytest core/tests/mesh/test_meshcore.py -k canal # tests dont le nom contient « canal »
cd frontend && npm test                                                      # frontend (Karma)
```

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
- **Authentification MQTT en production** (accès anonyme aujourd'hui, voir § 10.2) : recenser
  les clients radio, leur créer un compte, puis appliquer la configuration de dev.
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
