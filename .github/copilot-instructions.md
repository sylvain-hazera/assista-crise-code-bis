# Instructions pour les assistants de code — Assista-Crise

La référence est **[DOCUMENTATION.md](../DOCUMENTATION.md)** (architecture, conventions, tests,
pièges connus). Résumé des points à respecter :

- **Pile** : Django 5 + DRF + PostGIS (`backend/`, application unique `core/`), Angular 19
  standalone + MapLibre (`frontend/`), Nginx (`proxy/`), Docker Compose (base + override dev +
  prod), monitoring Prometheus/Alertmanager/Grafana (`monitoring/`).
- **Lancer** : `./scripts/init-secrets.sh` puis `docker compose up -d --build` ; application sur
  http://localhost.
- **Tests** : `docker compose exec backend pytest -o addopts="" --no-cov` (backend, pytest) ;
  `cd frontend && npm test` (Karma). 15 tests backend échouent déjà sur `main`.
- **Backend** : migrations écrites en dev et commitées ; nouvelle ressource = modèle +
  serializer + ViewSet enregistré dans `core/urls.py` + permissions + tests ; respecter
  `EnvironmentScopedModel` (isolation PROD/DEMO) et `zone_scoping.py`.
- **Frontend** : pages en composants standalone chargés par `loadComponent` dans
  `public/public.routes.ts` ou `admin/admin.routes.ts`.
- **Proxy** : toute route ajoutée à `proxy/nginx.conf` doit l'être aussi dans `proxy/nginx.dev.conf`.
- **Sécurité** : jamais de secret dans le code ou git (`.env`, `secrets/`) ; ne pas publier de
  nouveau port en production.
- **Style** : commentaires et commits en français ; un commentaire explique le *pourquoi*.
- **Prudence** : ne jamais lancer `docker compose down -v`, supprimer un volume ou réécrire
  l'historique git sans accord explicite (voir `.github/agents/assista-crise-reprise.agent.md`).
