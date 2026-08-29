import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { ContributionMateriel, ContributionMaterielPayload } from '../shared/models/contribution-materiel.model';

@Injectable({ providedIn: 'root' })
export class ContributionMaterielService {
  private url = `${environment.apiUrl}/contributions-materiel`;

  constructor(private http: HttpClient) {}

  getByMaterielPoint(materielPointId: string): Observable<ContributionMateriel[]> {
    return this.http.get<ContributionMateriel[]>(`${this.url}/`, { params: { materiel_point: materielPointId } });
  }

  create(data: ContributionMaterielPayload): Observable<ContributionMateriel> {
    return this.http.post<ContributionMateriel>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<ContributionMaterielPayload>): Observable<ContributionMateriel> {
    return this.http.patch<ContributionMateriel>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
