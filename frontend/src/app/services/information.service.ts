import { Injectable } from '@angular/core';
import { environment } from '../../environments/environment';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Information, InformationPayload, InformationType } from '../shared/models/information.model';
import { map, Observable } from 'rxjs';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';

@Injectable({
  providedIn: 'root'
})
export class InformationService {
  private readonly url     = `${environment.apiUrl}/informations`;
  private readonly typeUrl = `${environment.apiUrl}/types-information`;

  constructor(private http: HttpClient) { }

  getTypes(): Observable<InformationType[]> {
    return this.http.get<InformationType[]>(`${this.typeUrl}/`);
  }

  searchTypes(query: string): Observable<InformationType[]> {
    return this.http.get<InformationType[]>(`${this.typeUrl}/`, { params: { q: query } });
  }

  createType(type: string): Observable<InformationType> {
    return this.http.post<InformationType>(`${this.typeUrl}/`, { type });
  }

  getAll(params?: Record<string, string>): Observable<Information[]> {
    return this.http
      .get<Information[]>(`${this.url}/`, { params: this.toParams(params) })
      .pipe(map(list => list.map(this.normalize)));
  }

  getById(id: string): Observable<Information> {
    return this.http
      .get<Information>(`${this.url}/${id}/`)
      .pipe(map(this.normalize));
  }

  /** GET /api/informations/<id>/preview/ — 403 si pas auteur/acteur institutionnel. */
  preview(id: string): Observable<Blob> {
    return this.http.get(`${this.url}/${id}/preview/`, { responseType: 'blob' });
  }

  /** GET /api/informations/vue_mairie/ — signalements de la commune de l'institution de
   * l'utilisateur appelant (mairie). 400 si aucune commune associée au compte. */
  vueMairie(): Observable<Information[]> {
    return this.http
      .get<Information[]>(`${this.url}/vue_mairie/`)
      .pipe(map(list => list.map(this.normalize)));
  }

  create(data: Partial<Information> | FormData): Observable<Information> {
    return this.http.post<Information>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Information> | FormData): Observable<Information> {
    return this.http.patch<Information>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  private normalize = (i: any): Information => {
    if (i.location?.coordinates) {
      return { ...i, ...geoPointToLatLng(i.location) };
    }
    return i;
  };

  private toFormData(p: Partial<InformationPayload>): FormData {
    const fd = new FormData();
    const textFields: (keyof InformationPayload)[] = [
      'title', 'first_name_information', 'last_name_information',
      'email_information', 'phone_information',
      'information_type', 'crisis', 'expires_at'
    ];
    textFields.forEach(f => {
      if (p[f] != null) fd.append(f, String(p[f]));
    });

    fd.append('status', p.status ?? 'DISPONIBLE');

    if (p.latitude != null && p.longitude != null) {
      fd.append('location', latLngToGeoJson(p.latitude, p.longitude));
    }
    if (p.photo) fd.append('photo', p.photo);

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
}
