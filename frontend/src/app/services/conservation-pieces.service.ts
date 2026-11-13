import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, shareReplay } from 'rxjs';

import { environment } from '../../environments/environment';
import { TableConservation } from '../shared/models/conservation-piece.model';

/** La politique de conservation, lue une fois et partagée.
 *
 * `shareReplay` plutôt qu'un appel par page : cette table ne change qu'au déploiement, et
 * elle est affichée à deux endroits (dépôt et validation) qu'on ouvre souvent l'un après
 * l'autre. */
@Injectable({ providedIn: 'root' })
export class ConservationPiecesService {

  private url = `${environment.apiUrl}/conservation-pieces/`;
  private cache?: Observable<TableConservation>;

  constructor(private http: HttpClient) {}

  table(): Observable<TableConservation> {
    if (!this.cache) {
      this.cache = this.http.get<TableConservation>(this.url).pipe(shareReplay(1));
    }
    return this.cache;
  }
}
