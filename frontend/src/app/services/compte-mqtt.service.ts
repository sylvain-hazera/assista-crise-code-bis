import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { CompteMqtt, MotDePasseCompteMqtt, RoleCompteMqtt } from '../shared/models/compte-mqtt.model';

/** Comptes du broker MQTT — réservé aux administrateurs côté serveur (rôle PROD réel). */
@Injectable({ providedIn: 'root' })
export class CompteMqttService {

  private url = `${environment.apiUrl}/comptes-mqtt`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<CompteMqtt[]> {
    return this.http.get<CompteMqtt[]>(`${this.url}/`);
  }

  /** `mot_de_passe` omis : le serveur en engendre un. */
  create(data: { nom: string; role: RoleCompteMqtt; racine_topic?: string; description?: string }): Observable<CompteMqtt> {
    return this.http.post<CompteMqtt>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<CompteMqtt>): Observable<CompteMqtt> {
    return this.http.patch<CompteMqtt>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** Affiche le mot de passe. Journalisé côté serveur : à n'appeler que sur action explicite. */
  motDePasse(id: string): Observable<MotDePasseCompteMqtt> {
    return this.http.get<MotDePasseCompteMqtt>(`${this.url}/${id}/mot-de-passe/`);
  }

  /** Nouveau mot de passe : coupe la passerelle jusqu'à sa reconfiguration. */
  regenerer(id: string): Observable<MotDePasseCompteMqtt> {
    return this.http.post<MotDePasseCompteMqtt>(`${this.url}/${id}/regenerer/`, {});
  }
}
