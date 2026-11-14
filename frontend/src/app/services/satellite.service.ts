import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  Satellite, JetonEnrolementSatellite, IdentifiantsCompteServiceSatellite, LigneSupervision,
  MiseAJourSatellite, VersionSatellite, VersionsSatellite,
} from '../shared/models/satellite.model';

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
  genererJeton(profil: 'GW' | 'FULL' = 'GW'): Observable<JetonEnrolementSatellite> {
    return this.http.post<JetonEnrolementSatellite>(`${this.url}/generer-jeton/`, { profil });
  }

  /** POST /api/satellites/<id>/valider/ — approuve un satellite EN_ATTENTE et crée son compte
   * de service ; les identifiants ne sont renvoyés qu'ICI, une seule fois. */
  valider(id: string): Observable<Satellite & { identifiants_compte_service?: IdentifiantsCompteServiceSatellite; recuperation_automatique?: boolean }> {
    return this.http.post<Satellite & { identifiants_compte_service?: IdentifiantsCompteServiceSatellite; recuperation_automatique?: boolean }>(
      `${this.url}/${id}/valider/`, {}
    );
  }

  /** POST /api/satellites/<id>/regenerer-identifiants/ — nouveau mot de passe pour le compte de
   * service d'un satellite validé (l'ancien cesse de fonctionner) ; renvoyé une seule fois. */
  regenererIdentifiants(id: string): Observable<Satellite & { identifiants_compte_service: IdentifiantsCompteServiceSatellite }> {
    return this.http.post<Satellite & { identifiants_compte_service: IdentifiantsCompteServiceSatellite }>(
      `${this.url}/${id}/regenerer-identifiants/`, {}
    );
  }

  revoquer(id: string): Observable<Satellite> {
    return this.http.post<Satellite>(`${this.url}/${id}/revoquer/`, {});
  }

  // ── Mises à jour ordonnées depuis le central ─────────────────────────────

  /** Ordonne la mise à jour vers la dernière version signée. Pendant une crise le serveur
   * répond 409 avec le nom des crises : il faut alors confirmer et rappeler avec
   * `malgreCrise`. Rien n'est exécuté ici — le satellite vient chercher l'ordre. */
  mettreAJour(id: string, malgreCrise = false): Observable<Satellite> {
    return this.http.post<Satellite>(
      `${this.url}/${id}/mettre-a-jour/`, malgreCrise ? { malgre_crise: true } : {});
  }

  /** Annule un ordre que le satellite n'a pas encore pris. */
  annulerMiseAJour(id: string): Observable<Satellite> {
    return this.http.post<Satellite>(`${this.url}/${id}/annuler-mise-a-jour/`, {});
  }

  /** Les dix dernières mises à jour de ce satellite, avec leur journal. */
  misesAJour(id: string): Observable<MiseAJourSatellite[]> {
    return this.http.get<MiseAJourSatellite[]>(`${this.url}/${id}/mises-a-jour/`);
  }

  versions(): Observable<VersionsSatellite> {
    return this.http.get<VersionsSatellite>(`${environment.apiUrl}/versions-satellite/`);
  }

  /** Publie une version. Le serveur vérifie la signature et refuse si elle ne correspond pas. */
  publierVersion(commit: string, signature: string, libelle: string): Observable<VersionSatellite> {
    return this.http.post<VersionSatellite>(
      `${environment.apiUrl}/versions-satellite/`, { commit, signature, libelle });
  }

  retirerVersion(id: string): Observable<VersionSatellite> {
    return this.http.post<VersionSatellite>(
      `${environment.apiUrl}/versions-satellite/${id}/retirer/`, {});
  }

  /** GET /api/satellites/supervision/ — crises actives dans le périmètre de supervision du
   * viewer (communes voisines -> préfecture, EPCI/département/région voient automatiquement
   * leurs communes membres) avec l'état du PC Crise de chaque institution actrice, et ses
   * contacts de secours dès qu'il n'est pas Actif. */
  supervision(): Observable<LigneSupervision[]> {
    return this.http.get<LigneSupervision[]>(`${this.url}/supervision/`);
  }
}
