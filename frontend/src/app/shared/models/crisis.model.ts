export interface Crisis {
  id?: string;
  nom: string;
  localisation: { type: 'Point'; coordinates: [number, number] };
  date_debut?: string;
  date_fin?: string;
}

export enum statusCrisis {
  UNPROCESSED,
  PROCESSING,
  PROCESSED,
  AVAILABLE,
  UNAVAILABLE
}