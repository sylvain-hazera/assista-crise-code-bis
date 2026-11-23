import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Ce qu'un administrateur regarde : `MIENNE` (son institution), `TOUT` (toute la plateforme),
 * ou l'identifiant d'une institution. */
export type ChoixPerimetre = string;

export interface EtatPerimetre {
  administrateur: boolean;
  /** `INVALIDE` : le choix gardé ne désigne plus rien (institution supprimée). */
  mode: 'TOUT' | 'INSTITUTION' | 'INVALIDE' | null;
  institution: { id: string; nom: string; code_postal?: string } | null;
  mienne: { id: string; nom: string } | null;
  /** Rendue seulement pour une recherche (2 lettres au moins), 50 au plus (23/11/2026). */
  institutions: InstitutionPerimetre[];
}

export interface InstitutionPerimetre {
  id: string;
  nom: string;
  type_libelle: string;
  code_postal?: string;
  commune?: string;
}

/** Périmètre de consultation d'un administrateur de la plateforme.
 *
 * Un administrateur a le DROIT de tout voir, mais il travaille d'abord pour son institution :
 * par défaut il voit donc ce qu'en voit un cadre (ses équipes, ses missions, son secteur), et
 * un sélecteur dans la barre du haut lui permet de regarder une autre institution ou toute la
 * plateforme. Le choix vit dans le navigateur et part à chaque requête dans l'en-tête
 * `X-Perimetre` (voir l'intercepteur) ; le serveur l'ignore pour tout autre rôle.
 *
 * Il réduit ce qui est affiché dans les listes, jamais les droits. */
@Injectable({ providedIn: 'root' })
export class PerimetreService {
  static readonly CLE = 'ac_perimetre';
  static readonly MIENNE = 'MIENNE';
  static readonly TOUT = 'TOUT';

  constructor(private http: HttpClient) {}

  get choix(): ChoixPerimetre {
    try {
      return localStorage.getItem(PerimetreService.CLE) || PerimetreService.MIENNE;
    } catch {
      return PerimetreService.MIENNE;
    }
  }

  definir(choix: ChoixPerimetre): void {
    try {
      localStorage.setItem(PerimetreService.CLE, choix || PerimetreService.MIENNE);
    } catch { /* navigation privée : le choix ne tiendra que le temps de la page */ }
  }

  etat(): Observable<EtatPerimetre> {
    return this.http.get<EtatPerimetre>(`${environment.apiUrl}/me/perimetre/`);
  }

  /** Quelques lettres du nom, de la commune ou du code postal. */
  rechercher(q: string): Observable<EtatPerimetre> {
    return this.http.get<EtatPerimetre>(`${environment.apiUrl}/me/perimetre/`, { params: { q } });
  }
}
