import { GeoPoint } from "./geopoint.model";
import { Status } from "./status.model";

export interface RequestType {
  id: string;                           // UUID
  type: string;                         // Unique
  description: string;
  parent: string | null;                // UUID du RequestType parent, si sous-catégorie
}

export interface Request {
  id: string;                           // UUID
  title: string;
  description?: string | null;
  has_photo: boolean;
  location: GeoPoint | null;            // null pour une demande d'hébergement (zone de recherche à la place)
  latitude?: number | null;             // Extrait côté Angular
  longitude?: number | null;
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
  author_type?: string | null;
  commune?: string | null;              // Résolu côté serveur (commune_code ou reverse-géocodage)
  distance_from_crisis_km?: number | null;
  est_affectee?: boolean;               // true si au moins une équipe l'a prise en charge (Team.assigned_requests)
  actif?: boolean;                      // false = désactivée (politique de désactivation)
  hebergement_duree?: string | null;
  type_loyer?: string | null;
  loyer_montant_min?: number | null;
  loyer_montant_max?: number | null;
  type_logement?: string | null;
  niveau_logement?: string | null;
  acces_etage?: string | null;
  nombre_pieces?: number | null;
  nombre_chambres?: number | null;
  capacite_adultes?: number | null;
  capacite_enfants?: number | null;
  animaux_acceptes?: boolean;
  jardin?: boolean;
  pmr_compatible?: boolean;
  zone_recherche_communes?: string[];   // codes INSEE de la zone de recherche (hébergement)
  zone_recherche_rayon_km?: number | null;
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

