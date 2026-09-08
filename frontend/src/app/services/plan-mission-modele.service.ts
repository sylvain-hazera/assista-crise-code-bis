import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { PlanMissionModele, PlanMissionModelePayload } from '../shared/models/plan.model';

@Injectable({ providedIn: 'root' })
export class PlanMissionModeleService {
  private url = `${environment.apiUrl}/plans-missions-modeles`;

  constructor(private http: HttpClient) {}

  getByPlan(planId: string): Observable<PlanMissionModele[]> {
    return this.http.get<PlanMissionModele[]>(`${this.url}/`, { params: new HttpParams().set('plan', planId) });
  }

  create(data: PlanMissionModelePayload): Observable<PlanMissionModele> {
    return this.http.post<PlanMissionModele>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
