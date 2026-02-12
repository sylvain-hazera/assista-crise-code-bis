import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Offre, OffrePayload, TypeOffre } from '../shared/models/offer.model';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';
import { StatsResponse } from '../shared/models/api.model';

@Injectable({
  providedIn: 'root'
})
export class OfferService {
  // private apiUrl = `${environment.apiUrl}/offres`;
  private readonly url     = `${environment.apiUrl}/offres`;
  private readonly typeUrl = `${environment.apiUrl}/types-offre`;

  constructor(private http: HttpClient) {}

  // getAllOffers(): Observable<Offre[]> {
  //   return this.http.get<Offre[]>(this.apiUrl);
  // }

  // getOffers(params?: any): Observable<Offre[]> {
  //   let httpParams = new HttpParams();
  //   if (params) {
  //     Object.keys(params).forEach(key => {
  //       httpParams = httpParams.set(key, params[key]);
  //     });
  //   }
  //   return this.http.get<Offre[]>(this.apiUrl, { params: httpParams });
  // }

  // getOfferStats(filter?: any): Observable<any> {
  //   let httpParams = new HttpParams();
  //   if (filter) {
  //     Object.keys(filter).forEach(key => {
  //       httpParams = httpParams.set(key, filter[key]);
  //     });
  //   }
  //   return this.http.get<any>(`${this.apiUrl}/stats`, { params: httpParams });
  // }

  // // getOffers(params?: any): Observable<Offre[]> {
  // //   return this.http.get<Offre[]>(`${this.apiUrl}/offres/`, { params });
  // // }

  // getOffer(id: string): Observable<Offre> {
  //   return this.http.get<Offre>(`${this.apiUrl}/offres/${id}/`);
  // }

  // createOffer(data: Partial<Offre> | FormData): Observable<Offre> {
  //   return this.http.post<Offre>(`${this.apiUrl}/offres/`, data);
  // }

  // updateOffer(id: string, data: Partial<Offre> | FormData): Observable<Offre> {
  //   return this.http.put<Offre>(`${this.apiUrl}/offres/${id}/`, data);
  // }

  // deleteOffer(id: string): Observable<void> {
  //   return this.http.delete<void>(`${this.apiUrl}/offres/${id}/`);
  // }

  getTypes(): Observable<TypeOffre[]> {
    return this.http.get<TypeOffre[]>(`${this.typeUrl}/`);
  }

  getAll(params?: Record<string, string>): Observable<Offre[]> {
    return this.http
      .get<Offre[]>(`${this.url}/`, { params: this.toParams(params) })
      .pipe(map(list => list.map(this.normalize)));
  }

  /** GET /api/offres/my_offres/ */
  getMines(): Observable<Offre[]> {
    return this.http
      .get<Offre[]>(`${this.url}/my_offres/`)
      .pipe(map(list => list.map(this.normalize)));
  }

  getById(id: string): Observable<Offre> {
    return this.http
      .get<Offre>(`${this.url}/${id}/`)
      .pipe(map(this.normalize));
  }

    /**
     * Statistiques.
     * GET /api/offres/stats/?[params]
     */
  getStats(filter?: Record<string, string>): Observable<StatsResponse> {
    return this.http.get<StatsResponse>(
      `${this.url}/stats/`,
      { params: this.toParams(filter) }
    );
  }
    
  create(payload: OffrePayload): Observable<Offre> {
    return this.http
      .post<Offre>(`${this.url}/`, this.toFormData(payload))
      .pipe(map(this.normalize));
  }

  update(id: string, payload: Partial<OffrePayload>): Observable<Offre> {
    return this.http
      .patch<Offre>(`${this.url}/${id}/`, this.toFormData(payload))
      .pipe(map(this.normalize));
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  private normalize = (o: any): Offre => {
    if (o.localisation?.coordinates) {
      return { ...o, ...geoPointToLatLng(o.localisation) };
    }
    return o;
  };

  private toFormData(p: Partial<OffrePayload>): FormData {
    const fd = new FormData();
    const textFields: (keyof OffrePayload)[] = [
      'titre', 'prenom_offre', 'nom_offre',
      'email_offre', 'type_offre', 'crise', 'date_expiration'
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