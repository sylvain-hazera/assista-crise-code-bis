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
  severity: string;
  name: string;
  location: string;
  description: string;
  status: string;
  createdAt?: Date;
  latitude: number;
  longitude: number;
}


export enum statusCrisis {
  UNPROCESSED,
  PROCESSING,
  PROCESSED,
  AVAILABLE,
  UNAVAILABLE
}