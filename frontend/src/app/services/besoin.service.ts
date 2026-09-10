import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Besoin } from '../shared/models/besoin.model';

@Injectable({
  providedIn: 'root'
})
export class BesoinService {

  private url = `${environment.apiUrl}/besoins`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Besoin[]> {
    return this.http.get<Besoin[]>(`${this.url}/`);
  }

  search(query: string): Observable<Besoin[]> {
    return this.http.get<Besoin[]>(`${this.url}/`, { params: { q: query } });
  }

  create(data: Partial<Besoin>): Observable<Besoin> {
    return this.http.post<Besoin>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Besoin>): Observable<Besoin> {
    return this.http.put<Besoin>(`${this.url}/${id}/`, data);
  }

  patch(id: string, data: Partial<Besoin>): Observable<Besoin> {
    return this.http.patch<Besoin>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
