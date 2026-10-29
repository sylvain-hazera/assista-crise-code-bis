import type { MultiPolygon, Polygon } from 'geojson';

export interface PalierInondation {
  niveau: number;
  /** null = rien d'inondé à ce niveau (relief entièrement hors d'eau, voir core/inondation.py). */
  polygone_geojson: Polygon | MultiPolygon | null;
}

export interface AdresseSimulee {
  adresse: string;
  lon: number;
  lat: number;
  altitude: number | null;
  /** Plus petit niveau d'eau simulé (mètres) qui atteint cette adresse -- null = jamais
   * atteinte dans la plage testée, pas "non calculée". */
  seuil_inondation: number | null;
}

export type StatutSimulationInondation = 'EN_COURS' | 'TERMINEE' | 'ECHEC';

/** Relief + paliers d'eau d'une commune : calcul asynchrone (Celery) mais toujours borné.
 * Seul `statut` est renseigné tant que 'EN_COURS'. */
export interface SimulationInondation {
  statut: StatutSimulationInondation;
  erreur?: string;
  commune_code?: string;
  niveaux?: number[];
  paliers?: PalierInondation[];
}

/** Adresses BAN et leur seuil d'inondation : chargement sur demande, peut échouer sur une très
 * grande ville (SEUIL_VOIES_MAX) sans affecter la simulation. */
export interface SimulationAdresses {
  statut: StatutSimulationInondation;
  erreur?: string;
  commune_code?: string;
  adresses?: AdresseSimulee[];
}

export interface PointRuissellement {
  lon: number;
  lat: number;
  /** Valeur relative (cellules amont convergentes), pas un débit : signale un axe d'écoulement. */
  accumulation: number;
}

/** Accumulation de flux (ruissellement) sur la même grille d'altitude, toujours bornée. */
export interface SimulationRuissellement {
  statut: StatutSimulationInondation;
  erreur?: string;
  commune_code?: string;
  points?: PointRuissellement[];
  /** Espacement réel (m) de la grille, pour dessiner chaque case à sa taille. */
  pas_metres?: number;
}

/** Vigilance crues (Vigicrues) du tronçon surveillé le plus proche : qualitative, distincte du
 * niveau mesuré. */
export interface VigilanceCrue {
  troncon?: string;
  niveau?: number;
  libelle?: string;
  couleur?: string;
}

/** Dernier niveau mesuré (Hub'Eau), même référentiel NGF : repère informatif seulement. */
export interface NiveauObserve {
  disponible: boolean;
  station?: string;
  cours_eau?: string;
  niveau_ngf?: number;
  date_observation?: string;
  vigilance?: VigilanceCrue;
}

/** Périmètre de communes ouvert à l'utilisateur pour cet outil
 * (`GET /api/simulation-inondation/perimetre/`).
 *
 * `nationale` : aucune restriction (administration, institution à portée nationale, ou zone de
 * démonstration). `secteur` : la recherche de communes est bornée à `champ` == `valeur`, deux
 * valeurs directement utilisables comme filtre geo.api.gouv.fr. `aucune` : l'outil n'est ouvert
 * à ce compte sur aucune commune.
 *
 * Ce périmètre n'accorde rien : il évite de proposer des communes que l'API refusera ensuite,
 * et permet de dire lesquelles sont ouvertes. L'autorisation reste vérifiée à chaque appel. */
export interface PerimetreSimulation {
  portee: 'nationale' | 'secteur' | 'aucune';
  libelle: string;
  niveau?: string;
  champ?: string;
  valeur?: string;
}
