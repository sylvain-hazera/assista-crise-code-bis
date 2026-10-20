import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Team, MatrixMessage } from '../shared/models/team.model';  // ← import unique
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
  delete(id: string):                      Observable<void>    { return this.http.delete<void>(`${this.url}/${id}/`); }   // désactivation (réversible)
  supprimer(id: string):                   Observable<void>    { return this.http.post<void>(`${this.url}/${id}/supprimer/`, {}); }   // suppression définitive
  /** POST /api/teams/<id>/reactiver/ — réactive une équipe désactivée (voir delete). */
  reactiver(id: string):                   Observable<Team>    { return this.http.post<Team>(`${this.url}/${id}/reactiver/`, {}); }

  /** POST /api/teams/<id>/designer-rcsc/ — bascule est_equipe_rcsc (réservé à l'autorité locale
   * de l'institution de l'équipe) -- voir TeamViewSet.designer_rcsc côté backend. */
  designerRcsc(id: string):                Observable<Team>    { return this.http.post<Team>(`${this.url}/${id}/designer-rcsc/`, {}); }
  /** GET /api/teams/vue_mairie/ — équipes de toute la commune (toutes institutions). */
  vueMairie():                              Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/vue_mairie/`); }
  /** GET /api/teams/equipes-institution/ — équipes de la SEULE institution de l'appelant
   * (contrairement à vueMairie, toute la commune, et mesEquipes, celles dont on est membre). */
  equipesInstitution():                     Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/equipes-institution/`); }
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

  /** Plusieurs offres d'un coup (page Signalements) : mêmes règles qu'assignerRessource, les
   * offres déjà dans l'équipe sont ignorées. */
  assignerRessources(id: string, offerIds: string[]): Observable<{ team: Team; ajoutees: number; deja_affectees: number }> {
    return this.http.post<{ team: Team; ajoutees: number; deja_affectees: number }>(
      `${this.url}/${id}/assigner-ressources/`, { offer_ids: offerIds },
    );
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

  /** POST /api/teams/<id>/provisionner-canal-meshtastic/ — équivalent Meshtastic de
   * provisionnerCanalMeshCore. Le DM envoyé à chaque membre est automatiquement chiffré par
   * clé publique (PKI) dès qu'elle est connue pour lui, sinon repli sur le canal principal. */
  provisionnerCanalMeshtastic(id: string, regenerer = false): Observable<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }> {
    return this.http.post<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }>(
      `${this.url}/${id}/provisionner-canal-meshtastic/`, { regenerer },
    );
  }

  /** POST /api/teams/<id>/provisionner-salon-matrix/ — active le salon Matrix privé de
   * l'équipe (voir TeamViewSet.provisionner_salon_matrix). room_id reste vide dans la réponse
   * tant que le pont matrix-bridge ne l'a pas créé côté Synapse (poll périodique). */
  provisionnerSalonMatrix(id: string): Observable<{ id: string; room_id: string | null }> {
    return this.http.post<{ id: string; room_id: string | null }>(
      `${this.url}/${id}/provisionner-salon-matrix/`, {},
    );
  }

  /** GET /api/teams/<id>/salon-matrix-messages/ — messages du salon Matrix de l'équipe (voir
   * TeamViewSet.salon_matrix_messages), relayés côté serveur via le jeton du bot. */
  getSalonMatrixMessages(id: string): Observable<{ messages: MatrixMessage[] }> {
    return this.http.get<{ messages: MatrixMessage[] }>(`${this.url}/${id}/salon-matrix-messages/`);
  }

  /** POST /api/teams/<id>/salon-matrix-messages/ — poste un message dans le salon Matrix de
   * l'équipe (attribué à l'utilisateur courant, voir envoyer_message_salon). `urgent` : ouvert
   * à tout le monde, y compris un intervenant isolé (décision utilisateur du 26/09). */
  envoyerMessageSalonMatrix(id: string, texte: string, urgent = false): Observable<{ messages: MatrixMessage[] }> {
    return this.http.post<{ messages: MatrixMessage[] }>(`${this.url}/${id}/salon-matrix-messages/`, { texte, urgent });
  }

  /** POST /api/teams/<id>/salon-matrix-reagir/ — accusé "Vu" sur un message (réaction Matrix,
   * réservé aux cadres régulateur/chef d'équipe/institutionnel, voir salon_matrix_reagir). */
  reagirSalonMatrix(id: string, eventId: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.url}/${id}/salon-matrix-reagir/`, { event_id: eventId });
  }

  /** GET /api/teams/<id>/messagerie-unifiee/ — fenêtre de messagerie UNIQUE de l'équipe,
   * fusionnant Matrix/MeshCore/Meshtastic (voir TeamViewSet.messagerie_unifiee). Remplace
   * getSalonMatrixMessages pour la vue équipe (2026-10-05) -- le salon Matrix lui-même reste
   * provisionné à la volée côté serveur, plus besoin de bouton manuel préalable. */
  getMessagerieUnifiee(id: string): Observable<{ messages: MatrixMessage[] }> {
    return this.http.get<{ messages: MatrixMessage[] }>(`${this.url}/${id}/messagerie-unifiee/`);
  }

  /** POST /api/teams/<id>/messagerie-unifiee/ — envoie un message sur Matrix ET sur
   * MeshCore/Meshtastic pour les membres équipés (automatique, sans action manuelle). */
  envoyerMessageUnifie(id: string, texte: string, urgent = false): Observable<{ messages: MatrixMessage[] }> {
    return this.http.post<{ messages: MatrixMessage[] }>(`${this.url}/${id}/messagerie-unifiee/`, { texte, urgent });
  }

  /** POST /api/teams/<id>/demarrer-engagement/ — pose engagement_debut=maintenant si pas déjà
   * engagée (idempotent). Réservé aux cadres, voir Team.engagement_debut. */
  demarrerEngagement(id: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/demarrer-engagement/`, {});
  }

  /** POST /api/teams/<id>/mettre-au-repos/ — repasse engagement_debut à null. */
  mettreAuRepos(id: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/mettre-au-repos/`, {});
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