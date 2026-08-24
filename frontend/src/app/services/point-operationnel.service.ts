import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { PointOperationnel, PointOperationnelPayload } from '../shared/models/point-operationnel.model';

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

  create(payload: PointOperationnelPayload): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.apiUrl}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }
}
