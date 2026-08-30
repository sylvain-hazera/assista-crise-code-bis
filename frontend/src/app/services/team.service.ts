import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Team } from '../shared/models/team.model';  // ← import unique
import { Dossier } from '../shared/models/dossier.model';
import { PointOperationnel } from '../shared/models/point-operationnel.model';

@Injectable({ providedIn: 'root' })
export class TeamService {
  private url = `${environment.apiUrl}/teams`;
  constructor(private http: HttpClient) {}

  getAll():                                Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/`); }
  mesEquipes():                            Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/mes-equipes/`); }
  getById(id: string):                     Observable<Team>    { return this.http.get<Team>(`${this.url}/${id}/`); }
  create(data: Partial<Team>):             Observable<Team>    { return this.http.post<Team>(`${this.url}/`, data); }
  update(id: string, data: Partial<Team>): Observable<Team>    { return this.http.put<Team>(`${this.url}/${id}/`, data); }
  patch(id: string, data: Partial<Team>):  Observable<Team>    { return this.http.patch<Team>(`${this.url}/${id}/`, data); }
  delete(id: string):                      Observable<void>    { return this.http.delete<void>(`${this.url}/${id}/`); }

  inviterMembre(id: string, data: {
    first_name: string; last_name: string; email: string; phone_number: string; role_code: string;
  }): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/inviter-membre/`, data);
  }

  definirMission(id: string, titre: string, criseId?: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/definir-mission/`, { titre, crise_id: criseId });
  }

  assignerRessource(id: string, offerId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/assigner-ressource/`, { offer_id: offerId });
  }

  retirerRessource(id: string, offerId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/retirer-ressource/`, { offer_id: offerId });
  }

  definirDelegation(id: string, institutionId: string, commentaire?: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/definir-delegation/`, { institution_id: institutionId, commentaire });
  }

  retirerDelegation(id: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/retirer-delegation/`, {});
  }

  creerDossier(id: string, data: {
    titre: string; description: string; crise_id: string; priorite?: string;
  }): Observable<Dossier> {
    return this.http.post<Dossier>(`${this.url}/${id}/creer-dossier/`, data);
  }

  lierPoint(id: string, pointId: string): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.url}/${id}/lier-point/`, { point_id: pointId });
  }

  delierPoint(id: string, pointId: string): Observable<void> {
    return this.http.post<void>(`${this.url}/${id}/delier-point/`, { point_id: pointId });
  }

  creerPoint(id: string, data: {
    nom: string; type_id: string; crise_id?: string; adresse?: string; description?: string;
  }): Observable<PointOperationnel> {
    return this.http.post<PointOperationnel>(`${this.url}/${id}/creer-point/`, data);
  }

  rattacherEquipe(parentId: string, equipeId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${parentId}/rattacher-equipe/`, { equipe_id: equipeId });
  }

  detacherEquipe(parentId: string, equipeId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${parentId}/detacher-equipe/`, { equipe_id: equipeId });
  }
}