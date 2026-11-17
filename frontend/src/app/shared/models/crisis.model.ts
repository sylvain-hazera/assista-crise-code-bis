import { Status } from "./status.model";
import type { Polygon, MultiPolygon } from "geojson";

// Format GeoJSON retourné par GeoDjango (PointField)
export interface GeoPoint {
  type: 'Point';
  coordinates: [number, number];
}

export interface Crisis {
  id: string;
  name: string;
  type: string;
  type_display?: string;
  description?: string | null;
  status?:  Status;
  location: GeoPoint;
  latitude?: number;
  longitude?: number;
  radius?: number;
  zone?: string | null;          // WKT en écriture (ex: "POLYGON ((lng lat, ...))")
  zone_geojson?: Polygon | null; // GeoJSON natif en lecture, prêt pour l'affichage carte
  zone_departements?: string[];
  zone_communes?: string[];
  zone_secteurs?: string | null;                    // WKT MultiPolygon en écriture
  zone_secteurs_geojson?: MultiPolygon | null;       // union bufferisée des communes/départements ajoutés
  /** Communes concernées seulement sur une zone dessinée : leur contour entier n'entre pas
   * dans la zone composée. */
  zone_communes_partielles?: string[];
  /** Zones dessinées EN PLUS de la zone initiale, chacune par une institution. */
  zones_ajoutees?: ZoneAjoutee[];
  start_date: string;
  end_date: string | null;
  validator: string | null;
  author: string | null;
  author_nom?: string | null;
  commune?: string | null;
  has_photo: boolean;
  severity: string | null;
  is_open?: boolean;
  has_responsable_actif?: boolean;
  essai?: boolean;               // crise d'essai : ignorée par le monitoring
  /** Clôture proposée : la crise reste ouverte jusqu'à `fermeture_prevue_le` (sept jours après). */
  fermeture_proposee_le?: string | null;
  fermeture_prevue_le?: string | null;
}

export interface CrisisPayload {
  name: string;
  type: string;
  description?: string | null;
  status?: string;
  latitude: number;
  longitude: number;
  zone?: string | null;
  end_date?: string | null;
  validator?: string | null;
  author?: string | null;
}
/** Une zone dessinée en plus de la zone initiale d'une crise (voir ZoneAjouteeCrise). */
export interface ZoneAjoutee {
  id: string;
  nom: string;
  institution: string | null;
  institution_nom: string | null;
  geojson: Polygon;
  date_creation: string;
  /** Vrai pour l'institution qui l'a dessinée, l'auteur de la crise et l'administrateur. */
  peut_retirer: boolean;
}

/** Une forme d'aide qu'une institution peut proposer en renfort (catalogue du serveur). */
export interface AideRenfort {
  code: string;
  libelle: string;
  description: string;
}

/** Une crise en cours, vue par une institution qui peut y candidater. */
export interface CriseACandidater {
  id: string;
  name: string;
  type_display: string;
  commune: string | null;
  start_date: string;
  nb_communes: number;
  situation: {
    /** Déjà déclarée « impliquée » (son territoire est touché). */
    impliquee: boolean;
    /** Statut de sa proposition d'aide, s'il y en a une. */
    acteur: 'EN_ATTENTE' | 'VALIDEE' | 'REFUSEE' | null;
    /** Sa commune est dans la zone de la crise. */
    dans_la_zone: boolean;
  };
}

export interface CandidaturesCrises {
  /** L'institution au nom de laquelle on candidate ; null si le compte n'en a pas. */
  institution: { id: string; nom: string } | null;
  aides: AideRenfort[];
  crises: CriseACandidater[];
}
