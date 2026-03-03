import { Statut } from "./status.model";

// Format GeoJSON retourné par GeoDjango (PointField)
export interface GeoPoint {
  type: 'Point';
  coordinates: [number, number];        
}

export interface Crise {
  id: string;                           
  nom: string;
  type: string;
  description?: string | null;
  statut?:  Statut;
  localisation: GeoPoint;              
  latitude?: number;
  longitude?: number;
  date_debut: string;                   
  date_fin: string | null;
  validateur: string | null;           
  auteur: string | null;           
  photo: string | null;   
  severite: string | null;           
}

export interface CrisePayload {
  nom: string;
  type: string;
  description?: string | null;
  statut?: string;
  latitude: number;                     
  longitude: number;                    
  date_fin?: string | null;
  validateur?: string | null;
  auteur?: string | null;
}