import { Injectable } from '@angular/core';
import { environment } from '../../environments/environment';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Information, InformationPayload, TypeInformation } from '../shared/models/information.model';
import { map, Observable } from 'rxjs';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';

@Injectable({
  providedIn: 'root'
})
export class InformationService {
  // private apiUrl = `${environment.apiUrl}/informations/`;
  private readonly url     = `${environment.apiUrl}/informations`;
  private readonly typeUrl = `${environment.apiUrl}/types-information`;

  constructor(private http: HttpClient) { }

  // getInformations(params?: any): Observable<Information[]> {
  //   return this.http.get<Information[]>(`${this.apiUrl}/informations/`, { params });
  // }

  // getInformation(id: string): Observable<Information> {
  //   return this.http.get<Information>(`${this.apiUrl}/informations/${id}/`);
  // }

  // createInformation(data: Partial<Information> | FormData): Observable<Information> {
  //   return this.http.post<Information>(`${this.apiUrl}/informations/`, data);
  // }

  // updateInformation(id: string, data: Partial<Information> | FormData): Observable<Information> {
  //   return this.http.put<Information>(`${this.apiUrl}/informations/${id}/`, data);
  // }

  // deleteInformation(id: string): Observable<void> {
  //   return this.http.delete<void>(`${this.apiUrl}/informations/${id}/`);
  // }

  getTypes(): Observable<TypeInformation[]> {
    return this.http.get<TypeInformation[]>(`${this.typeUrl}/`);
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

  create(data: Partial<Information> | FormData): Observable<Information> {
    return this.http.post<Information>(`${this.url}/informations/`, data);
  }

  update(id: string, data: Partial<Information> | FormData): Observable<Information> {
    return this.http.put<Information>(`${this.url}/informations/${id}/`, data);
  }

  // create(payload: InformationPayload): Observable<Information> {
  //   return this.http
  //     .post<Information>(`${this.url}/`, this.toFormData(payload))
  //     .pipe(map(this.normalize));
  // }

  // update(id: string, payload: Partial<InformationPayload>): Observable<Information> {
  //   return this.http
  //     .patch<Information>(`${this.url}/${id}/`, this.toFormData(payload))
  //     .pipe(map(this.normalize));
  // }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  private normalize = (i: any): Information => {
    if (i.localisation?.coordinates) {
      return { ...i, ...geoPointToLatLng(i.localisation) };
    }
    return i;
  };

  private toFormData(p: Partial<InformationPayload>): FormData {
    const fd = new FormData();
    const textFields: (keyof InformationPayload)[] = [
      'titre', 'prenom_information', 'nom_information',
      'email_information', 'telephone_information',
      'type_information', 'crise', 'date_expiration'
    ];
    textFields.forEach(f => {
      if (p[f] != null) fd.append(f, String(p[f]));
    });

    fd.append('statut', p.statut ?? 'DISPONIBLE');

    if (p.latitude != null && p.longitude != null) {
      fd.append('localisation', latLngToGeoJson(p.latitude, p.longitude));
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
