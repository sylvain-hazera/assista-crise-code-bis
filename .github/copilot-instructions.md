# Instructions pour les assistants de code — Assista-Crise

La référence est **[DOCUMENTATION.md](../DOCUMENTATION.md)** (architecture, conventions, tests,
pièges connus). Résumé des points à respecter :

- **Pile** : Django 5 + DRF + PostGIS (`backend/`, application unique `core/`), Angular 19
  standalone + MapLibre (`frontend/`), Nginx (`proxy/`), Docker Compose (base + override dev +
  prod), monitoring Prometheus/Alertmanager/Grafana (`monitoring/`).
- **Lancer** : `./scripts/init-secrets.sh` puis `docker compose up -d --build` ; application sur
  http://localhost.
- **Tests** : `docker compose exec backend pytest -o addopts="" --no-cov` (backend, pytest) ;
  `cd frontend && npm test` (Karma). 1 test backend échoue déjà sur `main` ; les clés de
  chiffrement doivent être dans `.env` (sinon une quinzaine d'échecs de plus).
- **Où écrire un test backend** : dans `backend/core/tests/<domaine>/` (comptes, securite,
  audit, crises, citoyens, dossiers, equipes, institutions, zones, moyens, mesh, satellites,
  plateforme). D'abord le fichier existant de la fonctionnalité ; sinon `test_<sujet>.py` dans
  le domaine de la fonctionnalité testée ; règles transverses (confidentialité, PROD/DEMO,
  chiffrement, permissions) dans `securite/`. Tout nouveau dossier a un `__init__.py`. Ne
  jamais recréer `core/tests.py`. Détail : DOCUMENTATION.md, § 11.1.
- **Backend** : migrations écrites en dev et commitées ; nouvelle ressource = modèle +
  serializer + ViewSet enregistré dans `core/urls.py` + permissions + tests ; respecter
  `EnvironmentScopedModel` (isolation PROD/DEMO) et `zone_scoping.py`.
- **Frontend** : pages en composants standalone chargés par `loadComponent` dans
  `public/public.routes.ts` ou `admin/admin.routes.ts` ; une page admin s'ajoute au menu dans
  `layouts/admin-layout/admin-nav.config.ts`. Un composant ne va dans `shared/components/` que
  s'il sert à au moins deux pages ou layouts (DOCUMENTATION.md, § 6).
- **Proxy** : toute route ajoutée à `proxy/nginx.conf` doit l'être aussi dans `proxy/nginx.dev.conf`.
- **Sécurité** : jamais de secret dans le code ou git (`.env`, `secrets/`) ; ne pas publier de
  nouveau port en production.
- **Style** : commentaires et commits en français ; un commentaire court explique le
  *pourquoi*, sans historique ; les explications d'architecture vont dans DOCUMENTATION.md.
- **Chiffrement** : ne jamais filtrer `email=` ni `icontains` sur un champ chiffré : passer par
  l'index aveugle (`*_bidx`, `blind_index()`) ; voir DOCUMENTATION.md, § 10.1.
- **Prudence** : ne jamais lancer `docker compose down -v`, supprimer un volume ou réécrire
  l'historique git sans accord explicite (voir `.github/agents/assista-crise-reprise.agent.md`).
