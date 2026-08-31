import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface EngagementRessourceStatut {
  offer_title: string;
  team_nom: string;
  mission_titre: string | null;
  statut: 'EN_ATTENTE' | 'CONFIRME' | 'DECLINE' | 'EN_TRANSIT' | 'ARRIVE';
  statut_libelle: string;
  actions_possibles: ('confirmer' | 'decliner' | 'transit' | 'arrivee')[];
}

/** Page publique de confirmation d'une ressource affectée à une équipe — aucune
 * authentification requise, le jeton opaque dans l'URL fait foi. */
@Injectable({ providedIn: 'root' })
export class EngagementRessourceService {
  private apiUrl = `${environment.apiUrl}/engagement-ressource`;

  constructor(private http: HttpClient) {}

  getByToken(token: string): Observable<EngagementRessourceStatut> {
    return this.http.get<EngagementRessourceStatut>(`${this.apiUrl}/${token}/`);
  }

  agir(token: string, action: string): Observable<EngagementRessourceStatut> {
    return this.http.post<EngagementRessourceStatut>(`${this.apiUrl}/${token}/`, { action });
  }
}
