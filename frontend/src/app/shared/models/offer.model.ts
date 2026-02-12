import { GeoPoint } from "./geopoint.model";
import { Status, Statut } from "./status.model";

// export interface OfferType {
//   id?: string;
//   type: string;
//   description: string;
// }

// export interface Offer {
//   id?: string;
//   date_creation?: string;
//   // localisation: { type: 'Point'; coordinates: [number, number] };
//   latitude: number;
//   longitude: number;
//   prenom: string;
//   nom: string;
//   email: string;
//   titre: string;
//   photo?: string;
//   createdAt?: string;
//   date_expiration?: string;
//   statut: Status;
//   type_offre: string[]; // UUID
//   crise?: string; // UUID
//   auteur?: string; // UUID
// }

export interface TypeOffre {
  id: string;
  type: string;
}

export interface Offre {
  id: string;                           // UUID
  titre: string;
  photo: string | null;
  localisation: GeoPoint;
  latitude?: number;
  longitude?: number;
  prenom_offre: string;
  nom_offre: string;
  email_offre: string;
  date_creation: string;
  date_expiration: string | null;
  statut: Statut;
  type_offre: string;                  // UUID du TypeOffre (FK)
  crise: string | null;
  auteur: string | null;
}

export interface OffrePayload {
  titre: string;
  prenom_offre: string;
  nom_offre: string;
  email_offre: string;
  latitude: number;
  longitude: number;
  type_offre: string;
  statut?: Statut;
  date_expiration?: string | null;
  crise?: string | null;
  photo?: File;
}