import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface HelpRequest {
  id?: string; // UUID dans Django
  titre: string;
  prenom: string;
  nom: string;
  email: string;
  localisation: {
    type: 'Point';
    coordinates: [number, number]; // [longitude, latitude]
  };
  photo?: string; // URL ou File pour upload
  date_creation?: string;
  date_expiration?: string;
  statut?: 'NON_TRAITEE' | 'EN_COURS' | 'TRAITEE' | 'DISPONIBLE' | 'INDISPONIBLE';
  type_demande: string; // UUID du TypeDemande
  crise?: string; // UUID de la Crise (optionnel)
  auteur?: string; // UUID de l'Utilisateur (optionnel)
}

// interface HelpRequest {
//   id?: number;
//   eventType: string;
//   needType: string[];
//   description: string[];
//   streetNumber: string;
//   postalCode: string;
//   addressVisible: boolean;
//   image?: File;
//   createdAt?: Date;
// }

@Injectable({
  providedIn: 'root'
})
export class HelpRequestService {
  private apiUrl = `${environment.apiUrl}/demandes`;

  constructor(private http: HttpClient) {}

  createRequest(formData: FormData): Observable<HelpRequest> {
    return this.http.post<HelpRequest>(`${this.apiUrl}/`, formData);
  }

  getAllRequests(): Observable<HelpRequest[]> {
    return this.http.get<HelpRequest[]>(this.apiUrl);
  }

  getRequests(params?: any): Observable<HelpRequest[]> {
    let httpParams = new HttpParams();
    if (params) {
      Object.keys(params).forEach(key => {
        httpParams = httpParams.set(key, params[key]);
      });
    }
    return this.http.get<HelpRequest[]>(this.apiUrl, { params: httpParams });
  }

  getMyRequests(): Observable<HelpRequest[]> {
    return this.http.get<HelpRequest[]>(`${this.apiUrl}/my_requests/`);
  }
  
  getRequest(id: string): Observable<HelpRequest> {
    return this.http.get<HelpRequest>(`${this.apiUrl}/${id}/`);
  }

  updateRequest(id: string, formData: FormData): Observable<HelpRequest> {
    return this.http.put<HelpRequest>(`${this.apiUrl}/${id}/`, formData);
  }

  deleteRequest(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  getRequestStats(filter?: any): Observable<any> {
    let httpParams = new HttpParams();
    if (filter) {
      Object.keys(filter).forEach(key => {
        httpParams = httpParams.set(key, filter[key]);
      });
    }
    return this.http.get<any>(`${this.apiUrl}/stats`, { params: httpParams });
  }
}