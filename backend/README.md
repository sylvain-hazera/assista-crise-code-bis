# Backend — API Django d'Assista-Crise

API REST de la plateforme : Django 5 + Django REST Framework + PostGIS, servie par gunicorn.
Ce README sert de point d'entrée dans le code backend ; l'architecture détaillée (zones de
compétence, contrôle d'accès, chiffrement, satellites…) est dans
[DOCUMENTATION.md](../DOCUMENTATION.md), § 5.

## Démarrer

Le backend tourne dans Docker avec le reste de la pile (voir le [README principal](../README.md)) :

```bash
./scripts/init-secrets.sh            # depuis la racine : .env (base, SECRET_KEY, clés de chiffrement)
docker compose up -d --build
docker compose logs -f backend
```

| URL | |
|---|---|
| http://localhost:8000/api/ | API REST (ou http://localhost/api/ via Nginx) |
| http://localhost:8000/api/docs/ | documentation Swagger, générée depuis le code |
| http://localhost/django-admin/ | administration Django : consulter et **modifier** les données |
| http://localhost:8000/metrics | métriques Prometheus (non routé par Nginx) |

Le code est monté dans le conteneur, mais gunicorn ne recharge pas automatiquement :
`docker compose restart backend` après une modification.

## Organisation

```
backend/
├── config/                 projet Django
│   ├── settings.py         réglages, tous pilotés par variables d'environnement
│   ├── urls.py             routes racine : /api/, /django-admin/, /o/ (OIDC), /metrics
│   ├── celery.py           application Celery (simulation d'inondation)
│   └── wsgi.py, asgi.py
├── core/                   l'application unique
│   ├── models.py           tous les modèles (~150 classes)
│   ├── serializers.py      sérialisation, validation, masquage DEMO, visibilité des champs
│   ├── views.py            ViewSets et vues dédiées
│   ├── urls.py             enregistrement des routes de /api/
│   ├── migrations/         migrations commitées (schéma et données de référence)
│   ├── management/commands/  commandes manage.py (voir plus bas)
│   ├── tests/<domaine>/    tests pytest rangés par domaine
│   ├── templates/, static_assets/, fixtures/   page de connexion OIDC, logos, marque blanche
│   └── *.py                modules métier (tableau ci-dessous)
├── conftest.py             fixtures pytest partagées
├── pytest.ini, .coveragerc configuration des tests et de la couverture
├── entrypoint.sh           démarrage du conteneur
├── Dockerfile              image de production (non-root, uid 10001)
├── requirements.txt        dépendances Python
└── generate_test_data.py, update_status.py   scripts de dev (voir plus bas)
```

### Modules de `core/`

| Thème | Modules |
|---|---|
| Accès et sécurité | `permissions.py` (rôles), `zone_scoping.py` (zones de compétence), `auth_validation.py`, `validators.py`, `middleware.py`, `crypto_fields.py` / `file_crypto.py` (chiffrement) |
| Traçabilité | `audit.py` (`AuditLog`), `logging_handlers.py` (erreurs vers Matrix), `metrics.py` (Prometheus) |
| Institutions | `institution_attachment.py` (rattachement des comptes), `branding.py` (marque blanche), `convention_sous_traitance.py` (RGPD), `besoins_ecoute.py` |
| Géographie | `geo_lookup.py` (geo.api.gouv.fr, Géorisques, cache en base), `geo_reference.py` (niveaux de secteur) |
| Crise et terrain | `alertes_pcs.py`, `habitations.py` (dégâts), `vulnerabilites.py` (registre sensible), `attestation_mobilisation.py` (PDF) |
| Simulation d'inondation | `inondation.py`, `ruissellement.py`, `hydrometrie.py`, `tasks.py` (Celery) |
| Communication | `matrix.py`, `oidc.py` (SSO), `routage_mesh.py` (MeshCore) |
| Satellites | `sync_outbox.py` (synchronisation vers le central) |
| Échanges de fichiers | `imports.py` (CSV/XLS), `export.py` |

## Ajouter une fonctionnalité

1. **Modèle** dans `models.py` : hériter d'`EnvironmentScopedModel` si la donnée est un
   contenu propre à PROD ou à DEMO ; chiffrer les données personnelles
   (`EncryptedTextField`, index aveugle `*_bidx` si une recherche exacte est nécessaire).
2. **Migration** : `docker compose exec backend python manage.py makemigrations`, relire le
   fichier généré, le commiter.
3. **Serializer** : champs sensibles en `read_only` / `write_only`, visibilité selon la zone
   (`object_in_viewer_zone`), masquage en DEMO.
4. **ViewSet** dans `views.py`, enregistré dans `core/urls.py` ; permissions explicites et
   `filter_queryset_to_viewer_zone` dans `get_queryset`.
5. **Tests** dans `core/tests/<domaine>/` (voir plus bas).
6. Si une nouvelle route publique est ajoutée hors `/api/`, la reporter dans
   `proxy/nginx.conf` **et** `proxy/nginx.dev.conf`.

Règles à connaître avant de coder : [DOCUMENTATION.md](../DOCUMENTATION.md), § 5.5
(PROD/DEMO, zones), § 5.6 (contrôle d'accès), § 10.1 (chiffrement), § 13 (conventions).

## Tests

```bash
docker compose exec backend pytest -o addopts="" --no-cov                  # tout (~8 min)
docker compose exec backend pytest -o addopts="" --no-cov core/tests/mesh/ # un domaine
docker compose exec backend pytest core/tests/mesh/test_meshcore.py -k canal
docker compose exec backend pytest                                         # avec couverture (htmlcov/index.html)
```

Les tests sont rangés par domaine fonctionnel :

| Dossier | Domaine |
|---|---|
| `comptes/` | inscription, connexion, mots de passe, désactivation |
| `securite/` | confidentialité, PROD/DEMO, permissions transverses, chiffrement |
| `audit/` | main courante |
| `crises/` | crises, implications, plans, demandes de mobilisation |
| `citoyens/` | demandes, offres, signalements, déclarations de sécurité |
| `dossiers/` | dossiers et missions |
| `equipes/` | équipes, délégations, ressources, positions |
| `institutions/` | institutions, imports, rattachement, convention RGPD, personnes vulnérables |
| `zones/` | zones de compétence, vues mairie/secteur, géographie |
| `moyens/` | points opérationnels, matériel, registre de présence |
| `mesh/` | MeshCore, Meshtastic, alertes sismiques |
| `satellites/` | enrôlement, supervision, synchronisation |
| `plateforme/` | transverse : API, performances, métriques, emails |

**Où placer un nouveau test** : dans le fichier existant de la fonctionnalité ; sinon un
nouveau `test_<sujet>.py` dans le dossier du domaine testé ; une règle transverse
(confidentialité, PROD/DEMO, chiffrement, permissions) va dans `securite/`. Tout nouveau
dossier contient un `__init__.py`. Détails : [DOCUMENTATION.md](../DOCUMENTATION.md), § 11.1.

Les clés de chiffrement doivent être présentes dans `.env`, sinon une quinzaine de tests
échouent.

## Commandes de gestion

`docker compose exec backend python manage.py <commande>`

| Commande | Rôle |
|---|---|
| `import_communes 38 73` (ou `all`) | charge le référentiel des communes d'un ou plusieurs départements (préalable aux générateurs par population) |
| `generate_crise_gier_pilat [--total N] [--delete]` | scénario de démonstration complet (zone DEMO) |
| `generate_benevoles_pompiers 38 69 [--total N]` | simule des bénévoles par commune (DEMO, tests de volume) |
| `generate_benevoles_pompiers_national [--total N]` | idem sur toute la France, sur de vraies adresses BAN |
| `cleanup_crises [--dry-run]` | supprime les données des crises closes depuis plus de 30 jours (RGPD), avec archive CSV sans coordonnées |
| `purge_audit_logs` | supprime les entrées d'`AuditLog` plus anciennes que `AUDIT_LOG_RETENTION_DAYS` |
| `verifier_alertes_sismiques` | diffuse sur le mesh les séismes récents proches des institutions abonnées |
| `backfill_zones_mon_territoire` | rattrapage de la Zone « Mon territoire » des collectivités créées avant son automatisation |
| `synchroniser_sortant` / `synchroniser_entrant` | synchronisation satellite ↔ central (sur un satellite `full`) |

`cleanup_crises`, `purge_audit_logs` et `verifier_alertes_sismiques` sont prévues pour être
planifiées (cron) en production.

Scripts de développement à la racine du backend :

- `generate_test_data.py [--env DEMO] [--yes]` : ~145 crises, demandes, offres et
  informations réparties en France, avec des comptes de test (mot de passe `test123`) ;
  demande confirmation.
- `update_status.py` : remet toutes les demandes, offres et informations à « Non traitée ».
- `mock_serial.py` : fichier vide hérité du projet initial.

## Image et démarrage

`entrypoint.sh` exécute, à chaque démarrage : `migrate` → création d'un superutilisateur si
`DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` sont définis → types de demandes,
offres et informations par défaut → `collectstatic` → gunicorn (`GUNICORN_WORKERS`, 3 par
défaut, délai 60 s).

L'image (`Dockerfile`) part d'une image Python épinglée par digest et tourne sous
l'utilisateur non-root `appuser` (uid 10001). Les métriques des workers gunicorn sont
agrégées via `PROMETHEUS_MULTIPROC_DIR`.

## Configuration

Toutes les variables d'environnement sont décrites dans
[DOCUMENTATION.md](../DOCUMENTATION.md), § 5.4. Les indispensables : `DB_USER`, `DB_PASS`,
`SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `FIELD_BLIND_INDEX_KEY`, `FILE_ENCRYPTION_KEY`, toutes
générées en dev par `./scripts/init-secrets.sh`.

## Accéder aux données

- **Admin Django** (`/django-admin/`) : la seule interface qui affiche et modifie les champs
  chiffrés en clair. Créer un compte : `manage.py createsuperuser`.
- **Shell** : `docker compose exec backend python manage.py shell`.
- **SQL** : `localhost:5432`, base `assista-db`, en lecture seulement : une écriture directe
  dans une colonne chiffrée ou un email casse la lecture et la connexion.
