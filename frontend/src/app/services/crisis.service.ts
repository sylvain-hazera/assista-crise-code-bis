import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

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

@Injectable({
  providedIn: 'root'
})
export class CrisisService {
  private apiUrl = `${environment.apiUrl}/crises`;

  constructor(private http: HttpClient) {}

  getAllCrises(): Observable<Crisis[]> {
    return this.http.get<Crisis[]>(this.apiUrl);
  }

  getCrises(params?: any): Observable<Crisis[]> {
    let httpParams = new HttpParams();
    if (params) {
      Object.keys(params).forEach(key => {
        httpParams = httpParams.set(key, params[key]);
      });
    }
    return this.http.get<Crisis[]>(this.apiUrl, { params: httpParams });
  }

  getCrisisStats(filter?: any): Observable<any> {
    let httpParams = new HttpParams();
    if (filter) {
      Object.keys(filter).forEach(key => {
        httpParams = httpParams.set(key, filter[key]);
      });
    }
    return this.http.get<any>(`${this.apiUrl}/stats`, { params: httpParams });
  }

  getRecentCrises(limit: number = 10): Observable<Crisis[]> {
    return this.http.get<Crisis[]>(`${this.apiUrl}/recent?limit=${limit}`);
  }
}