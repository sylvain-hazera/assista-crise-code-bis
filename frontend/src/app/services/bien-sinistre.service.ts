import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { BienSinistre } from '../shared/models/bien-sinistre.model';

/** Biens sinistrés autres que les habitations (voir BienSinistre côté serveur). */
@Injectable({ providedIn: 'root' })
export class BienSinistreService {
  private readonly url = `${environment.apiUrl}/biens-sinistres`;

  constructor(private http: HttpClient) {}

  lister(crise?: string): Observable<BienSinistre[]> {
    const params: Record<string, string> = crise ? { crise } : {};
    return this.http.get<BienSinistre[]>(`${this.url}/`, { params });
  }

  creer(bien: Partial<BienSinistre>): Observable<BienSinistre> {
    return this.http.post<BienSinistre>(`${this.url}/`, bien);
  }

  modifier(id: string, bien: Partial<BienSinistre>): Observable<BienSinistre> {
    return this.http.patch<BienSinistre>(`${this.url}/${id}/`, bien);
  }

  supprimer(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** Envoie le rapport du bien, en pièce jointe, à l'adresse du propriétaire enregistrée. */
  envoyerAuProprietaire(id: string): Observable<BienSinistre & { envoye_a: string }> {
    return this.http.post<BienSinistre & { envoye_a: string }>(`${this.url}/${id}/envoyer-au-proprietaire/`, {});
  }
}
