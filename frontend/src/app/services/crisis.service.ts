import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Crisis, CrisisPayload } from '../shared/models/crisis.model';
import { StatsResponse, PageResponse } from '../shared/models/api.model';
import { StocksComparaison } from '../shared/models/materiel-point.model';
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

  /** GET /api/crises/?validateur=<uuid> */
  getMines(email: string): Observable<Crisis[]> {
    return this.getAll({ author_email: email });
  }

  /** GET /api/crises/?ordering=-date_debut&limit=<n> */
  getRecent(limit = 5): Observable<Crisis[]> {
    return this.getAll({ ordering: '-date_debut', limit: String(limit) });
  }

  /** GET /api/crises/?page=&page_size=&... — pagination serveur, comme OfferService.searchPage. */
  searchPage(params: Record<string, string>, page: number, pageSize: number): Observable<PageResponse<Crisis>> {
    const httpParams = this.toParams({ ...params, page: String(page), page_size: String(pageSize) });
    return this.http
      .get<PageResponse<Crisis>>(`${this.apiUrl}/`, { params: httpParams })
      .pipe(map(res => ({ ...res, results: res.results.map(this.normalize) })));
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

  /** GET /api/crises/stats/?[params] */
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

  /** POST /api/crises/<id>/fusionner-zone/ — union avec la zone existante ; 400 si les tracés
   * ne se touchent pas. */
  fusionnerZone(id: string, wkt: string): Observable<Crisis> {
    return this.http.post<Crisis>(`${this.apiUrl}/${id}/fusionner-zone/`, { wkt });
  }

  /** DELETE /api/crises/<id>/ */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  /** POST /api/crises/<id>/cloturer/ — réservé au responsable actif ou à un admin. */
  cloturer(id: string): Observable<{ status: string; end_date: string }> {
    return this.http.post<{ status: string; end_date: string }>(`${this.apiUrl}/${id}/cloturer/`, {});
  }

  /** POST /api/crises/<id>/reouvrir/ — réservé aux admins. */
  reouvrir(id: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.apiUrl}/${id}/reouvrir/`, {});
  }

  /** GET /api/crises/<id>/export/ — zip multi-CSV, réservé au responsable actif ou à un admin. */
  export(id: string): Observable<Blob> {
    return this.http.get(`${this.apiUrl}/${id}/export/`, { responseType: 'blob' });
  }

  /** GET /api/crises/<id>/stocks-comparaison/ — niveau de chaque item du catalogue matériel,
   * pour chaque point de la crise (tableau comparatif entre centres). */
  getStocksComparaison(id: string): Observable<StocksComparaison> {
    return this.http.get<StocksComparaison>(`${this.apiUrl}/${id}/stocks-comparaison/`);
  }

  /** GET /api/crises/<id>/commune/ — code INSEE calculé par géocodage inverse. */
  getCommune(id: string): Observable<{ commune_code: string | null }> {
    return this.http.get<{ commune_code: string | null }>(`${this.apiUrl}/${id}/commune/`);
  }

  // ── PRIVÉ ────────────────────────────────────────────────────

  /** Extrait latitude/longitude du GeoJSON { type: "Point", coordinates: [lng, lat] }. */
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