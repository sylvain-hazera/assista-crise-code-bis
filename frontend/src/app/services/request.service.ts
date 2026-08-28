import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Request, RequestPayload, RequestType } from '../shared/models/request.model';
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
  getTypes(): Observable<RequestType[]> {
    return this.http.get<RequestType[]>(`${this.typeUrl}/`);
  }

  // ── LECTURE ──────────────────────────────────────────────────

  /** GET /api/demandes/?[params] */
  getAll(params?: Record<string, string>): Observable<Request[]> {
    return this.http
      .get<Request[]>(`${this.url}/`, { params: this.toParams(params) })
      .pipe(map(list => list.map(this.normalize)));
  }

  /**
   * Demandes de l'utilisateur connecté.
   * GET /api/demandes/my_requests/
   * Django : @action(detail=False, url_path='my_requests')
   * L'authentification JWT identifie automatiquement l'utilisateur.
   */
  getMines(email: string): Observable<Request[]> {
    // return this.http
    //   .get<Request[]>(`${this.url}/my_requests/`)
    //   .pipe(map(list => list.map(this.normalize)));
    // return this.getAll({ auteur: userId });
    return this.getAll({ auteur_email: email });
  }

  /** GET /api/demandes/<id>/ */
  getById(id: string): Observable<Request> {
    return this.http
      .get<Request>(`${this.url}/${id}/`)
      .pipe(map(this.normalize));
  }

  /** GET /api/demandes/<id>/preview/ — 403 si pas auteur/acteur institutionnel/équipe. */
  preview(id: string): Observable<Blob> {
    return this.http.get(`${this.url}/${id}/preview/`, { responseType: 'blob' });
  }

  /** GET /api/demandes/vue_mairie/ — demandes de la commune de l'institution de l'utilisateur
   * appelant (mairie). 400 si aucune commune associée au compte. */
  vueMairie(): Observable<Request[]> {
    return this.http
      .get<Request[]>(`${this.url}/vue_mairie/`)
      .pipe(map(list => list.map(this.normalize)));
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

  create(data: Partial<Request> | FormData): Observable<Request> {
    return this.http.post<Request>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<Request> | FormData): Observable<Request> {
    return this.http.patch<Request>(`${this.url}/${id}/`, data);
  }


  /** DELETE /api/demandes/<id>/ */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** POST /api/demandes/<id>/assign_team/ — affecte la demande à une équipe : crée un
   * dossier de suivi, notifie le régulateur de l'équipe et informe le demandeur par email. */
  assignTeam(requestId: string, teamId: string): Observable<{ dossier?: string; numero?: string; already_assigned?: boolean }> {
    return this.http.post<{ dossier?: string; numero?: string; already_assigned?: boolean }>(
      `${this.url}/${requestId}/assign_team/`, { team: teamId }
    );
  }

  /** POST /api/demandes/bulk_assign_mission/ — affecte plusieurs demandes en une fois à une
   * mission (existante ou créée à la volée) et à une équipe. Toutes les demandes doivent
   * partager la même crise, sinon 400. */
  bulkAssignMission(
    requestIds: string[],
    teamId: string,
    mission: { missionId: string } | { newMission: { titre: string } },
  ): Observable<{ mission: string; dossiers_created: string[]; already_assigned: string[] }> {
    const body: any = { request_ids: requestIds, team: teamId };
    if ('missionId' in mission) {
      body.mission = mission.missionId;
    } else {
      body.new_mission = mission.newMission;
    }
    return this.http.post<{ mission: string; dossiers_created: string[]; already_assigned: string[] }>(
      `${this.url}/bulk_assign_mission/`, body
    );
  }

  // ── PRIVÉ ────────────────────────────────────────────────────

  private normalize = (d: any): Request => {
    if (d.location?.coordinates) {
      return { ...d, ...geoPointToLatLng(d.location) };
    }
    return d;
  };

  private toFormData(p: Partial<RequestPayload>): FormData {
    const fd = new FormData();
    // Champs texte — on n'ajoute que ceux définis
    const textFields: (keyof RequestPayload)[] = [
      'title', 'first_name_request', 'last_name_request',
      'email_request', 'phone_request',
      'request_type', 'crisis', 'expires_at'
    ];
    textFields.forEach(f => {
      if (p[f] != null) fd.append(f, String(p[f]));
    });

    fd.append('status', p.status ?? 'NON_TRAITEE');

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