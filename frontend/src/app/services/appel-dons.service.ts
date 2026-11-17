import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { AppelAuxDons, AvisDons, FamilleCatalogueDon, FoyerSinistre, LigneDon, PersonneFoyer } from '../shared/models/appel-dons.model';

/** Appels aux dons (voir core/appels_dons.py côté serveur). */
@Injectable({ providedIn: 'root' })
export class AppelDonsService {
  private readonly url = `${environment.apiUrl}/dons`;

  constructor(private http: HttpClient) {}

  catalogue(): Observable<{ familles: FamilleCatalogueDon[] }> { return this.http.get<{ familles: FamilleCatalogueDon[] }>(`${this.url}/catalogue/`); }

  /** Les avis publics : lisibles sans compte. */
  avis(): Observable<{ avis: AvisDons[]; comment_aider: string }> { return this.http.get<{ avis: AvisDons[]; comment_aider: string }>(`${this.url}/avis/`); }

  // ── Foyers ──────────────────────────────────────────────────────────────────────────────
  foyers(): Observable<FoyerSinistre[]> { return this.http.get<FoyerSinistre[]>(`${this.url}/foyers/`); }

  enregistrerFoyer(foyer: { id?: string; nom: string; contact?: string; adresse?: string; commentaire?: string; crise?: string | null;
                            personnes: PersonneFoyer[]; besoins: LigneDon[] }): Observable<FoyerSinistre> {
    return foyer.id ? this.http.patch<FoyerSinistre>(`${this.url}/foyers/${foyer.id}/`, foyer) : this.http.post<FoyerSinistre>(`${this.url}/foyers/`, foyer);
  }

  remettre(foyer: string, besoin: string, quantite: number, depot?: string): Observable<FoyerSinistre> {
    return this.http.post<FoyerSinistre>(`${this.url}/foyers/${foyer}/remettre/`, { besoin, quantite, ...(depot ? { depot } : {}) });
  }

  // ── Appels ──────────────────────────────────────────────────────────────────────────────
  /** `miens` : ceux de mon institution (tous états) ; sinon les appels ouverts des autres. */
  appels(miens: boolean): Observable<AppelAuxDons[]> {
    return this.http.get<AppelAuxDons[]>(`${this.url}/appels/`, { params: miens ? { miens: '1' } : { autres: '1' } });
  }

  enregistrerAppel(appel: Partial<AppelAuxDons>): Observable<AppelAuxDons> {
    return appel.id ? this.http.patch<AppelAuxDons>(`${this.url}/appels/${appel.id}/`, appel) : this.http.post<AppelAuxDons>(`${this.url}/appels/`, appel);
  }

  /** Tous les gestes d'un appel rendent l'appel à jour. */
  geste(appel: string, geste: 'lignes' | 'reprendre-foyers' | 'ouvrir' | 'clore' | 'engager' | 'annuler-engagement' | 'annoncer-envoi' | 'recevoir-envoi',
        corps: Record<string, unknown> = {}): Observable<AppelAuxDons> {
    return this.http.post<AppelAuxDons>(`${this.url}/appels/${appel}/${geste}/`, corps);
  }
}
