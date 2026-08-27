import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { RegistrePresence, RegistrePresencePayload } from '../shared/models/registre-presence.model';

@Injectable({
  providedIn: 'root'
})
export class RegistrePresenceService {

  private url = `${environment.apiUrl}/registre-presences`;

  constructor(private http: HttpClient) {}

  getByPoint(pointId: string): Observable<RegistrePresence[]> {
    return this.http.get<RegistrePresence[]>(`${this.url}/`, { params: { point: pointId } });
  }

  create(payload: RegistrePresencePayload): Observable<RegistrePresence> {
    return this.http.post<RegistrePresence>(`${this.url}/`, payload);
  }

  sortie(id: string): Observable<RegistrePresence> {
    return this.http.post<RegistrePresence>(`${this.url}/${id}/sortie/`, {});
  }
}
