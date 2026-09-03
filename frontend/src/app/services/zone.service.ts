import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Zone, ZonePayload } from '../shared/models/zone.model';

@Injectable({ providedIn: 'root' })
export class ZoneService {
  private url = `${environment.apiUrl}/zones`;

  constructor(private http: HttpClient) {}

  getAll(institutionId?: string): Observable<Zone[]> {
    const params = institutionId ? new HttpParams().set('institution', institutionId) : undefined;
    return this.http.get<Zone[]>(`${this.url}/`, { params });
  }

  getById(id: string): Observable<Zone> {
    return this.http.get<Zone>(`${this.url}/${id}/`);
  }

  create(data: ZonePayload): Observable<Zone> {
    return this.http.post<Zone>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<ZonePayload>): Observable<Zone> {
    return this.http.patch<Zone>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
