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

  /** GET /api/compagnons-meshcore/envoyables/ — résumé minimal (id/nom/principal, jamais la
   * config réseau) pour choisir un émetteur de DM sans passer par getAll() (bloqué en zone
   * DEMO, voir CompagnonMeshCoreViewSet). */
  envoyables(): Observable<Pick<CompagnonMeshCore, 'id' | 'nom' | 'principal'>[]> {
    return this.http.get<Pick<CompagnonMeshCore, 'id' | 'nom' | 'principal'>[]>(`${this.url}/envoyables/`);
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
