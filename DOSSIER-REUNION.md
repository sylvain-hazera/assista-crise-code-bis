# La Réunion — ce qui manque, source par source

Demande de Sylvain du 20/11/2026 : « regarde La Réunion, il me manque plein de données pour eux ».
Relevé fait le 20/11/2026 : comptage de la base de production dans l'emprise de l'île (lecture
seule), puis essai des sources publiques. Aucune institution réunionnaise n'existe encore en
base (les six satellites sont dans la Loire) ; les 24 communes sont connues.

Légende : ✅ présent · 🟢 facile (la source couvre l'île, notre emprise ou notre périmètre la
coupe) · 🟡 à construire (source trouvée, autre format) · 🔴 pas de source ouverte trouvée ·
⏳ se remplira à la création d'une institution réunionnaise

## 1. Ce qui est déjà là

| Donnée | En base (île) | Source |
|---|---|---|
| Vigilance météo, y compris cyclonique (violet) | ✅ | Météo-France, vigilance outre-mer |
| Stations météo | ✅ 57 | Météo-France |
| Hauteurs d'eau en rivière | ✅ 51 stations | Hub'Eau |
| Séismes (Piton de la Fournaise compris) | ✅ 35 | BCSF-Rénass, observatoires de l'IPGP |
| Défibrillateurs | ✅ 1 023 | Géo'DAE |
| Marégraphes | ✅ 2 | Shom |
| Radioactivité | ✅ 2 balises | Téléray |
| Qualité de l'air | ✅ 2 points | OpenWeather |
| Antennes mobiles en panne | ✅ | Arcep |
| Restrictions d'eau | ✅ | VigiEau |

## 2. Ce qui manque

| Donnée | Constat | Pourquoi | Piste | État |
|---|---|---|---|---|
| **Foudre (MTG)** | 0 | notre emprise s'arrête à la métropole ; le satellite voit jusqu'à 60° E (vérifié) | emprise de l'île ajoutée, marge en mer (20/11/2026) | ✅ |
| **Foyers de feu (FIRMS)** | 0 | nous ne lisons que le fichier « Europe » | fichier « Southern_Africa » lu, l'île seule gardée (20/11/2026) | ✅ |
| **Feux en cours (géostationnaire)** | 0 | MTG ne traite les feux que jusqu'à 50° E (vérifié sur juillet) | **MSG IODC** (océan Indien) : même compte LSA SAF, une liste toutes les 15 min, format HDF5 | 🟡 |
| **Orages et pluie observée (radar)** | 0 | l'analyse ne lit que la mosaïque métropole | mosaïque **REUNION** analysée comme la métropole (20/11/2026) : image et boucle sur la carte, cellules, cumuls par commune, nos estimations de l'heure qui vient ; sans AROME-PI ni Doppler | ✅ |
| **Doppler** | exclu volontairement | radars d'outre-mer écartés tant que leurs cellules ne sont pas analysées | suit le radar | 🟡 |
| **Pluie, rafales, neige prévues (prévision immédiate)** | 0 | AROME-PI ne couvre que la métropole | AROME outre-mer (océan Indien) : nom du produit à trouver sur le portail Météo-France | 🟡 |
| **Vent animé** | 0 | ARPEGE Europe | ARPEGE mondial (0,25°) | 🟡 |
| **Vigilance crues** | 0 | le flux national ne couvre que la métropole (vérifié : 337 tronçons, aucun outre-mer) | la cellule de veille hydrologique de la DEAL publie sur vigicrues-reunion.re ; **flux ouvert à trouver** | 🔴 |
| **Cyclones : trajectoire, cône, intensité prévue** | — | rien dans le projet | CMRS de La Réunion (Météo-France) : **pas de flux ouvert trouvé** ; la vigilance violette arrive déjà | 🔴 |
| **État des routes** (basculement de la route du Littoral, radiers) | 0 | Bison Futé ne couvre que les routes nationales de métropole | la Direction régionale des routes publie dans l'appli InfoTrafic 974, **sans API ouverte trouvée** ; routes.re calcule le basculement à partir des pluviomètres de Météo-France | 🔴 |
| **Stations-service** | 0 | le flux national ne contient aucune station de l'île (vérifié) | prix fixés chaque mois par la préfecture ; **pas de liste ouverte trouvée** | 🔴 |
| **Circulation, arrêtés de circulation** | 0 | sources métropolitaines | — | 🔴 |
| **Surfaces brûlées (EFFIS)** | 0 | EFFIS couvre l'Europe | GWIS (mondial) à essayer | 🟡 |
| **Météo des forêts, potentiel d'orage de feu** | — | la météo des forêts ne couvre pas l'outre-mer ; le potentiel est calculé sur ARPEGE Europe | à discuter (feux du Maïdo) | 🔴 |
| **Sites sensibles** (écoles, santé, ICPE, entreprises, équipements) | 0 sur 11 934 | chargés par périmètre d'institution | jeux nationaux, outre-mer compris | ⏳ |
| **Risques du territoire (Géorisques), zonages, PPR** | 1 commune sur 24 | chargés par commune d'institution | Géorisques couvre l'outre-mer | ⏳ |
| **Adresses** | 0 | relevé par commune d'institution | fichier BAN du département 974 (référentiel d'adresses, `DOSSIER-ADRESSES-ET-DEGATS.md`) | ⏳ |
| **Fond de carte du satellite** | — | PMTiles par département | à vérifier pour le 974 à l'installation d'un satellite | ❓ |

## 3. Ordre proposé

1. **Les trois corrections faciles** : foudre MTG et foyers FIRMS sur l'île, et la création de
   l'institution réunionnaise (qui charge sites sensibles, Géorisques et, avec le lot A,
   les adresses).
2. ~~**Radar REUNION**~~ : fait le 20/11/2026 (Doppler exclu).
3. **Feux MSG IODC** : même suivi que MTG, autre satellite.
4. **Prévision immédiate outre-mer et ARPEGE mondial** : après avoir trouvé les produits sur le
   portail Météo-France.
5. **Les manques sans source ouverte** (crues, cyclones, routes, carburants) : demander aux
   producteurs (DEAL, Météo-France La Réunion, Région, préfecture) un accès aux données.

Sources des recherches : [Vigicrues Réunion, communiqué de la préfecture](https://www.reunion.gouv.fr/contenu/telechargement/37266/277895/file/2023-07-06-CP-Vigicrues.pdf),
[outil de prévision des crues de la DEAL](https://www.reunion.developpement-durable.gouv.fr/IMG/pdf/deal-vsc-sprinr-01-outil_prevision_des_crues-2.pdf),
[RSMC La Réunion](https://en.wikipedia.org/wiki/RSMC_La_R%C3%A9union),
[routes.re](https://www.data.gouv.fr/reuses/routes-re),
[InfoTrafic 974](https://apps.apple.com/fr/app/infotrafic-974/id1331377238),
[prix des carburants fixés par la préfecture](https://www.reunion.gouv.fr/contenu/telechargement/41653/311934/file/2024-02-28-CP-Prix_Carburants_Mars2024.pdf).
