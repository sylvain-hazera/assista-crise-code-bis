import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface HelpPropose {
  id?: number;
  resourceType: string[];
  description: string;
  // localisation: {
  //   type: 'Point';
  //   coordinates: [number, number]; // [longitude, latitude]
  // };
  latitude: number;
  longitude: number;
  availability: string;
  createdAt?: Date;
}

@Injectable({
  providedIn: 'root'
})
export class HelpProposeService {
  private apiUrl = `${environment.apiUrl}/offres`;

  constructor(private http: HttpClient) {}

  getAllProposes(): Observable<HelpPropose[]> {
    return this.http.get<HelpPropose[]>(this.apiUrl);
  }

  getProposes(params?: any): Observable<HelpPropose[]> {
    let httpParams = new HttpParams();
    if (params) {
      Object.keys(params).forEach(key => {
        httpParams = httpParams.set(key, params[key]);
      });
    }
    return this.http.get<HelpPropose[]>(this.apiUrl, { params: httpParams });
  }

  getProposeStats(filter?: any): Observable<any> {
    let httpParams = new HttpParams();
    if (filter) {
      Object.keys(filter).forEach(key => {
        httpParams = httpParams.set(key, filter[key]);
      });
    }
    return this.http.get<any>(`${this.apiUrl}/stats`, { params: httpParams });
  }
}