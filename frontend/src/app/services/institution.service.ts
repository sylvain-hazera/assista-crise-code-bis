import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EMPTY, Observable, expand, reduce } from 'rxjs';
import { environment } from '../../environments/environment';
import { Institution } from '../shared/models/institution.model';

interface PaginatedInstitutions {
  count: number;
  next: string | null;
  previous: string | null;
  results: Institution[];
}

@Injectable({
  providedIn: 'root'
})
export class InstitutionService {

  private url = `${environment.apiUrl}/institutions`;

  constructor(private http: HttpClient) {}

  /** GET /api/institutions/ — toujours paginé côté serveur (InstitutionPagination, 25/page)
   * depuis le correctif de zonage ("chez moi" + ma zone, sauf rôle ADMIN qui voit tout, voir
   * InstitutionViewSet.get_queryset). Suit `next` et réassemble la liste complète : aucun des
   * appelants existants (sélecteurs d'institution dans crises/équipes/déclaration de crise
   * publique) n'a de pagination UI, ils attendent tous un tableau complet. */
  getAll(): Observable<Institution[]> {
    return this.http.get<PaginatedInstitutions>(`${this.url}/`).pipe(
      expand(page => page.next ? this.http.get<PaginatedInstitutions>(page.next) : EMPTY),
      reduce((acc, page) => acc.concat(page.results), [] as Institution[]),
    );
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
