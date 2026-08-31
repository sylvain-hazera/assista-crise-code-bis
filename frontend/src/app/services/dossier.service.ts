import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Dossier } from '../shared/models/dossier.model';

@Injectable({
  providedIn: 'root'
})
export class DossierService {

  private url = `${environment.apiUrl}/dossiers`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Dossier[]> {
    return this.http.get<Dossier[]>(`${this.url}/`);
  }

  getMaFile(): Observable<Dossier[]> {
    return this.http.get<Dossier[]>(`${this.url}/ma_file/`);
  }

  /** GET /api/dossiers/vue_mairie/ — dossiers dont la demande, le signalement ou l'équipe
   * relève de la commune de l'institution de l'utilisateur appelant. */
  vueMairie(): Observable<Dossier[]> {
    return this.http.get<Dossier[]>(`${this.url}/vue_mairie/`);
  }

  getById(id: string): Observable<Dossier> {
    return this.http.get<Dossier>(`${this.url}/${id}/`);
  }

  markViewed(id: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.url}/${id}/mark_viewed/`, {});
  }

  cloturer(id: string, statut: 'CLOTURE' | 'RESOLU' = 'CLOTURE'): Observable<{ status: string; statut: string }> {
    return this.http.post<{ status: string; statut: string }>(`${this.url}/${id}/cloturer/`, { statut });
  }

  /** Réservé au chef/régulateur de l'équipe affectée (ou institutionnel) : ne touche jamais
   * qu'aux champs priorite/ordre, jamais au reste du dossier. */
  definirPriorite(id: string, changes: { priorite?: string; ordre?: number }): Observable<Dossier> {
    return this.http.post<Dossier>(`${this.url}/${id}/definir-priorite/`, changes);
  }
}

