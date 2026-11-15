/** Veille du territoire : ce que le serveur a copié des sources ouvertes de l'État (vigilance
 * Météo-France, événements routiers Bison Futé, stations de carburant) — voir
 * backend/core/sources_ouvertes.py. Le navigateur ne lit que cette copie : il n'interroge
 * jamais ces services lui-même. */

export interface PeriodeVigilance { debut: string; fin: string; couleur: number; }

export interface PhenomeneVigilance {
  id: number;
  /** 2 jaune, 3 orange, 4 rouge (le vert n'est pas transmis). */
  couleur: number;
  periodes: PeriodeVigilance[];
}

export interface FicheVigilance {
  debut: string;
  fin: string;
  couleur: number;
  phenomenes: PhenomeneVigilance[];
}

export interface SectionBulletin { rubrique: string; alea: string; titre: string; lignes: string[]; }

export interface VigilanceDepartement {
  departement_code: string;
  nom: string;
  couleur_j: number;
  couleur_j1: number;
  detail: { J?: FicheVigilance; J1?: FicheVigilance };
  /** Servi seulement pour la France et pour le département consulté. */
  bulletin?: SectionBulletin[];
  publie_le: string;
  releve_le: string;
}

export interface VigilanceMeteo {
  disponible: boolean;
  source: string;
  releve_le: string | null;
  publie_le: string | null;
  /** La copie est trop ancienne pour être présentée comme actuelle. */
  perime: boolean;
  phenomenes: Record<string, string>;
  couleurs: Record<string, string>;
  france: VigilanceDepartement | null;
  mon_departement: VigilanceDepartement | null;
  departements: VigilanceDepartement[];
  vignettes: string[];
}

interface EnteteVeille {
  source: string;
  releve_le: string | null;
  perime: boolean;
  centre: { latitude: number; longitude: number } | null;
  rayon_km: number | null;
  /** Faux quand rien ne dit où regarder (compte sans commune de rattachement). */
  emprise_connue: boolean;
  tronque: boolean;
}

export type CategorieEvenementRoutier =
  'FERMETURE' | 'ACCIDENT' | 'OBSTACLE' | 'CONDITIONS' | 'DEVIATION' | 'TRAVAUX' | 'RESTRICTION' | 'AUTRE';

export interface EvenementRoutier {
  reference: string;
  categorie: CategorieEvenementRoutier;
  categorie_libelle: string;
  natures: string[];
  gravite: string;
  route: string;
  commune_nom: string;
  description: string;
  localisation: string;
  gestionnaire: string;
  departement_code: string | null;
  latitude: number;
  longitude: number;
  latitude_fin: number | null;
  longitude_fin: number | null;
  debut: string | null;
  fin: string | null;
  mis_a_jour_le: string | null;
}

export interface EvenementsRoutiers extends EnteteVeille { resultats: EvenementRoutier[]; }

export interface StationCarburant {
  reference: string;
  adresse: string;
  ville: string;
  code_postal: string;
  latitude: number;
  longitude: number;
  carburants_disponibles: string[];
  /** Carburants que la station vend d'ordinaire et n'a plus : le signal d'une pénurie. */
  ruptures_temporaires: string[];
  /** Carburants que la station ne vend plus : pas un signal de pénurie. */
  ruptures_definitives: string[];
  prix: Record<string, { prix: number; maj: string | null }>;
  automate_24_24: boolean;
  mis_a_jour_le: string | null;
}

export interface StationsCarburant extends EnteteVeille {
  bilan: { total: number; en_rupture: number; a_sec: number };
  resultats: StationCarburant[];
}

export interface ObservationMeteo {
  station: string;
  nom: string;
  altitude_m: number | null;
  latitude: number;
  longitude: number;
  /** Distance au centre de l'emprise, quand il y en a un. */
  distance_km: number | null;
  mesure_le: string | null;
  /** Une mesure absente vaut `null`, jamais zéro : toutes les stations ne mesurent pas tout. */
  temperature_c: number | null;
  humidite_pct: number | null;
  vent_kmh: number | null;
  vent_direction: number | null;
  rafale_kmh: number | null;
  pluie_6min_mm: number | null;
  neige_cm: number | null;
  heure_le: string | null;
  pluie_1h_mm: number | null;
  rafale_1h_kmh: number | null;
  /** Cumul construit par le serveur, heure après heure : il porte sur `heures_cumulees`
   * heures, 24 au plus. */
  pluie_24h_mm: number | null;
  heures_cumulees: number;
}

export interface ObservationsMeteo extends EnteteVeille { resultats: ObservationMeteo[]; }

/** Pluie prévue (prévision immédiate de Météo-France) : une image nationale par quart d'heure,
 * à poser sur la carte entre les quatre `coins`. C'est une prévision recalée chaque heure sur
 * les radars, pas l'image radar elle-même — l'écran doit le dire. */
export interface PluiePrevue {
  source: string;
  releve_le: string | null;
  perime: boolean;
  /** Heure du calcul qui a produit les images. */
  calcul: string | null;
  /** Haut-gauche, haut-droite, bas-droite, bas-gauche : [longitude, latitude]. */
  coins: [number, number][];
  echeances: string[];
}

/** Réglage de l'annonce de vigilance d'une institution (voir ConfigurationAlerteVigilance). */
export interface ConfigurationAlerteVigilance {
  id: number;
  institution: string;
  institution_nom?: string | null;
  actif: boolean;
  /** 2 jaune, 3 orange, 4 rouge. */
  couleur_min: number;
  date_creation?: string;
}
