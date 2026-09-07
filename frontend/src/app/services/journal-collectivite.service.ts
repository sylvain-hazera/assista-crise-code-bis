import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { JournalCollectivite } from '../shared/models/journal-collectivite.model';

@Injectable({ providedIn: 'root' })
export class JournalCollectiviteService {
  private url = `${environment.apiUrl}/journal-collectivite`;

  constructor(private http: HttpClient) {}

  // Scopé côté backend à la seule institution de l'utilisateur connecté — voir
  // JournalCollectiviteViewSet.get_queryset. `crise` (optionnel) filtre sur une crise précise
  // (?crise=, voir filterset_fields côté backend) — une institution peut être impliquée sur
  // plusieurs crises actives simultanément.
  getAll(crise?: string): Observable<JournalCollectivite[]> {
    let params = new HttpParams();
    if (crise) params = params.set('crise', crise);
    return this.http.get<JournalCollectivite[]>(`${this.url}/`, { params });
  }

  // Aucune route update/delete : une entrée est immuable une fois créée (voir
  // JournalCollectiviteViewSet, volontairement pas un ModelViewSet). `crise` obligatoire côté
  // backend (voir perform_create : l'institution doit y être effectivement impliquée).
  create(contenu: string, crise: string): Observable<JournalCollectivite> {
    return this.http.post<JournalCollectivite>(`${this.url}/`, { contenu, crise });
  }
}
