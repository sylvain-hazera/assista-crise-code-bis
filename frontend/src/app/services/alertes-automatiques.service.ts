import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** Les alertes automatiques d'une collectivité (backend/core/alertes_naturelles.py, 24/11/2026). */
export interface RegleAlerte {
  id: string;
  actif: boolean;
  seuils: Record<string, number>;
  email: boolean;
  radio_si_exceptionnel: boolean;
  silence_nuit: boolean;
  destinataires: 'CONTACTS' | 'PRINCIPAUX';
  modifie_le?: string;
}

export interface PhenomeneAlerte {
  code: string;
  libelle: string;
  famille: string;
  unite: string;
  conseille: Record<string, number>;
  minimum: number;
  maximum: number;
  pas: number;
  radio_possible: boolean;
  reglages: Record<string, { defaut: number; minimum: number; maximum: number }>;
  echelle: Record<string, string>;
  source: { source?: string; releve_le?: string | null; perime?: boolean };
  regle: RegleAlerte | null;
  derniere_alerte: string | null;
}

export interface AlerteNaturelle {
  id: string;
  phenomene: string;
  phenomene_libelle: string;
  famille: string;
  niveau: 'ALERTE' | 'EXCEPTIONNEL';
  valeur: number | null;
  unite: string;
  titre: string;
  detail: string;
  latitude: number | null;
  longitude: number | null;
  emise_le: string;
  bilan: { personnes?: number; courriels?: number; radio?: number };
  institution: string;
  crise: string | null;
  crise_nom: string | null;
  campagne: string | null;
  type_crise: string;
}

export interface MatriceAlertes {
  institution: { id: string; nom: string };
  choix: { id: string; nom: string }[];
  perimetre: { niveau: string; code: string; communes: number } | null;
  phenomenes: PhenomeneAlerte[];
  alertes: AlerteNaturelle[];
}

export interface PreremplissageCrise {
  type: string;
  titre: string;
  description: string;
  latitude: number | null;
  longitude: number | null;
  institution: string;
}

@Injectable({ providedIn: 'root' })
export class AlertesAutomatiquesService {
  private api = `${environment.apiUrl}/alertes-automatiques`;

  constructor(private http: HttpClient) {}

  matrice(institution?: string | null): Observable<MatriceAlertes> {
    const params = institution ? new HttpParams().set('institution', institution) : undefined;
    return this.http.get<MatriceAlertes>(`${this.api}/`, { params });
  }

  enregistrer(institution: string, phenomene: string, regle: Partial<RegleAlerte>): Observable<RegleAlerte> {
    return this.http.post<RegleAlerte>(`${this.api}/regle/`, { institution, phenomene, ...regle });
  }

  toutes(institution: string, actif: boolean): Observable<MatriceAlertes> {
    return this.http.post<MatriceAlertes>(`${this.api}/toutes/`, { institution, actif });
  }

  alerte(id: string): Observable<AlerteNaturelle> {
    return this.http.get<AlerteNaturelle>(`${this.api}/${id}/`);
  }

  preremplirCrise(id: string): Observable<PreremplissageCrise> {
    return this.http.get<PreremplissageCrise>(`${this.api}/${id}/crise/`);
  }

  relierCrise(id: string, crise: string): Observable<AlerteNaturelle> {
    return this.http.post<AlerteNaturelle>(`${this.api}/${id}/crise/`, { crise });
  }

  demanderDisponibilites(id: string): Observable<AlerteNaturelle & { campagne_creee: boolean }> {
    return this.http.post<AlerteNaturelle & { campagne_creee: boolean }>(`${this.api}/${id}/disponibilites/`, {});
  }
}
