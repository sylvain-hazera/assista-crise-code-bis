# Frontend — application Angular d'Assista-Crise

Interface web de la plateforme : Angular 19 (composants standalone) et MapLibre GL pour la
cartographie. Ce README sert de point d'entrée dans le code frontend. Les rôles, flux métier,
pièges de la carte et le menu d'administration sont détaillés dans
[DOCUMENTATION.md](../DOCUMENTATION.md), § 6.

## Démarrer

### Avec Docker (recommandé)

Le frontend tourne avec le reste de la pile (voir le [README principal](../README.md)) :

```bash
./scripts/init-secrets.sh          # depuis la racine, une seule fois
docker compose up -d --build
docker compose logs -f frontend
```

En dev, `docker-compose.override.yml` construit `Dockerfile.dev` (`ng serve`, rechargement à
chaud) et monte `frontend/` dans le conteneur : une modification du code est visible sans
reconstruire l'image.

| URL | |
|---|---|
| http://localhost | application via Nginx (recommandé : `/api` et le reste sur la même origine) |
| http://localhost:4200 | serveur de dev Angular en direct |

### Sans Docker

Le backend doit tourner (API attendue sur `http://localhost:8000/api`) :

```bash
cd frontend
npm ci          # installe exactement les versions de package-lock.json
npm start       # ng serve sur http://localhost:4200
```

## Commandes

```bash
npm start                 # serveur de dev
npm run build             # build de production dans dist/assista-crise-front/browser
npm run watch             # build de dev continu
npm test                  # tests unitaires Karma/Jasmine (navigateur, mode watch)
npm run test:ci           # tests une fois, Chrome headless, avec couverture
npx ng generate component admin/ma-page   # nouveau composant (standalone par défaut)
```

Les tests Karma ont besoin d'un Chrome : lancez-les sur le poste, pas dans le conteneur de dev
(image `node:alpine` sans navigateur). La CI ne les exécute pas encore.

## Organisation de `src/`

| Dossier | Contenu |
|---|---|
| `app/app.routes.ts` | routes racine : charge paresseusement `public/public.routes.ts` et `admin/admin.routes.ts` |
| `app/public/` | pages publiques : accueil, carte, formulaires (demande, offre, déclaration), suivi de dossier, paramètres, pages légales |
| `app/admin/` | espace d'administration (`/admin`) : une page par dossier (crises, équipes, institutions, signalements, radio, satellites…) |
| `app/pages/` | pages connectées hors admin : mes interventions, mon équipe, hébergement, recherche de personnes, dégâts |
| `app/layouts/` | coquilles publique et admin, avec leurs morceaux : `public-layout/` (`header/`, `footer/`, `geolocation-popup/`), `admin-layout/` (menu : `admin-nav.config.ts`, `admin-sidebar/` ; en-tête : `admin-header/`, avec la cloche `admin-header/admin-notifications/`) |
| `app/auth/` | connexion, inscription, `AuthService` (session, rôles, zone PROD/DEMO), intercepteurs (JWT, `X-Environment`) |
| `app/core/` | gardes de routes (`guards/`), intercepteurs, pipes et services transverses |
| `app/services/` | un service par ressource d'API (`crisis.service.ts`, `team.service.ts`…) |
| `app/shared/` | composants utilisés par **au moins deux** pages ou layouts (`components/common/` : cartes, modales… ; `components/public/` : briques des formulaires publics), modèles TypeScript (`models/`), utilitaires (`utils/`) |
| `environments/` | `environment.ts` (dev, API sur `http://localhost:8000/api`), `environment.prod.ts` (API relative `/api`) |
| `assets/`, `fonts.scss` | images ; polices auto-hébergées (fichiers dans `../public/assets/fonts/`, aucun appel à Google Fonts) |

## Ajouter une page

1. Créer un composant standalone dans le bon groupe (`public/`, `admin/` ou `pages/`).
2. Déclarer la route avec `loadComponent` dans `public.routes.ts` ou `admin.routes.ts`, avec la
   garde adaptée (`authGuard`, `institutionalEffectiveGuard`, `sysAdminGuard`…, voir
   DOCUMENTATION.md, § 6.1).
3. Pour une page d'administration, l'ajouter dans `layouts/admin-layout/admin-nav.config.ts`
   avec la bonne `visibilite` (§ 6.4) : sinon elle n'est atteignable que par son URL.
4. Appeler l'API via un service de `app/services/`. Pour un rafraîchissement périodique,
   utiliser `pollWhileVisible` (`shared/utils/polling.util.ts`) plutôt qu'un `setInterval`.

Le frontend masque ce que le backend refuserait, mais **le contrôle d'accès réel est toujours
côté serveur** : ne jamais compter sur une garde Angular pour protéger une donnée.

## Production

`Dockerfile.prod` compile l'application (`npm run build`) puis la sert avec un Nginx léger
(`nginx.conf` : repli sur `index.html` pour le routage Angular, `index.html` toujours revalidé
et chunks JS/CSS hachés mis en cache longue durée). La CI
construit et pousse cette image, et le proxy Nginx de la pile la place devant le backend sur
la même origine (voir [proxy/README.md](../proxy/README.md)).

## Pièges fréquents

| Symptôme | Cause et solution |
|---|---|
| `Cannot find module 'terra-draw'` (ou un autre paquet) | `node_modules` local plus ancien que `package.json` : `npm ci` |
| La carte est tronquée ou mal cadrée | taille du canvas MapLibre fixée à l'initialisation : voir DOCUMENTATION.md, § 6.3 |
| Une page admin n'apparaît pas dans le menu | entrée absente de `admin-nav.config.ts`, `visibilite` trop restrictive, ou rôle effectif non institutionnel (zone DEMO) |
| `ng test` : `EACCES` sur `.angular/cache` | cache créé par le conteneur (root) : lancer avec `CI=true` (désactive ce cache) ou supprimer `.angular/` avec `sudo` |
| Un droit accordé n'apparaît pas | profil en cache : recharger la page (les gardes rafraîchissent `/api/auth/me/`) |
