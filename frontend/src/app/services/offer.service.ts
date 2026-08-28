import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Offer, OfferPayload, OfferType } from '../shared/models/offer.model';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';
import { StatsResponse } from '../shared/models/api.model';
import { Team } from '../shared/models/team.model';

@Injectable({
  providedIn: 'root'
})
export class OfferService {
  // private apiUrl = `${environment.apiUrl}/offres`;
  private readonly url     = `${environment.apiUrl}/offres`;
  private readonly typeUrl = `${environment.apiUrl}/types-offre`;

  constructor(private http: HttpClient) {}

  getTypes(): Observable<OfferType[]> {
    return this.http.get<OfferType[]>(`${this.typeUrl}/`);
  }

  getAll(params?: Record<string, string>): Observable<Offer[]> {
    return this.http
      .get<Offer[]>(`${this.url}/`, { params: this.toParams(params) })
      .pipe(map(list => list.map(this.normalize)));
  }

  /** GET /api/offres/my_offres/ */
  getMines(email: string): Observable<Offer[]> {
      // return this.getAll({ auteur: userId });
      return this.getAll({ auteur_email: email });
  }

  getById(id: string): Observable<Offer> {
    return this.http
      .get<Offer>(`${this.url}/${id}/`)
      .pipe(map(this.normalize));
  }

  /** GET /api/offres/<id>/preview/ — 403 si pas auteur/acteur institutionnel/équipe. */
  preview(id: string): Observable<Blob> {
    return this.http.get(`${this.url}/${id}/preview/`, { responseType: 'blob' });
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
  
  create(data: Partial<Offer> | FormData): Observable<Offer> {
    return this.http.post<Offer>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Offer> | FormData): Observable<Offer> {
    return this.http.patch<Offer>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** POST /api/offres/<id>/assign_dossier/ — affecte l'auteur de l'offre au dossier (rôle OFFRANT). */
  assignDossier(offerId: string, dossierId: string): Observable<{ id: string; dossier: string; created: boolean }> {
    return this.http.post<{ id: string; dossier: string; created: boolean }>(
      `${this.url}/${offerId}/assign_dossier/`, { dossier: dossierId }
    );
  }

  /** POST /api/offres/bulk_create_team/ — crée une équipe à partir d'une sélection d'offres
   * (membres = auteurs distincts), lui assigne les offres et un régulateur optionnel. */
  bulkCreateTeam(offerIds: string[], teamName: string, regulateurId: string | null): Observable<Team> {
    return this.http.post<Team>(`${this.url}/bulk_create_team/`, {
      offer_ids: offerIds, team_name: teamName, regulateur: regulateurId,
    });
  }

  private normalize = (o: any): Offer => {
    if (o.location?.coordinates) {
      return { ...o, ...geoPointToLatLng(o.location) };
    }
    return o;
  };

  private toFormData(p: Partial<OfferPayload>): FormData {
    const fd = new FormData();
    const textFields: (keyof OfferPayload)[] = [
      'title', 'first_name_offer', 'last_name_offer',
      'email_offer', 'offer_type', 'crisis', 'expires_at'
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