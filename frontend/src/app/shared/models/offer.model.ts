import { Status } from "./status.model";

export interface OfferType {
  id?: string;
  type: string;
  description: string;
}

export interface Offer {
  id?: string;
  date_creation?: string;
  // localisation: { type: 'Point'; coordinates: [number, number] };
  latitude: number;
  longitude: number;
  prenom: string;
  nom: string;
  email: string;
  titre: string;
  photo?: string;
  createdAt?: string;
  date_expiration?: string;
  statut: Status;
  type_offre: string[]; // UUID
  crise?: string; // UUID
  auteur?: string; // UUID
}
