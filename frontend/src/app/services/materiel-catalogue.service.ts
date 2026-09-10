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

  getAll(categorie?: string): Observable<MaterielCatalogue[]> {
    const params: Record<string, string> = categorie ? { categorie } : {};
    return this.http.get<MaterielCatalogue[]>(`${this.url}/`, { params });
  }

  search(query: string): Observable<MaterielCatalogue[]> {
    return this.http.get<MaterielCatalogue[]>(`${this.url}/`, { params: { q: query } });
  }

  create(data: Partial<MaterielCatalogue>): Observable<MaterielCatalogue> {
    return this.http.post<MaterielCatalogue>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<MaterielCatalogue>): Observable<MaterielCatalogue> {
    return this.http.put<MaterielCatalogue>(`${this.url}/${id}/`, data);
  }

  patch(id: string, data: Partial<MaterielCatalogue>): Observable<MaterielCatalogue> {
    return this.http.patch<MaterielCatalogue>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
