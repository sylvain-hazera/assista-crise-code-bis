export type Creneau = 'MATIN' | 'MIDI' | 'SOIR' | 'NUIT';

export interface DisponibiliteOffre {
  id: string;
  offer: string;
  date: string;      // YYYY-MM-DD
  creneau: Creneau;
}

export interface DisponibiliteOffrePayload {
  offer: string;
  date: string;
  creneau: Creneau;
}
