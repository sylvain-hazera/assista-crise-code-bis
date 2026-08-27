import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { MaterielCatalogue } from '../shared/models/materiel-catalogue.model';

@Injectable({
  providedIn: 'root'
})
export class MaterielCatalogueService {

  private url = `${environment.apiUrl}/materiels-catalogue`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<MaterielCatalogue[]> {
    return this.http.get<MaterielCatalogue[]>(`${this.url}/`);
  }

  search(query: string): Observable<MaterielCatalogue[]> {
    return this.http.get<MaterielCatalogue[]>(`${this.url}/`, { params: { q: query } });
  }

  create(data: Partial<MaterielCatalogue>): Observable<MaterielCatalogue> {
    return this.http.post<MaterielCatalogue>(`${this.url}/`, data);
  }
}
