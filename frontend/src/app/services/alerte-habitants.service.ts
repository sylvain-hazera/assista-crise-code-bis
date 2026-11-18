import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** Un canal d'alerte : s'il est utilisable pour cette collectivité, et combien de personnes il
 * peut joindre. `joignables` est `null` quand nous ne pouvons pas le savoir (IntraMuros). */
export interface CanalAlerte {
  code: string; libelle: string; detail: string; defaut: boolean;
  disponible: boolean; motif: string; joignables: number | null;
}

export interface BilanCanal { partis: number; echecs: number; note: string; }

/** Un moyen d'alerte de terrain, décrit dans « Alerte de la population » : sirène, véhicule,
 * personne relais, porte-à-porte. Ici on le DÉCLENCHE ; là-bas on le décrit. */
export interface MoyenTerrain {
  id: string; type: string; type_libelle: string; description: string; zone_nom: string;
  personne: string; personne_telephone: string;
  /** Vrai : le message peut lui être envoyé par SMS pour qu'il le relaie. */
  peut_relayer: boolean; motif_relais: string;
  /** Ce qu'on fait quand on le déclenche : la fiche de la commune, sinon la fiche type. */
  consignes?: string; fiche_propre?: boolean;
  pieces: number;
}

/** Ce qu'une alerte a demandé sur le terrain, et ce qu'il en est advenu. */
export interface ActionTerrain { type_libelle: string; description: string; personne: string; relais: string; note: string; }

export interface AlerteHabitants {
  id: string; titre: string; message: string; urgent: boolean;
  crise: string | null; crise_nom: string | null;
  canaux: string[]; bilan: Record<string, BilanCanal>; destinataires: number;
  terrain?: ActionTerrain[];
  auteur: string; date: string;
}

export interface EtatAlertes {
  apercu: { destinataires: number; canaux: CanalAlerte[]; terrain?: MoyenTerrain[] };
  par_defaut: string[];
  alertes: AlerteHabitants[];
}

/** L'alerte de la commune à ses habitants (core/alerte_population.py côté serveur). */
@Injectable({ providedIn: 'root' })
export class AlerteHabitantsService {
  private url = `${environment.apiUrl}/alertes-population/`;

  constructor(private http: HttpClient) {}

  /** `crise` : pour compter aussi les personnes touchées par cette crise. */
  etat(crise?: string): Observable<EtatAlertes> {
    return this.http.get<EtatAlertes>(this.url, { params: crise ? { crise } : {} });
  }

  envoyer(alerte: { titre: string; message: string; canaux: string[]; urgent: boolean; crise?: string;
                    terrain?: string[]; relayer?: string[] }): Observable<AlerteHabitants> {
    return this.http.post<AlerteHabitants>(this.url, alerte);
  }

  // ── Côté habitant : recevoir les alertes d'une collectivité, parce qu'on l'a demandé. ──

  /** Les collectivités dont je reçois les alertes. */
  mesAbonnements(): Observable<AbonnementAlertes[]> {
    return this.http.get<AbonnementAlertes[]>(`${this.url}abonnement/`);
  }

  /** Communes et intercommunalités dont le nom contient `q` (deux lettres au moins). */
  chercherCollectivites(q: string): Observable<{ id: string; nom: string }[]> {
    return this.http.get<{ id: string; nom: string }[]>(`${this.url}collectivites/`, { params: { q } });
  }

  sAbonner(institution: string): Observable<AbonnementAlertes> {
    return this.http.post<AbonnementAlertes>(`${this.url}abonnement/`, { institution });
  }

  seDesabonner(institution: string): Observable<void> {
    return this.http.delete<void>(`${this.url}abonnement/`, { body: { institution } });
  }
}

export interface AbonnementAlertes { institution: string; institution_nom: string; }
