import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { BesoinMateriel } from '../shared/models/besoin-materiel.model';

@Injectable({
  providedIn: 'root'
})
export class BesoinMaterielService {

  private url = `${environment.apiUrl}/besoins-materiels`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<BesoinMateriel[]> {
    return this.http.get<BesoinMateriel[]>(`${this.url}/`);
  }

  create(besoin: string, materiel: string): Observable<BesoinMateriel> {
    return this.http.post<BesoinMateriel>(`${this.url}/`, { besoin, materiel });
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
