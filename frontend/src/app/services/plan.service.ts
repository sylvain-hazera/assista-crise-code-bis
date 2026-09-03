import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Plan, PlanActivationPayload, PlanActivationResult, PlanPayload } from '../shared/models/plan.model';

@Injectable({ providedIn: 'root' })
export class PlanService {
  private url = `${environment.apiUrl}/plans`;

  constructor(private http: HttpClient) {}

  getAll(institutionId?: string): Observable<Plan[]> {
    const params = institutionId ? new HttpParams().set('institution', institutionId) : undefined;
    return this.http.get<Plan[]>(`${this.url}/`, { params });
  }

  getById(id: string): Observable<Plan> {
    return this.http.get<Plan>(`${this.url}/${id}/`);
  }

  create(data: PlanPayload): Observable<Plan> {
    return this.http.post<Plan>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<PlanPayload>): Observable<Plan> {
    return this.http.patch<Plan>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** POST /api/plans/<id>/activer/ — applique le sous-ensemble choisi d'équipes/points du plan
   * à une crise réelle (existante ou créée à la volée). */
  activer(id: string, payload: PlanActivationPayload): Observable<PlanActivationResult> {
    return this.http.post<PlanActivationResult>(`${this.url}/${id}/activer/`, payload);
  }
}
