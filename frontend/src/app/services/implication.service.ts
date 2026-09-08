import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ImplicationInstitution, ImplicationInstitutionPayload } from '../shared/models/implication.model';

@Injectable({ providedIn: 'root' })
export class ImplicationService {
  private apiUrl = `${environment.apiUrl}/implications-crises`;

  constructor(private http: HttpClient) {}

  // `institution`/`actif` optionnels (?institution=&actif=, voir filterset_fields côté
  // backend) — utilisé par VueMairieComponent pour peupler le sélecteur de crise du journal
  // de bord (crises actives de MON institution uniquement).
  getAll(options?: { institution?: string; actif?: boolean }): Observable<ImplicationInstitution[]> {
    let params = new HttpParams();
    if (options?.institution) params = params.set('institution', options.institution);
    if (options?.actif !== undefined) params = params.set('actif', String(options.actif));
    return this.http.get<ImplicationInstitution[]>(`${this.apiUrl}/`, { params });
  }

  getByCrise(criseId: string): Observable<ImplicationInstitution[]> {
    return this.http.get<ImplicationInstitution[]>(`${this.apiUrl}/`, { params: { crise: criseId } });
  }

  create(payload: ImplicationInstitutionPayload): Observable<ImplicationInstitution> {
    return this.http.post<ImplicationInstitution>(`${this.apiUrl}/`, payload);
  }

  update(id: string, payload: Partial<ImplicationInstitutionPayload>): Observable<ImplicationInstitution> {
    return this.http.patch<ImplicationInstitution>(`${this.apiUrl}/${id}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  valider(id: string): Observable<ImplicationInstitution> {
    return this.http.post<ImplicationInstitution>(`${this.apiUrl}/${id}/valider/`, {});
  }

  refuser(id: string): Observable<ImplicationInstitution> {
    return this.http.post<ImplicationInstitution>(`${this.apiUrl}/${id}/refuser/`, {});
  }
}
