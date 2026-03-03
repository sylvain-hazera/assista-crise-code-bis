import { Status } from "./status.model";

// Format GeoJSON retourné par GeoDjango (PointField)
export interface GeoPoint {
  type: 'Point';
  coordinates: [number, number];        
}

export interface Crisis {
  id: string;                           
  name: string;
  type: string;
  description?: string | null;
  status?:  Status;
  location: GeoPoint;              
  latitude?: number;
  longitude?: number;
  start_date: string;                   
  end_date: string | null;
  validator: string | null;           
  author: string | null;           
  photo: string | null;   
  severity: string | null;           
}

export interface CrisisPayload {
  name: string;
  type: string;
  description?: string | null;
  status?: string;
  latitude: number;                     
  longitude: number;                    
  end_date?: string | null;
  validator?: string | null;
  author?: string | null;
}