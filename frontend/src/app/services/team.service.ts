import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Team } from '../shared/models/team.model';  // ← import unique
import { Dossier } from '../shared/models/dossier.model';
import { PointOperationnel } from '../shared/models/point-operationnel.model';
import { RessourceMobilisee } from '../shared/models/ressource-mobilisee.model';

@Injectable({ providedIn: 'root' })
export class TeamService {
  private url = `${environment.apiUrl}/teams`;
  constructor(private http: HttpClient) {}

  /** includeInactive : demande aussi les équipes désactivées (?actif=all, réservé
   * institutionnel — voir la politique de désactivation). */
  getAll(includeInactive = false): Observable<Team[]> {
    const params = includeInactive ? new HttpParams().set('actif', 'all') : undefined;
    return this.http.get<Team[]>(`${this.url}/`, { params });
  }
  mesEquipes():                            Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/mes-equipes/`); }
  getById(id: string):                     Observable<Team>    { return this.http.get<Team>(`${this.url}/${id}/`); }
  create(data: Partial<Team>):             Observable<Team>    { return this.http.post<Team>(`${this.url}/`, data); }
  update(id: string, data: Partial<Team>): Observable<Team>    { return this.http.put<Team>(`${this.url}/${id}/`, data); }
  patch(id: string, data: Partial<Team>):  Observable<Team>    { return this.http.patch<Team>(`${this.url}/${id}/`, data); }
  delete(id: string):                      Observable<void>    { return this.http.delete<void>(`${this.url}/${id}/`); }
  /** POST /api/teams/<id>/reactiver/ — réactive une équipe désactivée (voir delete). */
  reactiver(id: string):                   Observable<Team>    { return this.http.post<Team>(`${this.url}/${id}/reactiver/`, {}); }
  /** GET /api/teams/vue_mairie/ — équipes de l'institution de l'utilisateur appelant. */
  vueMairie():                              Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/vue_mairie/`); }
  /** GET /api/teams/ressources-mobilisees/ — récap personnes/matériel mobilisés, voir
   * RessourcesMobiliseesComponent. */
  ressourcesMobilisees():                   Observable<RessourceMobilisee[]> { return this.http.get<RessourceMobilisee[]>(`${this.url}/ressources-mobilisees/`); }

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

  definirStatutRessource(id: string, offerId: string, statut: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/definir-statut-ressource/`, { offer_id: offerId, statut });
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

  /** POST /api/teams/<id>/assigner-crise/ — rattache l'équipe à une crise (additif, jamais un
   * remplacement de Team.assigned_crises). Nécessaire en plus de lierPoint : lier un point
   * n'ajoute pas automatiquement la crise à assigned_crises, or plusieurs vues s'appuient sur
   * ce champ précisément (recrutement scopé, ressources mobilisées, matching hébergement). */
  assignerCrise(id: string, criseId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/assigner-crise/`, { crise_id: criseId });
  }

  /** POST /api/teams/<id>/provisionner-canal-meshcore/ — crée (ou récupère) le canal MeshCore
   * privé de l'équipe et envoie ses infos (nom + clé) en DM à chaque membre équipé d'un nœud.
   * `regenerer: true` change la clé et ne la renvoie qu'aux membres ACTUELS — le mécanisme de
   * révocation (retirer un membre problématique de l'équipe, puis régénérer). */
  provisionnerCanalMeshCore(id: string, regenerer = false): Observable<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }> {
    return this.http.post<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }>(
      `${this.url}/${id}/provisionner-canal-meshcore/`, { regenerer },
    );
  }

  rattacherEquipe(parentId: string, equipeId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${parentId}/rattacher-equipe/`, { equipe_id: equipeId });
  }

  detacherEquipe(parentId: string, equipeId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${parentId}/detacher-equipe/`, { equipe_id: equipeId });
  }

  /** GET /api/teams/<id>/institutions-liees/ — institution délégataire + institutions
   * co-impliquées sur une même crise, utilisées pour élargir la recherche de membre à recruter
   * au-delà de la seule institution de l'équipe (voir teams.component.ts, loadCandidateMembers).
   * `type: 'acteur'` restreint aux institutions ACTEUR (sélecteur "institution délégataire",
   * voir institutionsDelegablesPourEquipe). */
  institutionsLiees(id: string, type?: 'acteur'): Observable<{ id: string; nom: string }[]> {
    const params = type ? { type } : undefined;
    return this.http.get<{ id: string; nom: string }[]>(`${this.url}/${id}/institutions-liees/`, { params });
  }
}