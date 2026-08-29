import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { DernierePosition } from '../shared/models/derniere-position.model';

@Injectable({
  providedIn: 'root'
})
export class PositionEquipeService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  /**
   * GET /api/positions-equipes/
   * Réservé aux acteurs institutionnels : dernières positions connues des membres d'équipe.
   */
  getAll(): Observable<DernierePosition[]> {
    return this.http.get<DernierePosition[]>(`${this.apiUrl}/positions-equipes/`);
  }

  /**
   * POST /api/ma-position/
   * Auto-déclaration opportuniste de la position de l'utilisateur connecté (voir
   * GeolocationService : jamais un traçage forcé en tâche de fond, juste une mise à jour
   * lorsqu'on a déjà obtenu la position pour une autre raison).
   */
  reportMyPosition(latitude: number, longitude: number): Observable<DernierePosition> {
    return this.http.post<DernierePosition>(`${this.apiUrl}/ma-position/`, { latitude, longitude });
  }
}
