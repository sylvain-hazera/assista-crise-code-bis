import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { BesoinCompetence } from '../shared/models/besoin-competence.model';

@Injectable({
  providedIn: 'root'
})
export class BesoinCompetenceService {

  private url = `${environment.apiUrl}/besoins-competences`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<BesoinCompetence[]> {
    return this.http.get<BesoinCompetence[]>(`${this.url}/`);
  }

  create(besoin: string, competence: string): Observable<BesoinCompetence> {
    return this.http.post<BesoinCompetence>(`${this.url}/`, { besoin, competence });
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
