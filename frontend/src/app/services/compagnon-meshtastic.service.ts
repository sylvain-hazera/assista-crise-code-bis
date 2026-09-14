import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { CompagnonMeshtastic } from '../shared/models/compagnon-meshtastic.model';

@Injectable({ providedIn: 'root' })
export class CompagnonMeshtasticService {

  private url = `${environment.apiUrl}/compagnons-meshtastic`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<CompagnonMeshtastic[]> {
    return this.http.get<CompagnonMeshtastic[]>(`${this.url}/`);
  }

  /** GET /api/compagnons-meshtastic/envoyables/ — résumé minimal (id/nom/broker_host, jamais
   * les identifiants MQTT) pour le sélecteur de broker lors d'une réclamation de nœud. */
  envoyables(): Observable<Pick<CompagnonMeshtastic, 'id' | 'nom' | 'broker_host'>[]> {
    return this.http.get<Pick<CompagnonMeshtastic, 'id' | 'nom' | 'broker_host'>[]>(`${this.url}/envoyables/`);
  }

  create(data: Partial<CompagnonMeshtastic>): Observable<CompagnonMeshtastic> {
    return this.http.post<CompagnonMeshtastic>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<CompagnonMeshtastic>): Observable<CompagnonMeshtastic> {
    return this.http.patch<CompagnonMeshtastic>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
