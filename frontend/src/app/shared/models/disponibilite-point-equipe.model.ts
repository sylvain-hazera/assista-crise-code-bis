import { Creneau } from './disponibilite-offre.model';

export interface DisponibilitePointEquipe {
  id: string;
  point: string;
  membre: string;
  membre_nom?: string;
  date: string;      // YYYY-MM-DD
  creneau: Creneau;
}

export interface DisponibilitePointEquipePayload {
  point: string;
  membre: string;
  date: string;
  creneau: Creneau;
}
