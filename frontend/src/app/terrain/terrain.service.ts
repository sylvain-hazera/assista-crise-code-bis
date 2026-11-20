import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Mission } from '../shared/models/mission.model';

/** Une notification de l'application, telle que le serveur la rend (mes-notifications). */
export interface NotificationTerrain {
  id: string;
  genre: string;
  genre_libelle: string;
  titre: string;
  corps: string;
  urgent: boolean;
  institution_nom: string | null;
  campagne: unknown;
  date_creation: string;
  date_remise: string | null;
  date_vue: string | null;
  date_lue: string | null;
  date_reponse: string | null;
}

export type EtapeNotification = 'REMISE' | 'VUE' | 'LUE';

/**
 * Ce que l'espace terrain demande au serveur : les mêmes adresses que l'application Android
 * (missions, mes-notifications, mon-appareil), pour que le serveur ne fasse aucune différence.
 */
@Injectable({ providedIn: 'root' })
export class TerrainService {
  private api = environment.apiUrl;
  static readonly INSTALLATION = 'terrain-installation';

  constructor(private http: HttpClient) {}

  missions(): Observable<Mission[]> {
    return this.http.get<Mission[]>(`${this.api}/missions/`);
  }

  changerStatut(id: string, statut: Mission['statut']): Observable<Mission> {
    return this.http.patch<Mission>(`${this.api}/missions/${id}/`, { statut });
  }

  notifications(): Observable<NotificationTerrain[]> {
    return this.http.get<NotificationTerrain[]>(`${this.api}/mes-notifications/`);
  }

  accuser(ids: string[], etape: EtapeNotification): Observable<{ avancees: number }> {
    return this.http.post<{ avancees: number }>(`${this.api}/mes-notifications/accuser/`, { ids, etape });
  }

  /**
   * Cet appareil se présente au serveur, comme le fait l'application Android à chaque
   * ouverture : sans cela, le serveur ne déposerait aucune notification pour cette personne.
   * L'identifiant est tiré au hasard ici et ne désigne que cette installation.
   */
  presenterLAppareil(notificationsAutorisees: boolean): Observable<unknown> {
    return this.http.post(`${this.api}/mon-appareil/`, {
      installation: TerrainService.installation(), plateforme: 'WEB', version: 'pwa',
      notifications_autorisees: notificationsAutorisees,
    });
  }

  oublierLAppareil(): Observable<unknown> {
    return this.http.delete(`${this.api}/mon-appareil/`, { params: { installation: TerrainService.installation() } });
  }

  static installation(): string {
    let id = localStorage.getItem(TerrainService.INSTALLATION);
    if (!id) {
      id = crypto.randomUUID().replace(/-/g, '');
      localStorage.setItem(TerrainService.INSTALLATION, id);
    }
    return id;
  }
}
