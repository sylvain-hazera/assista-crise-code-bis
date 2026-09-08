import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { PointOperationnel, PointOperationnelPayload, PointEquipeResponse, CentreAccueilPublic, VueOperationnelle } from '../shared/models/point-operationnel.model';
import { AffectationPointBenevole, InviterBenevolePayload, InviterBenevoleResponse, ValiderBenevolePayload } from '../shared/models/affectation-point-benevole.model';
import { CandidatsBenevolesParams, CandidatsBenevolesResponse } from '../shared/models/candidat-benevole.model';
import { DemandeTransfertItem } from '../shared/models/materiel-point.model';

@Injectable({ providedIn: 'root' })
export class PointOperationnelService {
  private apiUrl = `${environment.apiUrl}/points-operationnels`;

  constructor(private http: HttpClient) {}

  getAll(): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/`);
  }

  getByCrise(criseId: string): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/`, { params: { crise: criseId } });
  }

  /** GET /api/points-operationnels/centres_accueil/?crise=<id> — endpoint public (AllowAny),
   * à champs restreints, utilisé par le formulaire public "je suis en sécurité" (aucune
   * session requise, contrairement à getByCrise/getAll ci-dessus). */
  getCentresAccueilPublics(criseId: string): Observable<CentreAccueilPublic[]> {
    return this.http.get<CentreAccueilPublic[]>(`${this.apiUrl}/centres_accueil/`, { params: { crise: criseId } });
  }

  /** GET /api/points-operationnels/carte_publique/ — endpoint public (AllowAny), toutes crises
   * confondues (contrairement à getCentresAccueilPublics, scopé à une seule crise) : alimente
   * les calques publics de la carte d'accueil (centres d'accueil, postes de secours). */
  getCartePublique(): Observable<CentreAccueilPublic[]> {
    return this.http.get<CentreAccueilPublic[]>(`${this.apiUrl}/carte_publique/`);
  }

  /** Points dont je suis responsable, leader d'équipe ou membre — toutes crises confondues
   * (page "Centres", filtre "Mes centres"). */
  getMine(): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/`, { params: { mine: 'true' } });
  }

  /** GET /api/points-operationnels/vue_mairie/ — points opérationnels de la commune de
   * l'institution de l'utilisateur appelant (réservé institutionnel). */
  vueMairie(): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/vue_mairie/`);
  }

  /** Centres "prévus" : créés hors contexte crise (crise vide), en amont d'une crise réelle —
   * page "Centres", 3e mode de la liste. */
  getPrevus(): Observable<PointOperationnel[]> {
    return this.http.get<PointOperationnel[]>(`${this.apiUrl}/`, { params: { crise__isnull: 'true' } });
  }

  create(payload: PointOperationnelPayload): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.apiUrl}/`, payload);
  }

  update(id: string, payload: Partial<PointOperationnelPayload>): Observable<PointOperationnel> {
    return this.http.patch<PointOperationnel>(`${this.apiUrl}/${id}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  getEquipe(id: string): Observable<PointEquipeResponse> {
    return this.http.get<PointEquipeResponse>(`${this.apiUrl}/${id}/equipe/`);
  }

  inviterBenevole(id: string, payload: InviterBenevolePayload): Observable<InviterBenevoleResponse> {
    return this.http.post<InviterBenevoleResponse>(`${this.apiUrl}/${id}/inviter-benevole/`, payload);
  }

  /** Validation (ou refus) par le régulateur d'un créneau bénévole préalablement accepté par
   * ce dernier (statut EN_VALIDATION) — voir PointOperationnelViewSet.valider_benevole. */
  validerBenevole(id: string, payload: ValiderBenevolePayload): Observable<AffectationPointBenevole> {
    return this.http.post<AffectationPointBenevole>(`${this.apiUrl}/${id}/valider-benevole/`, payload);
  }

  getCandidatsBenevoles(id: string, params: CandidatsBenevolesParams): Observable<CandidatsBenevolesResponse> {
    let httpParams = new HttpParams();
    if (params.search) httpParams = httpParams.set('search', params.search);
    if (params.ordering) httpParams = httpParams.set('ordering', params.ordering);
    if (params.page) httpParams = httpParams.set('page', params.page);
    if (params.page_size) httpParams = httpParams.set('page_size', params.page_size);
    (params.creneaux ?? []).forEach(c => httpParams = httpParams.append('creneaux', c));
    (params.competences ?? []).forEach(c => httpParams = httpParams.append('competences', c));

    return this.http.get<CandidatsBenevolesResponse>(`${this.apiUrl}/${id}/candidats-benevoles/`, { params: httpParams });
  }

  /** POST /api/points-operationnels/{id}/demander-transfert/ — id = point SOURCE (celui dont
   * le stock a été repéré en trop). Notifie (Notification + email) tous ses responsables. */
  demanderTransfert(
    pointSourceId: string, destinationPointId: string, items: DemandeTransfertItem[], message?: string
  ): Observable<{ notifies: number }> {
    return this.http.post<{ notifies: number }>(`${this.apiUrl}/${pointSourceId}/demander-transfert/`, {
      destination_point_id: destinationPointId, items, message,
    });
  }

  /** GET /api/points-operationnels/{id}/vue-operationnelle/ — équipes gestionnaires/de
   * ravitaillement (effectif + matériel) et civils accueillis. */
  getVueOperationnelle(id: string): Observable<VueOperationnelle> {
    return this.http.get<VueOperationnelle>(`${this.apiUrl}/${id}/vue-operationnelle/`);
  }
}
