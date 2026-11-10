import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { RattachementNoeudRadio } from '../shared/models/rattachement-noeud-radio.model';

/** Rattachement d'un nœud d'infrastructure (répéteur) à une institution ou à un compte.
 *
 * Le rattachement ouvre le droit d'ÉCRIRE sur ce nœud (core/acces_radio.py), d'où les gardes
 * côté serveur : on ne rattache qu'à soi ou à une de ses institutions, et un nœud déjà rattaché
 * ne se vole pas. Le firmware reste le dernier mot — écrire exige la clé d'administration posée
 * sur l'appareil. */
@Injectable({ providedIn: 'root' })
export class RattachementNoeudRadioService {

  private url = `${environment.apiUrl}/rattachements-noeuds-radio`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<RattachementNoeudRadio[]> {
    return this.http.get<RattachementNoeudRadio[]>(`${this.url}/`);
  }

  /** `institution` ou `utilisateur`, jamais les deux : « qui en répond ? » doit avoir une
   * seule réponse. */
  rattacher(donnees: {
    node_num: number; institution?: string | null; utilisateur?: string | null;
    libelle?: string; note?: string;
  }): Observable<RattachementNoeudRadio> {
    return this.http.post<RattachementNoeudRadio>(`${this.url}/`, donnees);
  }

  detacher(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }
}
