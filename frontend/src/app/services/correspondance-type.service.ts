import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Correspondance « type de demande / de signalement → besoin » (premier maillon de la chaîne
 * type → besoin → compétence qui donne sa compétence à un dossier, voir
 * resolve_competence_for_request côté backend). Modification réservée aux administrateurs. */
export interface CorrespondanceType {
  id: string;
  request_type?: string;
  request_type_nom?: string;
  information_type?: string;
  information_type_nom?: string;
  besoin: string;
  besoin_nom: string;
}

export type AxeType = 'demande' | 'signalement';

@Injectable({ providedIn: 'root' })
export class CorrespondanceTypeService {

  private urls: Record<AxeType, string> = {
    demande: `${environment.apiUrl}/request-types-besoins`,
    signalement: `${environment.apiUrl}/information-types-besoins`,
  };
  private champs: Record<AxeType, string> = { demande: 'request_type', signalement: 'information_type' };

  constructor(private http: HttpClient) {}

  getAll(axe: AxeType): Observable<CorrespondanceType[]> {
    return this.http.get<CorrespondanceType[]>(`${this.urls[axe]}/`);
  }

  create(axe: AxeType, typeId: string, besoinId: string): Observable<CorrespondanceType> {
    return this.http.post<CorrespondanceType>(`${this.urls[axe]}/`, { [this.champs[axe]]: typeId, besoin: besoinId });
  }

  delete(axe: AxeType, id: string): Observable<void> {
    return this.http.delete<void>(`${this.urls[axe]}/${id}/`);
  }
}
