import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { NoeudUtilisateurMeshtastic } from '../shared/models/noeud-utilisateur-meshtastic.model';
import { PositionNoeudMissionMeshtastic } from '../shared/models/position-noeud-mission-meshtastic.model';

@Injectable({ providedIn: 'root' })
export class NoeudUtilisateurMeshtasticService {

  private url = `${environment.apiUrl}/noeuds-meshtastic`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<NoeudUtilisateurMeshtastic[]> {
    return this.http.get<NoeudUtilisateurMeshtastic[]>(`${this.url}/`);
  }

  /** GET /api/noeuds-meshtastic/positions-en-mission/ — positions des nœuds personnels
   * d'utilisateurs en mission EN_COURS uniquement, jamais en dehors (même règle que MeshCore,
   * voir NoeudUtilisateurMeshtasticViewSet.positions_en_mission). */
  positionsEnMission(): Observable<PositionNoeudMissionMeshtastic[]> {
    return this.http.get<PositionNoeudMissionMeshtastic[]>(`${this.url}/positions-en-mission/`);
  }

  create(data: Partial<NoeudUtilisateurMeshtastic>): Observable<NoeudUtilisateurMeshtastic> {
    return this.http.post<NoeudUtilisateurMeshtastic>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
