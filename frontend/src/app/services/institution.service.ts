import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EMPTY, Observable, expand, reduce } from 'rxjs';
import { environment } from '../../environments/environment';
import { Institution } from '../shared/models/institution.model';
import { MatrixMessage } from '../shared/models/team.model';
import { ConfigurationEnvoi, ConfigurationEnvoiPatch } from '../shared/models/configuration-envoi.model';

export type TypeSalonInstitution = 'PERMANENTS' | 'BENEVOLES';

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

  /** GET /api/institutions/<id>/configuration-envoi/ — identifiants d'envoi (email Brevo,
   * SMS). Réservé au bureau de l'institution ; 403 sinon.
   *
   * La ligne est créée au premier appel plutôt que de rendre 404 : l'onglet doit s'ouvrir sur
   * un formulaire vide, pas sur une erreur. Les clés ne sont jamais rendues — voir le modèle. */
  getConfigurationEnvoi(id: string): Observable<ConfigurationEnvoi> {
    return this.http.get<ConfigurationEnvoi>(`${this.url}/${id}/configuration-envoi/`);
  }

  /** PATCH /api/institutions/<id>/configuration-envoi/ — une clé absente du corps est
   * inchangée, une chaîne vide l'effface. */
  majConfigurationEnvoi(id: string, patch: ConfigurationEnvoiPatch): Observable<ConfigurationEnvoi> {
    return this.http.patch<ConfigurationEnvoi>(`${this.url}/${id}/configuration-envoi/`, patch);
  }

  /** POST /api/institutions/<id>/provisionner-salons-matrix/ — active les deux salons
   * généraux (permanents/bénévoles), voir InstitutionViewSet.provisionner_salons_matrix. */
  provisionnerSalonsMatrix(id: string): Observable<{ id: string; type: TypeSalonInstitution; room_id: string | null }[]> {
    return this.http.post<{ id: string; type: TypeSalonInstitution; room_id: string | null }[]>(
      `${this.url}/${id}/provisionner-salons-matrix/`, {},
    );
  }

  /** GET/POST /api/institutions/<id>/salon-matrix-messages/<type>/ — chat intégré des salons
   * généraux d'institution, même relais côté bot que TeamService.getSalonMatrixMessages. */
  getSalonMatrixMessages(id: string, type: TypeSalonInstitution): Observable<{ messages: MatrixMessage[] }> {
    return this.http.get<{ messages: MatrixMessage[] }>(`${this.url}/${id}/salon-matrix-messages/${type}/`);
  }

  envoyerMessageSalonMatrix(id: string, type: TypeSalonInstitution, texte: string): Observable<{ messages: MatrixMessage[] }> {
    return this.http.post<{ messages: MatrixMessage[] }>(`${this.url}/${id}/salon-matrix-messages/${type}/`, { texte });
  }
}
