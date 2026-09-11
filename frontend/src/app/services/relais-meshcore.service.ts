import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { RelaisMeshCore } from '../shared/models/relais-meshcore.model';

@Injectable({ providedIn: 'root' })
export class RelaisMeshCoreService {

  private url = `${environment.apiUrl}/relais-meshcore`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<RelaisMeshCore[]> {
    return this.http.get<RelaisMeshCore[]>(`${this.url}/`);
  }

  create(data: Partial<RelaisMeshCore> & { latitude: number; longitude: number }): Observable<RelaisMeshCore> {
    return this.http.post<RelaisMeshCore>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
