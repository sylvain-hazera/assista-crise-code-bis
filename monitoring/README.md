# Monitoring — exploitation

Procédures et commandes. Architecture, liste des métriques et des alertes, principes :
[DOCUMENTATION.md, § 9](../DOCUMENTATION.md#9-monitoring).

## Contenu du dossier

| Dossier | Contenu |
|---|---|
| `prometheus/` | image : `prometheus.yml` (cibles), `alerts.yml` (règles), `alerts_test.yml` (tests, exécutés au build) |
| `alertmanager/` | image : `alertmanager.prod.yml` (SMTP + healthchecks.io) ; `alertmanager.yml` (dev, MailHog) est monté par l'override |
| `grafana/` | image : datasource et dashboards provisionnés |
| `postgres/` | création du rôle `monitoring` sur une base **neuve** (monté par la base compose) |

## Développement

```bash
./scripts/init-secrets.sh
docker compose up -d
```

| URL | |
|---|---|
| http://localhost:3000 | Grafana — `admin`, mot de passe dans `secrets/grafana_admin_password.txt` |
| http://localhost:9090 | Prometheus (cibles, alertes, PromQL) |
| http://localhost:9093 | Alertmanager (alertes actives, silences) |
| http://localhost:8025 | MailHog (emails de l'application et d'Alertmanager) |

Après modification d'une règle ou de la config : `docker compose restart prometheus` (ou
`alertmanager`). Les dashboards se modifient dans `grafana/dashboards/*.json`.

## Vérifications (également faites par la CI)

```bash
docker compose build prometheus alertmanager grafana     # build = validation complète
docker run --rm -v "$PWD/monitoring/prometheus":/m -w /m --entrypoint promtool prom/prometheus:v3.15.0 test rules alerts_test.yml
docker run --rm -v "$PWD/monitoring/alertmanager":/m --entrypoint amtool prom/alertmanager:v0.34.0 check-config /m/alertmanager.yml /m/alertmanager.prod.yml
docker run --rm -v "$PWD/monitoring/alertmanager":/m --entrypoint amtool prom/alertmanager:v0.34.0 config routes test --config.file=/m/alertmanager.prod.yml alertname=Watchdog
```

**Test de bout en bout** : `docker compose stop proxy` → email `[FIRING:1] ServiceDown` dans
MailHog après ~3 min ; `docker compose start proxy` → `[RESOLVED]` en ~5 min.

## Mots de passe sur un volume existant

Les secrets et variables `POSTGRES_*` ne s'appliquent qu'à la **création** d'un volume :

```bash
# créer le rôle monitoring sur une base qui ne l'a pas
docker compose exec db psql -U "$DB_USER" -d assista-db -c "CREATE USER monitoring WITH PASSWORD '<pg_monitoring_password.txt>'; GRANT pg_monitor TO monitoring;"
# changer son mot de passe
docker compose exec db psql -U "$DB_USER" -d assista-db -c "ALTER USER monitoring WITH PASSWORD '<pg_monitoring_password.txt>';"
# mot de passe administrateur de Grafana
docker compose exec grafana grafana cli admin reset-admin-password '<grafana_admin_password.txt>'
```

## Mise en production

1. Remplacer le `TODO` (adresse de l'équipe) dans `alertmanager/alertmanager.prod.yml`, puis
   construire et pousser les images (CI sur `prod` ou `./deploy_harbor.sh`).
2. Sur la VM, générer les secrets **hors** du dépôt :
   `sudo SECRETS_DIR=/etc/assista-crise/secrets ./scripts/init-secrets.sh`, ajouter
   `SECRETS_DIR=/etc/assista-crise/secrets` au `.env`, puis y créer `email_password.txt` (SMTP)
   et `healthchecks_url.txt` (URL de ping d'un check healthchecks.io).
3. Créer le rôle `monitoring` dans la base existante (section précédente), avec un compte
   superuser (sur .114 : `svc_dbmaint`, pas `assista_app`).
4. `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile monitoring up -d`
5. Grafana n'écoute que sur la VM : `ssh -L 3000:localhost:3000 <utilisateur>@<vm>` puis http://localhost:3000.

Mise à jour d'une image de base épinglée : `docker buildx imagetools inspect <image>`, remplacer
le `@sha256:…` dans le Dockerfile, reconstruire et relancer les tests.
