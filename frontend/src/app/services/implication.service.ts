import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ImplicationInstitution, ImplicationInstitutionPayload } from '../shared/models/implication.model';

@Injectable({ providedIn: 'root' })
export class ImplicationService {
  private apiUrl = `${environment.apiUrl}/implications-crises`;

  constructor(private http: HttpClient) {}

  // `institution`/`actif` optionnels (?institution=&actif=, voir filterset_fields côté
  // backend) — utilisé par VueMairieComponent pour peupler le sélecteur de crise du journal
  // de bord (crises actives de MON institution uniquement).
  getAll(options?: { institution?: string; actif?: boolean }): Observable<ImplicationInstitution[]> {
    let params = new HttpParams();
    if (options?.institution) params = params.set('institution', options.institution);
    if (options?.actif !== undefined) params = params.set('actif', String(options.actif));
    return this.http.get<ImplicationInstitution[]>(`${this.apiUrl}/`, { params });
  }

  getByCrise(criseId: string): Observable<ImplicationInstitution[]> {
    return this.http.get<ImplicationInstitution[]>(`${this.apiUrl}/`, { params: { crise: criseId } });
  }

  create(payload: ImplicationInstitutionPayload): Observable<ImplicationInstitution> {
    return this.http.post<ImplicationInstitution>(`${this.apiUrl}/`, payload);
  }

  update(id: string, payload: Partial<ImplicationInstitutionPayload>): Observable<ImplicationInstitution> {
    return this.http.patch<ImplicationInstitution>(`${this.apiUrl}/${id}/`, payload);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}/`);
  }

  /** `communes` limite l'acceptation à une partie de la zone de la crise. Omis = toute la
   * zone. Le serveur refuse toute commune hors du périmètre du donneur : on ne donne pas de
   * droits sur une commune dont on n'a pas soi-même les droits. */
  valider(id: string, communes?: string[]): Observable<ImplicationInstitution> {
    const corps = communes ? { communes } : {};
    return this.http.post<ImplicationInstitution>(`${this.apiUrl}/${id}/valider/`, corps);
  }

  /** Ce que l'appelant a le droit d'accorder sur cette crise — calculé par le serveur et
   * jamais déduit ici : la liste EST la règle d'accès. */
  zoneDelegable(id: string): Observable<ZoneDelegable> {
    return this.http.get<ZoneDelegable>(`${this.apiUrl}/${id}/zone-delegable/`);
  }

  refuser(id: string): Observable<ImplicationInstitution> {
    return this.http.post<ImplicationInstitution>(`${this.apiUrl}/${id}/refuser/`, {});
  }
}

/** Communes qu'une collectivité peut accorder à une institution sur une crise donnée. */
export interface ZoneDelegable {
  communes: { code: string; nom: string }[];
  /** Vrai seulement si l'appelant couvre toute la zone de la crise (un conseil départemental,
   * typiquement) — c'est ce qui autorise le raccourci « toute la crise ». */
  couvre_toute_la_crise: boolean;
  deja_accordees: string[];
}
