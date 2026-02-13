// export interface Crisis {
//   id?: string;
//   nom: string;
//   localisation: { type: 'Point'; coordinates: [number, number] };
//   date_debut?: string;
//   date_fin?: string;
// }

export interface Crisis {
  id?: number;
  type: string;
  //severity: string;
  nom: string;
  location: string;
  description: string;
  status: string;
  date_debut?: Date;
  date_fin?: Date;
  latitude: number;
  longitude: number;
  validateur?: string;
}


export enum statusCrisis {
  UNPROCESSED,
  PROCESSING,
  PROCESSED,
  AVAILABLE,
  UNAVAILABLE
}