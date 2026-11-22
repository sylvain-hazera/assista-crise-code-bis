import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Un message de terrain envoyé par un intervenant (22/11/2026). */
export interface MessageTerrain {
  id: string; auteur: string; auteur_nom: string; mission: string | null; equipe: string | null; equipe_nom: string | null;
  type: string; type_libelle: string; texte: string; nombre: number | null; latitude: string; longitude: string;
  canal: 'DONNEES' | 'MESHTASTIC' | 'MESHCORE'; canaux_recus: string[]; emis_le: string; recu_le: string; prioritaire: boolean;
  statut?: string;
}

@Injectable({ providedIn: 'root' })
export class MessagesTerrainService {
  private url = `${environment.apiUrl}/messages-terrain`;

  constructor(private http: HttpClient) {}

  fil(mission: string): Observable<MessageTerrain[]> {
    return this.http.get<MessageTerrain[]>(`${this.url}/`, { params: { mission } });
  }

  statuts(mission: string): Observable<MessageTerrain[]> {
    return this.http.get<MessageTerrain[]>(`${this.url}/statuts/`, { params: { mission } });
  }
}
