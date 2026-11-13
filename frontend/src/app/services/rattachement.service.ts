import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { ContactInstitution } from '../shared/models/institution.model';

/** Une page de rattachements, telle que le serveur la rend quand on demande `?page=`. */
export interface PageRattachements {
  count: number;
  next: string | null;
  previous: string | null;
  results: ContactInstitution[];
}

/** Les institutions où JE suis membre, et celle pour laquelle je travaille en ce moment. */
export interface InstitutionActive {
  active: string | null;
  institutions: { id: string; nom: string; nom_affichage: string; type_libelle: string }[];
}

/**
 * Qui est membre de quelle institution.
 *
 * **Toujours paginé et cherché côté serveur.** C'est la raison d'être de ce service : la page
 * doit tenir avec des milliers d'institutions, donc elle ne charge jamais la table entière
 * pour filtrer ensuite dans le navigateur. `?page=` est ce qui active la pagination côté
 * serveur (`OptionalPageNumberPagination`), les autres appelants gardant leur tableau brut.
 */
@Injectable({ providedIn: 'root' })
export class RattachementService {

  private url = `${environment.apiUrl}/contacts-institution`;
  private moi = `${environment.apiUrl}/me/institution-active/`;

  constructor(private http: HttpClient) {}

  rechercher(options: {
    recherche?: string; institution?: string; utilisateur?: string;
    actif?: boolean; page?: number; pageSize?: number;
  } = {}): Observable<PageRattachements> {
    const params: Record<string, string> = { page: String(options.page ?? 1) };
    if (options.pageSize) { params['page_size'] = String(options.pageSize); }
    if (options.recherche?.trim()) { params['search'] = options.recherche.trim(); }
    if (options.institution) { params['institution'] = options.institution; }
    if (options.utilisateur) { params['utilisateur'] = options.utilisateur; }
    if (options.actif !== undefined) { params['actif'] = String(options.actif); }
    return this.http.get<PageRattachements>(`${this.url}/`, { params });
  }

  institutionActive(): Observable<InstitutionActive> {
    return this.http.get<InstitutionActive>(this.moi);
  }

  definirInstitutionActive(institution: string): Observable<InstitutionActive> {
    return this.http.post<InstitutionActive>(this.moi, { institution });
  }

  retirer(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  basculerActif(id: string, actif: boolean): Observable<ContactInstitution> {
    return this.http.patch<ContactInstitution>(`${this.url}/${id}/`, { actif });
  }
}
