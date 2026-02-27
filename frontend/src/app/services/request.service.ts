import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Demande, DemandePayload, TypeDemande } from '../shared/models/request.model';
import { StatsResponse } from '../shared/models/api.model';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';

@Injectable({
  providedIn: 'root'
})
export class RequestService {
  // private apiUrl = `${environment.apiUrl}/demandes`;
  private readonly url     = `${environment.apiUrl}/demandes`;
  private readonly typeUrl = `${environment.apiUrl}/types-demande`;

  constructor(private http: HttpClient) {}

  // ── TYPES ────────────────────────────────────────────────────

  /**
   * Liste des types pour peupler les <select>.
   * GET /api/types-demande/
   */
  getTypes(): Observable<TypeDemande[]> {
    return this.http.get<TypeDemande[]>(`${this.typeUrl}/`);
  }

  // ── LECTURE ──────────────────────────────────────────────────

  /** GET /api/demandes/?[params] */
  getAll(params?: Record<string, string>): Observable<Demande[]> {
    return this.http
      .get<Demande[]>(`${this.url}/`, { params: this.toParams(params) })
      .pipe(map(list => list.map(this.normalize)));
  }

  /**
   * Demandes de l'utilisateur connecté.
   * GET /api/demandes/my_requests/
   * Django : @action(detail=False, url_path='my_requests')
   * L'authentification JWT identifie automatiquement l'utilisateur.
   */
  getMines(email: string): Observable<Demande[]> {
    // return this.http
    //   .get<Demande[]>(`${this.url}/my_requests/`)
    //   .pipe(map(list => list.map(this.normalize)));
    // return this.getAll({ auteur: userId });
    return this.getAll({ auteur_email: email });
  }

  /** GET /api/demandes/<id>/ */
  getById(id: string): Observable<Demande> {
    return this.http
      .get<Demande>(`${this.url}/${id}/`)
      .pipe(map(this.normalize));
  }

  /**
   * Statistiques.
   * GET /api/demandes/stats/?[params]
   */
  getStats(filter?: Record<string, string>): Observable<StatsResponse> {
    return this.http.get<StatsResponse>(
      `${this.url}/stats/`,
      { params: this.toParams(filter) }
    );
  }

  create(data: Partial<Demande> | FormData): Observable<Demande> {
    return this.http.post<Demande>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Demande> | FormData): Observable<Demande> {
    return this.http.put<Demande>(`${this.url}/${id}/`, data);
  }


  /** DELETE /api/demandes/<id>/ */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  // ── PRIVÉ ────────────────────────────────────────────────────

  private normalize = (d: any): Demande => {
    if (d.localisation?.coordinates) {
      return { ...d, ...geoPointToLatLng(d.localisation) };
    }
    return d;
  };

  private toFormData(p: Partial<DemandePayload>): FormData {
    const fd = new FormData();
    // Champs texte — on n'ajoute que ceux définis
    const textFields: (keyof DemandePayload)[] = [
      'titre', 'prenom_demande', 'nom_demande',
      'email_demande', 'telephone_demande',
      'type_demande', 'crise', 'date_expiration'
    ];
    textFields.forEach(f => {
      if (p[f] != null) fd.append(f, String(p[f]));
    });

    fd.append('statut', p.statut ?? 'NON_TRAITEE');

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