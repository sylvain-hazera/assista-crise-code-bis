import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { PointOperationnel, PointOperationnelPayload, PointEquipeResponse } from '../shared/models/point-operationnel.model';
import { AffectationPointBenevole, InviterBenevolePayload } from '../shared/models/affectation-point-benevole.model';

@Injectable({ providedIn: 'root' })
export class PointOperationnelService {
  private apiUrl = `${environment.apiUrl}/points-operationnels`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/`);
  }

  getByCrise(criseId: string): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/`, { params: { crise: criseId } });
  }

  /** Points dont je suis responsable, leader d'équipe ou membre — toutes crises confondues
   * (page "Centres", filtre "Mes centres"). */
  getMine(): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/`, { params: { mine: 'true' } });
  }

  create(payload: PointOperationnelPayload): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.apiUrl}/`, payload);
  }

  update(id: string, payload: Partial<PointOperationnelPayload>): Observable<PointOperationnel> {
    return this.http.patch<PointOperationnel>(`${this.apiUrl}/${id}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  getEquipe(id: string): Observable<PointEquipeResponse> {
    return this.http.get<PointEquipeResponse>(`${this.apiUrl}/${id}/equipe/`);
  }

  inviterBenevole(id: string, payload: InviterBenevolePayload): Observable<AffectationPointBenevole> {
    return this.http.post<AffectationPointBenevole>(`${this.apiUrl}/${id}/inviter-benevole/`, payload);
  }
}
