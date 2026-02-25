import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Crise, CrisePayload } from '../shared/models/crisis.model';
import { StatsResponse } from '../shared/models/api.model';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';
import { GeolocationService } from './geolocation.service';

@Injectable({
  providedIn: 'root'
})
export class CrisisService {
  private apiUrl = `${environment.apiUrl}/crises`;

  constructor(private http: HttpClient, private geolocationService: GeolocationService) {}

//   getAllCrisis(): Observable<Crise[]> {
//     return this.http.get<Crise[]>(this.apiUrl);
//   }

//   getParamCrisis(params?: any): Observable<Crise[]> {
//     let httpParams = new HttpParams();
//     if (params) {
//       Object.keys(params).forEach(key => {
//         httpParams = httpParams.set(key, params[key]);
//       });
//     }
//     return this.http.get<Crise[]>(this.apiUrl, { params: httpParams });
//   }

//   getCrisisStats(filter?: any): Observable<any> {
//     let httpParams = new HttpParams();
//     if (filter) {
//       Object.keys(filter).forEach(key => {
//         httpParams = httpParams.set(key, filter[key]);
//       });
//     }
//     return this.http.get<any>(`${this.apiUrl}/stats`, { params: httpParams });
//   }

//   getRecentCrisis(limit: number = 10): Observable<Crise[]> {
//     return this.http.get<Crise[]>(`${this.apiUrl}/recent?limit=${limit}`);
//   }

//   // getCrisis(params?: any): Observable<Crise[]> {
//   //   return this.http.get<Crise[]>(`${this.apiUrl}/`, { params });
//   // }
  
//   /**
//  * Récupère toutes les crises créées par un utilisateur spécifique
//  * @param userId L'ID de l'utilisateur (issu de l'objet User)
//  */
//   getMyCrisis(userId: number | string): Observable<Crise[]> {
//     // On passe l'ID en paramètre (ex: /api/crises/?user_id=1)
//     // Assure-toi que ton backend Django filtre bien sur ce paramètre
//     const params = new HttpParams().set('user_id', userId.toString());
    
//     return this.http.get<Crise[]>(this.apiUrl, { params });
//   }

//   getCrisis(id: string | number): Observable<Crise> {
//     return this.http.get<Crise>(`${this.apiUrl}/${id}/`);
//   }
  
//   // createCrisis(data: Partial<Crise>): Observable<Crise> {
//   //   return this.http.post<Crise>(`${this.apiUrl}/`, data);
//   // }

//   createCrisis(formData: FormData): Observable<Request> {
//     return this.http.post<Request>(`${this.apiUrl}/`, formData);
//   }
  
//   updateCrisis(id: string, data: Partial<Crise>): Observable<Crise> {
//     return this.http.put<Crise>(`${this.apiUrl}/${id}/`, data);
//   }
  
//   deleteCrisis(id: string): Observable<void> {
//     return this.http.delete<void>(`${this.apiUrl}/${id}/`);
//   }

  // ── LECTURE ──────────────────────────────────────────────────

  /** GET /api/crises/ */
  getAll(params?: Record<string, string>): Observable<Crise[]> {
    return this.http
      .get<Crise[]>(`${this.apiUrl}/`, { params: this.toParams(params) })
      .pipe(map(list => list.map(this.normalize)));
  }

  /**
   * Crises d'un utilisateur spécifique.
   * Django filtre via : ?validateur=<userId>
   * GET /api/crises/?validateur=<uuid>
   */
  getMines(email: string): Observable<Crise[]> {
    // return this.getAll({ auteur: userId });
    return this.getAll({ auteur_email: email });
  }

  /**
   * Crises récentes.
   * GET /api/crises/?ordering=-date_debut&limit=<n>
   * Nécessite LimitOffsetPagination ou un filtre custom côté Django.
   */
  getRecent(limit = 5): Observable<Crise[]> {
    return this.getAll({ ordering: '-date_debut', limit: String(limit) });
  }

  /** GET /api/crises/<id>/ */
  getById(id: string): Observable<Crise> {
    return this.http
      .get<Crise>(`${this.apiUrl}/${id}/`)
      .pipe(map(this.normalize));
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
  
  update(id: string, data: Partial<Crise>): Observable<Crise> {
    return this.http.put<Crise>(`${this.apiUrl}/${id}/`, data);
  }

  // /**
  //  * POST /api/crises/
  //  * Envoi via FormData pour gérer le champ photo éventuel.
  //  */
  // create(payload: CrisePayload): Observable<Crise> {
  //   return this.http
  //     .post<Crise>(`${this.apiUrl}/`, this.toFormData(payload))
  //     .pipe(map(this.normalize));
  // }

  // /**
  //  * PATCH /api/crises/<id>/
  //  * PATCH (partiel) plutôt que PUT (complet).
  //  */
  // update(id: string, payload: Partial<CrisePayload>): Observable<Crise> {
  //   return this.http
  //     .patch<Crise>(`${this.apiUrl}/${id}/`, this.toFormData(payload))
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
  private normalize = (c: any): Crise => {
    if (c.localisation?.coordinates) {
      return { ...c, ...geoPointToLatLng(c.localisation) };
    }
    return c;
  };

  /** Construit un FormData depuis un CrisePayload */
  private toFormData(payload: Partial<CrisePayload>): FormData {
    const fd = new FormData();
    if (payload.nom)       fd.append('nom', payload.nom);
    if (payload.date_fin)  fd.append('date_fin', payload.date_fin);
    if (payload.validateur) fd.append('validateur', payload.validateur);

    if (payload.latitude != null && payload.longitude != null) {
      fd.append('localisation', latLngToGeoJson(payload.latitude, payload.longitude));
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
  
    buildFormData(payload: CrisePayload, file?: File): FormData {
      const fd = new FormData();
      
      fd.append('nom', payload.nom);
      // fd.append('type_evenement', payload.type_evenement);
      // fd.append('description', payload.description || '');
      
      if (payload.date_fin) {
        fd.append('date_fin', payload.date_fin);
      }
      
      if (payload.validateur) {
        fd.append('validateur', payload.validateur);
      }

      if (payload.auteur) {
        fd.append('validateur', payload.auteur);
      }
      
      if (payload.latitude != null && payload.longitude != null) {
        fd.append('localisation', JSON.stringify({
          type: 'Point',
          coordinates: [payload.longitude, payload.longitude]
        }));
      }
      
      if (file) {
        fd.append('photo', file);
      }
      
      fd.append('statut', 'NON_TRAITEE');
      
      return fd;
    }
}