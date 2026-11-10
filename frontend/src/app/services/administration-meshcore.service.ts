import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { TacheAdminMeshCore, TypeTacheAdminMeshCore } from '../shared/models/administration-meshcore.model';
import { RattachementNoeudRadio } from '../shared/models/rattachement-noeud-radio.model';

/** Administration à distance des répéteurs MeshCore.
 *
 * Ni PATCH ni DELETE sur les tâches, comme pour Meshtastic : le pont rapporte par une action
 * dédiée côté serveur, qui décide seule du statut et du réessai. Laisser modifier `statut` ou
 * `reponse` depuis un client permettrait de maquiller une opération faite sur un relais. */
@Injectable({ providedIn: 'root' })
export class AdministrationMeshCoreService {

  private url = `${environment.apiUrl}/taches-admin-meshcore`;
  private urlRattachements = `${environment.apiUrl}/rattachements-noeuds-radio`;

  constructor(private http: HttpClient) {}

  taches(): Observable<TacheAdminMeshCore[]> {
    return this.http.get<TacheAdminMeshCore[]>(`${this.url}/`);
  }

  creer(data: {
    compagnon: string;
    pubkey_cible: string;
    type_tache: TypeTacheAdminMeshCore;
    parametres?: Record<string, unknown> | null;
  }): Observable<TacheAdminMeshCore> {
    return this.http.post<TacheAdminMeshCore>(`${this.url}/`, data);
  }

  /** Les répéteurs réclamés : seuls ceux dont la preuve est faite acceptent une écriture. */
  rattachements(): Observable<RattachementNoeudRadio[]> {
    return this.http.get<RattachementNoeudRadio[]>(`${this.urlRattachements}/`);
  }

  /** Met la preuve en file : le pont ouvrira une session, ou constatera que le répéteur nous
   * répond parce que notre clé est dans son ACL. Rejouable — un mot de passe changé par son
   * exploitant invalide la preuve d'hier. */
  verifier(id: string): Observable<RattachementNoeudRadio> {
    return this.http.post<RattachementNoeudRadio>(`${this.urlRattachements}/${id}/verifier/`, {});
  }
}
