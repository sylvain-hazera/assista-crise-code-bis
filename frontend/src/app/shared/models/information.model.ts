import { GeoPoint } from "./geopoint.model";
import { Status, Statut } from "./status.model";

// export interface InformationType {
//   id?: string;
//   type: string;
//   description: string;
// }

// export interface Information {
//   id?: string;
//   titre: string;
//   photo?: string;
//   prenom: string;
//   nom: string;
//   email: string;
//   // localisation: { type: 'Point'; coordinates: [number, number] };
//   latitude: number;
//   longitude: number;
//   date_creation?: string;
//   date_expiration?: string;
//   statut: Status;
//   type_information: string[]; // UUID
//   crise?: string; // UUID
//   auteur?: string; // UUID
// }

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
