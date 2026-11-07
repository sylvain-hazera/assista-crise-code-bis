/** Propagation radio sur le relief (voir backend/core/relief_radio.py, porté de `relief.js` de
 * carte-live-meshtastic).
 *
 * Deux outils de nature différente : le **bilan de liaison** est calculé tout de suite (un profil
 * de terrain, quelques secondes), la **couverture d'un site** part en file (un balayage radial,
 * quelques milliers d'interrogations d'altimétrie IGN, limitées à 2,5 par seconde).
 *
 * `calibre` est le champ qui décide de la confiance : à faux, la perte d'environnement est une
 * valeur par défaut et le résultat est une indication de relief, pas une prévision. */

export type StatutCouvertureRadio = 'EN_COURS' | 'TERMINEE' | 'ECHEC';

export interface CouvertureRadioSite {
  id: string;
  nom: string;
  latitude: number | null;
  longitude: number | null;
  node_num: number | null;
  hauteur_antenne_m: number;
  hauteur_cible_m: number;
  preset: string;
  puissance_dbm: number;
  rayon_max_km: number;
  nb_rayons: number;
  pas_m: number;
  perte_environnement_db: number;
  /** Faux = perte d'environnement par défaut, donc indication et non prévision. */
  calibre: boolean;
  surface_estimee_km2: number | null;
  /** Points pour lesquels l'IGN n'a rien renvoyé : au-delà de quelques pourcents, la couverture
   * est sous-estimée. */
  points_sans_altitude: number;
  nombre_points: number;
  statut: StatutCouvertureRadio;
  erreur: string | null;
  date_lancement: string;
  date_calcul: string | null;
}

/** Résultat d'un bilan de liaison point à point. */
export interface BilanLiaison {
  /** Positive : la liaison passe avec cette marge. Négative : il manque ce nombre de dB. */
  marge_db: number;
  distance_m: number;
  diffraction_db: number;
  /** L'obstacle de plus grand paramètre de Fresnel — pas le plus haut. Null = rien ne dépasse
   * la ligne de visée. */
  obstacle: { distance_km: number; hauteur_m: number } | null;
  parametres: {
    preset: string;
    hauteur_site_m: number;
    hauteur_cible_m: number;
    puissance_dbm: number;
    gains_dbi: number;
    pertes_db: number;
    marge_securite_db: number;
    perte_environnement_db: number;
    calibre: boolean;
    seuil_dbm: number;
    rayon_max_km: number;
  };
}

export interface CalibrationRadio {
  id: string;
  preset: string;
  liaisons_retenues: number;
  ecart_median_db: number | null;
  /** Null = moins de cinq liaisons exploitables : on ne conclut pas. */
  perte_environnement_db: number | null;
  exemples: {
    ecart_db: number; emetteur: number; recepteur: number;
    distance_km: number; snr_mesure: number; snr_predit: number;
  }[] | null;
  date_calcul: string;
}

/** Presets proposés. Les valeurs doivent correspondre à PRESETS_LORA côté serveur, qui refuse
 * tout ce qu'il ne connaît pas. */
export const PRESETS_RADIO = [
  { valeur: 'LONG_FAST', libelle: 'LONG_FAST (défaut Meshtastic)' },
  { valeur: 'LONG_MODERATE', libelle: 'LONG_MODERATE' },
  { valeur: 'LONG_SLOW', libelle: 'LONG_SLOW' },
  { valeur: 'VERY_LONG_SLOW', libelle: 'VERY_LONG_SLOW (portée maximale)' },
  { valeur: 'MEDIUM_FAST', libelle: 'MEDIUM_FAST' },
  { valeur: 'SHORT_FAST', libelle: 'SHORT_FAST (débit maximal)' },
  { valeur: 'MESHCORE_FR', libelle: 'MeshCore France (869,618 MHz)' },
];
