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
  photo: string | null;
  location: GeoPoint;
  latitude?: number;
  longitude?: number;
  first_name_offer: string;
  last_name_offer: string;
  email_offer: string;
  created_at: string;
  expires_at: string | null;
  status: Status;
  offer_type: string;                   // UUID du OfferType (FK)
  crisis: string | null;
  author: string | null;
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