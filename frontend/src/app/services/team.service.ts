import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Team, MatrixMessage, SalonMatrixEquipe } from '../shared/models/team.model';
import { Dossier } from '../shared/models/dossier.model';
import { PointOperationnel } from '../shared/models/point-operationnel.model';
import { RessourceMobilisee } from '../shared/models/ressource-mobilisee.model';

@Injectable({ providedIn: 'root' })
export class TeamService {
  private url = `${environment.apiUrl}/teams`;
  constructor(private http: HttpClient) {}

  /** includeInactive : ajoute les équipes désactivées (?actif=all, institutionnels). */
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

  /** POST /api/teams/<id>/designer-rcsc/ — bascule est_equipe_rcsc (autorité locale de l'institution). */
  designerRcsc(id: string):                Observable<Team>    { return this.http.post<Team>(`${this.url}/${id}/designer-rcsc/`, {}); }
  /** GET /api/teams/vue_mairie/ — équipes de toute la commune (toutes institutions). */
  vueMairie():                              Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/vue_mairie/`); }
  /** GET /api/teams/equipes-institution/ — équipes de la seule institution de l'appelant. */
  equipesInstitution():                     Observable<Team[]>  { return this.http.get<Team[]>(`${this.url}/equipes-institution/`); }
  /** GET /api/teams/ressources-mobilisees/ — récap personnes/matériel mobilisés. */
  ressourcesMobilisees():                   Observable<RessourceMobilisee[]> { return this.http.get<RessourceMobilisee[]>(`${this.url}/ressources-mobilisees/`); }

  /** POST /api/teams/<id>/rejoindre/ — entrer soi-même dans une équipe de son institution
   * ou d'une institution fille. Celui qui crée une équipe n'en est pas membre d'office. */
  rejoindre(id: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/rejoindre/`, {});
  }

  inviterMembre(id: string, data: {
    first_name: string; last_name: string; email: string; phone_number: string; role_code: string;
  }): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/inviter-membre/`, data);
  }

  /** Affecte plusieurs personnes à l'équipe d'un seul geste, avec sa mission.
   *
   * **Jamais un `patch({ member_ids })` pour cela** : un PATCH envoie la liste entière telle
   * que ce navigateur la connaissait, donc deux régulateurs qui affectent en même temps et le
   * second efface les ajouts du premier. Cette action-ci ajoute, et l'ordre des appels n'a
   * plus d'importance. Elle refuse aussi nommément un membre sorti — et le dit dans
   * `refuses` : une affectation partielle qui se présente comme un succès fait partir une
   * équipe incomplète en croyant l'avoir au complet. */
  ajouterMembres(id: string, utilisateurs: string[], options: OptionsAffectation = {})
      : Observable<AjoutMembresResultat> {
    return this.http.post<AjoutMembresResultat>(
      `${this.url}/${id}/ajouter-membres/`, { utilisateurs, ..._corps(options) });
  }

  /** POST /api/teams/creer-avec-membres/ — constitue une équipe d'intervention NEUVE.
   *
   * Ne se ramène pas à `create()` + `ajouterMembres()` : `POST /teams/` exige un type de
   * compte institutionnel (un membre du bureau d'une association ne l'est pas toujours) et
   * accepte `members` sans vérifier le rattachement. Ici le bureau de l'association suffit, et
   * la sélection passe par le même tri que l'affectation — refus nommés compris. */
  creerAvecMembres(institutionId: string, nom: string, utilisateurs: string[],
                   options: OptionsAffectation = {}): Observable<AjoutMembresResultat> {
    return this.http.post<AjoutMembresResultat>(`${this.url}/creer-avec-membres/`, {
      institution: institutionId, nom, utilisateurs, ..._corps(options),
    });
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

  /** POST /api/teams/<id>/assigner-crise/ — ajoute une crise à Team.assigned_crises. Nécessaire
   * en plus de lierPoint (voir DOCUMENTATION.md, § 6.2). */
  assignerCrise(id: string, criseId: string): Observable<Team> {
    return this.http.post<Team>(`${this.url}/${id}/assigner-crise/`, { crise_id: criseId });
  }

  /** POST /api/teams/<id>/provisionner-canal-meshcore/ — crée ou récupère le canal privé et envoie
   * nom + clé en DM aux membres équipés. `regenerer: true` change la clé et ne l'envoie qu'aux
   * membres actuels (révocation). */
  provisionnerCanalMeshCore(id: string, regenerer = false): Observable<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }> {
    return this.http.post<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }>(
      `${this.url}/${id}/provisionner-canal-meshcore/`, { regenerer },
    );
  }

  /** POST /api/teams/<id>/provisionner-canal-meshtastic/ — idem en Meshtastic ; DM chiffré par
   * clé publique (PKI) quand elle est connue. */
  provisionnerCanalMeshtastic(id: string, regenerer = false): Observable<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }> {
    return this.http.post<{ canal_id: string; nom: string; destinataires: number; compagnon_disponible: boolean }>(
      `${this.url}/${id}/provisionner-canal-meshtastic/`, { regenerer },
    );
  }

  /** POST /api/teams/<id>/provisionner-salon-matrix/ — provisionne LES DEUX salons de l'équipe
   * (Intervenants et Encadrement) depuis le 11/11/2026 et rend donc un tableau. `room_id` reste
   * vide tant que matrix-bridge n'a pas créé le salon côté Synapse (poll ~30 s).
   *
   * L'URL garde son nom au singulier : la renommer casserait les appels en place sans rien
   * apporter. */
  provisionnerSalonMatrix(id: string): Observable<SalonMatrixEquipe[]> {
    return this.http.post<SalonMatrixEquipe[]>(
      `${this.url}/${id}/provisionner-salon-matrix/`, {},
    );
  }

  /** POST /api/teams/<id>/definir-encadrement/ — remplace la liste entière, donc idempotent et
   * un retrait ne demande pas d'appel séparé. Le serveur refuse une personne qui n'est pas
   * membre de l'équipe (400, `hors_equipe`) : l'encadrement est une qualité au sein de
   * l'équipe, pas une appartenance de plus. */
  definirEncadrement(id: string, membresEncadrement: string[]): Observable<Team> {
    return this.http.post<Team>(
      `${this.url}/${id}/definir-encadrement/`, { membres_encadrement: membresEncadrement },
    );
  }

  /** GET /api/teams/<id>/salon-matrix-messages/ — relayés par le serveur avec le jeton du bot. */
  getSalonMatrixMessages(id: string): Observable<{ messages: MatrixMessage[] }> {
    return this.http.get<{ messages: MatrixMessage[] }>(`${this.url}/${id}/salon-matrix-messages/`);
  }

  /** POST /api/teams/<id>/salon-matrix-messages/ — `urgent` est ouvert à tous les membres. */
  envoyerMessageSalonMatrix(id: string, texte: string, urgent = false): Observable<{ messages: MatrixMessage[] }> {
    return this.http.post<{ messages: MatrixMessage[] }>(`${this.url}/${id}/salon-matrix-messages/`, { texte, urgent });
  }

  /** POST /api/teams/<id>/salon-matrix-reagir/ — accusé « Vu » (cadres seulement). */
  reagirSalonMatrix(id: string, eventId: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.url}/${id}/salon-matrix-reagir/`, { event_id: eventId });
  }

  /** GET /api/teams/<id>/messagerie-unifiee/ — Matrix + MeshCore + Meshtastic fusionnés ; le
   * salon Matrix est provisionné à la volée. */
  getMessagerieUnifiee(id: string): Observable<{ messages: MatrixMessage[] }> {
    return this.http.get<{ messages: MatrixMessage[] }>(`${this.url}/${id}/messagerie-unifiee/`);
  }

  /** POST /api/teams/<id>/messagerie-unifiee/ — envoie sur Matrix et sur MeshCore/Meshtastic. */
  envoyerMessageUnifie(id: string, texte: string, urgent = false): Observable<{ messages: MatrixMessage[] }> {
    return this.http.post<{ messages: MatrixMessage[] }>(`${this.url}/${id}/messagerie-unifiee/`, { texte, urgent });
  }

  /** POST /api/teams/<id>/demarrer-engagement/ — engagement_debut=maintenant (idempotent, cadres). */
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

  /** GET /api/teams/<id>/institutions-liees/ — délégataire + institutions co-impliquées sur une
   * crise (élargit les candidats). `type: 'acteur'` : institutions ACTEUR seulement. */
  institutionsLiees(id: string, type?: 'acteur'): Observable<{ id: string; nom: string }[]> {
    const params = type ? { type } : undefined;
    return this.http.get<{ id: string; nom: string }[]>(`${this.url}/${id}/institutions-liees/`, { params });
  }
}

/** Résultat d'une affectation en masse. Les refus sont rendus, jamais tus. */
/** Un créneau pointé à la main dans la grille : « je prends cette personne CE soir-là ». */
export interface CreneauPointe {
  utilisateur: string;
  date: string;
  creneau: string;
}

export interface OptionsAffectation {
  missionTitre?: string;
  criseId?: string | null;
  /** La campagne sur laquelle la grille était ouverte : c'est elle qui donne un sens aux
   * créneaux pointés, en les versant dans ses tours de garde. */
  campagneId?: string | null;
  creneaux?: CreneauPointe[];
}

function _corps(options: OptionsAffectation): Record<string, unknown> {
  const corps: Record<string, unknown> = {};
  if (options.missionTitre) { corps['mission_titre'] = options.missionTitre; }
  if (options.criseId) { corps['crise_id'] = options.criseId; }
  if (options.campagneId) { corps['campagne'] = options.campagneId; }
  if (options.creneaux?.length) { corps['creneaux'] = options.creneaux; }
  return corps;
}

export interface AjoutMembresResultat {
  team: Team;
  ajoutes: number;
  deja_presents: number;
  refuses: { utilisateur: string; motif: string }[];
  /** Combien de créneaux ont été pointés, et combien ont réellement pu être enregistrés.
   *
   * Les deux nombres diffèrent, et c'est volontaire : rien dans le modèle ne stocke « cette
   * équipe tient le soir du 14 » — seuls les tours de garde d'une campagne le savent
   * (`AffectationRotation`), et leur maille est la rotation, pas le jour. Hors campagne, les
   * créneaux restent dans le journal d'audit, et l'écran doit le dire plutôt que laisser
   * croire à un planning qui n'existe pas. */
  creneaux_pointes?: number;
  creneaux_enregistres?: number;
  creneaux_ignores?: { utilisateur?: string; date?: string; creneau?: string;
                       motif: string }[];
  /** Posés au planning de l'équipe (`CreneauEquipe`). Écrit dans TOUS les cas, campagne ou
   * non : le planning répond à « qui tient ce créneau pour cette équipe », la rotation à
   * « qui arme ce tour de garde ». Deux questions, deux tables. */
  creneaux_planning?: number;
  /** La même personne attendue par une AUTRE équipe au même moment. Signalé sans bloquer :
   * il existe des cas légitimes, mais quelqu'un doit trancher. */
  conflits_planning?: { utilisateur: string; nom: string; date: string; creneau: string;
                        equipe: string; equipe_nom: string; motif: string }[];
}
