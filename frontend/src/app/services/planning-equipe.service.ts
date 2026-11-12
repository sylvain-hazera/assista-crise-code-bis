import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  PlanningEquipe, ResultatPointage, StatutCreneauEquipe,
} from '../shared/models/planning-equipe.model';

@Injectable({ providedIn: 'root' })
export class PlanningEquipeService {
  private url = `${environment.apiUrl}/creneaux-equipe`;

  constructor(private http: HttpClient) {}

  /** Le planning complet d'une équipe sur une fenêtre. `effectifCible` fait rendre en plus la
   * liste des créneaux sous-armés : la chercher à l'œil dans quatorze colonnes est exactement
   * ce qu'un écran doit éviter de faire faire. */
  planning(equipeId: string, jours = 14, debut?: string, effectifCible = 0)
      : Observable<PlanningEquipe> {
    const params: Record<string, string> = {
      equipe: equipeId, jours: String(jours), effectif_cible: String(effectifCible),
    };
    if (debut) { params['debut'] = debut; }
    return this.http.get<PlanningEquipe>(`${this.url}/planning/`, { params });
  }

  /** Pose plusieurs créneaux d'un coup. Idempotent : la clé est
   * (équipe, personne, jour, créneau), repointer met à jour au lieu de dupliquer. */
  pointer(equipeId: string, creneaux: { utilisateur: string; date: string; creneau: string }[],
          options: { statut?: StatutCreneauEquipe; role?: string; point?: string;
                     crise?: string } = {}): Observable<ResultatPointage> {
    return this.http.post<ResultatPointage>(`${this.url}/pointer/`, {
      equipe: equipeId, creneaux, ...options,
    });
  }

  changerStatut(id: string, statut: StatutCreneauEquipe): Observable<unknown> {
    return this.http.patch(`${this.url}/${id}/`, { statut });
  }

  retirer(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
