import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { PointOperationnel } from '../shared/models/point-operationnel.model';
import {
  CategorieSiteSensible, CoordonneesDevoilees, ResultatImport, SiteSensible, SourceSiteSensible,
  SyntheseSitesSensibles,
} from '../shared/models/site-sensible.model';

@Injectable({ providedIn: 'root' })
export class SiteSensibleService {
  private url = `${environment.apiUrl}/sites-sensibles`;

  constructor(private http: HttpClient) {}

  getAll(filtres: Record<string, string> = {}): Observable<SiteSensible[]> {
    return this.http.get<SiteSensible[]>(`${this.url}/`, { params: filtres });
  }

  synthese(): Observable<SyntheseSitesSensibles> {
    return this.http.get<SyntheseSitesSensibles>(`${this.url}/synthese/`);
  }

  /** Lance l'import des sources demandées. FINESS et SIRENE partent en tâche de fond
   * (`asynchrone: true`) : leur état se suit en rappelant `synthese`.
   *
   * `categories` ne concerne que SIRENE : ce sont les thèmes à recenser (élevages, moyens,
   * hébergement…). Sans elles, SIRENE prendrait ses thèmes par défaut — inexploitable en ville,
   * d'où le choix explicite dans la page. */
  importer(sources: SourceSiteSensible[],
           categories?: CategorieSiteSensible[]): Observable<ResultatImport> {
    const corps: { sources: SourceSiteSensible[]; categories?: CategorieSiteSensible[] } =
      { sources };
    if (categories?.length) corps.categories = categories;
    return this.http.post<ResultatImport>(`${this.url}/importer/`, corps);
  }

  /** Dévoile l'adresse et les coordonnées d'une personne en nom propre. Appel serveur
   * délibéré : il écrit une ligne de main courante, ce qu'une bascule d'affichage ne ferait
   * pas. */
  devoiler(id: string): Observable<CoordonneesDevoilees> {
    return this.http.get<CoordonneesDevoilees>(`${this.url}/${id}/devoiler/`);
  }

  update(id: string, data: Partial<SiteSensible>): Observable<SiteSensible> {
    return this.http.patch<SiteSensible>(`${this.url}/${id}/`, data);
  }

  create(data: Partial<SiteSensible>): Observable<SiteSensible> {
    return this.http.post<SiteSensible>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  creerPoint(id: string, data: { type: string; capacite_accueil?: number | null }): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.url}/${id}/creer-point/`, data);
  }
}
