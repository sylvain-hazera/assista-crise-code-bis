import { GeoPoint } from "./geopoint.model";
import { Statut } from "./status.model";

// export interface RequestType {
//   id?: string;
//   type: string;
//   description: string;
// }

// export interface Request {
//   id?: string;
//   titre: string;
//   photo?: string;
//   // localisation: { type: 'Point'; coordinates: [number, number] };
//   latitude: number;
//   longitude: number;
//   prenom: string;
//   nom: string;
//   email: string;
//   date_creation?: string;
//   date_expiration?: string;
//   statut: Status;
//   type_demande: string[]; // UUID
//   crise?: string; // UUID
//   auteur?: string; // UUID
// }

export interface TypeDemande {
  id: string;                           // UUID
  type: string;                         // Unique
}

export interface Demande {
  id: string;                           // UUID
  titre: string;
  photo: string | null;                 // URL en lecture
  localisation: GeoPoint;
  latitude?: number;                    // Extrait côté Angular
  longitude?: number;
  prenom_demande: string;
  nom_demande: string;
  email_demande: string;
  telephone_demande: string;
  date_creation: string;               // auto_now_add → read-only
  date_expiration: string | null;
  statut: Statut;
  type_demande: string;                // UUID du TypeDemande (FK)
  crise: string | null;               // UUID de Crise (FK)
  auteur: string | null;              // UUID de l'Utilisateur (FK)
}

// Payload pour le formulaire de création
export interface DemandePayload {
  titre: string;
  prenom_demande: string;
  nom_demande: string;
  email_demande: string;
  telephone_demande: string;
  latitude: number;
  longitude: number;
  type_demande: string;               // UUID
  statut?: Statut;
  date_expiration?: string | null;
  crise?: string | null;
  photo?: File;
}

