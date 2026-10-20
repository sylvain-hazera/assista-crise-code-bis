import type { MultiPolygon, Polygon } from 'geojson';
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { NiveauObserve, SimulationAdresses, SimulationInondation, SimulationRuissellement } from '../shared/models/simulation-inondation.model';

@Injectable({ providedIn: 'root' })
export class SimulationInondationService {

  private url = `${environment.apiUrl}/simulation-inondation`;

  constructor(private http: HttpClient) {}

  /** GET /api/simulation-inondation/<commune_code>/ — calcule (ou relit le cache de) la grille
   * d'altitude et les paliers d'inondation de la commune -- TOUJOURS borné (grille plafonnée),
   * indépendant du chargement des adresses (voir chargerAdresses). Premier appel non mis en
   * cache : quelques secondes à quelques minutes, les suivants sont instantanés. `recalculer`
   * force un recalcul complet même si déjà en cache. */
  simuler(communeCode: string, recalculer = false): Observable<SimulationInondation> {
    const params = recalculer ? '?recalculer=1' : '';
    return this.http.get<SimulationInondation>(`${this.url}/${communeCode}/${params}`);
  }

  /** GET /api/simulation-inondation/<commune_code>/adresses/ — scan BAN + seuil d'inondation
   * par adresse. Déclenché explicitement (jamais automatique à la sélection d'une commune) :
   * peut prendre bien plus longtemps sur une grande ville, voire échouer clairement si elle est
   * vraiment trop grande (voir core/inondation.py:SEUIL_VOIES_MAX) -- sans affecter `simuler`. */
  chargerAdresses(communeCode: string, recalculer = false): Observable<SimulationAdresses> {
    const params = recalculer ? '?recalculer=1' : '';
    return this.http.get<SimulationAdresses>(`${this.url}/${communeCode}/adresses/${params}`);
  }

  /** GET /api/simulation-inondation/<commune_code>/ruissellement/ — accumulation de flux
   * (crue éclair) sur la même grille d'altitude. TOUJOURS bornée comme `simuler`, jamais comme
   * `chargerAdresses` -- se lance automatiquement au premier passage en mode ruissellement. */
  chargerRuissellement(communeCode: string, recalculer = false): Observable<SimulationRuissellement> {
    const params = recalculer ? '?recalculer=1' : '';
    return this.http.get<SimulationRuissellement>(`${this.url}/${communeCode}/ruissellement/${params}`);
  }

  /** GET /api/simulation-inondation/<commune_code>/niveau-observe/ — dernier niveau d'eau
   * RÉELLEMENT mesuré (Hub'Eau, station la plus proche), sur le MÊME référentiel NGF que le
   * curseur de `simuler` -- repère informatif seulement, jamais de curseur/calcul piloté par
   * cette donnée. `disponible: false` si aucune station exploitable à proximité (jamais une
   * erreur HTTP). */
  niveauObserve(communeCode: string): Observable<NiveauObserve> {
    return this.http.get<NiveauObserve>(`${this.url}/${communeCode}/niveau-observe/`);
  }

  /** GET /api/simulation-inondation/<commune_code>/georisques/?couche=… — zones inondables
   * officielles (Géorisques, vecteur) de la commune ; `geometrie` null = aucune zone pour ce
   * scénario (commune hors Territoire à Risque Important d'Inondation). */
  zonesGeorisques(communeCode: string, couche: string): Observable<{ couche: string; libelle: string; geometrie: Polygon | MultiPolygon | null }> {
    return this.http.get<{ couche: string; libelle: string; geometrie: Polygon | MultiPolygon | null }>(
      `${this.url}/${communeCode}/georisques/`, { params: { couche } },
    );
  }
}
