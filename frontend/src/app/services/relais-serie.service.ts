import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map } from 'rxjs';

import { environment } from '../../environments/environment';
import { IdentiteRadio, Protocole } from '../shared/mesh/pilotes';
import { NomTransport } from '../shared/mesh/transports';
import { EntreePlan } from '../shared/mesh/plan-canaux';

export interface PlanCanaux {
  canaux: EntreePlan[];
  emplacements: number;
  isolee: boolean;
  avertissement: string;
  /** nom du canal sur la radio (minuscules) → identifiant du canal d'Assista-Crise. */
  correspondances?: Record<string, string>;
}

export interface CompagnonRelayable {
  id: string;
  /** `compagnon` = passerelle déjà déclarée ; `noeud` = ma radio personnelle, promue en
   * companion au branchement. Voir core/relais_navigateur.py. */
  genre: 'compagnon' | 'noeud';
  protocole: Protocole;
  nom: string;
  institution_nom: string;
  connexion_type: string;
}

export interface SessionRelais {
  session: string;
  compagnon: string;
  protocole: Protocole;
  nom: string;
  transport: NomTransport;
  ouverte_le: string;
  trames_recues: number;
  trames_envoyees: number;
}

export interface EtatRelais {
  compagnons: CompagnonRelayable[];
  sessions: SessionRelais[];
  secondes_avant_session_morte: number;
}

export interface OuvertureRelais {
  session: string | null;
  compagnon?: string;
  protocole?: Protocole;
  nom?: string;
  cree?: boolean;
  avertissement?: string;
}

/** Comment désigner la radio au serveur. Le cas nominal est l'identité seule. */
export interface DesignationRadio {
  protocole: Protocole;
  identite?: IdentiteRadio;
  compagnon?: string;
  noeud?: string;
  transport?: NomTransport;
}

export interface MessageSortant {
  id: string;
  contenu: string;
  /** MeshCore */
  contact_pubkey_hex?: string;
  /** Meshtastic */
  contact_node_num?: number;
}

/**
 * Le côté serveur du relais : session, files, messages entrants.
 *
 * **Les endpoints de messages sont ceux des ponts Python**, pas des endpoints dédiés : ils
 * existent, ils sont éprouvés, et le serveur n'a rien de nouveau à décoder. Le navigateur est un
 * pont qui se trouve tourner dans un onglet.
 */
@Injectable({ providedIn: 'root' })
export class RelaisSerieService {

  private relais = `${environment.apiUrl}/relais-serie/`;
  private api = environment.apiUrl;

  constructor(private http: HttpClient) {}

  private messages(protocole: Protocole): string {
    return protocole === 'MESHTASTIC' ? `${this.api}/messages-meshtastic` : `${this.api}/messages-meshcore`;
  }

  etat(): Observable<EtatRelais> {
    return this.http.get<EtatRelais>(this.relais);
  }

  /** Ouvre la session, ou bat la mesure si elle est déjà ouverte — c'est la même opération. */
  ouvrirOuBattre(radio: DesignationRadio, tramesRecues = 0, tramesEnvoyees = 0)
      : Observable<OuvertureRelais> {
    return this.http.post<OuvertureRelais>(this.relais, {
      ...radio, trames_recues: tramesRecues, trames_envoyees: tramesEnvoyees,
    });
  }

  fermer(radio: DesignationRadio): Observable<{ session: null }> {
    return this.http.post<{ session: null }>(this.relais, { ...radio, fermer: true });
  }

  /** La file sortante de CETTE radio. Le paramètre est obligatoire côté serveur. */
  aEnvoyer(protocole: Protocole, compagnon: string): Observable<MessageSortant[]> {
    return this.http.get<MessageSortant[]>(`${this.messages(protocole)}/a-envoyer/`,
                                           { params: { compagnon } });
  }

  marquer(protocole: Protocole, id: string, statut: 'ENVOYE' | 'ECHEC', erreur?: string)
      : Observable<unknown> {
    return this.http.patch(`${this.messages(protocole)}/${id}/`,
                           erreur ? { statut, erreur } : { statut });
  }

  deposerDm(protocole: Protocole, compagnon: string, expediteur: string | number, contenu: string)
      : Observable<unknown> {
    const contact = protocole === 'MESHTASTIC'
      ? { contact_node_num: Number(expediteur) }
      : { contact_pubkey_hex: String(expediteur) };
    return this.http.post(`${this.messages(protocole)}/`, {
      compagnon, direction: 'ENTRANT', contenu, ...contact,
    });
  }

  /**
   * Message de canal Meshtastic entendu par la radio. Le companion est nommé dans l'URL et non
   * dans le corps : dans le corps, il CIBLERAIT le message (`MessageCanalMeshtastic.compagnon`).
   */
  deposerCanalMeshtastic(compagnon: string, canal: string, expediteur: number, contenu: string)
      : Observable<unknown> {
    return this.http.post(`${this.api}/messages-canal-meshtastic/`,
                          { direction: 'ENTRANT', canal, contact_node_num: expediteur, contenu },
                          { params: { compagnon } });
  }

  // ══ Plan de canaux d'une passerelle locale (règle du 14/11/2026) ══════════════

  planCanaux(compagnon: string): Observable<PlanCanaux> {
    return this.http.get<PlanCanaux>(`${this.relais}plan-canaux/`, { params: { compagnon } });
  }

  /** Remplace les correspondances de cette radio (tel canal présent EST tel canal d'Assista-Crise). */
  enregistrerCorrespondances(compagnon: string, correspondances: Record<string, string>)
      : Observable<{ correspondances: Record<string, string> }> {
    return this.http.post<{ correspondances: Record<string, string> }>(
      `${this.relais}correspondances-canaux/`, { compagnon, correspondances });
  }

  /** Annonce les canaux de crise et de commune sur Fr_EMCOM, par cette passerelle seulement. */
  annoncer(compagnon: string): Observable<{ annonce: string | null; raison?: string }> {
    return this.http.post<{ annonce: string | null; raison?: string }>(
      `${this.relais}annoncer/`, { compagnon });
  }

  /** La file d'un canal pour cette passerelle. Pour une passerelle isolée, le serveur note la
   * diffusion à la prise : rien à confirmer ensuite. */
  aEnvoyerCanalMeshtastic(compagnon: string, canal: string)
      : Observable<{ id: string; contenu: string }[]> {
    return this.http.get<{ id: string; contenu: string }[]>(
      `${this.api}/messages-canal-meshtastic/a-envoyer/`, { params: { compagnon, canal } });
  }

  /** Statut global « envoyé » — utile pour une passerelle ouverte au réseau ; le companion est
   * nommé dans l'URL, c'est ce qui permet au relais de marquer un message non ciblé. */
  marquerCanalMeshtastic(compagnon: string, id: string): Observable<unknown> {
    return this.http.patch(`${this.api}/messages-canal-meshtastic/${id}/`, { statut: 'ENVOYE' },
                           { params: { compagnon } });
  }

  /** Nom → identifiant des canaux Meshtastic déclarés. Sans PSK : l'API ne la renvoie jamais. */
  canauxMeshtastic(): Observable<Map<string, string>> {
    return this.http.get<{ id: string; nom: string }[] | { results: { id: string; nom: string }[] }>(
      `${this.api}/canaux-meshtastic/`,
    ).pipe(map(r => {
      const liste = Array.isArray(r) ? r : r.results || [];
      return new Map(liste.map(c => [c.nom.toLowerCase(), c.id] as [string, string]));
    }));
  }
}
