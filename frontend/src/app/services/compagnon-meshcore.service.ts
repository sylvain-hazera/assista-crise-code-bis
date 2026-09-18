import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { CompagnonMeshCore } from '../shared/models/compagnon-meshcore.model';

@Injectable({ providedIn: 'root' })
export class CompagnonMeshCoreService {

  private url = `${environment.apiUrl}/compagnons-meshcore`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<CompagnonMeshCore[]> {
    return this.http.get<CompagnonMeshCore[]>(`${this.url}/`);
  }

  /** GET /api/compagnons-meshcore/envoyables/ — résumé minimal (id/nom/principal, jamais la
   * config réseau) pour choisir un émetteur de DM sans passer par getAll() (bloqué en zone
   * DEMO, voir CompagnonMeshCoreViewSet). */
  envoyables(): Observable<Pick<CompagnonMeshCore, 'id' | 'nom' | 'principal'>[]> {
    return this.http.get<Pick<CompagnonMeshCore, 'id' | 'nom' | 'principal'>[]>(`${this.url}/envoyables/`);
  }

  create(data: Partial<CompagnonMeshCore>): Observable<CompagnonMeshCore> {
    return this.http.post<CompagnonMeshCore>(`${this.url}/`, data);
  }

  update(id: string, data: Partial<CompagnonMeshCore>): Observable<CompagnonMeshCore> {
    return this.http.patch<CompagnonMeshCore>(`${this.url}/${id}/`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}/`);
  }

  /** POST /api/compagnons-meshcore/<id>/envoyer-advert/ — programme l'envoi d'un advert
   * (annonce de présence) par CE companion ; `flood=true` pour une annonce propagée sur le
   * mesh. Exécuté par le pont à son prochain cycle (quelques secondes), pas immédiat. Refusé
   * en zone DEMO. */
  envoyerAdvert(id: string, flood: boolean): Observable<{ id: string; statut: string }> {
    return this.http.post<{ id: string; statut: string }>(`${this.url}/${id}/envoyer-advert/`, { flood });
  }

  /** GET /api/compagnons-meshcore/meilleur-pour-contact/ — suggère le companion le plus adapté
   * pour joindre un contact (chemin le plus court déjà connu, sinon région, sinon principal) —
   * voir core/routage_mesh.py côté backend. Au moins un des deux paramètres requis. */
  meilleurPourContact(pubkeyHex?: string, regionTag?: string): Observable<{
    compagnon_id: string | null; compagnon_nom: string | null; raison: string; region_tag: string | null;
  }> {
    const params: Record<string, string> = {};
    if (pubkeyHex) params['pubkey_hex'] = pubkeyHex;
    if (regionTag) params['region_tag'] = regionTag;
    return this.http.get<{ compagnon_id: string | null; compagnon_nom: string | null; raison: string; region_tag: string | null }>(
      `${this.url}/meilleur-pour-contact/`, { params },
    );
  }
}
