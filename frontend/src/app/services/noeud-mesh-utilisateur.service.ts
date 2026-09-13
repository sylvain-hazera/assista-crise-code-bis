import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { NoeudMeshUtilisateur } from '../shared/models/noeud-mesh-utilisateur.model';
import { PositionNoeudMission } from '../shared/models/position-noeud-mission.model';

@Injectable({ providedIn: 'root' })
export class NoeudMeshUtilisateurService {

  private url = `${environment.apiUrl}/noeuds-meshcore`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<NoeudMeshUtilisateur[]> {
    return this.http.get<NoeudMeshUtilisateur[]>(`${this.url}/`);
  }

  /** GET /api/noeuds-meshcore/positions-en-mission/ — positions des nœuds personnels
   * d'utilisateurs en mission EN_COURS uniquement, jamais en dehors (voir
   * NoeudMeshUtilisateurViewSet.positions_en_mission). */
  positionsEnMission(): Observable<PositionNoeudMission[]> {
    return this.http.get<PositionNoeudMission[]>(`${this.url}/positions-en-mission/`);
  }

  create(data: Partial<NoeudMeshUtilisateur>): Observable<NoeudMeshUtilisateur> {
    return this.http.post<NoeudMeshUtilisateur>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
