import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export type StatutAction = 'A_FAIRE' | 'EN_COURS' | 'FAIT' | 'ABANDONNEE';

/** backend/core/views_cellule.py */
export interface ActionCellule {
  id: string;
  crise: string;
  decision: string | null;
  decision_texte?: string | null;
  intitule: string;
  responsable: string | null;
  responsable_nom: string;
  responsable_libre: string;
  equipe: string | null;
  equipe_nom: string | null;
  echeance: string | null;
  statut: StatutAction;
  statut_libelle: string;
  faite_le: string | null;
  commentaire: string;
  en_retard: boolean;
}

export interface DecisionCellule {
  id: string;
  crise: string;
  texte: string;
  auteur_nom: string;
  decidee_le: string;
  actions: ActionCellule[];
}

export interface InstantaneReleve {
  le: string;
  chiffres: { dossiers_ouverts: number; dossiers_urgents: number; dossiers_sans_equipe: number; equipes_engagees: number };
  decisions: { le: string; texte: string }[];
  actions_ouvertes: { intitule: string; responsable: string; echeance: string | null; statut: string; en_retard: boolean }[];
  alertes_terrain: { type: string; auteur: string; le: string; texte: string }[];
}

export interface ReleveCellule {
  id: string;
  redigee_par_nom: string;
  redigee_le: string;
  instantane: InstantaneReleve;
  points_vigilance: string;
  reprise_par_nom: string | null;
  reprise_le: string | null;
}

export interface NouvelleAction {
  intitule: string;
  responsable?: string | null;
  responsable_libre?: string;
  echeance?: string | null;
}

@Injectable({ providedIn: 'root' })
export class CellulePilotageService {
  private readonly url = `${environment.apiUrl}/cellule`;

  constructor(private http: HttpClient) {}

  decisions(crise: string): Observable<DecisionCellule[]> {
    return this.http.get<DecisionCellule[]>(`${this.url}/decisions/`, { params: { crise } });
  }
  decider(crise: string, texte: string, actions: NouvelleAction[]): Observable<DecisionCellule> {
    return this.http.post<DecisionCellule>(`${this.url}/decisions/`, { crise, texte, actions });
  }
  actions(crise: string, miennes = false): Observable<ActionCellule[]> {
    return this.http.get<ActionCellule[]>(`${this.url}/actions/`, { params: miennes ? { crise, miennes: '1' } : { crise } });
  }
  modifierAction(id: string, changement: Partial<ActionCellule>): Observable<ActionCellule> {
    return this.http.patch<ActionCellule>(`${this.url}/actions/${id}/`, changement);
  }
  releves(crise: string): Observable<ReleveCellule[]> {
    return this.http.get<ReleveCellule[]>(`${this.url}/releves/`, { params: { crise } });
  }
  apercuReleve(crise: string): Observable<InstantaneReleve> {
    return this.http.get<InstantaneReleve>(`${this.url}/releves/apercu/`, { params: { crise } });
  }
  rediger(crise: string, points_vigilance: string): Observable<ReleveCellule> {
    return this.http.post<ReleveCellule>(`${this.url}/releves/`, { crise, points_vigilance });
  }
  reprendre(id: string): Observable<ReleveCellule> {
    return this.http.post<ReleveCellule>(`${this.url}/releves/${id}/reprendre/`, {});
  }
}
