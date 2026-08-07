import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Institution } from '../shared/models/institution.model';

@Injectable({
  providedIn: 'root'
})
export class InstitutionService {

  private url = `${environment.apiUrl}/institutions`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Institution[]> {
    return this.http.get<Institution[]>(`${this.url}/`);
  }

  getById(id: string): Observable<Institution> {
    return this.http.get<Institution>(`${this.url}/${id}/`);
  }

  create(data: Partial<Institution>): Observable<Institution> {
    return this.http.post<Institution>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Institution>): Observable<Institution> {
    return this.http.put<Institution>(`${this.url}/${id}/`, data);
  }

  patch(id: string, data: Partial<Institution>): Observable<Institution> {
    return this.http.patch<Institution>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
