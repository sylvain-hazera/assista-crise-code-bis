import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  AffectationRotation, ApercuCiblage, BilanRotations, CampagneDisponibilite, CibleCampagne,
  CouvertureCampagne, RotationCampagne,
} from '../shared/models/campagne-disponibilite.model';

/** Campagnes de disponibilité d'une association.
 *
 * Le cycle est en trois temps et le service le reflète : **composer** (create/update sur un
 * brouillon), **vérifier la cible** (`apercu`, qui donne le nombre avant d'écrire à qui que ce
 * soit), puis **envoyer**. Écrire à quatre cents personnes au nom d'une association ne doit pas
 * pouvoir se faire d'un clic depuis un formulaire qu'on vient de remplir. */
@Injectable({ providedIn: 'root' })
export class CampagneDisponibiliteService {

  private url = `${environment.apiUrl}/campagnes-disponibilite`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<CampagneDisponibilite[]> {
    return this.http.get<CampagneDisponibilite[]>(`${this.url}/`);
  }

  getById(id: string): Observable<CampagneDisponibilite> {
    return this.http.get<CampagneDisponibilite>(`${this.url}/${id}/`);
  }

  creer(donnees: Partial<CampagneDisponibilite>): Observable<CampagneDisponibilite> {
    return this.http.post<CampagneDisponibilite>(`${this.url}/`, donnees);
  }

  modifier(id: string, donnees: Partial<CampagneDisponibilite>)
      : Observable<CampagneDisponibilite> {
    return this.http.patch<CampagneDisponibilite>(`${this.url}/${id}/`, donnees);
  }

  /** Fige la liste des destinataires et rend le COMPTE, sans écrire à personne.
   *
   * C'est le garde-fou de toute la fonctionnalité : « 87 bénévoles retenus » est la seule
   * chose qui permette de s'apercevoir qu'un critère ne filtre pas ce qu'on croyait. Un
   * ciblage découvert à l'arrivée du premier mail est un ciblage qu'on ne peut plus
   * corriger. */
  apercu(id: string): Observable<ApercuCiblage> {
    return this.http.post<ApercuCiblage>(`${this.url}/${id}/apercu/`, {});
  }

  envoyer(id: string): Observable<{ envoyes: number; echecs: number;
                                    campagne: CampagneDisponibilite }> {
    return this.http.post<{ envoyes: number; echecs: number;
                            campagne: CampagneDisponibilite }>(
      `${this.url}/${id}/envoyer/`, {});
  }

  /** Relance les SILENCIEUX seulement. Ceux qui ont répondu « aucune disponibilité » ont
   * répondu : les relancer est le meilleur moyen de ne plus être lu. */
  relancer(id: string): Observable<{ envoyes: number; echecs: number; relances: number }> {
    return this.http.post<{ envoyes: number; echecs: number; relances: number }>(
      `${this.url}/${id}/relancer/`, {});
  }

  cibles(id: string): Observable<CibleCampagne[]> {
    return this.http.get<CibleCampagne[]>(`${this.url}/${id}/cibles/`);
  }

  couverture(id: string): Observable<CouvertureCampagne> {
    return this.http.get<CouvertureCampagne>(`${this.url}/${id}/couverture/`);
  }

  rotations(id: string): Observable<{ bilan: BilanRotations | null;
                                      rotations: RotationCampagne[] }> {
    return this.http.get<{ bilan: BilanRotations | null; rotations: RotationCampagne[] }>(
      `${this.url}/${id}/rotations/`);
  }

  /** (Re)génère les tours de garde. Garde les affectations confirmées : sinon chaque recalcul
   * détruirait les décisions de l'encadrement. */
  genererRotations(id: string): Observable<{ bilan: BilanRotations;
                                             rotations: RotationCampagne[] }> {
    return this.http.post<{ bilan: BilanRotations; rotations: RotationCampagne[] }>(
      `${this.url}/${id}/rotations/`, {});
  }

  /** L'encadrement tranche sur une proposition. C'est ce geste qui rend la génération
   * automatique acceptable : rien n'est acquis par le calcul. */
  decider(id: string, affectation: string, decision: 'CONFIRMEE' | 'RETIREE')
      : Observable<AffectationRotation> {
    return this.http.post<AffectationRotation>(
      `${this.url}/${id}/confirmer-affectation/`, { affectation, decision });
  }

  cloturer(id: string): Observable<CampagneDisponibilite> {
    return this.http.post<CampagneDisponibilite>(`${this.url}/${id}/cloturer/`, {});
  }
}