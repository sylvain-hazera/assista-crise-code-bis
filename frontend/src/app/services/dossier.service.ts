import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Dossier } from '../shared/models/dossier.model';

@Injectable({
  providedIn: 'root'
})
export class DossierService {

  private url = `${environment.apiUrl}/dossiers`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Dossier[]> {
    return this.http.get<Dossier[]>(`${this.url}/`);
  }

  getById(id: string): Observable<Dossier> {
    return this.http.get<Dossier>(`${this.url}/${id}/`);
  }

  markViewed(id: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.url}/${id}/mark_viewed/`, {});
  }
}

