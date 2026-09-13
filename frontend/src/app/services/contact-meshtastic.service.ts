import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { ContactMeshtastic } from '../shared/models/contact-meshtastic.model';

/** Répertoire de nœuds découverts passivement sur MQTT — lecture seule (voir
 * ContactMeshtasticViewSet). */
@Injectable({ providedIn: 'root' })
export class ContactMeshtasticService {

  private url = `${environment.apiUrl}/contacts-meshtastic`;

  constructor(private http: HttpClient) {}

  getAll(compagnonId?: string): Observable<ContactMeshtastic[]> {
    return this.http.get<ContactMeshtastic[]>(`${this.url}/`, { params: compagnonId ? { compagnon: compagnonId } : {} });
  }
}
