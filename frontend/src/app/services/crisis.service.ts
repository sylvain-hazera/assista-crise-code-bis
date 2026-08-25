import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Crisis, CrisisPayload } from '../shared/models/crisis.model';
import { StatsResponse } from '../shared/models/api.model';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';
import { GeolocationService } from './geolocation.service';

@Injectable({
  providedIn: 'root'
})
export class CrisisService {
  private apiUrl = `${environment.apiUrl}/crises`;

  constructor(private http: HttpClient, private geolocationService: GeolocationService) {}

  // ── LECTURE ──────────────────────────────────────────────────

  /** GET /api/crises/ */
  getAll(params?: Record<string, string>): Observable<Crisis[]> {
    return this.http
      .get<Crisis[]>(`${this.apiUrl}/`, { params: this.toParams(params) })
      .pipe(map(list => list.map(this.normalize)));
  }

  /**
   * Crises d'un utilisateur spécifique.
   * Django filtre via : ?validateur=<userId>
   * GET /api/crises/?validateur=<uuid>
   */
  getMines(email: string): Observable<Crisis[]> {
    // return this.getAll({ auteur: userId });
    return this.getAll({ auteur_email: email });
  }

  /**
   * Crises récentes.
   * GET /api/crises/?ordering=-date_debut&limit=<n>
   * Nécessite LimitOffsetPagination ou un filtre custom côté Django.
   */
  getRecent(limit = 5): Observable<Crisis[]> {
    return this.getAll({ ordering: '-date_debut', limit: String(limit) });
  }

  /** GET /api/crises/<id>/ */
  getById(id: string): Observable<Crisis> {
    return this.http
      .get<Crisis>(`${this.apiUrl}/${id}/`)
      .pipe(map(this.normalize));
  }

  /** GET /api/crises/<id>/preview/ — 403 si pas auteur/acteur institutionnel. */
  preview(id: string): Observable<Blob> {
    return this.http.get(`${this.apiUrl}/${id}/preview/`, { responseType: 'blob' });
  }

  /**
   * Statistiques pour le dashboard.
   * GET /api/crises/stats/?[params]
   * Nécessite un @action(detail=False) Django.
   */
  getStats(filter?: Record<string, string>): Observable<StatsResponse> {
    return this.http.get<StatsResponse>(
      `${this.apiUrl}/stats/`,
      { params: this.toParams(filter) }
    );
  }

  // ── ÉCRITURE ─────────────────────────────────────────────────

  create(formData: FormData): Observable<Request> {
    return this.http.post<Request>(`${this.apiUrl}/`, formData);
  }
  
  update(id: string, data: Partial<Crisis>): Observable<Crisis> {
    return this.http.put<Crisis>(`${this.apiUrl}/${id}/`, data);
  }

  /** PATCH /api/crises/<id>/ — mise à jour partielle (ex: seulement `zone`). */
  patch(id: string, data: Partial<Crisis>): Observable<Crisis> {
    return this.http.patch<Crisis>(`${this.apiUrl}/${id}/`, data);
  }

  // /**
  //  * POST /api/crises/
  //  * Envoi via FormData pour gérer le champ photo éventuel.
  //  */
  // create(payload: CrisisPayload): Observable<Crisis> {
  //   return this.http
  //     .post<Crisis>(`${this.apiUrl}/`, this.toFormData(payload))
  //     .pipe(map(this.normalize));
  // }

  // /**
  //  * PATCH /api/crises/<id>/
  //  * PATCH (partiel) plutôt que PUT (complet).
  //  */
  // update(id: string, payload: Partial<CrisePayload>): Observable<Crisis> {
  //   return this.http
  //     .patch<Crisis>(`${this.apiUrl}/${id}/`, this.toFormData(payload))
  //     .pipe(map(this.normalize));
  // }

  /** DELETE /api/crises/<id>/ */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  // ── PRIVÉ ────────────────────────────────────────────────────

  /**
   * Django retourne { localisation: { type: "Point", coordinates: [lng, lat] } }
   * On extrait latitude/longitude pour un usage pratique dans les templates.
   */
  private normalize = (c: any): Crisis => {
    if (c.location?.coordinates) {
      return { ...c, ...geoPointToLatLng(c.location) };
    }
    return c;
  };

  /** Construit un FormData depuis un CrisisPayload */
  private toFormData(payload: Partial<CrisisPayload>): FormData {
    const fd = new FormData();
    if (payload.name)       fd.append('name', payload.name);
    if (payload.end_date)  fd.append('end_date', payload.end_date);
    if (payload.validator) fd.append('validator', payload.validator);

    if (payload.latitude != null && payload.longitude != null) {
      fd.append('location', latLngToGeoJson(payload.latitude, payload.longitude));
    }
    
    return fd;
  }

  private toParams(obj?: Record<string, string>): HttpParams {
    let p = new HttpParams();
    if (obj) {
      Object.entries(obj)
        .filter(([, v]) => v != null && v !== '')
        .forEach(([k, v]) => (p = p.set(k, v)));
    }
    return p;
  }
  
    buildFormData(payload: CrisisPayload, file?: File): FormData {
      const fd = new FormData();
      
      fd.append('name', payload.name);
      fd.append('type', payload.type);
      if (payload.description) {
        fd.append('description', payload.description);
      }

      if (payload.end_date) {
        fd.append('end_date', payload.end_date);
      }
      
      if (payload.validator) {
        fd.append('validator', payload.validator);
      }

      if (payload.author) {
        fd.append('validator', payload.author);
      }
      
      if (payload.latitude != null && payload.longitude != null) {
        fd.append('location', JSON.stringify({
          type: 'Point',
          coordinates: [payload.longitude, payload.latitude]
        }));
      }

      if (payload.zone) {
        fd.append('zone', payload.zone);
      }

      if (file) {
        fd.append('photo', file);
      }
      
      fd.append('status', 'NON_TRAITEE');
      
      return fd;
    }
}