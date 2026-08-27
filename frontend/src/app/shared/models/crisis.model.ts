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
  start_date: string;
  end_date: string | null;
  validator: string | null;
  author: string | null;
  has_photo: boolean;
  severity: string | null;
  is_open?: boolean;
  has_responsable_actif?: boolean;
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