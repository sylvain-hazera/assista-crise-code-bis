import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Messagerie SMTP propre à une institution (22/11/2026). Identifiant et mot de passe en
 * écriture seule : la lecture dit seulement s'ils sont renseignés. */
export interface ConnecteurSMTP {
  id?: string; institution: string; nom: string; hote: string; port: number;
  chiffrement: 'STARTTLS' | 'SSL' | 'AUCUN'; identifiant?: string; mot_de_passe?: string;
  identifiant_renseigne?: boolean; mot_de_passe_renseigne?: boolean;
  expediteur_email: string; expediteur_nom: string; actif: boolean;
  dernier_succes?: string | null; dernier_echec?: string | null; dernier_echec_motif?: string;
}

@Injectable({ providedIn: 'root' })
export class ConnecteursSmtpService {
  private url = `${environment.apiUrl}/connecteurs-smtp`;

  constructor(private http: HttpClient) {}

  lister(institution: string): Observable<ConnecteurSMTP[]> {
    return this.http.get<ConnecteurSMTP[]>(`${this.url}/`, { params: { institution } });
  }

  creer(c: ConnecteurSMTP): Observable<ConnecteurSMTP> { return this.http.post<ConnecteurSMTP>(`${this.url}/`, c); }

  modifier(id: string, c: Partial<ConnecteurSMTP>): Observable<ConnecteurSMTP> {
    return this.http.patch<ConnecteurSMTP>(`${this.url}/${id}/`, c);
  }

  supprimer(id: string): Observable<void> { return this.http.delete<void>(`${this.url}/${id}/`); }

  essai(id: string): Observable<{ ok: boolean; message?: string; error?: string }> {
    return this.http.post<{ ok: boolean; message?: string; error?: string }>(`${this.url}/${id}/essai/`, {});
  }
}
