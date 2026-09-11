import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { MessageMeshLog } from '../shared/models/canal-meshcore.model';

/** DM privés régulateur <-> équipe via MeshCore — cloisonnés par équipe côté serveur (voir
 * MessageMeshLogViewSet.get_queryset : seuls le leader et le régulateur de l'équipe concernée
 * les voient). Cette page ne fait qu'appeler l'API, le cloisonnement réel est côté backend. */
@Injectable({ providedIn: 'root' })
export class MessageMeshService {

  private url = `${environment.apiUrl}/messages-meshcore`;

  constructor(private http: HttpClient) {}

  getPourEquipe(equipeId: string): Observable<MessageMeshLog[]> {
    return this.http.get<MessageMeshLog[]>(`${this.url}/`, { params: { equipe: equipeId } });
  }

  /** Fil de discussion avec UNE personne précise (son nœud), distinct de getPourEquipe qui
   * mélangerait les messages de tous les membres équipés d'une même équipe. */
  getPourContact(pubkeyHex: string): Observable<MessageMeshLog[]> {
    return this.http.get<MessageMeshLog[]>(`${this.url}/`, { params: { contact_pubkey_hex: pubkeyHex } });
  }

  envoyer(compagnonId: string, contactPubkeyHex: string, contenu: string): Observable<MessageMeshLog> {
    return this.http.post<MessageMeshLog>(`${this.url}/`, {
      compagnon: compagnonId, direction: 'SORTANT', contact_pubkey_hex: contactPubkeyHex, contenu,
    });
  }
}
