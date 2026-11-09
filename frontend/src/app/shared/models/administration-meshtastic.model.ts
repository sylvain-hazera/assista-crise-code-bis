/** Administration à distance des nœuds Meshtastic (voir backend/core/models.py:
 * TacheAdminMeshtastic et meshtastic-bridge/admin_meshtastic.py).
 *
 * Ce qu'il faut savoir avant d'utiliser cette page : un nœud n'accepte une commande
 * d'administration venant d'un autre nœud que si la clé publique de l'APPAREIL passerelle
 * figure dans sa liste `security.admin_key` (trois emplacements). Cela se pose une fois, avec
 * l'application Meshtastic officielle, en ayant l'appareil en main. Seule exception : la
 * passerelle elle-même, que son propre pont administre sans aucune autorisation préalable. */

export type TypeTacheAdminMeshtastic =
  | 'LIRE_METADATA'
  | 'LIRE_CONFIG_LORA'
  | 'LIRE_CONFIG_APPAREIL'
  | 'LIRE_PROPRIETAIRE'
  | 'LIRE_CONFIG_MQTT'
  | 'LIRE_REGLAGES'
  | 'DEFINIR_REGLAGES'
  | 'DEFINIR_NOM'
  | 'DEFINIR_PUISSANCE'
  | 'DEFINIR_MQTT_JSON'
  | 'REDEMARRER';

/** Catalogue des réglages modifiables, servi par
 * `GET /api/taches-admin-meshtastic/reglages/`.
 *
 * Servi et non recopié ici : les bornes sont des contraintes du firmware (nombre de sauts 1-7,
 * intervalle de voisinage au moins 4 h), et les dupliquer dans deux langages garantit qu'elles
 * divergeront. Le serveur revalide de toute façon. */
export interface ChampReglage {
  type: 'entier' | 'reel' | 'booleen' | 'enumeration' | 'inconnu';
  libelle: string;
  aide: string;
  mini?: number;
  maxi?: number;
  /** Valeurs acceptées hors de l'intervalle, avec leur sens propre (0 = défaut du firmware). */
  valeurs_speciales?: number[];
  valeurs?: string[];
  /** Ce réglage décide de ce qui part dans l'air (bande, puissance, occupation du temps
   * d'antenne). Son écriture exige une confirmation explicite, nominative et journalisée. */
  reglementaire: boolean;
  /** Texte à afficher à côté du champ, jamais enfoui dans une documentation. */
  avertissement: string;
  /** Avertissement propre à chaque valeur : c'est ce qui rend l'alerte adaptée à la zone
   * géographique au lieu d'être la même partout (868 MHz n'est pas la même bande en métropole
   * et outre-mer). L'interface affiche celui de la valeur choisie. */
  avertissements_par_valeur?: Record<string, string>;
}

export interface SectionReglages {
  libelle: string;
  /** Vrai = module (`set_module_config`) et non section de configuration. */
  module: boolean;
  /** Vrai = le firmware redémarre le nœud de lui-même après un changement ici. */
  redemarre: boolean;
  /** Vrai dès qu'un champ de la section est sous contrainte réglementaire. */
  reglementaire: boolean;
  champs: Record<string, ChampReglage>;
}

export interface RegionFirmware {
  debut_mhz: number;
  fin_mhz: number;
  rapport_cyclique_pct: number;
  puissance_max_dbm: number;
}

/** `GET /api/taches-admin-meshtastic/reglages/`. Le texte réglementaire et la table des régions
 * du firmware viennent du serveur : les recopier ici garantirait qu'ils divergent. */
export interface CatalogueReglages {
  sections: Record<string, SectionReglages>;
  avertissement_france: string;
  regions_firmware: Record<string, RegionFirmware>;
  regions_sans_table_firmware: string[];
  regions_radioamateur: string[];
}

export type StatutTacheAdminMeshtastic = 'EN_ATTENTE' | 'EN_COURS' | 'TERMINEE' | 'ECHEC';

export interface TacheAdminMeshtastic {
  id: string;
  compagnon: string;
  compagnon_nom?: string;
  /** Null = la passerelle elle-même. */
  node_num_cible: number | null;
  type_tache: TypeTacheAdminMeshtastic;
  type_tache_libelle?: string;
  /** Vrai pour les opérations qui MODIFIENT le nœud : réservées au rôle administrateur réel. */
  est_ecriture?: boolean;
  parametres?: Record<string, unknown> | null;
  statut: StatutTacheAdminMeshtastic;
  tentatives: number;
  /** JSON sérialisé par le pont, chiffré au repos côté serveur (une configuration lue peut
   * contenir une PSK WiFi ou une clé de canal). */
  reponse?: string | null;
  erreur?: string | null;
  demande_par?: string | null;
  demande_par_email?: string | null;
  date_creation: string;
  date_prise?: string | null;
  date_reponse?: string | null;
}

export interface ConfigurationNoeudMeshtastic {
  id: string;
  node_num: number;
  /** dBm. ATTENTION : 0 ne veut pas dire 0 dBm — le firmware applique alors le maximum autorisé
   * pour la région, c'est donc une puissance INCONNUE. Affichée comme telle. */
  puissance_emission_dbm: number | null;
  region: string;
  modem_preset: string;
  hop_limit: number | null;
  role: string;
  firmware_version: string;
  hardware_model: string;
  releve_par?: string | null;
  releve_par_nom?: string | null;
  date_releve: string;
}

/** Opérations proposées par l'interface, dans l'ordre où elles servent. */
export const OPERATIONS_ADMIN_MESHTASTIC: {
  type: TypeTacheAdminMeshtastic; libelle: string; ecriture: boolean; explication: string;
}[] = [
  {
    type: 'LIRE_CONFIG_LORA', libelle: 'Lire la configuration LoRa', ecriture: false,
    explication: "Puissance d'émission, région, preset, nombre de sauts. C'est cette lecture "
      + "qui alimente la correction de puissance du diagnostic des liaisons.",
  },
  {
    type: 'LIRE_METADATA', libelle: 'Lire firmware et modèle', ecriture: false,
    explication: 'Version de firmware, modèle de matériel, rôle, présence du chiffrement par clé publique.',
  },
  {
    type: 'LIRE_CONFIG_APPAREIL', libelle: "Lire la configuration de l'appareil", ecriture: false,
    explication: 'Rôle du nœud et mode de rediffusion : dit si un nœud relaie vraiment le trafic.',
  },
  {
    type: 'LIRE_PROPRIETAIRE', libelle: 'Lire le nom du nœud', ecriture: false,
    explication: 'Nom long et nom court déclarés sur l’appareil.',
  },
  {
    type: 'LIRE_REGLAGES', libelle: 'Lire une section de réglages', ecriture: false,
    explication: "Tous les réglages d'une section : radio, appareil, position, module Voisinage "
      + 'ou Télémétrie. À faire avant toute modification, pour voir ce qui est en place.',
  },
  {
    type: 'DEFINIR_REGLAGES', libelle: 'Modifier des réglages', ecriture: true,
    explication: "Rôle, mode de rediffusion, preset, nombre de sauts, module Voisinage… "
      + "Seuls les réglages que vous cochez sont envoyés : les autres sont relus sur le nœud et "
      + 'renvoyés inchangés, car le firmware remplace tout le bloc.',
  },
  {
    type: 'DEFINIR_NOM', libelle: 'Renommer le nœud', ecriture: true,
    explication: 'Nom long (39 octets au plus) et nom court (4 octets) — en octets, pas en '
      + 'caractères : un emoji ou quatre lettres accentuées dépassent déjà.',
  },
  {
    type: 'LIRE_CONFIG_MQTT', libelle: 'Lire la configuration MQTT', ecriture: false,
    explication: "Broker, compte, racine de topic, et si la publication JSON est active. Le mot "
      + "de passe du broker n'est jamais remonté, seulement le fait qu'il soit défini.",
  },
  {
    type: 'DEFINIR_MQTT_JSON', libelle: 'Activer la publication JSON du MQTT', ecriture: true,
    explication: "Le nœud publie en plus une version décodée EN CLAIR sur « …/2/json/# ». Utile "
      + "aux outils tiers du site (Node-RED, tableau de bord) ; sans effet sur ce pont, qui ne "
      + "lit que « …/2/e/# ». À réserver à un broker de site : le broker voit alors le texte.",
  },
  {
    type: 'DEFINIR_PUISSANCE', libelle: "Définir la puissance d'émission", ecriture: true,
    explication: "Le nœud redémarre tout seul après ce changement (le firmware l'impose). "
      + '1 à 27 dBm : 27 dBm est le plafond de la bande 869,4-869,65 MHz.',
  },
  {
    type: 'REDEMARRER', libelle: 'Redémarrer le nœud', ecriture: true,
    explication: 'Redémarrage logiciel. À éviter sur un relais difficile d’accès si un doute subsiste.',
  },
];

/** Diagnostic des liaisons radio (voir backend/core/analyse_liaisons.py, porté d'`asymetrie.js`
 * de carte-live-meshtastic).
 *
 * Chaque conclusion porte de quoi la juger : d'où vient la preuve, combien d'observations, et si
 * la puissance d'émission était connue. Ce n'est pas du détail d'affichage — désigner un relais
 * comme sourd envoie quelqu'un sur un point haut, et une conclusion non corrigée en puissance ne
 * vaut pas la même chose qu'une conclusion corrigée. */

/** « A rapporte ce qu'il entend et n'entend jamais B, alors que B l'entend. » */
export interface LiaisonSensUnique {
  /** `passerelle` : SNR mesuré par une passerelle MQTT. `voisinage` : rapport NeighborInfo —
   * plafonné à 10 voisins, donc une absence ne prouve rien si la liste est pleine. */
  preuve: 'passerelle' | 'voisinage';
  entend: number;
  entendu: number;
  nom_entend: string;
  nom_entendu: string;
  snr: number | null;
  nombre: number;
  sources: string[];
  distance_km: number | null;
}

/** Plus de 10 dB d'écart entre les deux sens, correction de puissance appliquée. */
export interface LiaisonDesequilibree {
  a: number;
  b: number;
  nom_a: string;
  nom_b: string;
  snr_fort: number;
  snr_faible: number;
  ecart_db: number;
  /** Écart de puissance d'émission retiré du calcul. 0 = puissances inconnues. */
  correction_db: number;
  puissance_connue: boolean;
  distance_km: number | null;
}

/** Entend ses voisins, mais personne ne l'entend : antenne en réception seulement, ou émission
 * en panne. */
export interface NoeudInaudible {
  node_num: number;
  nom: string;
  entend: number;
  voisins: string[];
}

export interface MesureRelaisSourd {
  partenaire: number;
  nom_partenaire: string;
  entendu_chez_partenaire: number;
  /** Null = il ne l'a jamais rapporté : l'écart n'est alors qu'une BORNE BASSE. */
  entendu_chez_lui: number | null;
  ecart_db: number;
  borne: boolean;
  correction_db: number;
  puissance_connue: boolean;
}

export interface RelaisSourd {
  node_num: number;
  nom: string;
  /** Médiane des écarts, pas une mesure isolée. */
  ecart_db: number;
  nb_voisins: number;
  nb_concordantes: number;
  /** Faux dès qu'un seul voisin a une puissance inconnue : la médiane redevient discutable. */
  puissance_connue: boolean;
  mesures: MesureRelaisSourd[];
}

export interface DiagnosticLiaisons {
  sens_unique: LiaisonSensUnique[];
  desequilibrees: LiaisonDesequilibree[];
  inaudibles: NoeudInaudible[];
  sourds: RelaisSourd[];
  /** Vrai dès qu'au moins un nœud a une puissance relevée. */
  puissance_connue: boolean;
  noeuds_puissance_connue: number;
  calcule_le: string;
}
