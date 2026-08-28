import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { DeclarationSecurite } from '../shared/models/declaration-securite.model';

@Injectable({ providedIn: 'root' })
export class DeclarationSecuriteService {
  private url = `${environment.apiUrl}/declarations-securite`;

  constructor(private http: HttpClient) {}

  getAll(params?: Record<string, string>): Observable<DeclarationSecurite[]> {
    return this.http.get<DeclarationSecurite[]>(`${this.url}/`, { params });
  }

  create(data: Partial<DeclarationSecurite>): Observable<DeclarationSecurite> {
    return this.http.post<DeclarationSecurite>(`${this.url}/`, data);
  }

  /** GET /api/declarations-securite/vue_mairie/ — déclarations liées à un centre d'accueil
   * situé dans la commune de l'institution de l'utilisateur appelant. */
  vueMairie(): Observable<DeclarationSecurite[]> {
    return this.http.get<DeclarationSecurite[]>(`${this.url}/vue_mairie/`);
  }

  /** GET /api/declarations-securite/mes_declarations/ — déclarations de l'utilisateur
   * connecté lui-même, accessible sans droits institutionnels. */
  mesDeclarations(): Observable<DeclarationSecurite[]> {
    return this.http.get<DeclarationSecurite[]>(`${this.url}/mes_declarations/`);
  }

  /** PATCH /api/declarations-securite/:id/ — l'auteur peut faire évoluer sa propre situation
   * (arrivée/départ d'un centre d'accueil, relogement...). */
  update(id: string, data: Partial<DeclarationSecurite>): Observable<DeclarationSecurite> {
    return this.http.patch<DeclarationSecurite>(`${this.url}/${id}/`, data);
  }
}
