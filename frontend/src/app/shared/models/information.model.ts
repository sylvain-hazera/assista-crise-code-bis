import { GeoPoint } from "./geopoint.model";
import { Status, Statut } from "./status.model";

export interface TypeInformation {
  id: string;
  type: string;
}

export interface Information {
  id: string;                           // UUID
  titre: string;
  photo: string | null;
  localisation: GeoPoint;
  latitude?: number;
  longitude?: number;
  prenom_information: string;
  nom_information: string;
  email_information: string;
  telephone_information: string;
  date_creation: string;
  date_expiration: string | null;
  statut: Statut;
  type_information: string;            // UUID du TypeInformation (FK)
  crise: string | null;
  auteur: string | null;
}

export interface InformationPayload {
  titre: string;
  prenom_information: string;
  nom_information: string;
  email_information: string;
  telephone_information: string;
  latitude: number;
  longitude: number;
  type_information: string;
  statut?: Statut;
  date_expiration?: string | null;
  crise?: string | null;
  photo?: File;
}
