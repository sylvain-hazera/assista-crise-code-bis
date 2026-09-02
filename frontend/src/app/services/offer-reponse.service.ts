import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Offer } from '../shared/models/offer.model';
import { OfferMessage } from '../shared/models/offer-message.model';

export interface OfferReponseData {
  offer: Offer;
  messages: OfferMessage[];
}

/** Page publique de réponse/édition d'une offre — aucune authentification requise, le jeton
 * opaque reçu par email (Offer.reponse_token) fait foi. Voir OfferReponsePublicView. */
@Injectable({ providedIn: 'root' })
export class OfferReponseService {
  private apiUrl = `${environment.apiUrl}/repondre-offre`;

  constructor(private http: HttpClient) {}

  getByToken(token: string): Observable<OfferReponseData> {
    return this.http.get<OfferReponseData>(`${this.apiUrl}/${token}/`);
  }

  reply(token: string, contenu: string): Observable<OfferMessage> {
    return this.http.post<OfferMessage>(`${this.apiUrl}/${token}/`, { contenu });
  }

  updateOffer(token: string, data: Partial<Offer>): Observable<Offer> {
    return this.http.patch<Offer>(`${this.apiUrl}/${token}/`, data);
  }
}
