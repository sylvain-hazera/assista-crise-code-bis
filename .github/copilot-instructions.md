# Copilot instructions for Assista-Crise

This file gives succinct, actionable guidance to AI coding assistants working on this repository. Focus on concrete, discoverable patterns and commands used by developers here.

1) Big-picture architecture
- Frontend: an Angular 19 single-page app in `frontend/`. Entry is `frontend/src/main.ts`. Routes are defined in `frontend/src/app/app.routes.ts` and the public section is exported as `PUBLIC_ROUTES` from `frontend/src/app/public/public.routes.ts`.
- Backend: a minimal Django project in `backend/app/` (Django settings at `backend/app/config/settings.py`). The Django project currently exposes only `admin/` in `config/urls.py`.
- Data: development uses SQLite (`backend/app/db.sqlite3` as configured in settings). There is no configured production DB in the repo.

2) How the pieces communicate / dev flow
- The frontend runs independently (ng serve) and the backend runs with Django's dev server. There is no automatic proxy config in the repo; APIs (if added) will be served from Django and consumed by the Angular app (CORS/proxy should be added if needed).
- Docker: a `docker-compose.yml` file exists but is empty — do not assume docker orchestration is configured. If you add docker support, update the compose file and README.

3) Developer commands (precise)
- Frontend (dev):
  - cd frontend && npm ci && npm start    # starts `ng serve` on http://localhost:4200
  - Build: `cd frontend && npm run build` (artifacts -> `dist/`)
  - Tests: `cd frontend && npm test`
- Backend (dev):
  - Create venv, install Django: `python3 -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt`.
    - NOTE: `backend/requirements.txt` is currently empty. The Django version in `settings.py` is 6.0.1 — if requirements remain empty, install `django==6.0.1` manually.
  - Run: `cd backend/app && python manage.py migrate && python manage.py runserver` (default http://127.0.0.1:8000)

4) Project-specific conventions and patterns
- Routing: the app uses a top-level router in `app.routes.ts` that lazy-loads logical route groups. Example: `loadChildren: () => import('./public/public.routes').then(m => m.PUBLIC_ROUTES)` — prefer returning route arrays named `PUBLIC_ROUTES` when adding new route groups.
- Lazy components: many routes use `loadComponent` to lazy-load standalone components (see `frontend/src/app/public/public.routes.ts` for examples). Follow the same pattern for new standalone/lazy components.
- Forms and components: public forms live under `frontend/src/app/public/forms/` and are individually lazy-loaded.
- Keep Angular CLI version compatibility in mind: project used Angular CLI v19.1.2 (see `frontend/README.md`). Use matching global CLI or `npx` when necessary.

5) Integration points & external deps to watch
- No external APIs are configured in-code. If adding third-party services, update README and add required environment variables.
- Hardware/mock: `backend/mock_serial.py` exists and may be used to simulate serial input — review before modifying hardware integration.

6) Quick navigation map (files to check first)
- `frontend/package.json` — scripts & dependencies (Angular, Material, etc.)
- `frontend/src/app/app.routes.ts` — top-level routing and lazy loading
- `frontend/src/app/public/public.routes.ts` — canonical example of route arrays, `loadComponent` usage
- `backend/app/config/settings.py` — Django configuration (DB, DEBUG, INSTALLED_APPS)
- `backend/app/manage.py` — Django entrypoint

7) When you modify project behavior
- If you add backend APIs, add CORS/proxy instructions and sample `.env` or sample proxy config in `frontend/`.
- If you add Docker support, populate `docker-compose.yml` and document `docker-compose up` commands in the root README and here.

8) Tests and quality gates
- Frontend: `ng test` (Karma) — add unit tests alongside components in the current project pattern.
- Backend: no automated tests found. If you add tests, include a `pytest` or Django `manage.py test` instruction here.

If anything in these instructions is unclear or you want more detail (for example: typical API shapes, environment variables, or CI commands), tell me which area and I will expand or merge with existing docs from `.github/` or `frontend/README.md`.

References: `frontend/README.md`, `frontend/package.json`, `frontend/src/app/public/public.routes.ts`, `frontend/src/app/app.routes.ts`, `backend/app/config/settings.py`, `backend/app/manage.py`, `backend/mock_serial.py`
