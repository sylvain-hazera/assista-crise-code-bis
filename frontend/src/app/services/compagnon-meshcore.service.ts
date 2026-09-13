import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { CompagnonMeshCore } from '../shared/models/compagnon-meshcore.model';

@Injectable({ providedIn: 'root' })
export class CompagnonMeshCoreService {

  private url = `${environment.apiUrl}/compagnons-meshcore`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<CompagnonMeshCore[]> {
    return this.http.get<CompagnonMeshCore[]>(`${this.url}/`);
  }

  create(data: Partial<CompagnonMeshCore>): Observable<CompagnonMeshCore> {
    return this.http.post<CompagnonMeshCore>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<CompagnonMeshCore>): Observable<CompagnonMeshCore> {
    return this.http.patch<CompagnonMeshCore>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
