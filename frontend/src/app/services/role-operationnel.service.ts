import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { RoleOperationnel } from '../shared/models/institution.model';

@Injectable({
  providedIn: 'root'
})
export class RoleOperationnelService {

  private url = `${environment.apiUrl}/roles-operationnels`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<RoleOperationnel[]> {
    return this.http.get<RoleOperationnel[]>(`${this.url}/`);
  }

  create(data: Partial<RoleOperationnel>): Observable<RoleOperationnel> {
    return this.http.post<RoleOperationnel>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<RoleOperationnel>): Observable<RoleOperationnel> {
    return this.http.put<RoleOperationnel>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
