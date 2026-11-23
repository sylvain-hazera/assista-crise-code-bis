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

export interface JalonChronologie { le: string; genre: string; libelle: string; par?: string; id?: string; }

export interface PointSituation { id: string; diffuse_le: string; redige_par: string; texte: string; instantane: Record<string, any>; }

export interface EtatPoints { cadence_h: number | null; prochain: string | null; du: boolean; points: PointSituation[]; }

export interface Retex {
  crise: { nom: string; debut: string | null; fin: string | null };
  retex: { ce_qui_a_marche: string; ce_qui_a_manque: string; ameliorations: string; maj_par: string; maj_le: string } | null;
  decisions: number;
  actions: { total: number; faites: number; faites_en_retard: number; ouvertes: number };
  delais: { dossiers: number; creation_affectation: { mediane_min: number | null; nombre: number };
            affectation_arrivee: { mediane_min: number | null; nombre: number };
            creation_resolution: { mediane_min: number | null; nombre: number } };
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
  chronologie(crise: string): Observable<JalonChronologie[]> {
    return this.http.get<JalonChronologie[]>(`${this.url}/chronologie/`, { params: { crise } });
  }
  ajouterJalon(crise: string, libelle: string): Observable<JalonChronologie> {
    return this.http.post<JalonChronologie>(`${this.url}/chronologie/`, { crise, libelle });
  }
  points(crise: string): Observable<EtatPoints> {
    return this.http.get<EtatPoints>(`${this.url}/points/`, { params: { crise } });
  }
  apercuPoint(crise: string): Observable<Record<string, any>> {
    return this.http.get<Record<string, any>>(`${this.url}/points/apercu/`, { params: { crise } });
  }
  diffuserPoint(crise: string, texte: string): Observable<PointSituation> {
    return this.http.post<PointSituation>(`${this.url}/points/`, { crise, texte });
  }
  cadence(crise: string, heures: number | null): Observable<{ cadence_h: number | null }> {
    return this.http.post<{ cadence_h: number | null }>(`${this.url}/points/cadence/`, { crise, heures });
  }
  retex(crise: string): Observable<Retex> {
    return this.http.get<Retex>(`${this.url}/retex/`, { params: { crise } });
  }
  enregistrerRetex(crise: string, champs: { ce_qui_a_marche: string; ce_qui_a_manque: string; ameliorations: string }): Observable<{ ok: boolean }> {
    return this.http.post<{ ok: boolean }>(`${this.url}/retex/`, { crise, ...champs });
  }

  reprendre(id: string): Observable<ReleveCellule> {
    return this.http.post<ReleveCellule>(`${this.url}/releves/${id}/reprendre/`, {});
  }
}
