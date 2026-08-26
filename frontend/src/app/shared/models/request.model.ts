import { GeoPoint } from "./geopoint.model";
import { Status } from "./status.model";

export interface RequestType {
  id: string;                           // UUID
  type: string;                         // Unique
  description: string;
}

export interface Request {
  id: string;                           // UUID
  title: string;
  has_photo: boolean;
  location: GeoPoint;
  latitude?: number;                    // Extrait côté Angular
  longitude?: number;
  commune_code?: string | null;         // Code INSEE résolu par l'autocomplete d'adresse
  first_name_request: string;
  last_name_request: string;
  email_request: string;
  phone_request: string;
  created_at: string;                   // auto_now_add → read-only
  expires_at: string | null;
  status: Status;
  request_type: string;                 // UUID du RequestType (FK)
  crisis: string | null;                // UUID de Crisis (FK)
  crisis_nom?: string | null;
  author: string | null;                // UUID de l'User (FK)
  author_nom?: string | null;
  author_email?: string | null;
}

// Payload pour le formulaire de création
export interface RequestPayload {
  title: string;
  first_name_request: string;
  last_name_request: string;
  email_request: string;
  phone_request: string;
  latitude: number;
  longitude: number;
  request_type: string;                 // UUID
  status?: Status;
  expires_at?: string | null;
  crisis?: string | null;
  photo?: File;
}

