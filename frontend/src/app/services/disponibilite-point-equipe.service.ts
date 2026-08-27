import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { DisponibilitePointEquipe, DisponibilitePointEquipePayload } from '../shared/models/disponibilite-point-equipe.model';

@Injectable({ providedIn: 'root' })
export class DisponibilitePointEquipeService {
  private apiUrl = `${environment.apiUrl}/disponibilites-points-equipe`;

  constructor(private http: HttpClient) {}

  create(payload: DisponibilitePointEquipePayload): Observable<DisponibilitePointEquipe> {
    return this.http.post<DisponibilitePointEquipe>(`${this.apiUrl}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }
}
