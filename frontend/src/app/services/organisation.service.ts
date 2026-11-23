import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** Une équipe dans l'arbre de l'organisation (backend/core/organisation.py). */
export interface EquipeOrganisation {
  id: string;
  nom: string;
  rcsc: boolean;
  membres: number;
  sous_equipes: EquipeOrganisation[];
}

/** Une institution dans l'arbre : elle, ses équipes, ses filles. */
export interface NoeudOrganisation {
  id: string;
  nom: string;
  actif: boolean;
  type_code: string;
  type_libelle: string;
  rcsc: boolean;
  commune: string;
  membres: number;
  equipes: EquipeOrganisation[];
  filles: NoeudOrganisation[];
}

@Injectable({ providedIn: 'root' })
export class OrganisationService {
  private readonly url = `${environment.apiUrl}/organisation/`;

  constructor(private http: HttpClient) {}

  /** Les arbres du périmètre ; `recherche` : l'arbre de chaque institution trouvée (administrateur). */
  arbres(recherche = ''): Observable<{ arbres: NoeudOrganisation[] }> {
    const params = recherche.trim() ? new HttpParams().set('q', recherche.trim()) : undefined;
    return this.http.get<{ arbres: NoeudOrganisation[] }>(this.url, { params });
  }
}
