import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** Ce qu'il manque au plan, avec l'écran où le compléter. Calculé par le serveur à chaque
 * lecture : c'est la même liste qui ouvre le document édité. */
export interface ManquePcs { partie: string; message: string; ou: string; route: string; }

export interface RevisionPcs { date: string; objet: string; auteur: string; }

/** Un paragraphe du plan : son écran, à quoi il sert une fois la crise ouverte, et son état.
 * `A_PART` : il ne se compte pas d'ici (le registre des personnes vulnérables a ses droits). */
export interface ParagraphePcs {
  numero: string; titre: string; route: string; reutilise: string;
  nombre: number | null; etat: 'RENSEIGNE' | 'VIDE' | 'A_PART';
}

/** La partie administrative du plan (les seuls champs que rien d'autre ne porte) et l'état de
 * ce que le document reprendra du reste de l'application. */
export interface DossierPcs {
  institution: string;
  institution_nom: string;
  commune: { nom: string; code: string; population: number | null };
  arrete_numero: string;
  arrete_date: string | null;
  lieu_pcc: string;
  lieu_pcc_repli: string;
  modalites_activation: string;
  paragraphes: ParagraphePcs[];
  /** Équipe permanente désignée par l'organigramme pour chaque point proposé au démarrage d'une
   * crise (code du type de point -> équipe). L'équipe de la crise en reprend les membres. */
  equipes_par_point: Record<string, { id: string; nom: string }>;
  revisions: RevisionPcs[];
  manques: ManquePcs[];
  contenu: {
    risques: number; sites_sensibles: number; dispositifs: number; missions_types: number;
    interlocuteurs: number; membres: number; equipes: number; points: number;
  };
}

export type PartieAdministrative = Pick<DossierPcs,
  'arrete_numero' | 'arrete_date' | 'lieu_pcc' | 'lieu_pcc_repli' | 'modalites_activation'>;

/** Le dossier du plan communal de sauvegarde (core/views_pcs.py côté serveur). Le document
 * lui-même n'est jamais stocké : il est construit à chaque demande depuis les données du jour. */
@Injectable({ providedIn: 'root' })
export class DossierPcsService {
  private url = `${environment.apiUrl}/dossier-pcs`;

  constructor(private http: HttpClient) {}

  lire(): Observable<DossierPcs> {
    return this.http.get<DossierPcs>(`${this.url}/`);
  }

  enregistrer(partie: Partial<PartieAdministrative>): Observable<DossierPcs> {
    return this.http.patch<DossierPcs>(`${this.url}/`, partie);
  }

  ajouterRevision(objet: string, date?: string): Observable<DossierPcs> {
    return this.http.post<DossierPcs>(`${this.url}/revisions/`, date ? { objet, date } : { objet });
  }

  /** `fondIgn` : les cartes d'annexe posées sur le Plan IGN plutôt qu'en schéma. */
  document(fondIgn = false): Observable<Blob> {
    const params: Record<string, string> = fondIgn ? { fond: 'ign' } : {};
    return this.http.get(`${this.url}/document/`, { responseType: 'blob', params });
  }

  /** Le document d'information des habitants sur les risques : public, sans donnée personnelle. */
  dicrim(): Observable<Blob> {
    return this.http.get(`${this.url}/dicrim/`, { responseType: 'blob' });
  }
}
