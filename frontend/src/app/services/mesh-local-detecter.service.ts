import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export interface MeshLocalDetectionResultat {
  type: 'meshtastic' | 'meshcore';
  id: string;
  nom: string;
}

@Injectable({ providedIn: 'root' })
export class MeshLocalDetecterService {

  private url = `${environment.apiUrl}/mesh-local/detecter`;

  constructor(private http: HttpClient) {}

  /** POST /api/mesh-local/detecter/ — connexion locale directe (usage offline, sans internet) :
   * on donne juste IP + port d'un vrai appareil, le serveur essaie une vraie connexion
   * Meshtastic puis MeshCore et crée le companion correspondant tout seul (voir
   * MeshLocalDetecterView côté Django). */
  detecter(ip: string, port: number, nom?: string): Observable<MeshLocalDetectionResultat> {
    return this.http.post<MeshLocalDetectionResultat>(`${this.url}/`, { ip, port, nom });
  }
}
