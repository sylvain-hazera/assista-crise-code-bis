import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import type { FeatureCollection, Point } from 'geojson';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Une ligne d'état par bouton de l'accueil `/ouvert`. */
export interface ResumeOuvert {
  cellules_orageuses: number;
  repeteurs: number;
  kp: number | null;
  g: number | null;
  g_libelle: string | null;
  occupation_canal: number | null;
  couvertures: number;
}

export interface CouvertureOuverte {
  id: string; nom: string; calibre: boolean; preset: string; surface_estimee_km2: number | null; date_calcul: string | null;
}

export interface PrevisionHf { date: string | null; g: number | null; r_mineur_pct: number | null; r_majeur_pct: number | null }

export interface ResumeHf {
  kp: number | null; kp_le: string | null; kp_max_prevu_3j: number | null; flux_10cm: number | null;
  eruption_max_24h: { classe: string; le: string } | null;
  g: number | null; r: number | null; g_libelle: string | null; r_libelle: string | null;
  effet_g: string | null; effet_r: string | null; prevision: PrevisionHf[]; releve_le: string;
}

export interface Propagation {
  hf: ResumeHf | null;
  hf_source: { source: string; releve_le: string | null; perime: boolean };
  tropo: {
    nos_estimations: boolean; source: string; calcul: string | null;
    coins: [number, number][]; limite: string;
    legende: { classe: number; libelle: string; effet: string; couleur: string }[];
    echeances: { echeance: string; classe_max: number; part_conduit_pct: number }[];
  };
}

export interface PointSerie { t: string; v: number }

export interface SanteReseau {
  calcule_le: string;
  meshtastic: {
    passerelles: 'aucune' | 'une' | 'plusieurs';
    occupation_canal: PointSerie[]; occupation_actuelle: number | null; temps_antenne_tx: PointSerie[];
    paquets_par_heure: PointSerie[]; par_type: { type: string; nombre: number }[];
  };
  meshcore: {
    trames_24h: number; par_type: { type: string; trames: number }[]; courbe: unknown[];
    repeteurs_publics: number; repeteurs_vus_24h: number;
  };
}

export interface BilanOuvert {
  marge_db: number; distance_m: number; diffraction_db: number;
  obstacle: { distance_km: number; hauteur_m: number } | null;
  parametres: { preset: string; calibre: boolean; puissance_dbm: number };
  verdict: 'passe' | 'passe de justesse' | 'ne passe pas';
}

/** La partie publique « pour les copains » (28/11/2026) : rien que des points d'accès sans
 * connexion (backend/core/views_carte_ouverte.py). */
@Injectable({ providedIn: 'root' })
export class CarteOuverteService {
  private readonly url = `${environment.apiUrl}/carte-ouverte`;

  constructor(private http: HttpClient) {}

  resume(): Observable<ResumeOuvert> { return this.http.get<ResumeOuvert>(`${this.url}/`); }

  radio(): Observable<FeatureCollection<Point>> { return this.http.get<FeatureCollection<Point>>(`${this.url}/radio/`); }

  couvertures(): Observable<CouvertureOuverte[]> { return this.http.get<CouvertureOuverte[]>(`${this.url}/radio/couvertures/`); }

  couverture(id: string): Observable<FeatureCollection<Point, { marge_db: number }>> {
    return this.http.get<FeatureCollection<Point, { marge_db: number }>>(`${this.url}/radio/couvertures/${id}/geojson/`);
  }

  sante(): Observable<SanteReseau> { return this.http.get<SanteReseau>(`${this.url}/radio/sante/`); }

  propagation(): Observable<Propagation> { return this.http.get<Propagation>(`${this.url}/propagation/`); }

  imageTropo(echeance: string): string {
    return `${this.url}/propagation/tropo/image/?echeance=${encodeURIComponent(echeance)}`;
  }

  liaison(corps: { lat_a: number; lon_a: number; lat_b: number; lon_b: number; preset: string; hauteur_a_m: number; hauteur_b_m: number }):
    Observable<BilanOuvert> {
    return this.http.post<BilanOuvert>(`${this.url}/radio/liaison/`, corps);
  }
}
