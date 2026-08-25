import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { DossierCommentaire } from '../shared/models/dossier-commentaire.model';

@Injectable({
  providedIn: 'root'
})
export class DossierCommentaireService {

  private apiUrl =
    `${environment.apiUrl}/dossier-commentaires/`;

  constructor(
    private http: HttpClient
  ) {}

  getAll(): Observable<DossierCommentaire[]> {
    return this.http.get<DossierCommentaire[]>(this.apiUrl);
  }

  create(payload: { dossier: string; commentaire: string }): Observable<DossierCommentaire> {
    return this.http.post<DossierCommentaire>(
      this.apiUrl,
      payload
    );
  }

}
