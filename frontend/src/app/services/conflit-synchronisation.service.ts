import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { ConflitSynchronisation } from '../shared/models/conflit-synchronisation.model';

@Injectable({ providedIn: 'root' })
export class ConflitSynchronisationService {

  private url = `${environment.apiUrl}/conflits-synchronisation`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<ConflitSynchronisation[]> {
    return this.http.get<ConflitSynchronisation[]>(`${this.url}/`);
  }

  /** POST /api/conflits-synchronisation/<id>/resoudre/ — GARDE_LOCAL applique payload_local sur
   * l'objet central (le satellite avait raison), GARDE_CENTRAL ne touche à rien. Voir
   * ConflitSynchronisationViewSet.resoudre côté backend. */
  resoudre(id: string, choix: 'GARDE_CENTRAL' | 'GARDE_LOCAL'): Observable<ConflitSynchronisation> {
    return this.http.post<ConflitSynchronisation>(`${this.url}/${id}/resoudre/`, { choix });
  }
}
