import { GeoPoint } from "./geopoint.model";
import { Status } from "./status.model";

export interface OfferType {
  id: string;
  type: string;
  description: string;
}

export interface Offer {
  id: string;                           // UUID
  title: string;
  description?: string | null;
  photo: string | null;
  location: GeoPoint | null;            // null si l'offreur n'a pas indiqué d'adresse,
                                         // ou si l'adresse est masquée pour ce lecteur (public)
  latitude?: number | null;
  longitude?: number | null;
  first_name_offer: string;
  last_name_offer: string;
  email_offer: string;
  created_at: string;
  expires_at: string | null;
  status: Status;
  offer_type: string;                   // UUID du OfferType (FK)
  crisis: string | null;
  crisis_nom?: string | null;
  author: string | null;
  author_nom?: string | null;
  author_email?: string | null;
  hebergement_duree?: string | null;
  numero_adeli_rpps?: string | null;
  transport_type?: string | null;
  materiel_type?: string | null;
  soutien_type?: string | null;
  renouvelable?: boolean;
}

export interface OfferPayload {
  title: string;
  first_name_offer: string;
  last_name_offer: string;
  email_offer: string;
  latitude: number;
  longitude: number;
  offer_type: string;
  status?: Status;
  expires_at?: string | null;
  crisis?: string | null;
  photo?: File;
}