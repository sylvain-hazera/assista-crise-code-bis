import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Competence } from '../shared/models/competence.model';

@Injectable({
  providedIn: 'root'
})
export class CompetenceService {

  private url = `${environment.apiUrl}/competences`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Competence[]> {
    return this.http.get<Competence[]>(`${this.url}/`);
  }

  search(query: string): Observable<Competence[]> {
    return this.http.get<Competence[]>(`${this.url}/`, { params: { q: query } });
  }

  create(data: Partial<Competence>): Observable<Competence> {
    return this.http.post<Competence>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Competence>): Observable<Competence> {
    return this.http.put<Competence>(`${this.url}/${id}/`, data);
  }

  patch(id: string, data: Partial<Competence>): Observable<Competence> {
    return this.http.patch<Competence>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}

