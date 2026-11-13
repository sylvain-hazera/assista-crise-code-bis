import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AffectationRoleOperationnel } from '../shared/models/institution.model';

@Injectable({
  providedIn: 'root'
})
export class AffectationRoleOperationnelService {

  private url = `${environment.apiUrl}/affectations-roles`;

  constructor(private http: HttpClient) {}

  /** Toutes, ou celles d'UNE institution.
   *
   * Le filtre existe depuis le 13/11/2026 : sans lui, la fiche d'une institution chargeait les
   * affectations de toutes les institutions de la plateforme pour n'en afficher qu'une. À
   * l'échelle visée (des milliers d'institutions), c'est la table entière rapatriée dans le
   * navigateur. */
  getAll(filtres?: { institution?: string }): Observable<AffectationRoleOperationnel[]> {
    const params: Record<string, string> = {};
    if (filtres?.institution) { params['institution'] = filtres.institution; }
    return this.http.get<AffectationRoleOperationnel[]>(`${this.url}/`, { params });
  }

  create(data: Partial<AffectationRoleOperationnel>): Observable<AffectationRoleOperationnel> {
    return this.http.post<AffectationRoleOperationnel>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<AffectationRoleOperationnel>): Observable<AffectationRoleOperationnel> {
    return this.http.put<AffectationRoleOperationnel>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
