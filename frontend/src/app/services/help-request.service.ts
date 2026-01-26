import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
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

@Injectable({
  providedIn: 'root'
})
export class HelpRequestService {
  private apiUrl = `${environment.apiUrl}/demandes`;

  constructor(private http: HttpClient) {}

  createRequest(formData: FormData): Observable<HelpRequest> {
    return this.http.post<HelpRequest>(`${this.apiUrl}/`, formData);
  }

  getRequests(params?: any): Observable<HelpRequest[]> {
    return this.http.get<HelpRequest[]>(`${this.apiUrl}/`, { params });
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
}