import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ImplicationInstitution, ImplicationInstitutionPayload } from '../shared/models/implication.model';

@Injectable({ providedIn: 'root' })
export class ImplicationService {
  private apiUrl = `${environment.apiUrl}/implications-crises`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<ImplicationInstitution[]> {
    return this.http.get<ImplicationInstitution[]>(`${this.apiUrl}/`);
  }

  getByCrise(criseId: string): Observable<ImplicationInstitution[]> {
    return this.http.get<ImplicationInstitution[]>(`${this.apiUrl}/`, { params: { crise: criseId } });
  }

  create(payload: ImplicationInstitutionPayload): Observable<ImplicationInstitution> {
    return this.http.post<ImplicationInstitution>(`${this.apiUrl}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }
}
