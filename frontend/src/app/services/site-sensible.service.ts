import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { PointOperationnel } from '../shared/models/point-operationnel.model';
import {
  ResultatImport, SiteSensible, SourceSiteSensible, SyntheseSitesSensibles,
} from '../shared/models/site-sensible.model';

@Injectable({ providedIn: 'root' })
export class SiteSensibleService {
  private url = `${environment.apiUrl}/sites-sensibles`;

  constructor(private http: HttpClient) {}

  getAll(filtres: Record<string, string> = {}): Observable<SiteSensible[]> {
    return this.http.get<SiteSensible[]>(`${this.url}/`, { params: filtres });
  }

  synthese(): Observable<SyntheseSitesSensibles> {
    return this.http.get<SyntheseSitesSensibles>(`${this.url}/synthese/`);
  }

  /** Lance l'import des sources demandées. FINESS part en tâche de fond (`asynchrone: true`) :
   * son état se suit en rappelant `synthese`. */
  importer(sources: SourceSiteSensible[]): Observable<ResultatImport> {
    return this.http.post<ResultatImport>(`${this.url}/importer/`, { sources });
  }

  update(id: string, data: Partial<SiteSensible>): Observable<SiteSensible> {
    return this.http.patch<SiteSensible>(`${this.url}/${id}/`, data);
  }

  create(data: Partial<SiteSensible>): Observable<SiteSensible> {
    return this.http.post<SiteSensible>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  creerPoint(id: string, data: { type: string; capacite_accueil?: number | null }): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.url}/${id}/creer-point/`, data);
  }
}
