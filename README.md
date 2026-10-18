# Assista-Crise

Application de gestion de crise et d'entraide citoyenne.
Plateforme web permettant la mise en relation entre citoyens et autorités locales lors de catastrophes (incendies, inondations), incluant une cartographie en temps réel.

## Avertissement — un outil complémentaire, pas un substitut

Assista-Crise est un outil d'appui à la gestion de crise. Il ne remplace **en aucun cas** le
Plan Communal de Sauvegarde (PCS) ni le Plan Intercommunal de Sauvegarde (PICS) d'une
collectivité. Une collectivité locale doit conserver ses procédures établies sur support
papier et être en mesure de gérer une crise sans dépendre de la disponibilité du site —
celui-ci vient en complément de ces procédures, jamais en substitution.

## Nom et marque

« Assista-Crise », son nom et son logo sont réservés à leur auteur (Sylvain Hazera). Toute
redistribution ou fork doit être clairement renommé(e) et ne doit pas laisser entendre un
lien ou un soutien avec le projet original.

## Licence

Ce projet est distribué sous licence **AGPL-3.0** (GNU Affero General Public License v3.0) —
voir le fichier [LICENSE](LICENSE). En résumé : le code est libre, réutilisable et modifiable,
y compris à l'étranger, mais toute version modifiée exploitée comme service en ligne doit
republier ses modifications sous la même licence.

## Stack technique

* **Backend :** Django 5 + Django REST Framework, gunicorn, Celery (Python)
* **Frontend :** Angular 19 + MapLibre GL (TypeScript)
* **Base de données :** PostgreSQL + PostGIS
* **Communication :** emails, Matrix/Element, réseaux radio MeshCore et Meshtastic (MQTT)
* **Infrastructure :** Docker Compose, Nginx, monitoring Prometheus / Alertmanager / Grafana

## Démarrage rapide

Prérequis : Docker (Compose v2), Git, `openssl`.

```bash
./scripts/init-secrets.sh      # crée .env et secrets/ (n'écrase jamais l'existant)
docker compose up -d --build   # application + monitoring
```

`.env` contient aussi les clés de chiffrement des données personnelles : **sauvegardez-le**,
sans lui les données chiffrées de votre base deviennent illisibles.

| Adresse | Service |
|---|---|
| http://localhost | application (via Nginx) |
| http://localhost:8000/api/docs/ | documentation de l'API (Swagger) |
| http://localhost/django-admin/ | administration Django |
| http://localhost:8025 | emails envoyés en développement (MailHog) |
| http://localhost:3000 | Grafana (monitoring) |

Créer le premier administrateur, puis des données de test :

```bash
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py generate_crise_gier_pilat --total 100   # scénario de démo
```

## Commandes utiles

```bash
docker compose logs -f backend                        # logs du backend
docker compose exec backend python manage.py <cmd>    # commande Django
docker compose exec backend pytest -o addopts="" --no-cov   # tests backend (tous)
docker compose exec backend pytest core/tests/mesh/          # tests d'un domaine
docker compose down                                   # arrêt (données conservées)
docker compose down -v                                # arrêt + suppression de toutes les données
```

## Documentation

* **[DOCUMENTATION.md](DOCUMENTATION.md)** — architecture, code, environnements, sécurité, tests,
  déploiement, pièges connus et chantiers ouverts : **à lire pour reprendre le projet.**
  Les tests backend sont rangés par domaine dans `backend/core/tests/` (comptes, securite,
  crises, citoyens, equipes, mesh…) : où placer un nouveau test, voir son § 11.1.
* [monitoring/README.md](monitoring/README.md) — exploitation du monitoring.
* READMEs des modules : [backend](backend/README.md), [frontend](frontend/README.md),
  [proxy](proxy/README.md), [satellite](satellite/README.md),
  [meshtastic-bridge](meshtastic-bridge/README.md), [meshcore-bridge](meshcore-bridge/README.md),
  [matrix-bridge](matrix-bridge/README.md), [mosquitto](mosquitto/README.md),
  [tileserver](tileserver/README.md), [security](security/README.md).
