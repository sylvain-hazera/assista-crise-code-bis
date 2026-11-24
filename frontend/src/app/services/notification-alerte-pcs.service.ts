import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { NotificationAlertePCS } from '../shared/models/notification-alerte-pcs.model';

@Injectable({ providedIn: 'root' })
export class NotificationAlertePCSService {

  private url = `${environment.apiUrl}/notifications-alerte-pcs`;

  constructor(private http: HttpClient) {}

  getForCrise(criseId: string): Observable<NotificationAlertePCS[]> {
    return this.http.get<NotificationAlertePCS[]>(`${this.url}/`, { params: { crise: criseId } });
  }

  /** La mairie coche "prévenu" à la main (typiquement après un appel téléphonique). */
  confirmer(id: string): Observable<NotificationAlertePCS> {
    return this.http.post<NotificationAlertePCS>(`${this.url}/${id}/confirmer/`, {});
  }

  /** Envoi explicite (email/application) pour les lignes sélectionnées, avec le message choisi/
   * modifié par l'utilisateur pour cette fois uniquement. */
  envoyerLot(criseId: string, notificationIds: string[], message: string): Observable<{ traitees: number; notifications: NotificationAlertePCS[] }> {
    return this.http.post<{ traitees: number; notifications: NotificationAlertePCS[] }>(`${this.url}/envoyer_lot/`, {
      crise: criseId, notification_ids: notificationIds, message,
    });
  }
}
