import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { JournalCollectivite } from '../shared/models/journal-collectivite.model';

@Injectable({ providedIn: 'root' })
export class JournalCollectiviteService {
  private url = `${environment.apiUrl}/journal-collectivite`;

  constructor(private http: HttpClient) {}

  // Scopé côté backend à la seule institution de l'utilisateur connecté — voir
  // JournalCollectiviteViewSet.get_queryset.
  getAll(): Observable<JournalCollectivite[]> {
    return this.http.get<JournalCollectivite[]>(`${this.url}/`);
  }

  // Aucune route update/delete : une entrée est immuable une fois créée (voir
  // JournalCollectiviteViewSet, volontairement pas un ModelViewSet).
  create(contenu: string): Observable<JournalCollectivite> {
    return this.http.post<JournalCollectivite>(`${this.url}/`, { contenu });
  }
}
