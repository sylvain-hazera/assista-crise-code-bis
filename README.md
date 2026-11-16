# Assista-Crise

Application de gestion de crise et d'entraide citoyenne.
Plateforme web permettant la mise en relation entre citoyens et autorités locales lors de catastrophes (incendies, inondations), incluant une cartographie en temps réel.

## Avertissement — un outil complémentaire, pas un substitut

Assista-Crise est un outil d'appui à la gestion de crise. Il ne remplace **en aucun cas** le
Plan Communal de Sauvegarde (PCS) ni le Plan Intercommunal de Sauvegarde (PICS) d'une
collectivité. Une collectivité locale doit conserver ses procédures établies sur support
papier et être en mesure de gérer une crise sans dépendre de la disponibilité du site —
celui-ci vient en complément de ces procédures, jamais en substitution.

## Fonctionnalités

**Avant la crise : le plan communal de sauvegarde, paragraphe par paragraphe**

Chaque paragraphe du plan a son écran, dit à quoi il sert une fois la crise ouverte, et aucun
n'est obligatoire pour en ouvrir une : on commence avec ce qu'on a, on revient compléter.

- **Risques de la commune**, avec les suggestions de Géorisques, et un **guide des risques
  majeurs** public par commune.
- **Sites sensibles** proposés depuis les bases publiques nationales (enseignement, santé,
  installations classées, équipements, défibrillateurs, élevages) ; rien n'entre au plan avant
  que la commune l'ait vérifié.
- **Registre des personnes vulnérables**, réservé aux agents nommément désignés par le maire
  (art. R. 121-7 du code de l'action sociale et des familles), chiffré, éditable en PDF par eux
  seuls — voir [BASE-LEGALE-REGISTRE-VULNERABLES.md](BASE-LEGALE-REGISTRE-VULNERABLES.md).
- **Poste de commandement et fiches réflexes** : qui dirige, qui coordonne, qui alerte, avec
  leurs suppléants ; relié aux équipes, pour ne nommer les personnes qu'une fois.
- **Dispositifs pré-enregistrés** (zones, équipes, points, missions types) activables en un
  geste, **annuaire de crise**, **moyens d'alerte**, **lieux d'accueil**, **matériel**,
  **exercices** et leurs enseignements, **simulation d'inondation**.
- **Le document du plan en PDF**, construit à la demande depuis ces données, dans l'ordre de la
  trame de l'État, avec la liste de ce qui reste à compléter ; et le **DICRIM**, le document
  d'information des habitants, sans aucune donnée personnelle.
- **Veille du territoire** sur les sources ouvertes de l'État : vigilance crues, hauteurs d'eau,
  niveau de la mer, météo et rafales, circulation et arrêtés, stations-service en rupture,
  qualité de l'air, radioactivité ambiante.

**Pendant la crise**

- **Cellule de crise**, **journal de bord** (écrit à la main et nourri par les messages des
  équipes), **main courante** automatique, supervision du poste de commandement.
- **Demandes d'aide, offres et signalements** des habitants, géolocalisés ; déclarations
  « je suis en sécurité » ; **recherche de personnes**.
- **Dossiers, missions, équipes** : affectation selon les compétences, planning, ressources
  mobilisées, centres et **hébergement** ; les équipes permanentes se réutilisent d'une crise
  à l'autre.
- **Alerte aux habitants** qui l'ont demandée : messagerie, application mobile, courriel, SMS.
  Ce n'est pas FR-Alert, qui relève du préfet.
- **Carte en temps réel** (MapLibre), avec les calques de veille ; **application Android**.

**Après la crise**

- **Recensement des dégâts**, **relogement des familles**, logement des intervenants, bilans.

**Quand les réseaux tombent**

- **Messagerie Matrix/Element** auto-hébergée : un salon par équipe, par mission et par crise.
- **Radio maillée LoRa** : ponts MeshCore et Meshtastic, carte et diagnostic des liaisons,
  planification de la couverture sur le relief, administration à distance des nœuds.
- **Satellites** : un Raspberry Pi ou un PC sur site, avec le site complet et ses cartes hors
  ligne, qui continue sans Internet et se resynchronise ensuite ; passerelle radio pour Windows.

**Pour plusieurs structures**

- Mairies, intercommunalités, associations agréées de sécurité civile et réserves communales sur
  la même plateforme, chacune dans son périmètre ; **marque blanche** par domaine.

### Par rapport au plan communal de sauvegarde (PCS)

| Volet du PCS | Assista-Crise |
|---|---|
| Document du plan (trame de l'État) | Oui : généré en PDF depuis les données, jamais rédigé à part |
| Identification des risques | Oui : risques de la commune, guide public, veille, simulation d'inondation |
| Recensement des enjeux | Oui : sites sensibles issus des bases publiques, vérifiés par la commune |
| Registre des personnes vulnérables | Oui, avec habilitation nominative et chiffrement |
| Organisation, fiches réflexes | Oui : poste de commandement, titulaires et suppléants, fiches types de la trame |
| Annuaire de crise | Oui : interlocuteurs prévenus à l'ouverture, accusés de réception suivis |
| Alerte de la population | Moyens de la commune recensés ; alerte aux habitants abonnés. **FR-Alert : non**, réservé au préfet |
| Soutien des populations, moyens | Oui : lieux d'accueil, équipes, matériel |
| Exercices, DICRIM | Oui : exercices consignés, DICRIM en PDF |
| Conduite de la crise | Oui : cellule, journal de bord, missions, entraide |
| Communication de secours sans Internet | Oui : Matrix, MeshCore, Meshtastic, satellites hors ligne |

Ce qui n'y est pas : les cartes en annexe du plan, les modèles d'arrêtés pré-remplis, un
éditeur de documents (le plan se saisit dans des formulaires).

### État du projet

En service sur [assista-crise.fr](https://www.assista-crise.fr), développé en continu. Plus de
4 000 tests automatisés côté serveur et plus de 700 côté site (novembre 2026). Sécurité et
données personnelles — chiffrement au repos, cloisonnement, journal d'audit — :
[DOCUMENTATION.md](DOCUMENTATION.md) § 10.

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
* **Frontend :** Angular 20 + MapLibre GL (TypeScript)
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
| http://localhost:3000/grafana/ | Grafana (monitoring), aussi dans l'admin : `/admin/monitoring` |

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
  [security](security/README.md).
