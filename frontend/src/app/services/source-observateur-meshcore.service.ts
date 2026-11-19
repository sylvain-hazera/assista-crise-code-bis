import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Broker où des observateurs MeshCore republient ce qu'ils entendent (SourceObservateurMeshCore).
 * Le mot de passe part vers le serveur, il n'en revient jamais. */
export interface SourceObservateurMeshCore {
  id: string;
  nom: string;
  /** MQTT : un broker où publient les observateurs. CORESCOPE : le flux temps réel d'une instance. */
  type_source: 'MQTT' | 'CORESCOPE';
  broker_host: string;
  broker_port: number;
  mqtt_username: string;
  mqtt_password?: string;
  mqtt_use_tls: boolean;
  mqtt_transport: 'tcp' | 'websockets';
  mqtt_ws_chemin: string;
  filtre_topic: string;
  actif: boolean;
  derniere_connexion: string | null;
  dernier_etat: string | null;
  derniere_erreur: string | null;
}

@Injectable({ providedIn: 'root' })
export class SourceObservateurMeshCoreService {
  private url = `${environment.apiUrl}/sources-observateurs-meshcore`;

  constructor(private http: HttpClient) {}

  liste(): Observable<SourceObservateurMeshCore[]> {
    return this.http.get<SourceObservateurMeshCore[]>(`${this.url}/`);
  }

  creer(data: Partial<SourceObservateurMeshCore>): Observable<SourceObservateurMeshCore> {
    return this.http.post<SourceObservateurMeshCore>(`${this.url}/`, data);
  }

  modifier(id: string, data: Partial<SourceObservateurMeshCore>): Observable<SourceObservateurMeshCore> {
    return this.http.patch<SourceObservateurMeshCore>(`${this.url}/${id}/`, data);
  }

  supprimer(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
