import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { CanalMeshCore, MessageCanalMeshCore } from '../shared/models/canal-meshcore.model';

@Injectable({ providedIn: 'root' })
export class CanalMeshCoreService {

  private url = `${environment.apiUrl}/canaux-meshcore`;
  private urlMessages = `${environment.apiUrl}/messages-canal-meshcore`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<CanalMeshCore[]> {
    return this.http.get<CanalMeshCore[]>(`${this.url}/`);
  }

  create(data: Partial<CanalMeshCore>): Observable<CanalMeshCore> {
    return this.http.post<CanalMeshCore>(`${this.url}/`, data);
  }

  getMessages(canalId: string): Observable<MessageCanalMeshCore[]> {
    return this.http.get<MessageCanalMeshCore[]>(`${this.urlMessages}/`, { params: { canal: canalId } });
  }

  envoyerMessage(canalId: string, contenu: string): Observable<MessageCanalMeshCore> {
    return this.http.post<MessageCanalMeshCore>(`${this.urlMessages}/`, {
      canal: canalId, direction: 'SORTANT', contenu,
    });
  }
}
