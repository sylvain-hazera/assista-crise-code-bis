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
  | 'DEFINIR_PUISSANCE'
  | 'REDEMARRER';

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
