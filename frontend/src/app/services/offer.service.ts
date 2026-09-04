import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Offer, OfferPayload, OfferType } from '../shared/models/offer.model';
import { OfferMessage } from '../shared/models/offer-message.model';
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
      return this.getAll({ author_email: email });
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

  /** POST /api/photos-offres/ — ajoute une photo à la galerie d'une offre déjà créée (au-delà
   * de sa photo principale, voir OfferPhoto/propose-help-form). */
  addPhoto(offerId: string, file: File, ordre: number): Observable<void> {
    const fd = new FormData();
    fd.append('offer', offerId);
    fd.append('image', file);
    fd.append('ordre', String(ordre));
    return this.http.post<void>(`${environment.apiUrl}/photos-offres/`, fd);
  }

  /** POST /api/offres/<id>/transformer/ — recrée cette offre en demande ou signalement
   * (réservé institutionnel, refusé si déjà affectée). Supprime l'offre d'origine. */
  transformer(id: string, cible: 'REQUEST' | 'INFORMATION'): Observable<any> {
    return this.http.post<any>(`${this.url}/${id}/transformer/`, { cible });
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

  /** POST /api/offres/<id>/reactiver/ — réactive une offre désactivée (voir delete). */
  reactiver(id: string): Observable<Offer> {
    return this.http.post<Offer>(`${this.url}/${id}/reactiver/`, {});
  }

  /** GET /api/offres/vue_mairie/ — offres de la commune de l'institution de l'utilisateur
   * appelant (réservé institutionnel). */
  vueMairie(): Observable<Offer[]> {
    return this.http.get<Offer[]>(`${this.url}/vue_mairie/`).pipe(map(list => list.map(this.normalize)));
  }

  /** GET /api/offres/vue_secteur/ — comme vue_mairie, mais à l'échelle adaptée au type
   * d'institution de l'appelant (commune/EPCI/département, voir _institution_secteur_or_400
   * côté backend). Sans ?page=, renvoie tout d'un coup — volontaire ici : un secteur (même un
   * département) reste d'un volume raisonnable, contrairement à /offres/ non filtré. */
  vueSecteur(): Observable<Offer[]> {
    return this.http.get<Offer[]>(`${this.url}/vue_secteur/`).pipe(map(list => list.map(this.normalize)));
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

  /** POST /api/offres/{id}/affecter-stock/ — ajoute une offre de matériel au stock d'un point
   * (crée un apport individuel, voir ContributionMateriel). Retourne la ligne MaterielPoint
   * mise à jour. */
  affecterStock(offerId: string, pointId: string): Observable<any> {
    return this.http.post<any>(`${this.url}/${offerId}/affecter-stock/`, { point_id: pointId });
  }

  /** GET /api/offres/{id}/messages/ — fil de discussion avec le propriétaire de l'offre
   * (réservé acteur institutionnel — voir vue équipe hébergement). */
  getMessages(offerId: string): Observable<OfferMessage[]> {
    return this.http.get<OfferMessage[]>(`${this.url}/${offerId}/messages/`);
  }

  /** POST /api/offres/{id}/messages/ — envoie un message au propriétaire de l'offre, qui
   * reçoit un lien de réponse/édition par email. */
  sendMessage(offerId: string, contenu: string): Observable<OfferMessage> {
    return this.http.post<OfferMessage>(`${this.url}/${offerId}/messages/`, { contenu });
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