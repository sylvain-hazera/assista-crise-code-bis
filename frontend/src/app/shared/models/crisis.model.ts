// export interface Crisis {
//   id?: number;
//   type: string;
//   severity: string;
//   name: string;
//   location: string;
//   description: string;
//   status: string;
//   createdAt?: Date;
//   latitude: number;
//   longitude: number;
// }

import { Statut } from "./status.model";


// export enum statusCrisis {
//   UNPROCESSED,
//   PROCESSING,
//   PROCESSED,
//   AVAILABLE,
//   UNAVAILABLE
// }

// Format GeoJSON retourné par GeoDjango (PointField)
export interface GeoPoint {
  type: 'Point';
  coordinates: [number, number];        // [longitude, latitude]
}

export interface Crise {
  id: string;                           // UUID
  nom: string;
  type: string;
  description?: string | null;
  statut?:  Statut;
  localisation: GeoPoint;              // Django retourne toujours ce format
  // Pratique côté Angular (extraits de localisation)
  latitude?: number;
  longitude?: number;
  date_debut: string;                   // auto_now_add → read-only
  date_fin: string | null;
  validateur: string | null;           // UUID de l'Utilisateur (FK)
  auteur: string | null;           
  severite: string | null;              
}

// Payload envoyé pour créer/modifier une crise
export interface CrisePayload {
  nom: string;
  type: string;
  description?: string | null;
  statut?: string;
  latitude: number;                     // Angular envoie séparément…
  longitude: number;                    // …le service construit le GeoJSON
  date_fin?: string | null;
  validateur?: string | null;
  auteur?: string | null;
}