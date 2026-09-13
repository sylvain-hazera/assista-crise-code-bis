import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { CanalMeshtastic, MessageCanalMeshtastic } from '../shared/models/canal-meshtastic.model';

@Injectable({ providedIn: 'root' })
export class CanalMeshtasticService {

  private url = `${environment.apiUrl}/canaux-meshtastic`;
  private urlMessages = `${environment.apiUrl}/messages-canal-meshtastic`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<CanalMeshtastic[]> {
    return this.http.get<CanalMeshtastic[]>(`${this.url}/`);
  }

  create(data: Partial<CanalMeshtastic>): Observable<CanalMeshtastic> {
    return this.http.post<CanalMeshtastic>(`${this.url}/`, data);
  }

  getMessages(canalId: string): Observable<MessageCanalMeshtastic[]> {
    return this.http.get<MessageCanalMeshtastic[]>(`${this.urlMessages}/`, { params: { canal: canalId } });
  }

  envoyerMessage(canalId: string, contenu: string): Observable<MessageCanalMeshtastic> {
    return this.http.post<MessageCanalMeshtastic>(`${this.urlMessages}/`, {
      canal: canalId, direction: 'SORTANT', contenu,
    });
  }
}
