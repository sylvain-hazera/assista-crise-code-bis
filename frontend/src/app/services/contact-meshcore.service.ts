import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { ContactMeshCore } from '../shared/models/contact-meshcore.model';

/** Répertoire de contacts déjà tenu par le firmware d'un companion, synchronisé
 * périodiquement par le service-pont — lecture seule ici (voir ContactMeshCoreViewSet). */
@Injectable({ providedIn: 'root' })
export class ContactMeshCoreService {

  private url = `${environment.apiUrl}/contacts-meshcore`;

  constructor(private http: HttpClient) {}

  getAll(compagnonId?: string): Observable<ContactMeshCore[]> {
    return this.http.get<ContactMeshCore[]>(`${this.url}/`, { params: compagnonId ? { compagnon: compagnonId } : {} });
  }
}
