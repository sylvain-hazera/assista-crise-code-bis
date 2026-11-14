import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export interface CompagnonRelayable {
  id: string;
  nom: string;
  institution_nom: string;
  relaye_par_moi: boolean;
}

export interface EtatRelais {
  compagnons: CompagnonRelayable[];
  session: {
    session: string; compagnon: string; ouverte_le: string;
    trames_recues: number; trames_envoyees: number;
  } | null;
  secondes_avant_session_morte: number;
}

export interface MessageSortant {
  id: string;
  compagnon: string;
  contact_pubkey_hex: string;
  contenu: string;
}

/**
 * Le côté serveur du relais : session, file sortante, messages entrants.
 *
 * **Les endpoints de messages sont ceux du pont Python**, pas des endpoints dédiés : ils
 * existent déjà, ils sont éprouvés, et le serveur n'a donc rien de nouveau à décoder. Le
 * navigateur est un pont qui se trouve tourner dans un onglet.
 */
@Injectable({ providedIn: 'root' })
export class RelaisSerieService {

  private relais = `${environment.apiUrl}/relais-serie/`;
  private messages = `${environment.apiUrl}/messages-meshcore`;

  constructor(private http: HttpClient) {}

  etat(): Observable<EtatRelais> {
    return this.http.get<EtatRelais>(this.relais);
  }

  /** Ouvre la session, ou bat la mesure si elle est déjà ouverte — c'est la même opération. */
  ouvrirOuBattre(compagnon: string, tramesRecues = 0, tramesEnvoyees = 0)
      : Observable<{ session: string | null }> {
    return this.http.post<{ session: string | null }>(this.relais, {
      compagnon, trames_recues: tramesRecues, trames_envoyees: tramesEnvoyees,
    });
  }

  fermer(compagnon: string): Observable<{ session: null }> {
    return this.http.post<{ session: null }>(this.relais, { compagnon, fermer: true });
  }

  /** La file sortante de CETTE radio. Le paramètre est obligatoire côté serveur. */
  aEnvoyer(compagnon: string): Observable<MessageSortant[]> {
    return this.http.get<MessageSortant[]>(`${this.messages}/a-envoyer/`,
                                           { params: { compagnon } });
  }

  marquer(id: string, statut: 'ENVOYE' | 'ECHEC', erreur?: string): Observable<unknown> {
    return this.http.patch(`${this.messages}/${id}/`, erreur ? { statut, erreur } : { statut });
  }

  deposerEntrant(compagnon: string, contactPubkeyHex: string, contenu: string)
      : Observable<unknown> {
    return this.http.post(`${this.messages}/`, {
      compagnon, direction: 'ENTRANT', contact_pubkey_hex: contactPubkeyHex, contenu,
    });
  }
}
