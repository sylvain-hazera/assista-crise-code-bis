import { Creneau } from './disponibilite-offre.model';

export interface CandidatBenevole {
  id: string;
  first_name_offer: string;
  last_name_offer: string;
  email_offer: string;
  title: string;
  competences_libelles: string[];
  distance_km: number | null;
  disponibilites: { date: string; creneau: Creneau }[];
}

export interface CandidatsBenevolesResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: CandidatBenevole[];
}

export interface CandidatsBenevolesParams {
  search?: string;
  creneaux?: string[];     // "YYYY-MM-DD:CRENEAU"
  competences?: string[];  // UUID de Competence
  ordering?: 'distance' | 'nom';
  page?: number;
  page_size?: number;
}
