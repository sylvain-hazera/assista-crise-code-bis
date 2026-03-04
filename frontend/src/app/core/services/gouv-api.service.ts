import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

export interface Departement {
  code: string;
  name: string;
}

export interface Commune {
  code: string;
  name: string;
  codeDepartement: string;
  codesPostaux: string[];
}

export interface RisqueDetail {
  num_risque: string;
  libelle_risque_long: string;
  zone_sismicite: string | null;
}

export interface RisqueCommune {
  code_insee: string;
  libelle_commune: string;
  risques_detail: RisqueDetail[];
  response_code: number;
  message: string | null;
}

export interface GeoRisquesResponse {
  results: number;
  page: number;
  total_pages: number;
  data: RisqueCommune[];
  next: string | null;
  previous: string | null;
}

export interface DicrimInfo {
  annee_publication: string;
  code_insee: string;
  libelle_commune: string;
}

export interface DicrimResponse {
  results: number;
  page: number;
  total_pages: number;
  data: DicrimInfo[];
  response_code: number;
  message: string | null;
}

export interface TimInfo {
  date_transmission: string;
  code_insee: string;
  libelle_commune: string;
}

export interface TimResponse {
  results: number;
  page: number;
  total_pages: number;
  data: TimInfo[];
  response_code: number;
  message: string | null;
}

@Injectable({
  providedIn: 'root'
})
export class GouvApiService {
  private readonly GEO_API_URL = 'https://geo.api.gouv.fr';
  private readonly GEORISQUES_API_URL = 'https://georisques.gouv.fr/api/v1';

  constructor(private http: HttpClient) {}

  /**
   * Récupère la liste de tous les départements français
   */
  getDepartements(): Observable<Departement[]> {
    return this.http.get<any[]>(`${this.GEO_API_URL}/departements`)
      .pipe(map(deps => deps.map(d => ({ code: d.code, name: d.nom }))));
  }

  /**
   * Récupère la liste des communes d'un département
   * @param codeDept Code du département (ex: "33", "75")
   */
  getCommunesByDepartement(codeDept: string): Observable<Commune[]> {
    return this.http.get<any[]>(
      `${this.GEO_API_URL}/departements/${codeDept}/communes`
    ).pipe(map(communes => communes.map(c => ({
      code: c.code,
      name: c.nom,
      codeDepartement: c.codeDepartement,
      codesPostaux: c.codesPostaux
    }))));
  }

  /**
   * Récupère les risques majeurs et informations PCS/DICRIM d'une commune
   * @param codeInsee Code INSEE de la commune (ex: "33063" pour Bordeaux)
   */
  getRisquesByCommune(codeInsee: string): Observable<GeoRisquesResponse> {
    return this.http.get<GeoRisquesResponse>(
      `${this.GEORISQUES_API_URL}/gaspar/risques`,
      { params: { code_insee: codeInsee } }
    );
  }

  /**
   * Récupère les informations DICRIM (Document d'Information Communal sur les Risques Majeurs)
   * @param codeInsee Code INSEE de la commune
   */
  getDicrimByCommune(codeInsee: string): Observable<DicrimResponse> {
    return this.http.get<DicrimResponse>(
      `${this.GEORISQUES_API_URL}/gaspar/dicrim`,
      { params: { code_insee: codeInsee } }
    );
  }

  /**
   * Récupère les informations TIM (Transmission d'Information au Maire) qui contient les infos PCS
   * @param codeInsee Code INSEE de la commune
   */
  getTimByCommune(codeInsee: string): Observable<TimResponse> {
    return this.http.get<TimResponse>(
      `${this.GEORISQUES_API_URL}/gaspar/tim`,
      { params: { code_insee: codeInsee } }
    );
  }
}
