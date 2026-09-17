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

## Stack Technique

* **Backend :** Django 5 + Django REST Framework (Python)
* **Frontend :** Angular 19 + MapLibre GL (TypeScript)
* **Base de données :** PostgreSQL + PostGIS (Spatial)
* **Infrastructure :** Docker & Docker Compose

## Prérequis

Avant de lancer le projet, assurez-vous d'avoir installé :
* Docker
* Git

## Installation et Démarrage

### 1. Lancer l'application
À la racine du projet (au niveau du fichier docker-compose.yml), ouvrez un terminal et exécutez la commande suivante :

```bash
docker compose up -d --build
```
Note : L'option --build force la reconstruction des images pour inclure les nouvelles dépendances. Le premier démarrage peut prendre quelques minutes le temps que la base de données PostGIS s'initialise complètement.

### 2. Accéder aux services

Une fois les conteneurs actifs, les services sont accessibles aux adresses suivantes :

- Frontend (Application Web) : http://localhost:4200
- Backend (API REST) : http://localhost:8000/api/
- Documentation API (Swagger UI) : http://localhost:8000/api/docs/
- Administration Django : http://localhost:8000/admin/**

## Arrêt et Nettoyage
### Arrêt standard

Pour arrêter les conteneurs tout en conservant les données enregistrées dans la base de données :


```bash
docker compose down
```

### Arrêt complet (Réinitialisation)

Pour arrêter les conteneurs et supprimer le volume de la base de données (remise à zéro complète) :


```bash
docker compose down -v
```

Attention : Cette commande effacera toutes les données (utilisateurs, crises, signalements) créées depuis le dernier lancement.
## Commandes utiles pour le développement
### Consulter les logs
Pour voir les logs du backend pour debug :

```bash
docker compose logs -f backend
```

### Exécuter des commandes Django

Pour exécuter des commandes administratives (migrations, shell, etc.) à l'intérieur du conteneur backend :
```bash
docker compose exec backend python manage.py <votre_commande>
```

Exemple pour créer les migrations manuellement :
```bash
docker compose exec backend python manage.py makemigrations
```

### Reconstruire le Frontend

En cas de problème avec les dépendances npm ou node_modules :
```bash
docker compose build --no-cache frontend
docker compose up -d
```
