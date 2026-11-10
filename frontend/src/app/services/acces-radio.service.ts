import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { DemandeAccesRadio, EtatAccesRadio, StatutDemandeAccesRadio } from '../shared/models/acces-radio.model';
import { NiveauAccesRadio } from '../shared/models/user.model';

/** Droit d'accès au domaine radio : où j'en suis, demander, instruire.
 *
 * Le niveau n'est jamais calculé ici : il dépend du matériel enregistré (nœud personnel,
 * passerelle de l'institution) et des droits accordés, dont le navigateur ne sait rien. Voir
 * backend/core/acces_radio.py. */
@Injectable({ providedIn: 'root' })
export class AccesRadioService {

  private url = `${environment.apiUrl}/demandes-acces-radio`;

  constructor(private http: HttpClient) {}

  /** Mon niveau, les titres qui l'ouvrent, et ma dernière demande. Ouvert à tout compte
   * authentifié, y compris — et surtout — quand la réponse est « aucun accès ». */
  monAcces(): Observable<EtatAccesRadio> {
    return this.http.get<EtatAccesRadio>(`${this.url}/mon-acces/`);
  }

  demander(niveau: NiveauAccesRadio, motif: string): Observable<DemandeAccesRadio> {
    return this.http.post<DemandeAccesRadio>(`${this.url}/`, { niveau_demande: niveau, motif });
  }

  /** Mes demandes, ou toutes pour un administrateur (le serveur filtre). */
  lister(statut?: StatutDemandeAccesRadio): Observable<DemandeAccesRadio[]> {
    return this.http.get<DemandeAccesRadio[]>(
      `${this.url}/`, statut ? { params: { statut } } : {},
    );
  }

  /** Accorde, refuse ou retire. `niveau` est obligatoire pour ACCORDEE et peut être inférieur
   * au niveau demandé : c'est une décision, pas un refus. */
  instruire(id: string, decision: StatutDemandeAccesRadio, niveau: NiveauAccesRadio | null,
            commentaire: string): Observable<DemandeAccesRadio> {
    return this.http.post<DemandeAccesRadio>(`${this.url}/${id}/instruire/`, {
      decision, niveau_accorde: niveau, commentaire,
    });
  }
}
