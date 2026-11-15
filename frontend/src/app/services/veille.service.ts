import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  ConfigurationAlerteVigilance, EvenementsRoutiers, StationsCarburant, VigilanceMeteo,
} from '../shared/models/veille.model';

/** Zone à regarder : un rectangle (la carte), un point et un rayon, ou rien — le serveur prend
 * alors la commune de l'institution de l'appelant. */
export interface EmpriseVeille {
  bbox?: [number, number, number, number];
  lat?: number;
  lon?: number;
  rayon_km?: number;
}

/** Lecture de la veille du territoire. Tout vient de NOTRE serveur, qui tient une copie des
 * sources de l'État : ce service ne doit jamais appeler un service extérieur. */
@Injectable({ providedIn: 'root' })
export class VeilleService {

  private api = environment.apiUrl;

  constructor(private http: HttpClient) {}

  vigilance(departement?: string): Observable<VigilanceMeteo> {
    const params: Record<string, string> = departement ? { departement } : {};
    return this.http.get<VigilanceMeteo>(`${this.api}/vigilance-meteo/`, { params });
  }

  /** Adresse de la carte nationale officielle, servie par notre serveur. */
  vignetteUrl(echeance: string): string {
    return `${this.api}/vigilance-meteo/vignette/${echeance}/`;
  }

  evenementsRoutiers(emprise: EmpriseVeille = {}): Observable<EvenementsRoutiers> {
    return this.http.get<EvenementsRoutiers>(`${this.api}/evenements-routiers/`, { params: this.params(emprise) });
  }

  stationsCarburant(emprise: EmpriseVeille = {}): Observable<StationsCarburant> {
    return this.http.get<StationsCarburant>(`${this.api}/stations-carburant/`, { params: this.params(emprise) });
  }

  private params(emprise: EmpriseVeille): Record<string, string> {
    const params: Record<string, string> = {};
    if (emprise.bbox) params['bbox'] = emprise.bbox.join(',');
    if (emprise.lat != null && emprise.lon != null) {
      params['lat'] = String(emprise.lat);
      params['lon'] = String(emprise.lon);
    }
    if (emprise.rayon_km != null) params['rayon_km'] = String(emprise.rayon_km);
    return params;
  }

  // ── Réglage de l'annonce de vigilance, par institution ──

  alerteVigilance(institutionId: string): Observable<ConfigurationAlerteVigilance[]> {
    return this.http.get<ConfigurationAlerteVigilance[]>(
      `${this.api}/configurations-alerte-vigilance/`, { params: { institution: institutionId } });
  }

  creerAlerteVigilance(data: { institution: string; actif: boolean; couleur_min: number }): Observable<ConfigurationAlerteVigilance> {
    return this.http.post<ConfigurationAlerteVigilance>(`${this.api}/configurations-alerte-vigilance/`, data);
  }

  modifierAlerteVigilance(id: number, data: Partial<ConfigurationAlerteVigilance>): Observable<ConfigurationAlerteVigilance> {
    return this.http.patch<ConfigurationAlerteVigilance>(`${this.api}/configurations-alerte-vigilance/${id}/`, data);
  }
}
