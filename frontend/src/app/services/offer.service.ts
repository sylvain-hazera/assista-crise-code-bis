import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Offer, OfferNationalPartial, OfferPayload, OfferType } from '../shared/models/offer.model';
import { OfferMessage } from '../shared/models/offer-message.model';
import { geoPointToLatLng, latLngToGeoJson } from '../shared/models/geopoint.model';
import { StatsResponse, PageResponse } from '../shared/models/api.model';
import { Team } from '../shared/models/team.model';
import { AVEC_COORDONNEES } from './coordonnees';

@Injectable({
  providedIn: 'root'
})
export class OfferService {
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
      return this.getAll({ author_email: email, ...AVEC_COORDONNEES });
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

  /** POST /api/photos-offres/ — ajoute une photo à la galerie d'une offre (OfferPhoto). */
  addPhoto(offerId: string, file: File, ordre: number): Observable<void> {
    const fd = new FormData();
    fd.append('offer', offerId);
    fd.append('image', file);
    fd.append('ordre', String(ordre));
    return this.http.post<void>(`${environment.apiUrl}/photos-offres/`, fd);
  }

  /** GET /api/photos-offres/?offer=<id> — galerie. */
  getPhotos(offerId: string): Observable<{ id: string; ordre: number }[]> {
    return this.http.get<{ id: string; ordre: number }[]>(`${environment.apiUrl}/photos-offres/`, {
      params: { offer: offerId },
    });
  }

  /** GET /api/photos-offres/<id>/preview/ */
  previewPhoto(photoId: string): Observable<Blob> {
    return this.http.get(`${environment.apiUrl}/photos-offres/${photoId}/preview/`, { responseType: 'blob' });
  }

  /** POST /api/offres/<id>/transformer/ — recrée l'offre en demande ou signalement et la supprime
   * (institutionnels, refusé si déjà affectée). */
  transformer(id: string, cible: 'REQUEST' | 'INFORMATION'): Observable<any> {
    return this.http.post<any>(`${this.url}/${id}/transformer/`, { cible });
  }

    /** GET /api/offres/stats/?[params] */
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

  /** POST /api/offres/<id>/reactiver/ — réactive une offre désactivée (voir delete). */
  reactiver(id: string): Observable<Offer> {
    return this.http.post<Offer>(`${this.url}/${id}/reactiver/`, {});
  }

  /** POST /api/offres/<id>/valider-accueil-intervenants/ — confirme qu'un hébergement peut
   * accueillir des intervenants. */
  validerAccueilIntervenants(id: string): Observable<Offer> {
    return this.http.post<Offer>(`${this.url}/${id}/valider-accueil-intervenants/`, {});
  }

  /** GET /api/offres/?page=&page_size=&... — pagination serveur (OptionalPageNumberPagination),
   * enveloppe {count,next,previous,results}. Utilisé par ReportingComponent. */
  searchPage(params: Record<string, string>, page: number, pageSize: number): Observable<PageResponse<Offer>> {
    const httpParams = this.toParams({ ...params, page: String(page), page_size: String(pageSize) });
    return this.http
      .get<PageResponse<Offer>>(`${this.url}/`, { params: httpParams })
      .pipe(map(res => ({ ...res, results: res.results.map(this.normalize) })));
  }

  /** GET /api/offres/vue_mairie/ — offres de la commune de l'institution de l'utilisateur
   * appelant (réservé institutionnel). */
  vueMairie(): Observable<Offer[]> {
    return this.http.get<Offer[]>(`${this.url}/vue_mairie/`).pipe(map(list => list.map(this.normalize)));
  }

  /** GET /api/offres/vue_secteur/ — à l'échelle du type d'institution (commune/EPCI/département).
   * `limite` plafonne côté serveur (l'annuaire de bénévoles peut compter des milliers de fiches). */
  vueSecteur(options?: { limite?: number; type?: string; excludeType?: string }): Observable<Offer[]> {
    let params = new HttpParams();
    if (options?.limite) params = params.set('page', '1').set('page_size', String(options.limite));
    if (options?.type) params = params.set('type', options.type);
    if (options?.excludeType) params = params.set('exclude_type', options.excludeType);
    return this.http.get<Offer[] | { results: Offer[] }>(`${this.url}/vue_secteur/`, { params }).pipe(
      map(res => (Array.isArray(res) ? res : res.results).map(this.normalize))
    );
  }

  /** GET /api/offres/vue_secteur/?echelle=national — vue nationale partielle (type/statut/crise/date,
   * OfferNationalPartialSerializer), jamais de coordonnées. */
  vueSecteurNationalPartiel(options?: { limite?: number }): Observable<OfferNationalPartial[]> {
    let params = new HttpParams().set('echelle', 'national');
    if (options?.limite) params = params.set('page', '1').set('page_size', String(options.limite));
    return this.http
      .get<OfferNationalPartial[] | { results: OfferNationalPartial[] }>(`${this.url}/vue_secteur/`, { params })
      .pipe(map(res => (Array.isArray(res) ? res : res.results)));
  }

  /** POST /api/offres/<id>/assign_dossier/ — affecte l'auteur de l'offre au dossier (rôle OFFRANT). */
  assignDossier(offerId: string, dossierId: string): Observable<{ id: string; dossier: string; created: boolean }> {
    return this.http.post<{ id: string; dossier: string; created: boolean }>(
      `${this.url}/${offerId}/assign_dossier/`, { dossier: dossierId }
    );
  }

  /** POST /api/offres/bulk_create_team/ — crée une équipe à partir d'une sélection d'offres
   * (membres = auteurs distincts), lui assigne les offres et un régulateur optionnel. */
  bulkCreateTeam(offerIds: string[], teamName: string, regulateurId: string | null, missionTitre = ''): Observable<Team> {
    return this.http.post<Team>(`${this.url}/bulk_create_team/`, {
      offer_ids: offerIds, team_name: teamName, regulateur: regulateurId, mission_titre: missionTitre,
    });
  }

  /** POST /api/offres/{id}/affecter-stock/ — ajoute l'offre au stock d'un point (ContributionMateriel) ;
   * renvoie la ligne MaterielPoint. */
  affecterStock(offerId: string, pointId: string): Observable<any> {
    return this.http.post<any>(`${this.url}/${offerId}/affecter-stock/`, { point_id: pointId });
  }

  /** GET /api/offres/{id}/messages/ — fil avec le propriétaire de l'offre (institutionnels). */
  getMessages(offerId: string): Observable<OfferMessage[]> {
    return this.http.get<OfferMessage[]>(`${this.url}/${offerId}/messages/`);
  }

  /** POST /api/offres/{id}/messages/ — le propriétaire reçoit un lien de réponse par email. */
  sendMessage(offerId: string, contenu: string): Observable<OfferMessage> {
    return this.http.post<OfferMessage>(`${this.url}/${offerId}/messages/`, { contenu });
  }

  /** GET /api/offres/retours-externes/ — offres avec un message non lu par l'institution. */
  retoursExternes(criseId: string): Observable<Offer[]> {
    return this.http.get<Offer[]>(`${this.url}/retours-externes/`, { params: { crisis: criseId } });
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