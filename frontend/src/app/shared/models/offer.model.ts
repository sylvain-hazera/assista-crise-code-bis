import { GeoPoint } from "./geopoint.model";
import { Status, Statut } from "./status.model";

export interface TypeOffre {
  id: string;
  type: string;
  description: string;
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