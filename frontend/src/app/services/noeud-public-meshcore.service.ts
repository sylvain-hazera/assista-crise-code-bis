import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import type { FeatureCollection, Point } from 'geojson';

import { environment } from '../../environments/environment';
import { ResumeCartographiePublique } from '../shared/models/noeud-public-meshcore.model';

/** Cartographie du réseau MeshCore public, importée d'une instance CoreScope.
 *
 * Lecture seule : ces lignes s'importent (`manage.py importer_cartographie_meshcore`), elles ne
 * se saisissent pas — les modifier à la main créerait une divergence avec l'instance d'origine
 * que rien ne signalerait. Il n'y a donc volontairement ni `create` ni `delete` ici. */
@Injectable({ providedIn: 'root' })
export class NoeudPublicMeshCoreService {

  private url = `${environment.apiUrl}/noeuds-publics-meshcore`;

  constructor(private http: HttpClient) {}

  /** Le GeoJSON entier. Plusieurs milliers de points : à charger à la demande, jamais au
   * démarrage d'une page. */
  geojson(options: { role?: string; actifsSeulement?: boolean } = {}): Observable<FeatureCollection<Point>> {
    const params: Record<string, string> = {};
    if (options.role) params['role'] = options.role;
    if (options.actifsSeulement) params['actifs'] = '1';
    return this.http.get<FeatureCollection<Point>>(`${this.url}/geojson/`, { params });
  }

  resume(): Observable<ResumeCartographiePublique> {
    return this.http.get<ResumeCartographiePublique>(`${this.url}/resume/`);
  }
}
