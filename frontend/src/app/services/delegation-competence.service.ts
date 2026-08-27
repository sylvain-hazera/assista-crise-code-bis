import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { DelegationCompetence, DelegationCompetencePayload } from '../shared/models/delegation-competence.model';

@Injectable({ providedIn: 'root' })
export class DelegationCompetenceService {
  private apiUrl = `${environment.apiUrl}/delegations-competences`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<DelegationCompetence[]> {
    return this.http.get<DelegationCompetence[]>(`${this.apiUrl}/`);
  }

  getByCrise(criseId: string): Observable<DelegationCompetence[]> {
    return this.http.get<DelegationCompetence[]>(`${this.apiUrl}/`, { params: { crise: criseId } });
  }

  create(payload: DelegationCompetencePayload): Observable<DelegationCompetence> {
    return this.http.post<DelegationCompetence>(`${this.apiUrl}/`, payload);
  }

  update(id: string, payload: Partial<DelegationCompetencePayload> & { active?: boolean }): Observable<DelegationCompetence> {
    return this.http.patch<DelegationCompetence>(`${this.apiUrl}/${id}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }
}
