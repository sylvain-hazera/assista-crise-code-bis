import type { Polygon } from "geojson";

export interface Zone {
  id: string;
  institution: string;
  institution_nom?: string | null;
  nom: string;
  description?: string | null;
  communes: string[];
  zone_precise?: string | null;          // WKT en écriture
  zone_precise_geojson?: Polygon | null; // GeoJSON natif en lecture
  actif: boolean;
}

export interface ZonePayload {
  nom: string;
  description?: string;
  communes?: string[];
  zone_precise?: string | null;
  institution?: string;
}
