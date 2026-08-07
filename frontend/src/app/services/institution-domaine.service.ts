import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { InstitutionDomaine } from '../shared/models/institution.model';

@Injectable({
  providedIn: 'root'
})
export class InstitutionDomaineService {

  private url = `${environment.apiUrl}/institutions-domaines`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<InstitutionDomaine[]> {
    return this.http.get<InstitutionDomaine[]>(`${this.url}/`);
  }

  create(data: Partial<InstitutionDomaine>): Observable<InstitutionDomaine> {
    return this.http.post<InstitutionDomaine>(`${this.url}/`, data);
  }

  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
