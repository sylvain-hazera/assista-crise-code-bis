import { GeoPoint } from "./geopoint.model";
import { Status } from "./status.model";

export interface InformationType {
  id: string;
  type: string;
}

export interface Information {
  id: string;                           // UUID
  title: string;
  has_photo: boolean;
  location: GeoPoint;
  latitude?: number;
  longitude?: number;
  azimuth?: number | null;
  first_name_information: string;
  last_name_information: string;
  email_information: string;
  phone_information: string;
  created_at: string;
  expires_at: string | null;
  status: Status;
  information_type: string;             // UUID du InformationType (FK)
  crisis: string | null;
  crisis_nom?: string | null;
  author: string | null;
  author_nom?: string | null;
  author_email?: string | null;
}

export interface InformationPayload {
  title: string;
  first_name_information: string;
  last_name_information: string;
  email_information: string;
  phone_information: string;
  latitude: number;
  longitude: number;
  azimuth?: number | null;
  information_type: string;
  status?: Status;
  expires_at?: string | null;
  crisis?: string | null;
  photo?: File;
}
