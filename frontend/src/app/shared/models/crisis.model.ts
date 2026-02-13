export interface Crisis {
  id?: string;
  name: string;
  description?: string;
  location?: { type: 'Point'; coordinates: [number, number] };
  radius?: number;
  start_date?: Date;
  end_date?: Date;
  latitude: number;
  longitude: number;
  validator?: string;
  status?: string;
}


export enum statusCrisis {
  UNPROCESSED,
  PROCESSING,
  PROCESSED,
  AVAILABLE,
  UNAVAILABLE
}