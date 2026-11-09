import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  CatalogueReglages, ConfigurationNoeudMeshtastic, DiagnosticLiaisons, TacheAdminMeshtastic,
  TypeTacheAdminMeshtastic,
} from '../shared/models/administration-meshtastic.model';

/** Administration à distance des nœuds Meshtastic.
 *
 * Il n'y a volontairement ni PATCH ni DELETE : le pont rapporte le résultat par une action
 * dédiée côté serveur, qui décide seule du statut et du réessai. Laisser modifier `statut` ou
 * `reponse` depuis un client permettrait de maquiller une opération faite sur un relais. */
@Injectable({ providedIn: 'root' })
export class AdministrationMeshtasticService {

  private url = `${environment.apiUrl}/taches-admin-meshtastic`;
  private urlConfigurations = `${environment.apiUrl}/configurations-noeuds-meshtastic`;

  constructor(private http: HttpClient) {}

  taches(): Observable<TacheAdminMeshtastic[]> {
    return this.http.get<TacheAdminMeshtastic[]>(`${this.url}/`);
  }

  /** `node_num_cible` à null = la passerelle elle-même, le seul cas qui ne demande aucune
   * autorisation préalable sur le nœud visé. */
  creer(data: {
    compagnon: string;
    node_num_cible: number | null;
    type_tache: TypeTacheAdminMeshtastic;
    parametres?: Record<string, unknown> | null;
  }): Observable<TacheAdminMeshtastic> {
    return this.http.post<TacheAdminMeshtastic>(`${this.url}/`, data);
  }

  /** Sections, champs, types et bornes des réglages modifiables. */
  catalogueReglages(): Observable<CatalogueReglages> {
    return this.http.get<CatalogueReglages>(`${this.url}/reglages/`);
  }

  configurations(): Observable<ConfigurationNoeudMeshtastic[]> {
    return this.http.get<ConfigurationNoeudMeshtastic[]>(`${this.urlConfigurations}/`);
  }

  /** Diagnostic des liaisons radio. Calcul lourd (il relit une semaine d'observations) et sans
   * effet de bord : appelé à la demande, jamais en boucle. */
  diagnostic(): Observable<DiagnosticLiaisons> {
    return this.http.get<DiagnosticLiaisons>(`${environment.apiUrl}/contacts-meshtastic/analyse-liaisons/`);
  }
}
