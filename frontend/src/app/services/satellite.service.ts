import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Satellite, JetonEnrolementSatellite, IdentifiantsCompteServiceSatellite, LigneSupervision } from '../shared/models/satellite.model';

@Injectable({ providedIn: 'root' })
export class SatelliteService {

  private url = `${environment.apiUrl}/satellites`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<Satellite[]> {
    return this.http.get<Satellite[]>(`${this.url}/`);
  }

  /** POST /api/satellites/generer-jeton/ — jeton à usage unique (24h), pour l'institution de
   * l'appelant, à communiquer hors-bande au responsable du satellite (saisi lors de
   * l'installation du Pi). Voir SatelliteViewSet.generer_jeton. */
  genererJeton(): Observable<JetonEnrolementSatellite> {
    return this.http.post<JetonEnrolementSatellite>(`${this.url}/generer-jeton/`, {});
  }

  /** POST /api/satellites/<id>/valider/ — approuve un satellite EN_ATTENTE et crée son compte
   * de service ; les identifiants ne sont renvoyés qu'ICI, une seule fois. */
  valider(id: string): Observable<Satellite & { identifiants_compte_service: IdentifiantsCompteServiceSatellite }> {
    return this.http.post<Satellite & { identifiants_compte_service: IdentifiantsCompteServiceSatellite }>(
      `${this.url}/${id}/valider/`, {}
    );
  }

  revoquer(id: string): Observable<Satellite> {
    return this.http.post<Satellite>(`${this.url}/${id}/revoquer/`, {});
  }

  /** GET /api/satellites/supervision/ — crises actives dans le périmètre de supervision du
   * viewer (communes voisines -> préfecture, EPCI/département/région voient automatiquement
   * leurs communes membres) avec l'état du PC Crise de chaque institution actrice, et ses
   * contacts de secours dès qu'il n'est pas Actif. */
  supervision(): Observable<LigneSupervision[]> {
    return this.http.get<LigneSupervision[]>(`${this.url}/supervision/`);
  }
}
