import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { MessageMeshtasticLog } from '../shared/models/canal-meshtastic.model';

/** DM privés régulateur <-> équipe via Meshtastic — cloisonnés par équipe côté serveur, même
 * principe que MessageMeshService (MeshCore). Contrairement à MeshCore, un DM Meshtastic est
 * chiffré avec la PSK d'un CANAL partagé (pas une clé propre au destinataire) : il faut donc
 * préciser lequel à l'envoi. */
@Injectable({ providedIn: 'root' })
export class MessageMeshtasticService {

  private url = `${environment.apiUrl}/messages-meshtastic`;

  constructor(private http: HttpClient) {}

  getPourEquipe(equipeId: string): Observable<MessageMeshtasticLog[]> {
    return this.http.get<MessageMeshtasticLog[]>(`${this.url}/`, { params: { equipe: equipeId } });
  }

  getPourContact(nodeNum: number): Observable<MessageMeshtasticLog[]> {
    return this.http.get<MessageMeshtasticLog[]>(`${this.url}/`, { params: { contact_node_num: String(nodeNum) } });
  }

  /** canalId : null quand le destinataire a une clé publique connue (PKI) — le canal n'a alors
   * aucun rôle dans le chiffrement ni la conversation, le pont en choisit un automatiquement
   * pour le seul besoin technique du topic MQTT (voir CanalMeshtastic.principal). */
  envoyer(compagnonId: string, canalId: string | null, contactNodeNum: number, contenu: string): Observable<MessageMeshtasticLog> {
    return this.http.post<MessageMeshtasticLog>(`${this.url}/`, {
      compagnon: compagnonId, canal: canalId, direction: 'SORTANT', contact_node_num: contactNodeNum, contenu,
    });
  }
}
