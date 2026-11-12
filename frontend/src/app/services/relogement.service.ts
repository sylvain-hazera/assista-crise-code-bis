import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  DossierRelogement, SyntheseRelogement,
} from '../shared/models/relogement.model';

/** Suivi du relogement des familles sinistrées. */
@Injectable({ providedIn: 'root' })
export class RelogementService {
  private url = `${environment.apiUrl}/dossiers-relogement`;

  constructor(private http: HttpClient) {}

  getAll(criseId?: string): Observable<DossierRelogement[]> {
    const params = criseId ? { crise: criseId } : undefined;
    return this.http.get<DossierRelogement[]>(`${this.url}/`, { params });
  }

  creer(data: Partial<DossierRelogement>): Observable<DossierRelogement> {
    return this.http.post<DossierRelogement>(`${this.url}/`, data);
  }

  modifier(id: string, data: Partial<DossierRelogement>): Observable<DossierRelogement> {
    return this.http.patch<DossierRelogement>(`${this.url}/${id}/`, data);
  }

  /** Enregistre un nouvel hébergement ET clôt le précédent : un foyer ne dort pas à deux
   * endroits. Le serveur s'en charge, pour qu'un oubli côté écran ne puisse pas laisser deux
   * lignes ouvertes. */
  ajouterSolution(id: string, data: Record<string, unknown>): Observable<DossierRelogement> {
    return this.http.post<DossierRelogement>(`${this.url}/${id}/ajouter-solution/`, data);
  }

  cloturerSolution(id: string, dateFin?: string, motif?: string)
      : Observable<DossierRelogement> {
    return this.http.post<DossierRelogement>(`${this.url}/${id}/cloturer-solution/`, {
      date_fin_effective: dateFin, motif_fin: motif,
    });
  }

  /** Le bilan : calculé sur toute la crise, pas sur ce qui est affiché. */
  synthese(criseId: string): Observable<SyntheseRelogement> {
    return this.http.get<SyntheseRelogement>(`${this.url}/synthese/`,
                                             { params: { crise: criseId } });
  }
}
