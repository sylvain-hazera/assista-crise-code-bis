import { Status } from "./status.model";

export interface InformationType {
  id?: string;
  type: string;
  description: string;
}

export interface Information {
  id?: string;
  titre: string;
  photo?: string;
  prenom: string;
  nom: string;
  email: string;
  // localisation: { type: 'Point'; coordinates: [number, number] };
  latitude: number;
  longitude: number;
  date_creation?: string;
  date_expiration?: string;
  statut: Status;
  type_information: string[]; // UUID
  crise?: string; // UUID
  auteur?: string; // UUID
}