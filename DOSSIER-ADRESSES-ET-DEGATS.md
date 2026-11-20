# Adresses en local, et évaluation des dégâts à pied — dossier de projet

Demande de Sylvain du 20/11/2026 : « adresses en local, recopiées vers le satellite, et vers le
smartphone au besoin uniquement (évaluation des dégâts). Sur smartphone, la personne doit pouvoir
évaluer seule, à pied : tel point, début de l'évaluation ; bien placé par rapport à l'adresse ?
oui / non, replacer ; évaluer… ; nouveau point ici, description… »

Suite de `DOSSIER-HORS-LIGNE.md` (§ 4, § 5 bis). État du code relevé le 20/11/2026.

## 1. Ce qui existe déjà, et sur quoi on s'appuie

| Brique | Où | Ce qu'elle fait |
|---|---|---|
| Pointage de terrain | `POST /api/habitations/pointer/`, `PointageTerrain` | une maison pointée à la position du téléphone ; pas de doublon à moins de 15 m ou à même adresse ; validation par la commune pour un intervenant, directe pour le personnel communal |
| Évaluation | `Habitation` (`statut_evaluation`, `nature_degats`, surfaces, valeur) | cinq états (non évaluée → détruite), huit natures (eau, feu, vent…) ; une maison détruite ouvre un dossier |
| Relevé d'adresses | `AdresseSimuleeInondation`, `scanner_ban_commune` | rempli par la simulation d'inondation ou le relevé simple, **une requête par rue** à la Base Adresse Nationale |
| Adresse la plus proche d'un point | `views_adresses._interroger` | **demandée à un service extérieur** |
| Descente vers le satellite | `SatelliteViewSet.donnees`, `sync_referentiel` | toutes les 5 min, copie à l'identique ; pas faite pour des dizaines de milliers de lignes |
| Application de terrain | `mobile/` (Kotlin) | file d'attente persistée, magasin chiffré, photos scellées (empreinte, heure, lieu), carte MapLibre |

## 2. Le référentiel d'adresses (central)

### 2.1 Une table à part entière

`AdresseBAN`, donnée publique partagée PROD/DEMO, non chiffrée (c'est le **lien** entre une
personne et une adresse qui est chiffré, comme aujourd'hui) :

| Champ | Origine (fichier BAN) |
|---|---|
| `ban_id` (clé) | `id` (clé d'interopérabilité) |
| `commune_code`, `code_postal` | `code_insee`, `code_postal` |
| `numero`, `suffixe`, `voie`, `lieu_dit` | `numero`, `rep`, `nom_voie`, `nom_ld` |
| `location`, `type_position` | `lon`, `lat`, `type_position` (entrée, bâtiment, segment…) |
| `parcelles` | `cad_parcelles` (utile au suivi des dégâts) |
| `retiree_le` | vide tant que l'adresse figure dans le fichier |
| `modifie_le` | pour la copie incrémentale |

`AdresseSimuleeInondation` garde les niveaux d'eau de la simulation, rattachés par `ban_id`.

### 2.2 Chargement

- **Source** : le fichier complet du département publié chaque nuit par la Base Adresse
  Nationale (`adresses-<dép>.csv.gz` ; Gironde : 27,5 Mo compressés, vérifié le 20/11/2026), lu
  en flux, filtré sur les communes voulues. Aucune requête par rue, aucune adresse de personne
  envoyée nulle part.
- **Quand** : à la création d'une institution et quand une commune entre dans son territoire
  (tâche de fond) ; puis **chaque semaine**, un téléchargement par département concerné.
- **Mise à jour** : ajout et modification par `ban_id` ; une adresse disparue du fichier est
  marquée `retiree_le`, jamais effacée (les fiches et les habitations qui y renvoient tiennent).
- **Quelles communes** : celles du territoire de chaque institution (commune, EPCI). Voir § 6,
  décision 1, pour les institutions départementales.

### 2.3 Ce qui s'appuie dessus

- le rattachement du registre et les secteurs vulnérables (`rattachement_adresses.Releve`) ;
- l'adresse la plus proche d'un point (pointage, application) : **calculée chez nous**, plus
  aucun appel extérieur ;
- la recherche d'adresse dans les formulaires ;
- la simulation d'inondation, sans nouveau balayage de la BAN ;
- la copie vers les satellites et les téléphones.

## 3. Copie vers le satellite

- `GET /api/satellites/<id>/adresses/?depuis=<horodatage>` : les adresses des communes du
  territoire du satellite modifiées depuis la dernière copie, par pages. Compte de service du
  satellite uniquement.
- Côté satellite : copie complète à l'installation, puis incrémentale une fois par jour (et au
  retour du lien), en tâche à part de la synchronisation des 5 minutes.
- Volume : quelques milliers de lignes pour une commune, quelques dizaines de milliers pour un
  EPCI.

## 4. Copie vers le smartphone : au besoin, pour l'évaluation des dégâts

- **Seulement** quand l'intervenant ouvre l'évaluation des dégâts et choisit d'**embarquer un
  secteur** : une commune, ou un rayon autour de lui, sur une crise donnée.
- Ce qui est embarqué : les adresses du secteur, les biens déjà référencés pour la crise avec
  leur dernier état, les dossiers ouverts de la crise dans le secteur, les cercles des personnes
  vulnérables (sans identité) et le fond de carte du secteur.
- Chiffré sur le téléphone (magasin existant), **daté** à l'écran, et **effacé** à la fin de la
  crise ou à la demande (§ 6, décision 4).
- Sans secteur embarqué, l'évaluation marche en ligne (adresses demandées au serveur au fil des
  pas).

## 5. L'évaluation à pied, seul

Pensée pour une personne qui marche, téléphone à la main, sans aide : gros boutons, une main,
la tournée guidée par la distance.

### 5.1 Le parcours

| Écran | Ce qu'on voit | Ce qu'on fait |
|---|---|---|
| **Tournée** | carte et liste des points **les plus proches de moi**, colorés par état (à évaluer, évalué, pointé) | toucher un point, ou « Je suis devant » (le plus proche) |
| **Début de l'évaluation** | l'adresse, le point sur la carte et **ma position** | « Le point est-il bien placé par rapport au bâtiment ? » **Oui** / **Non → replacer** |
| **Replacer** | la carte centrée sur le point | déplacer le point du doigt, ou « à ma position » ; l'adresse ne change pas |
| **Évaluer** | état (pas de dégâts, faibles, forts, détruit), nature (préremplie par la crise), dangers (structure, électricité, gaz, eau), personne sur place ou à reloger | photos scellées (plusieurs), un commentaire court |
| **Enregistré** | « Suivant : 14 rue des Pins, à 20 m » | continuer, ou revenir à la carte |
| **Nouveau point ici** | ma position (ou un appui long sur la carte) | catégorie (voiture, bâtiment sans adresse, route ou ouvrage, réseau électrique, arbre ou obstacle, autre), description, état, photos, « ouvrir un dossier ? » |
| **En attente** | « 12 évaluations, 31 photos en attente » | rien : tout part seul au retour du réseau |

Une personne sur place ou à reloger, un bien détruit ou dangereux **propose** l'ouverture d'un
dossier ; l'intervenant confirme.

### 5.2 Au retour du réseau

| Ce qui remonte | Au central |
|---|---|
| Constat sur une adresse du référentiel | rattaché au bien de cette adresse pour la crise (créé s'il n'existe pas) ; validation par la commune si l'auteur est un intervenant, comme aujourd'hui |
| Position replacée | proposée comme position du bien ; l'adresse nationale ne change pas |
| Nouveau point sans adresse | un bien d'une catégorie à moins de 50 m d'un bien de même catégorie de la crise → **fusion proposée** à la commune, jamais faite d'office |
| Dossier ouvert hors ligne | un dossier déjà ouvert pour ce bien → **rattachement proposé** |
| Photos | empreinte vérifiée, rattachées au constat |

Chaque création porte l'identifiant tiré **sur le téléphone** : un renvoi ne crée jamais de
doublon. Les propositions de fusion rejoignent la file de validation de la commune, avec les deux
fiches côte à côte.

## 6. Décisions à prendre

1. **Institutions départementales** (préfecture, SDIS, conseil départemental) : charger tout le
   département (jusqu'à plusieurs centaines de milliers d'adresses) ou seulement les communes
   d'une crise ouverte ? Proposé : seulement à l'ouverture d'une crise sur ces communes.
2. **Les biens qui ne sont pas des bâtiments** (voiture, ouvrage, réseau) : une **catégorie** sur
   le bien existant (`Habitation`, affiché « bien ») ou un modèle à part ? Proposé : la catégorie,
   pour garder carte, décomptes, rapports et dossiers tels qu'ils sont.
3. **Qui évalue sur le téléphone** : les intervenants des équipes engagées sur la crise (constat
   validé par la commune) et le personnel communal (direct) — comme le pointage du site.
   Proposé : inchangé.
4. **Effacement du secteur embarqué** : à la clôture de la crise, ou au plus tard sept jours après
   l'embarquement s'il n'est pas renouvelé. Proposé.
5. **Seuil de rapprochement** des biens sans adresse : 50 m proposé.

## 7. Lots

| Lot | Contenu | Essais |
|---|---|---|
| **A** | Référentiel `AdresseBAN` : import par fichier départemental, mise à jour hebdomadaire, adresses retirées ; branché sur le registre, les secteurs, la recherche et l'adresse la plus proche | import sur un fichier réduit fabriqué, retraits, rattachements inchangés |
| **B** | Copie vers le satellite (incrémentale, par pages) | rejeu complet puis incrémental |
| **C** | API de l'évaluation : points proches, constat avec identifiant du téléphone, position replacée, nouveau point avec catégorie, photos, propositions de fusion et de rattachement, écran de validation sur le site | idempotence, fusion jamais automatique |
| **D** | Application : la tournée à pied **en ligne** | parcours complet sur émulateur |
| **E** | Application : **embarquer un secteur**, tournée hors ligne, effacement | parcours en mode avion |
| **F** | Satellite : biens, constats et photos dans la synchronisation (lot 4 du dossier hors ligne) | coupure simulée |
