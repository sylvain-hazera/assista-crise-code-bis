import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Crisis } from '../shared/models/crisis.model';

@Injectable({
  providedIn: 'root'
})
export class CrisisService {
  private apiUrl = `${environment.apiUrl}/crises`;

  constructor(private http: HttpClient) {}

  getAllCrisis(): Observable<Crisis[]> {
    return this.http.get<Crisis[]>(this.apiUrl);
  }

  getParamCrisis(params?: any): Observable<Crisis[]> {
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

  getRecentCrisis(limit: number = 10): Observable<Crisis[]> {
    return this.http.get<Crisis[]>(`${this.apiUrl}/recent?limit=${limit}`);
  }

  // getCrisis(params?: any): Observable<Crisis[]> {
  //   return this.http.get<Crisis[]>(`${this.apiUrl}/`, { params });
  // }
  
  /**
 * Récupère toutes les crises créées par un utilisateur spécifique
 * @param userId L'ID de l'utilisateur (issu de l'objet User)
 */
  getMyCrisis(userId: number | string): Observable<Crisis[]> {
    // On passe l'ID en paramètre (ex: /api/crises/?user_id=1)
    // Assure-toi que ton backend Django filtre bien sur ce paramètre
    const params = new HttpParams().set('user_id', userId.toString());
    
    return this.http.get<Crisis[]>(this.apiUrl, { params });
  }

  getCrisis(id: string | number): Observable<Crisis> {
    return this.http.get<Crisis>(`${this.apiUrl}/${id}/`);
  }
  
  // createCrisis(data: Partial<Crisis>): Observable<Crisis> {
  //   return this.http.post<Crisis>(`${this.apiUrl}/`, data);
  // }

  createCrisis(formData: FormData): Observable<Request> {
    return this.http.post<Request>(`${this.apiUrl}/`, formData);
  }
  
  updateCrisis(id: string, data: Partial<Crisis>): Observable<Crisis> {
    return this.http.put<Crisis>(`${this.apiUrl}/${id}/`, data);
  }
  
  deleteCrisis(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }
  
}