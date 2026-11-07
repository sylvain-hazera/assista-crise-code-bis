import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { FeatureCollection, Point } from 'geojson';

import { environment } from '../../environments/environment';
import {
  BilanLiaison, CalibrationRadio, CouvertureRadioSite,
} from '../shared/models/couverture-radio.model';

/** Propagation radio sur le relief. */
@Injectable({ providedIn: 'root' })
export class CouvertureRadioService {

  private url = `${environment.apiUrl}/couvertures-radio`;
  private urlCalibrations = `${environment.apiUrl}/calibrations-radio`;

  constructor(private http: HttpClient) {}

  couvertures(): Observable<CouvertureRadioSite[]> {
    return this.http.get<CouvertureRadioSite[]>(`${this.url}/`);
  }

  /** Met en file le calcul : réponse 202, le résultat arrive dans la liste. */
  calculer(data: {
    nom: string; latitude: number; longitude: number;
    hauteur_antenne_m?: number; hauteur_cible_m?: number; preset?: string;
    puissance_dbm?: number; rayon_max_km?: number; nb_rayons?: number; pas_m?: number;
    node_num?: number | null;
  }): Observable<CouvertureRadioSite> {
    return this.http.post<CouvertureRadioSite>(`${this.url}/calculer/`, data);
  }

  /** Points atteints, pour la carte. Des points et non un contour : une couverture radio est
   * trouée, un contour déclarerait couvert ce qu'il englobe. */
  geojson(id: string): Observable<FeatureCollection<Point, { marge_db: number; distance_m: number }>> {
    return this.http.get<FeatureCollection<Point, { marge_db: number; distance_m: number }>>(
      `${this.url}/${id}/geojson/`,
    );
  }

  /** Bilan point à point, calculé tout de suite. */
  analyserLiaison(data: {
    lat_a: number; lon_a: number; lat_b: number; lon_b: number;
    hauteur_a_m?: number; hauteur_b_m?: number; preset?: string; puissance_dbm?: number;
  }): Observable<BilanLiaison> {
    return this.http.post<BilanLiaison>(`${this.url}/analyser-liaison/`, data);
  }

  calibrations(): Observable<CalibrationRadio[]> {
    return this.http.get<CalibrationRadio[]>(`${this.urlCalibrations}/`);
  }

  calibrer(): Observable<{ statut: string }> {
    return this.http.post<{ statut: string }>(`${this.urlCalibrations}/calculer/`, {});
  }
}
