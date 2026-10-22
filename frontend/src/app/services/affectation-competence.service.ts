import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { AffectationCompetence } from '../shared/models/affectation-competence.model';

@Injectable({
  providedIn: 'root'
})
export class AffectationCompetenceService {

  private url = `${environment.apiUrl}/affectations`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<AffectationCompetence[]> {
    return this.http.get<AffectationCompetence[]>(`${this.url}/`);
  }

  create(data: Partial<AffectationCompetence>): Observable<AffectationCompetence> {
    return this.http.post<AffectationCompetence>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<AffectationCompetence>): Observable<AffectationCompetence> {
    return this.http.put<AffectationCompetence>(`${this.url}/${id}/`, data);
  }

  /** PATCH partiel (ex: { active: false } pour annuler un apprentissage de la cellule de crise). */
  patch(id: string, data: Partial<AffectationCompetence>): Observable<AffectationCompetence> {
    return this.http.patch<AffectationCompetence>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
