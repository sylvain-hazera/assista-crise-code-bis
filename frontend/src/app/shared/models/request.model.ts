import { Status } from "./status.model";

export interface RequestType {
  id?: string;
  type: string;
  description: string;
}

export interface Request {
  id?: string;
  titre: string;
  photo?: string;
  // localisation: { type: 'Point'; coordinates: [number, number] };
  latitude: number;
  longitude: number;
  prenom: string;
  nom: string;
  email: string;
  date_creation?: string;
  date_expiration?: string;
  statut: Status;
  type_demande: string[]; // UUID
  crise?: string; // UUID
  auteur?: string; // UUID
}
