import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export type NatureAppel = 'DEMANDE_AIDE' | 'OFFRE_AIDE' | 'SIGNALEMENT' | 'RENSEIGNEMENT' | 'AUTRE';
export type SuiteAppel = 'A_TRAITER' | 'TRANSMIS' | 'TRAITE' | 'SANS_SUITE';

/** Une fiche d'appel du standard de crise (voir core/standard_crise.py). */
export interface AppelStandard {
  id: string;
  numero: number;
  crise: string | null;
  crise_nom: string | null;
  nature: NatureAppel;
  nature_libelle: string;
  appelant_nom: string;
  appelant_telephone: string;
  lieu: string;
  objet: string;
  suite: SuiteAppel;
  suite_libelle: string;
  suite_donnee: string;
  dossier: string | null;
  dossier_numero: string | null;
  recu_par_nom: string;
  date_appel: string;
}

export interface SyntheseAppels {
  natures: { code: NatureAppel; libelle: string }[];
  total: number;
  a_traiter: number;
  par_nature: { code: NatureAppel; libelle: string; nombre: number }[];
}

/** Les chiffres d'une crise pour la collectivité, rassemblés (voir core/point_situation.py). */
export interface PointDeSituation {
  crise: string;
  collectivite: string;
  etabli_le: string;
  chiffres: Record<string, { libelle: string; valeur: number }[]>;
  par_centre: { centre: string; personnes: number }[];
  equipes: string[];
  texte: string;
}

@Injectable({ providedIn: 'root' })
export class StandardCriseService {
  private readonly url = `${environment.apiUrl}/standard-crise/appels`;

  constructor(private http: HttpClient) {}

  appels(crise?: string | null): Observable<AppelStandard[]> {
    return this.http.get<AppelStandard[]>(`${this.url}/`, { params: crise ? { crise } : {} });
  }

  synthese(crise?: string | null): Observable<SyntheseAppels> {
    return this.http.get<SyntheseAppels>(`${this.url}/synthese/`, { params: crise ? { crise } : {} });
  }

  enregistrer(appel: { nature: NatureAppel; objet: string; crise?: string | null; appelant_nom?: string;
                       appelant_telephone?: string; lieu?: string }): Observable<AppelStandard> {
    return this.http.post<AppelStandard>(`${this.url}/`, appel);
  }

  clore(id: string, suite: SuiteAppel, suite_donnee: string): Observable<AppelStandard> {
    return this.http.post<AppelStandard>(`${this.url}/${id}/clore/`, { suite, suite_donnee });
  }

  ouvrirDossier(id: string, priorite: string): Observable<AppelStandard> {
    return this.http.post<AppelStandard>(`${this.url}/${id}/ouvrir-dossier/`, { priorite });
  }

  pointDeSituation(crise: string): Observable<PointDeSituation> {
    return this.http.get<PointDeSituation>(`${environment.apiUrl}/point-de-situation/`, { params: { crise } });
  }
}
