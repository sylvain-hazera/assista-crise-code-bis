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

  /** POST /api/dossiers/<id>/marquer-important/ — bascule le signalement "important" (notifie
   * les régulateurs concernés au passage à true). Accessible à tout participant du dossier. */
  marquerImportant(id: string): Observable<Dossier> {
    return this.http.post<Dossier>(`${this.url}/${id}/marquer-important/`, {});
  }

  /** POST /api/dossiers/<id>/affecter-equipe/ — affecte (ou réaffecte) une équipe directement
   * depuis la vue régulateur, peuple les participants et notifie ses régulateurs. Réservé
   * institutionnel. */
  affecterEquipe(id: string, equipeId: string): Observable<Dossier> {
    return this.http.post<Dossier>(`${this.url}/${id}/affecter-equipe/`, { equipe: equipeId });
  }

  /** POST /api/dossiers/<id>/definir-statut/ — statuts intermédiaires uniquement (avant
   * affectation, en attente, affecté, en cours) ; utiliser cloturer() pour CLOTURE/RESOLU. */
  definirStatut(id: string, statut: string): Observable<Dossier> {
    return this.http.post<Dossier>(`${this.url}/${id}/definir-statut/`, { statut });
  }
}

