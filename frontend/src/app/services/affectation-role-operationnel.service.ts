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

  getAll(): Observable<AffectationRoleOperationnel[]> {
    return this.http.get<AffectationRoleOperationnel[]>(`${this.url}/`);
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
