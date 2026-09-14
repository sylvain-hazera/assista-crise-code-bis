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

  /** GET /api/noeuds-meshcore/messageables/?equipe=<id> — résumé minimal (jamais
   * utilisateur/utilisateur_id) des nœuds équipés de cette équipe, pour composer un DM sans
   * passer par getAll() (bloqué en zone DEMO, voir NoeudMeshUtilisateurViewSet). */
  messageables(equipeId: string): Observable<Pick<NoeudMeshUtilisateur, 'id' | 'pubkey_hex' | 'nom_noeud' | 'utilisateur_nom'>[]> {
    return this.http.get<Pick<NoeudMeshUtilisateur, 'id' | 'pubkey_hex' | 'nom_noeud' | 'utilisateur_nom'>[]>(
      `${this.url}/messageables/`, { params: { equipe: equipeId } },
    );
  }

  create(data: Partial<NoeudMeshUtilisateur>): Observable<NoeudMeshUtilisateur> {
    return this.http.post<NoeudMeshUtilisateur>(`${this.url}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** GET /api/noeuds-meshcore/mes-noeuds/ — mes propres nœuds réclamés (page Paramètres du
   * compte), ouvert à tout utilisateur authentifié. */
  mesNoeuds(): Observable<NoeudMeshUtilisateur[]> {
    return this.http.get<NoeudMeshUtilisateur[]>(`${this.url}/mes-noeuds/`);
  }

  /** POST /api/noeuds-meshcore/reclamer/ — auto-service, voir NoeudMeshUtilisateurViewSet.reclamer. */
  reclamer(pubkeyHex: string, nomNoeud?: string): Observable<NoeudMeshUtilisateur> {
    return this.http.post<NoeudMeshUtilisateur>(`${this.url}/reclamer/`, { pubkey_hex: pubkeyHex, nom_noeud: nomNoeud || '' });
  }

  /** POST /api/noeuds-meshcore/liberer/ — ne peut libérer que son propre nœud. */
  liberer(pubkeyHex: string): Observable<void> {
    return this.http.post<void>(`${this.url}/liberer/`, { pubkey_hex: pubkeyHex });
  }
}
