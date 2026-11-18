"""Bibliothèque de fiches réflexes et de fiches conseils, reprises de documents publics de l'État
(18/11/2026).

Demande de Sylvain : « base-toi sur de l'existant libre (préfecture…) ; ce peut être des fiches
de conseil sur un rôle, un poste, comment tenir un centre d'accueil ».

**D'où viennent-elles.** De deux documents publiés par des services de l'État, lus en entier
avant d'être repris ici :

- la maquette du plan communal de sauvegarde de la préfecture du Lot : neuf fiches réflexes par
  poste du poste de commandement communal et sur le terrain, et des fiches action par risque ;
- la plaquette « Organiser le soutien des populations — mettre en place un centre d'accueil et
  de regroupement » de la direction générale de la sécurité civile et de la gestion des crises
  (ministère de l'Intérieur, version de janvier 2025).

**Pourquoi on peut les reprendre.** Ce sont des informations publiques : leur réutilisation est
libre, à condition de ne pas en altérer le sens et d'en mentionner la source et la date de
mise à jour (code des relations entre le public et l'administration, art. L. 321-1 et
L. 322-1). Chaque fiche porte donc sa source. On n'a retiré que ce qui ne vaut que pour le Lot
(numéros de téléphone, arrêtés départementaux) ; quand une phrase est ajoutée pour dire OÙ cela
se fait dans l'application, elle est entre crochets et ne change pas le fond.

Ces fiches sont des CONSEILS à lire et à adapter. Une commune qui veut faire d'une fiche la
sienne la reprend dans son plan (fiche réflexe d'une fonction, fiche d'un moyen d'alerte), où
elle la réécrit à sa guise.
"""

SOURCE_LOT = {
    "titre": "Maquette de plan communal de sauvegarde",
    "editeur": "Préfecture du Lot",
    "url": "https://www.lot.gouv.fr/contenu/telechargement/12946/102772/file/maquette_pcs_46.pdf",
    "consulte_le": "2026-11-18",
}
SOURCE_CARE = {
    "titre": "Organiser le soutien des populations — mettre en place un centre d'accueil et de regroupement",
    "editeur": "Ministère de l'Intérieur, direction générale de la sécurité civile et de la gestion des crises",
    "url": "https://www.securite-civile.interieur.gouv.fr/sites/securitecivile/files/2025-01/plaquette%20CARE-2.pdf",
    "consulte_le": "2026-11-18",
}

#: Les astuces de terrain ne viennent d'aucun document officiel : ce sont des conseils pratiques,
#: de bon sens, rassemblés pour Assista-Crise (idée de Sylvain du 18/11/2026 : « vous avez une
#: médiathèque ? Les livres peuvent aider à occuper les personnes, les enfants »). Elles sont
#: présentées comme telles, à part des fiches de l'État.
SOURCE_ASTUCES = {
    "titre": "Astuces de terrain",
    "editeur": "Assista-Crise — conseils pratiques, non officiels",
    "url": "",
    "consulte_le": "2026-11-18",
}

#: Les familles de fiches, dans l'ordre où on les présente.
CATEGORIES = {
    "POSTE": "Postes du poste de commandement communal",
    "TERRAIN": "Rôles sur le terrain",
    "CENTRE": "Tenir un centre d'accueil et de regroupement",
    "RISQUE": "Fiches action par situation",
    "ASTUCES": "Astuces de terrain pour un centre d'accueil (non officielles)",
}

FICHES = [
    # ── Postes du poste de commandement communal ─────────────────────────────────────────
    {"code": "decisions", "categorie": "POSTE", "fonction": "DOS", "source": SOURCE_LOT,
     "titre": "Décisions — le maire, directeur des opérations",
     "sections": [
         ("Missions", (
             "Assure la première alerte, appelle les élus et le personnel communal.",
             "Décide de la mise en œuvre du plan communal de sauvegarde.",
             "Prend les premières mesures d'urgence et décide des actions à mener.",
             "Donne ses consignes pour les relais de quartier.",
             "S'assure que l'ensemble de la population concernée est bien alertée.",
             "Valide les actions proposées.",
             "Informe le préfet selon le format « je suis, je vois, je fais, je demande ».",
             "Communique (médias…).",
             "Anime des points de situation réguliers, en fonction des événements [Point de situation].",
         )),
         ("Rappel du rôle du directeur des opérations", (
             "Dirige et coordonne les actions des intervenants.",
             "Assure et coordonne la communication.",
             "Informe les niveaux administratifs supérieurs.",
             "Anticipe les conséquences.",
             "Mobilise les moyens publics et privés sur son territoire.",
         )),
         ("Commune isolée", (
             "En cas d'isolement total de la commune, le maire peut prendre, sous sa responsabilité, les mesures "
             "qui s'imposent pour rétablir les liaisons avec l'échelon supérieur, les communes voisines et les habitants.",
         )),
     ]},
    {"code": "installation-pcc", "categorie": "POSTE", "fonction": "SECRETARIAT", "source": SOURCE_LOT,
     "titre": "Installation du poste de commandement — administration",
     "sections": [
         ("Missions", (
             "Alerte les relais de quartier.",
             "Ouvre le poste de commandement communal.",
             "Installe le matériel dans les différents bureaux (tables, chaises, tableaux, téléphones…).",
             "Met à disposition les outils opérationnels (plan communal de sauvegarde, cartes, documents, mains courantes, "
             "fournitures de bureau…).",
             "Accueille et recense les effectifs (réservistes communaux, bénévoles…).",
             "Renseigne une main courante [journal de bord de la crise].",
         )),
         ("Conseil", ("Disposer d'un plan de configuration du poste de commandement.",)),
     ]},
    {"code": "renseignements", "categorie": "POSTE", "fonction": "COORDINATION", "source": SOURCE_LOT,
     "titre": "Renseignements — collecte d'informations",
     "sections": [
         ("Missions", (
             "Recueille et analyse les informations communiquées par les relais de quartier [Signalements, Standard de crise].",
             "Fait remonter les informations collectées au responsable de la conduite des opérations.",
             "Renseigne une main courante.",
         )),
     ]},
    {"code": "conduite-operations", "categorie": "POSTE", "fonction": "COORDINATION", "source": SOURCE_LOT,
     "titre": "Conduite des opérations",
     "sections": [
         ("Missions", (
             "Exploite les fiches action selon la nature du risque.",
             "Centralise les comptes rendus, les remontées d'informations, les demandes [Cellule de crise].",
             "Propose au maire les actions à mener.",
             "Est en lien avec la préfecture (ou le centre opérationnel départemental s'il est activé).",
             "Élabore régulièrement une synthèse de la situation [Point de situation].",
             "Renseigne une main courante.",
         )),
     ]},
    {"code": "logistique", "categorie": "POSTE", "fonction": "LOGISTIQUE", "source": SOURCE_LOT,
     "titre": "Logistique",
     "sections": [
         ("Missions", (
             "Recense le matériel disponible [Stocks].",
             "Prépare le matériel nécessaire.",
             "Recense le matériel utilisé.",
             "Anticipe les besoins.",
             "Est en contact avec le groupe d'intervention (téléphone, radio, talkie-walkie…).",
             "Fait des points réguliers des effectifs et des moyens disponibles.",
             "Renseigne une main courante.",
         )),
     ]},
    {"code": "secretariat", "categorie": "POSTE", "fonction": "SECRETARIAT", "source": SOURCE_LOT,
     "titre": "Secrétariat",
     "sections": [
         ("Missions", (
             "Assure la permanence téléphonique [Standard de crise].",
             "Prépare les documents à transmettre après validation de l'autorité (réquisitions, communiqués types, arrêtés…).",
             "Prépare les relèves [Planning des équipes].",
             "Renseigne une main courante.",
         )),
     ]},
    # ── Rôles sur le terrain ─────────────────────────────────────────────────────────────
    {"code": "relais-quartier", "categorie": "TERRAIN", "moyen": "RELAIS", "source": SOURCE_LOT,
     "titre": "Relais de quartier",
     "sections": [
         ("Avant de partir — en binôme, jamais seul", (
             "Dès qu'il est contacté, se rend rapidement au poste de commandement avec son téléphone portable.",
             "Se fait recenser à l'administration du poste de commandement [Je pars].",
             "Dispose d'un sac comprenant : deux gilets fluorescents, une lampe de poche, une couverture de survie, un crayon, "
             "un stylo, un cahier, des gommettes, un rouleau adhésif, deux badges de chargé de mission de la mairie.",
             "Dispose des informations sur son secteur (cahier, carte…).",
             "Prend les consignes auprès du maire ou de son remplaçant désigné.",
         )),
         ("Sur le terrain", (
             "Alerte et informe la population par un message précis rédigé par le maire.",
             "Vérifie le nombre de personnes présentes dans chaque maison et le note, si le maire le demande.",
             "Rassure la population pour éviter la panique.",
             "Repère et note les maisons vides, et colle un avis de passage sur la porte.",
             "Observe sa zone et note tout ce qui paraît anormal.",
         )),
         ("Au retour", (
             "Se fait recenser à l'administration du poste de commandement [Je rentre].",
             "Rend compte aux renseignements.",
             "Attend les nouvelles instructions au poste de commandement.",
         )),
     ]},
    {"code": "groupe-intervention", "categorie": "TERRAIN", "source": SOURCE_LOT,
     "titre": "Groupe d'intervention",
     "sections": [
         ("Missions", (
             "Est en contact avec le poste de commandement (téléphone, radio, talkie-walkie…).",
             "Évalue la situation sur le terrain.",
             "Dirige le groupe d'intervention.",
             "Met en place un périmètre de sécurité.",
             "Relaie sur le terrain les consignes.",
             "Demande au poste de commandement les moyens logistiques nécessaires.",
             "Organise l'évacuation si nécessaire, en lien avec la conduite des opérations.",
             "Se met à disposition des services de secours et facilite leur mobilité.",
             "Met en œuvre des moyens techniques (tracteurs, tronçonneuses, groupes électrogènes, tractopelles…).",
         )),
     ]},
    # ── Tenir un centre d'accueil et de regroupement ─────────────────────────────────────
    {"code": "accueil-regroupement", "categorie": "CENTRE", "fonction": "SOUTIEN", "source": SOURCE_LOT,
     "titre": "Accueil et regroupement — le responsable du centre",
     "sections": [
         ("Missions", (
             "Ouvre le centre d'accueil et de regroupement [Centres].",
             "Accueille et recense les sinistrés [registre des présences du centre].",
             "Prépare les locaux pour l'accueil (lits, couvertures, tables, chaises, chauffage…).",
             "Prévoit la sécurisation électrique du site (groupe électrogène, convention avec le distributeur).",
             "Met en place une signalétique pour flécher l'itinéraire.",
             "Prévoit le nécessaire pour un premier ravitaillement (boissons chaudes, sucre, biscuits…).",
             "Prévoit du matériel de nettoyage (sacs poubelle, balais…) et un stock de vaisselle jetable.",
             "Assure un soutien psychologique.",
             "Anticipe une éventuelle durée (kits d'hygiène…).",
             "Oriente les personnes (mise en relation avec d'autres structures) [Relogement des familles].",
             "Renseigne une main courante.",
         )),
         ("Conseil", ("Disposer d'un plan du local.",)),
     ]},
    {"code": "care-preparer", "categorie": "CENTRE", "source": SOURCE_CARE,
     "titre": "Préparer un centre d'accueil : choisir et équiper les lieux",
     "sections": [
         ("Le lieu doit être", (
             "Accessible.",
             "Hors des zones à risques connus.",
             "Ergonomique : chauffé, éclairé, spacieux, avec des locaux d'hygiène.",
             "Équipé de moyens de communication.",
             "Évolutif, pour accueillir une structure plus développée.",
         )),
         ("Mesurer la capacité", (
             "Deux valeurs servent de repère : l'unité, soit 50 personnes ; la surface, soit 4 m² par personne.",
             "Exemple : un local de 600 m² accueille 600 / 4 = 150 personnes, soit 3 unités.",
             "Les capacités de la commune sont transmises à la préfecture selon les modalités du département.",
         )),
         ("Travail préparatoire général", (
             "Recenser les lieux, hors zones à risques, pouvant servir de centre (gymnase, salle polyvalente…), avec leur "
             "capacité d'accueil et d'hébergement et leurs autres ressources (sanitaires, point cuisine…) "
             "[Stocks : un dépôt peut être ce lieu].",
             "Mettre en place une signalétique permanente pour flécher l'itinéraire.",
             "Définir les modalités d'ouverture (gardien, clés, alarme, chauffage, électricité).",
             "Élaborer un plan type avec les différentes zones (accueil, ravitaillement, hébergement).",
             "Identifier les ressources humaines : associations de sécurité civile, bénévoles, réserve communale.",
             "Définir le nombre de personnes sur chaque poste.",
             "Prévoir le lieu de stockage du matériel (couchage, denrées, petit matériel) et son acheminement.",
             "Établir avec les commerçants une convention de ravitaillement en cas de crise.",
             "Prévoir un moyen d'identifier les bénévoles (chasuble, brassard…).",
             "Identifier les personnes aptes aux tâches logistiques et celles qui ont des qualités d'écoute et de dialogue.",
             "Prévoir la sécurisation électrique du site (groupe électrogène ou convention avec le distributeur).",
         )),
     ]},
    {"code": "care-fonctions", "categorie": "CENTRE", "source": SOURCE_CARE,
     "titre": "Tenir un centre d'accueil : les fonctions",
     "sections": [
         ("Accueil", (
             "Prévoir une liaison téléphonique et les numéros utiles (mairie, poste de commandement, services techniques…).",
             "Prévoir des fournitures de bureau et un ordinateur pour le recensement des personnes accueillies (entrées, sorties).",
             "Prévoir des tables et des chaises.",
             "Prévoir le nécessaire pour un premier ravitaillement (boisson chaude, sucre, biscuits) et de quoi chauffer l'eau.",
             "Aménager un espace d'attente (jeux pour enfants, télévision).",
             "Aménager un espace d'information, avec si possible une ligne téléphonique dédiée aux personnes accueillies.",
         )),
         ("Ravitaillement d'urgence", (
             "Il couvre les vingt-quatre premières heures : de type « panier froid », il se consomme sans préparation.",
             "Prévoir tables et chaises pour la collation ou le repas.",
             "Définir un repas type « panier froid » (repas unique et boisson), un repas de substitution (religion ou "
             "allergie) et des repas pour enfants.",
             "Disposer d'un nécessaire de nettoyage et d'un stock de vaisselle jetable.",
             "Au-delà de vingt-quatre heures, un ravitaillement intermédiaire s'organise (cantine scolaire, restaurant d'entreprise…).",
         )),
         ("Hébergement d'urgence", (
             "Il abrite ceux qui n'ont plus de logement et pas d'autre solution. Si l'événement dure, un hébergement "
             "intermédiaire prend le relais (hôtels, centres de vacances, internats…) [Relogement des familles].",
             "Recenser les tapis de sol ou lits de camp et les couvertures ; ce qui manque se demande à la préfecture.",
             "Prévoir un espace pour les enfants en bas âge (change, chauffe-biberon…).",
             "Prévoir des kits d'hygiène si l'événement dure.",
             "Disposer d'éléments verticaux de séparation de la zone d'hébergement.",
         )),
         ("Les missions du centre", (
             "Accueil et recensement : établir la liste des personnes concernées, repérer celles en difficulté et celles "
             "qui ont des compétences utiles au dispositif.",
             "Réconfort : couper la population de l'événement, lui donner un sentiment de sécurité, l'écouter, lui donner "
             "les premières informations.",
             "Orientation : mettre la personne en relation avec les autres structures (hébergement, assistance matérielle…).",
             "Information et soutien administratif : des informations fiables sur l'événement, et un guichet unique pour "
             "les démarches (assurances, logement, papiers d'identité…).",
             "Soutien médico-psychologique : médecins, psychologues, infirmiers ; à demander à la préfecture si la commune "
             "n'en a pas.",
             "Assistance matérielle : vêtements, hygiène, puériculture, le plus souvent par les associations caritatives.",
         )),
     ]},
    # ── Astuces de terrain (non officielles) ─────────────────────────────────────────────
    {"code": "astuces-ressources", "categorie": "ASTUCES", "source": SOURCE_ASTUCES, "officielle": False,
     "titre": "Ce que la commune a déjà sous la main",
     "sections": [
         ("Pensez à vos équipements", (
             "Vous avez une médiathèque ? Des livres, des bandes dessinées, des revues occupent adultes et enfants ; "
             "une bibliothécaire peut animer un coin lecture.",
             "La ludothèque, le centre de loisirs, l'école : jeux de société, ballons, craies, matériel de motricité.",
             "Le club de sport ou le gymnase lui-même : tapis de sol pour dormir, bancs, vestiaires et douches.",
             "La cantine scolaire ou la cuisine de la salle des fêtes : de quoi réchauffer et servir chaud au-delà du premier jour.",
             "Les services techniques : barrières, grilles d'exposition pour séparer les espaces, rallonges, éclairage.",
             "La salle des fêtes : tables, chaises, sono pour les annonces.",
         )),
         ("Pensez aux gens du village", (
             "Les commerçants : boulanger pour le petit-déjeuner, pharmacien pour les traitements oubliés.",
             "Les associations : chorale, club des anciens, comité des fêtes — des bras, de la bonne humeur, et des gens qui connaissent tout le monde.",
             "Les personnes qui parlent une langue étrangère ou la langue des signes : à noter dès l'arrivée des volontaires.",
             "Un médecin, un infirmier, un psychologue parmi les habitants ou les accueillis : leur demander s'ils acceptent d'aider.",
         )),
     ]},
    {"code": "astuces-enfants", "categorie": "ASTUCES", "source": SOURCE_ASTUCES, "officielle": False,
     "titre": "Les enfants",
     "sections": [
         ("Les occuper", (
             "Prévoir des feuilles, des crayons, des coloriages, des petits jeux de cartes, de la pâte à modeler.",
             "Un coin enfants à l'écart du passage et du bruit, avec un tapis et quelques coussins.",
             "Une activité à heure fixe (lecture, dessin, jeu collectif) : ça structure la journée et rassure.",
             "Faire participer les plus grands : distribuer l'eau, aider au coin lecture — se rendre utile apaise.",
         )),
         ("Le nécessaire", (
             "Couches de plusieurs tailles, lingettes, lait infantile, petits pots, chauffe-biberon, une bouilloire.",
             "Un espace calme pour allaiter ou changer un bébé, avec un rideau ou un paravent.",
             "Doudous et peluches : en avoir quelques-uns à donner, un enfant parti sans le sien dort mal.",
         )),
         ("Les protéger", (
             "Ne jamais laisser un enfant sans adulte référent identifié ; noter qui s'occupe de qui à l'accueil.",
             "Un mineur arrivé seul : le signaler tout de suite au responsable du centre.",
         )),
     ]},
    {"code": "astuces-confort", "categorie": "ASTUCES", "source": SOURCE_ASTUCES, "officielle": False,
     "titre": "Le confort et le moral",
     "sections": [
         ("Les petites choses qui comptent", (
             "Des multiprises et des chargeurs de téléphone (plusieurs types de prise) : rassurer ses proches est la première demande.",
             "Le code du wifi affiché, ou un partage de connexion si le réseau tient.",
             "Une bouilloire et du café, du thé, des tisanes en libre-service : un geste simple qui réchauffe.",
             "Des bouchons d'oreilles et des masques de nuit pour dormir dans un gymnase éclairé.",
             "Une radio ou une télévision pour suivre l'information — mais pas allumée en permanence dans l'espace de repos.",
             "Des journaux du jour et un tableau d'affichage tenu à jour : heure de la dernière information, prochaines étapes.",
         )),
         ("Respecter chacun", (
             "Séparer un coin calme et un coin animé ; garder un espace pour qui veut s'isoler ou pleurer.",
             "Des paravents ou des cartons pour un peu d'intimité entre les couchages.",
             "Demander les régimes alimentaires (allergies, sans porc, végétarien, diabète) dès l'accueil.",
             "Prévoir des lunettes de lecture de dépannage, des appareils auditifs se perdent aussi.",
         )),
     ]},
    {"code": "astuces-vulnerables", "categorie": "ASTUCES", "source": SOURCE_ASTUCES, "officielle": False,
     "titre": "Les personnes âgées, malades ou handicapées",
     "sections": [
         ("À l'arrivée", (
             "Demander tout de suite : un traitement à prendre aujourd'hui ? une ordonnance ? un appareil à recharger "
             "(fauteuil électrique, concentrateur d'oxygène) ?",
             "Garder une liste des traitements et des horaires ; le pharmacien de garde peut dépanner.",
             "Des chaises avec accoudoirs et des lits de camp surélevés : se relever d'un tapis de sol est difficile.",
             "Placer ces personnes près des sanitaires et loin des courants d'air.",
         )),
         ("Pendant le séjour", (
             "Passer régulièrement les voir : boire, manger, se lever — la confusion arrive vite chez une personne âgée déplacée.",
             "Prévoir des protections pour incontinence et du linge de rechange, discrètement.",
         )),
     ]},
    {"code": "astuces-animaux", "categorie": "ASTUCES", "source": SOURCE_ASTUCES, "officielle": False,
     "titre": "Les animaux",
     "sections": [
         ("Les accueillir sans gêner", (
             "Beaucoup refusent de partir sans leur animal : annoncer clairement si le centre les accepte.",
             "Un espace à part pour les animaux, à l'écart des personnes allergiques ou craintives.",
             "Gamelles, laisses, sacs pour les déjections ; un vétérinaire du secteur joignable.",
             "Noter le nom de l'animal et de son maître : un animal seul se retrouve plus facilement.",
         )),
     ]},
    {"code": "astuces-organisation", "categorie": "ASTUCES", "source": SOURCE_ASTUCES, "officielle": False,
     "titre": "L'organisation",
     "sections": [
         ("Pour s'y retrouver", (
             "Des chasubles ou des badges pour les bénévoles, et un prénom écrit en gros : on doit savoir à qui s'adresser.",
             "Un plan du centre affiché à l'entrée : accueil, repos, repas, sanitaires, coin enfants, infirmerie.",
             "Un point « objets trouvés » et un point « messages » pour les familles séparées.",
             "Une relève prévue pour les bénévoles toutes les quatre à six heures : un bénévole épuisé fait des erreurs [Planning des équipes].",
         )),
         ("Pour la suite", (
             "Noter à l'accueil où chacun pourra être joint en partant : on doit pouvoir le prévenir quand il pourra rentrer.",
             "Garder des sacs-poubelle, des gants et des produits d'entretien : un centre propre est un centre calme.",
             "Avant de fermer : un mot de remerciement aux bénévoles et aux prêteurs de matériel, et le rendu du matériel emprunté [Stocks : prêts].",
         )),
     ]},
    # ── Fiches action par situation ──────────────────────────────────────────────────────
    {"code": "evacuation", "categorie": "RISQUE", "source": SOURCE_LOT,
     "titre": "Évacuation",
     "sections": [
         ("Diffusion du message d'alerte", (
             "Déterminer les secteurs à alerter.",
             "Utiliser les moyens de diffusion de l'alerte (sirène, porte-voix, porte-à-porte, radio, téléphone…) "
             "[Alerter les habitants].",
             "Actionner les relais.",
         )),
         ("Évacuation", (
             "Actionner les équipes d'évacuation par secteur.",
             "Déterminer les moyens à mettre en œuvre : carrefours à bloquer, rues à emprunter, balisage, moyens de "
             "transport, groupes scolaires, établissements recevant du public…",
             "Évacuer toutes les habitations du secteur, en sachant où sont les personnes à mobilité réduite.",
             "Si des personnes refusent d'évacuer, noter leur situation pour une évacuation d'autorité en cas de danger grave.",
             "Diriger les personnes évacuées vers les centres d'accueil.",
         )),
         ("Protection des zones évacuées", (
             "Mettre en place un périmètre de sécurité pour empêcher tout retour dans la zone.",
             "Prévoir des patrouilles pour empêcher tout acte de malveillance.",
             "Établir un plan de circulation.",
             "Penser à nourrir les animaux ; prévoir un centre d'accueil des animaux domestiques.",
         )),
     ]},
    {"code": "vigilance-meteo", "categorie": "RISQUE", "source": SOURCE_LOT,
     "titre": "Vigilance météo",
     "sections": [
         ("Le maire est alerté", ("Par la préfecture, à partir du niveau de vigilance orange.",)),
         ("Missions du maire", (
             "Recenser les situations à risque sur la commune (chantiers de toiture, grues sur la voie publique…) et "
             "prévenir leurs responsables.",
             "Recenser les manifestations prévues (rassemblements, manifestations de plein air ou sous chapiteau) et, le "
             "cas échéant, les interdire.",
             "Relayer les conseils de comportement adaptés au phénomène prévu.",
             "Se tenir informé de l'évolution de la situation [Veille du territoire].",
             "Avertissement pluies intenses à l'échelle des communes (APIC) et Vigicrues Flash : des services gratuits "
             "de Météo-France pour anticiper une inondation, sur abonnement.",
         )),
     ]},
    {"code": "inondation", "categorie": "RISQUE", "source": SOURCE_LOT,
     "titre": "Pluies intenses, crues, inondation",
     "sections": [
         ("Préparer", (
             "Connaître les zones inondables (plans de prévention, atlas des zones inondables) [Risques de la commune, "
             "Enjeux exposés].",
             "Évaluer la population concernée, secteur par secteur.",
             "Préparer la transmission de l'alerte aux riverains [annuaire, relais de quartier].",
             "Noter les points à surveiller : station d'observation, repère de crue, seuils critiques, sites exposés et "
             "interventions à entreprendre.",
             "Tenir l'historique des crues : dates, hauteurs, temps de propagation.",
         )),
         ("Surveiller", (
             "Rivières surveillées par l'État : information puis alerte par l'automate d'appel de la préfecture, suivi "
             "en temps réel sur Vigicrues [Veille du territoire].",
             "Rivières non surveillées : vigilance communale, et Vigicrues Flash quand le cours d'eau est couvert.",
         )),
     ]},
    {"code": "grand-froid", "categorie": "RISQUE", "source": SOURCE_LOT,
     "titre": "Grand froid",
     "sections": [
         ("Veille saisonnière (du 1er novembre au 31 mars)", (
             "S'assurer que le dispositif de veille et d'alerte est opérationnel (plan communal de sauvegarde, astreintes…).",
             "Tenir à jour le registre nominatif des personnes vulnérables ou isolées, et le faire connaître "
             "[Personnes vulnérables].",
             "Repérer les personnes sans abri.",
             "Renforcer les visites aux personnes vulnérables ou en habitat précaire.",
             "Sensibiliser les intervenants de proximité (associations, bénévoles…).",
             "Recenser les lieux publics chauffés pouvant accueillir les personnes exposées.",
             "Relayer les campagnes d'information préventive.",
             "Signaler à la préfecture toute situation anormale liée au froid.",
         )),
         ("Vigilance jaune, orange ou rouge", (
             "Poursuivre et renforcer les mesures de la veille saisonnière.",
             "Informer la préfecture des moyens et des renforts nécessaires.",
             "À la levée du dispositif : faire un bilan de la gestion des événements liés au froid.",
         )),
     ]},
    {"code": "canicule", "categorie": "RISQUE", "source": SOURCE_LOT,
     "titre": "Canicule",
     "sections": [
         ("Veille saisonnière (du 1er juin au 15 septembre) et vigilance jaune", (
             "S'assurer que le dispositif de veille et d'alerte est opérationnel.",
             "Registre des personnes âgées et handicapées isolées qui en ont fait la demande : informer les habitants, "
             "collecter les inscriptions, en assurer la conservation, la mise à jour et la confidentialité "
             "[Personnes vulnérables].",
             "Repérer les personnes sans abri ; renforcer les visites aux personnes en habitat précaire.",
             "Identifier les lieux publics frais et les points de distribution d'eau potable.",
             "Recenser les intervenants de proximité (associations, bénévoles…).",
             "Diffuser des messages de recommandations au public.",
             "Pré-alerter les services et établissements communaux (centre communal d'action sociale, crèches…).",
             "Signaler à la préfecture toute situation anormale.",
         )),
         ("Le saviez-vous", (
             "Canicule info service : 0 800 06 66 66, appel gratuit, pour des conseils au public.",
         )),
     ]},
]


def par_code() -> dict:
    return {f["code"]: f for f in FICHES}


def en_texte(fiche: dict) -> str:
    """La fiche en texte simple, pour la reprendre dans le plan de la commune."""
    morceaux = []
    for titre, lignes in fiche["sections"]:
        morceaux.append(titre)
        morceaux += [f"• {ligne}" for ligne in lignes]
    source = fiche["source"]
    morceaux.append(f"(D'après : {source['titre']}, {source['editeur']}.)" if source.get("url")
                    else f"({source['titre']} — {source['editeur']}.)")
    return "\n".join(morceaux)


def catalogue() -> list:
    """Ce que la page montre, dans l'ordre des catégories."""
    ordre = list(CATEGORIES)
    return [{**f, "officielle": f.get("officielle", True), "categorie_libelle": CATEGORIES[f["categorie"]],
             "sections": [{"titre": t, "lignes": list(l)} for t, l in f["sections"]]}
            for f in sorted(FICHES, key=lambda f: ordre.index(f["categorie"]))]


def une_astuce_au_hasard(nombre: int = 3) -> list:
    """Quelques astuces de terrain tirées au hasard, pour la page des centres."""
    import random
    toutes = [ligne for f in FICHES if f["categorie"] == "ASTUCES" for _t, lignes in f["sections"] for ligne in lignes]
    return random.sample(toutes, min(nombre, len(toutes)))
