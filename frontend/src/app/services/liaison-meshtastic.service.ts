import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { FeatureCollection, LineString } from 'geojson';

import { environment } from '../../environments/environment';

/** Propriétés portées par chaque trait de liaison (voir LiaisonMeshtasticViewSet.geojson). */
export interface ProprietesLiaison {
  emetteur: number;
  recepteur: number;
  snr: number | null;
  source: 'RF' | 'VOISINAGE' | 'TRACEROUTE';
  nombre: number;
  distance_km: number | null;
}

/** Liaisons radio mesurées — alimentées par le pont Meshtastic, jamais saisies à la main. */
@Injectable({ providedIn: 'root' })
export class LiaisonMeshtasticService {

  private url = `${environment.apiUrl}/liaisons-meshtastic`;

  constructor(private http: HttpClient) {}

  /** Traits prêts pour la carte. `depuisHeures` est borné à 30 jours par le serveur. */
  geojson(depuisHeures = 24): Observable<FeatureCollection<LineString, ProprietesLiaison>> {
    return this.http.get<FeatureCollection<LineString, ProprietesLiaison>>(
      `${this.url}/geojson/`, { params: { depuis_heures: String(depuisHeures) } },
    );
  }
}
