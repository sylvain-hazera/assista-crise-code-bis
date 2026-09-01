import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';

import { TeamService }       from '../../services/team.service';
import { UserService }       from '../../services/user.service';
import { InstitutionService } from '../../services/institution.service';
import { CrisisService }     from '../../services/crisis.service';
import { OfferService }      from '../../services/offer.service';
import { RequestService }    from '../../services/request.service';
import { DisponibiliteOffreService } from '../../services/disponibilite-offre.service';
import { DossierService } from '../../services/dossier.service';
import { CompetenceService } from '../../services/competence.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { AuditLogService, AuditLogEntry } from '../../services/audit-log.service';
import { DossierHistoriqueService } from '../../services/dossier-historique.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { ZoneMapComponent } from '../../shared/components/common/zone-map/zone-map.component';
import { MinimapComponent } from '../../shared/components/common/minimap/minimap.component';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';
import { PointModalComponent } from '../crises/point-modal/point-modal.component';

import { Team, TeamMission }  from '../../shared/models/team.model';
import { User }        from '../../shared/models/user.model';
import { RoleOperationnel } from '../../shared/models/institution.model';
import { Crisis }              from '../../shared/models/crisis.model';
import { Offer }              from '../../shared/models/offer.model';
import { Request }            from '../../shared/models/request.model';
import { Status }             from '../../shared/models/status.model';
import { DisponibiliteOffre } from '../../shared/models/disponibilite-offre.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Competence } from '../../shared/models/competence.model';
import { Institution } from '../../shared/models/institution.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';

type ModalView = 'none' | 'create' | 'detail' | 'edit' | 'delete' | 'assign' | 'planning';

const COLORS = ['#ef4444','#f97316','#eab308','#22c55e','#06b6d4','#3b82f6','#8b5cf6','#ec4899'];

@Component({
  selector: 'app-teams',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, ZoneMapComponent, MinimapComponent, TagSearchInputComponent, PointModalComponent],
  templateUrl: './teams.component.html',
  styleUrls: ['./teams.component.scss'],
})
export class TeamsComponent implements OnInit {

  // ── Data ────────────────────────────────────────────────────
  teams:    Team[]        = [];
  users:    User[] = [];
  crisis:   Crisis[]       = [];
  offers:   Offer[]       = [];
  requests: Request[]     = [];
  disponibilites: DisponibiliteOffre[] = [];
  dossiers: Dossier[] = [];
  competences: Competence[] = [];
  roles: RoleOperationnel[] = [];
  institutions: Institution[] = [];
  points: PointOperationnel[] = [];
  pointTypes: PointType[] = [];

  /** Membres candidats pour l'équipe SÉLECTIONNÉE uniquement (rechargés à l'ouverture du
   * détail, scopés sur son institution) — distinct de `users` (liste globale, encore
   * nécessaire pour résoudre noms/initiales de membres déjà affectés, y compris ceux qui
   * auraient depuis quitté l'institution). */
  candidateMembers: User[] = [];
  showInviteForm = false;
  inviteError = '';

  // ── UI ──────────────────────────────────────────────────────
  isLoading      = true;
  isSaving       = false;
  errorMessage   = '';
  successMessage = '';

  modal: ModalView         = 'none';
  selectedTeam: Team | null = null;

  searchQuery = '';
  memberSearchQuery  = '';
  missionSearchQuery = '';

  // ── Forms ───────────────────────────────────────────────────
  createForm!: FormGroup;
  editForm!:   FormGroup;
  inviteForm!: FormGroup;

  readonly COLORS = COLORS;
  selectedColor = COLORS[5];

  constructor(
    private fb:          FormBuilder,
    private teamService: TeamService,
    private userService: UserService,
    private institutionService: InstitutionService,
    private crisisService:  CrisisService,
    private offerService:   OfferService,
    private requestService: RequestService,
    private disponibiliteOffreService: DisponibiliteOffreService,
    private dossierService: DossierService,
    private competenceService: CompetenceService,
    private roleOperationnelService: RoleOperationnelService,
    private auditLogService: AuditLogService,
    private dossierHistoriqueService: DossierHistoriqueService,
    private pointOperationnelService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private route: ActivatedRoute,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.buildForms();
    this.loadRemoteData();
  }

  /** Retour depuis "Ouvrir le tableau des offres" (voir ReportingComponent, mode picker) :
   * rouvre directement le détail de l'équipe concernée une fois les données chargées. */
  private openTeamFromQueryParam(): void {
    const openTeamId = this.route.snapshot.queryParamMap.get('openTeam');
    if (!openTeamId) return;
    const team = this.teams.find(t => t.id === openTeamId);
    if (team) {
      this.openDetail(team);
      this.router.navigate([], { relativeTo: this.route, queryParams: {} });
    }
  }

  // Équipes désactivées (voir la politique de désactivation) sont masquées par défaut par le
  // backend — ce bouton demande explicitement ?actif=all pour les retrouver et les réactiver.
  showDesactives = false;

  // ── Load ─────────────────────────────────────────────────────
  private loadRemoteData(): void {
    this.isLoading = true;
    forkJoin({
      users:    this.userService.getAll(),
      crisis:   this.crisisService.getAll(),
      offers:   this.offerService.getAll(),
      requests: this.requestService.getAll(),
      teams:    this.teamService.getAll(this.showDesactives),       // ← ajouté ici
      disponibilites: this.disponibiliteOffreService.getAll(),
      dossiers: this.dossierService.getAll(),
      competences: this.competenceService.getAll(),
      roles: this.roleOperationnelService.getAll(),
      institutions: this.institutionService.getAll(),
      points: this.pointOperationnelService.getAll(),
      pointTypes: this.pointTypeService.getAll(),
    }).subscribe({
      next: ({ users, crisis, offers, requests, teams, disponibilites, dossiers, competences, roles, institutions, points, pointTypes }) => {
        this.users    = users;
        this.crisis   = crisis;
        this.offers   = offers;
        this.requests = requests;
        this.disponibilites = disponibilites;
        this.dossiers = dossiers;
        this.competences = competences;
        this.roles = roles;
        this.institutions = institutions;
        this.points = points;
        this.pointTypes = pointTypes;
        this.teams    = teams.map(t => ({ ...t, missions: this.buildMissions(t) }));
        this.isLoading = false;
        this.openTeamFromQueryParam();
      },
      error: () => {
        this.showError('Impossible de charger les données.');
        this.isLoading = false;
      },
    });
  }

  /** Reconstruit les missions affichées à partir des ids réellement assignés côté backend
   * (assigned_crisis_ids/assigned_offer_ids/assigned_request_ids) — `missions` n'est jamais
   * renvoyé tel quel par l'API, c'est une projection locale pour l'affichage. */
  private buildMissions(team: Team): TeamMission[] {
    const missions: TeamMission[] = [];
    for (const id of team.assigned_crisis_ids ?? []) {
      const c = this.crisis.find(c => c.id === id);
      if (c) missions.push({ id, kind: 'Crisis', titre: c.name, statut: c.status, date: c.start_date });
    }
    for (const id of team.assigned_offer_ids ?? []) {
      const o = this.offers.find(o => o.id === id);
      if (o) missions.push({
        id, kind: 'Offer', titre: o.title, statut: o.status, date: o.created_at,
        engagementStatut: o.engagement_statut ?? null,
        engagementStatutLibelle: o.engagement_statut_libelle ?? null,
      });
    }
    for (const id of team.assigned_request_ids ?? []) {
      const r = this.requests.find(r => r.id === id);
      if (r) missions.push({ id, kind: 'Request', titre: r.title, statut: r.status, date: r.created_at });
    }
    return missions;
  }

  reloadTeams(): void {
    this.teamService.getAll(this.showDesactives).subscribe(teams => {
      this.teams = teams.map(t => ({ ...t, missions: this.buildMissions(t) }));
    });
  }

  toggleShowDesactives(): void {
    this.reloadTeams();
  }

  // ── Forms ─────────────────────────────────────────────────────
  private buildForms(): void {
    this.createForm = this.fb.group({
      name:        ['', [Validators.required, Validators.minLength(2)]],
      description: [''],
      leader:    [null],
    });
    this.editForm = this.fb.group({
      name:        ['', [Validators.required, Validators.minLength(2)]],
      description: [''],
      leader:    [null],
    });
    this.inviteForm = this.fb.group({
      first_name:   ['', Validators.required],
      last_name:    ['', Validators.required],
      email:        ['', [Validators.required, Validators.email]],
      phone_number: ['', Validators.required],
      role_code:    [null, Validators.required],
    });
  }

  // ── CREATE ────────────────────────────────────────────────────
  openCreate(): void {
    this.createForm.reset();
    this.selectedColor = COLORS[Math.floor(Math.random() * COLORS.length)];
    this.modal = 'create';
  }

  submitCreate(): void {
    if (this.createForm.invalid) { this.createForm.markAllAsTouched(); return; }
    const { name, description, leader } = this.createForm.value;
    const payload: Partial<Team> = {
      name,
      description: description ?? '',
      color:                this.selectedColor,
      leader:               leader ?? null,
      member_ids:           leader ? [leader] : [],
      assigned_crisis_ids:  [],
      assigned_offer_ids:   [],
      assigned_request_ids: [],
      competence_ids:       [],
    };
    this.teamService.create(payload).subscribe({
      next: () => { this.reloadTeams(); this.showSuccess('Équipe créée.'); this.closeModal(); },
      error: () => this.showError('Erreur lors de la création.'),
    });
  }


  // ── DETAIL ────────────────────────────────────────────────────
  openDetail(team: Team): void {
    this.selectedTeam = team;
    this.departementsInput = (team.departements ?? []).join(', ');
    this.communesInput = (team.communes ?? []).join(', ');
    this.pendingZoneWkt = team.zone_precise ?? null;
    this.modal = 'detail';
    this.showInviteForm = false;
    this.inviteError = '';
    this.inviteForm.reset();
    this.showCreateDossierForm = false;
    this.showLinkPointForm = false;
    this.showPointModal = false;
    this.showAttachTeamForm = false;
    this.loadCandidateMembers(team);
    this.loadHistory(team);
  }

  // ── HISTORIQUE ────────────────────────────────────────────────
  auditEntries: AuditLogEntry[] = [];
  dossierHistoriqueEntries: any[] = [];
  historyLoading = false;

  /** Charge la main courante de l'équipe (qui a rejoint/quitté, ressources/mission) et
   * l'historique de traitement de ses dossiers (déjà tracé par DossierHistorique) — deux
   * sources déjà existantes, fusionnées ici en une seule timeline. */
  private loadHistory(team: Team): void {
    if (!team.id) return;
    this.historyLoading = true;
    this.auditLogService.forObject('Team', team.id).subscribe({
      next: (entries) => { this.auditEntries = entries; this.historyLoading = false; },
      error: () => { this.auditEntries = []; this.historyLoading = false; },
    });
    this.dossierHistoriqueService.getAll().subscribe({
      next: (entries) => this.dossierHistoriqueEntries = entries,
      error: () => this.dossierHistoriqueEntries = [],
    });
  }

  /** Timeline unifiée équipe + dossiers de l'équipe, triée du plus récent au plus ancien. */
  get historyTimeline(): { date: string; icon: string; label: string; detail: string }[] {
    if (!this.selectedTeam) return [];
    const dossierIds = new Set(this.dossiersForSelectedTeam.map(d => d.id));
    const fromAudit = this.auditEntries.map(e => ({
      date: e.date_action,
      icon: 'groups',
      label: e.action_libelle || 'Équipe',
      detail: `${e.commentaire || ''} — ${e.utilisateur_nom}`,
    }));
    const fromDossiers = this.dossierHistoriqueEntries
      .filter(e => dossierIds.has(e.dossier))
      .map(e => ({
        date: e.date_creation,
        icon: 'folder_open',
        label: e.evenement,
        detail: `${e.commentaire || ''} — ${e.auteur_nom}`,
      }));
    return [...fromAudit, ...fromDossiers].sort((a, b) => b.date.localeCompare(a.date));
  }

  /** Ne propose comme candidats à l'ajout QUE les membres de l'institution responsable de
   * cette équipe ET, le cas échéant, de son institution délégataire — avant ce correctif, tous
   * les comptes de la plateforme (admins, secours, particuliers sans lien avec cette mairie...)
   * apparaissaient dans le sélecteur. Vide si l'équipe n'a aucune institution (rien de
   * pertinent à proposer). */
  private loadCandidateMembers(team: Team): void {
    const institutionIds = [team.institution, team.institution_delegataire].filter((id): id is string => !!id);
    if (institutionIds.length === 0) {
      this.candidateMembers = [];
      return;
    }
    this.userService.getAll({ institution: institutionIds }).subscribe({
      next: (users) => this.candidateMembers = users,
      error: () => this.candidateMembers = [],
    });
  }

  // ── INSTITUTION / DÉLÉGATION ────────────────────────────────────
  changerInstitution(institutionId: string): void {
    if (!this.selectedTeam?.id || !institutionId || institutionId === this.selectedTeam.institution) return;
    if (!confirm("Changer l'institution responsable de cette équipe ?")) return;
    this.teamService.patch(this.selectedTeam.id, { institution: institutionId }).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.loadCandidateMembers(this.selectedTeam);
        this.reloadTeams();
        this.showSuccess('Institution responsable mise à jour.');
      },
      error: (err) => this.showError(err?.error?.error || "Erreur lors du changement d'institution."),
    });
  }

  delegerA(institutionId: string): void {
    if (!this.selectedTeam?.id || !institutionId) return;
    this.teamService.definirDelegation(this.selectedTeam.id, institutionId).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.loadCandidateMembers(this.selectedTeam);
        this.reloadTeams();
        this.showSuccess('Équipe déléguée.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors de la délégation.'),
    });
  }

  retirerDelegation(): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.retirerDelegation(this.selectedTeam.id).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.loadCandidateMembers(this.selectedTeam);
        this.reloadTeams();
        this.showSuccess('Délégation retirée.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors du retrait de la délégation.'),
    });
  }

  /** Institutions proposables comme délégataire : toutes sauf l'institution responsable
   * actuelle (une équipe ne peut pas se déléguer à elle-même). */
  get institutionsDelegablesPourEquipe(): Institution[] {
    if (!this.selectedTeam) return this.institutions;
    return this.institutions.filter(i => i.id !== this.selectedTeam!.institution);
  }

  // ── ZONE D'INTERVENTION ─────────────────────────────────────────
  departementsInput = '';
  communesInput = '';
  pendingZoneWkt: string | null = null;

  private parseCodeList(raw: string): string[] {
    return raw.split(',').map(s => s.trim()).filter(Boolean);
  }

  saveZoneCodes(): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.patch(this.selectedTeam.id, {
      departements: this.parseCodeList(this.departementsInput),
      communes: this.parseCodeList(this.communesInput),
    }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
      this.showSuccess('Zone (départements/communes) enregistrée.');
    });
  }

  onZoneChange(wkt: string | null): void {
    this.pendingZoneWkt = wkt;
  }

  saveZonePrecise(): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.patch(this.selectedTeam.id, { zone_precise: this.pendingZoneWkt }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
      this.showSuccess('Zone précise enregistrée.');
    });
  }

  // ── EDIT ──────────────────────────────────────────────────────
  openEdit(team: Team, e?: Event): void {
    e?.stopPropagation();
    this.selectedTeam = team;
    this.selectedColor = team.color;
    this.editForm.patchValue({ name: team.name, description: team.description, leader: team.leader });
    this.modal = 'edit';
  }

  submitEdit(): void {
    if (!this.selectedTeam || this.editForm.invalid) { this.editForm.markAllAsTouched(); return; }
    const { name, description, leader } = this.editForm.value;
    this.teamService.patch(this.selectedTeam.id!, {
      name, description, leader: leader ?? null, color: this.selectedColor,
    }).subscribe({
      next: () => { this.reloadTeams(); this.showSuccess('Équipe modifiée.'); this.closeModal(); },
      error: () => this.showError('Erreur lors de la modification.'),
    });
  }

  // ── DELETE ────────────────────────────────────────────────────
  openDelete(team: Team, e?: Event): void {
    e?.stopPropagation();
    this.selectedTeam = team;
    this.modal = 'delete';
  }

  confirmDelete(): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.delete(this.selectedTeam.id).subscribe({
      next: () => { this.reloadTeams(); this.showSuccess('Équipe désactivée.'); this.closeModal(); },
      error: () => this.showError('Erreur lors de la désactivation.'),
    });
  }

  reactiver(team: Team, e?: Event): void {
    e?.stopPropagation();
    if (!team.id) return;
    this.teamService.reactiver(team.id).subscribe({
      next: () => { this.reloadTeams(); this.showSuccess('Équipe réactivée.'); },
      error: () => this.showError('Erreur lors de la réactivation.'),
    });
  }

  // ── MEMBERS ───────────────────────────────────────────────────
  toggleMember(userId: string): void {
    if (!this.selectedTeam) return;
    const ids = this.selectedTeam.member_ids ?? [];
    const newIds = ids.includes(userId) ? ids.filter(id => id !== userId) : [...ids, userId];
    this.teamService.patch(this.selectedTeam.id!, { member_ids: newIds }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
    });
  }

  isMember(userId: string): boolean {
    return this.selectedTeam?.member_ids?.includes(userId) ?? false;
  }

  /** Invite un nouveau membre dans l'institution de l'équipe (nom/prénom/email/tél/rôle) et
   * l'ajoute directement à l'équipe — même s'il n'a pas encore activé son compte (voir
   * TeamViewSet.inviter_membre côté backend). */
  submitInvite(): void {
    if (!this.selectedTeam?.id || this.inviteForm.invalid) {
      this.inviteForm.markAllAsTouched();
      return;
    }
    this.inviteError = '';
    this.teamService.inviterMembre(this.selectedTeam.id, this.inviteForm.value).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.loadCandidateMembers(updated);
        this.reloadTeams();
        this.showInviteForm = false;
        this.inviteForm.reset();
        this.showSuccess('Membre invité et ajouté à l\'équipe.');
      },
      error: (err) => {
        this.inviteError = err?.error?.error || "Erreur lors de l'invitation.";
      },
    });
  }

  // ── THÈMES D'INTERVENTION ─────────────────────────────────────
  toggleCompetence(competenceId: string): void {
    if (!this.selectedTeam) return;
    const ids = this.selectedTeam.competence_ids ?? [];
    const newIds = ids.includes(competenceId) ? ids.filter(id => id !== competenceId) : [...ids, competenceId];
    this.teamService.patch(this.selectedTeam.id!, { competence_ids: newIds }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
    });
  }

  hasCompetence(competenceId: string): boolean {
    return this.selectedTeam?.competence_ids?.includes(competenceId) ?? false;
  }

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  onCompetenceSearchSelected(item: Competence): void {
    if (!this.competences.find(c => c.id === item.id)) {
      this.competences = [...this.competences, item];
    }
    if (!this.hasCompetence(item.id)) {
      this.toggleCompetence(item.id);
    }
  }

  // ── ASSIGN MISSIONS ───────────────────────────────────────────
  openAssign(team: Team, e?: Event): void {
    e?.stopPropagation();
    this.selectedTeam = team;
    this.modal        = 'assign';
  }

  toggleMission(id: string, kind: TeamMission['kind'], titre: string, statut?: string, date?: string): void {
    if (!this.selectedTeam) return;
    const team = this.selectedTeam;
    const exists = team.missions.some(m => m.id === id && m.kind === kind);
    const missions = exists
      ? team.missions.filter(m => !(m.id === id && m.kind === kind))
      : [...team.missions, { id, kind, titre, statut, date }];

    // Mettre à jour les listes d'IDs selon le kind
    const crisisIds  = missions.filter(m => m.kind === 'Crisis').map(m => m.id);
    const offerIds   = missions.filter(m => m.kind === 'Offer').map(m => m.id);
    const requestIds = missions.filter(m => m.kind === 'Request').map(m => m.id);

    // Les offres (ressources) ne passent plus par ce mécanisme générique — voir
    // assignerRessource/retirerRessource, qui gèrent déjà l'ajout de l'auteur comme membre —
    // offerIds n'est recalculé ici que pour ne pas écraser les ressources déjà affectées.
    this.teamService.patch(team.id!, {
      assigned_crisis_ids:  crisisIds,
      assigned_offer_ids:   offerIds,
      assigned_request_ids: requestIds,
    }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions };
      this.reloadTeams();
    });
  }

  isMissionAssigned(id: string, kind: TeamMission['kind']): boolean {
    return this.selectedTeam?.missions.some(m => m.id === id && m.kind === kind) ?? false;
  }

  // ── HELPERS ───────────────────────────────────────────────────
  closeModal(): void { this.modal = 'none'; this.selectedTeam = null; }

  getUserById(id: string): User | undefined {
    return this.users.find(u => u.id === id);
  }

  userName(id: string): string {
    const u = this.getUserById(id);
    return u ? `${u.first_name} ${u.last_name}`.trim() || u.username : id.slice(0,8);
  }

  userInitials(id: string): string {
    const u = this.getUserById(id);
    if (!u) return '?';
    return ((u.first_name?.[0] ?? '') + (u.last_name?.[0] ?? u.username?.[0] ?? '')).toUpperCase();
  }

  missionIcon(kind: TeamMission['kind']): string {
    return { Crisis: 'local_fire_department', Offer: 'volunteer_activism', Request: 'emergency' }[kind];
  }

  missionClass(kind: TeamMission['kind']): string {
    return { Crisis: 'mk-crisis', Offer: 'mk-offer', Request: 'mk-request' }[kind];
  }

  missionKindLabel(kind: TeamMission['kind']): string {
    return { Crisis: 'Crises', Offer: "Offres d'aide", Request: "Demandes d'aide" }[kind];
  }

  /** Demandes assignées à l'équipe — la crise se rattache désormais directement à la mission
   * (voir mission-active-bar/submitDefinirMission), ce groupe ne couvre plus que les demandes
   * d'aide. Les offres (ressources) ont leur propre section dédiée, voir
   * resourcesForSelectedTeam. */
  get missionsByKind(): { kind: TeamMission['kind']; missions: TeamMission[] }[] {
    if (!this.selectedTeam) return [];
    return (['Request'] as TeamMission['kind'][])
      .map(kind => ({ kind, missions: this.selectedTeam!.missions.filter(m => m.kind === kind) }))
      .filter(g => g.missions.length > 0);
  }

  /** Nombre total de demandes assignées. */
  get missionsCount(): number {
    return this.missionsByKind.reduce((sum, g) => sum + g.missions.length, 0);
  }

  /** Ressources (offres) affectées à l'équipe — bénévoles seuls, bénévoles + matériel, ou
   * matériel seul (voir Offer.materiel_type/transport_type/diplome_secourisme). */
  get resourcesForSelectedTeam(): TeamMission[] {
    return this.selectedTeam?.missions.filter(m => m.kind === 'Offer') ?? [];
  }

  /** Récapitulatif rapide : combien de ressources affectées sont des bénévoles seuls, des
   * bénévoles avec matériel, ou du matériel seul — dérivé des offres déjà chargées, sans appel
   * réseau supplémentaire. */
  get resourcesSummary(): { seul: number; avecMateriel: number; materielSeul: number } {
    let seul = 0, avecMateriel = 0, materielSeul = 0;
    for (const m of this.resourcesForSelectedTeam) {
      const o = this.offers.find(o => o.id === m.id);
      if (!o) continue;
      const estMateriel = o.materiel_type != null || o.materiel_livraison != null;
      // presence_physique déclaré explicitement à la soumission (voir propose-help-form) —
      // remplace l'ancienne heuristique (diplome_secourisme/transport_type), incapable de
      // distinguer un Transport/Matériel avec ou sans l'offreur. Null (offres antérieures à
      // ce champ) est traité comme présence pour ne pas changer leur classement rétroactivement.
      const estEnPersonne = !!o.author && o.presence_physique !== false;
      if (estMateriel && estEnPersonne) avecMateriel++;
      else if (estMateriel) materielSeul++;
      else seul++;
    }
    return { seul, avecMateriel, materielSeul };
  }

  // Même liste que propose-help-form.component.ts (materielTypeOptions) — dupliquée ici
  // volontairement, comme le reste de ce fichier le fait déjà pour de petites tables de
  // correspondance, plutôt que de créer un import partagé pour six libellés fixes.
  private readonly MATERIEL_TYPE_LABELS: Record<string, string> = {
    CUVE: 'Cuve', POMPE: 'Pompe', ETUVE: 'Étuve',
    CHAMBRE_FROIDE: 'Chambre froide', REMORQUE: 'Remorque', AUTRE: 'Autre',
  };

  offerFor(m: TeamMission): Offer | undefined {
    return this.offers.find(o => o.id === m.id);
  }

  /** Compétences déclarées par le bénévole sur cette ressource — vide pour du matériel seul. */
  resourceCompetencesLabel(m: TeamMission): string | null {
    const libelles = this.offerFor(m)?.competences_libelles;
    return libelles?.length ? libelles.join(', ') : null;
  }

  /** Matériel apporté avec la ressource — le catalogue partagé (nom libre) prime sur le type
   * générique quand l'offreur a précisé "Autre" avec un nom (voir propose-help-form). */
  resourceMaterielLabel(m: TeamMission): string | null {
    const o = this.offerFor(m);
    if (!o) return null;
    if (o.materiel_catalogue_nom) return o.materiel_catalogue_nom;
    if (o.materiel_type) return this.MATERIEL_TYPE_LABELS[o.materiel_type] || o.materiel_type;
    return null;
  }

  // ── Ressources : mission active + ajout/retrait ──────────────
  missionTitreInput = '';
  missionCriseId: string | null = null;

  submitDefinirMission(): void {
    if (!this.selectedTeam?.id || !this.missionTitreInput.trim()) return;
    this.teamService.definirMission(this.selectedTeam.id, this.missionTitreInput.trim(), this.missionCriseId ?? undefined).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.missionTitreInput = '';
        this.missionCriseId = null;
        this.reloadTeams();
        this.showSuccess('Mission de l\'équipe définie.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors de la définition de la mission.'),
    });
  }

  /** Crises ouvertes proposables pour la mission — une mission ne doit pas pouvoir se rattacher
   * à une crise déjà clôturée (voir validate_crisis_open côté backend). */
  get crisesOuvertes(): Crisis[] {
    return this.crisis.filter(c => !c.end_date);
  }

  retirerRessource(offerId: string): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.retirerRessource(this.selectedTeam.id, offerId).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.buildMissions(updated) };
        this.reloadTeams();
      },
      error: () => this.showError('Erreur lors du retrait de la ressource.'),
    });
  }

  ouvrirTableauOffres(): void {
    if (!this.selectedTeam?.id) return;
    this.router.navigate(['/admin/signalements'], { queryParams: { pickForTeam: this.selectedTeam.id } });
  }

  // ── Progression de l'engagement d'une ressource ───────────────
  private static readonly PROCHAIN_STATUT: Record<string, string> = {
    EN_ATTENTE: 'CONFIRME',
    CONFIRME: 'EN_TRANSIT',
    EN_TRANSIT: 'ARRIVE',
  };
  private static readonly LIBELLE_ACTION: Record<string, string> = {
    EN_ATTENTE: 'Confirmer',
    CONFIRME: 'Marquer en transit',
    EN_TRANSIT: 'Marquer arrivée',
  };

  /** Prochaine étape pour le bouton "Étape suivante" — null si aucun engagement ou déjà à un
   * statut terminal (ARRIVE/DECLINE, plus rien à faire avancer manuellement). */
  prochainStatutRessource(m: TeamMission): string | null {
    if (!m.engagementStatut) return null;
    return TeamsComponent.PROCHAIN_STATUT[m.engagementStatut] ?? null;
  }

  libelleActionRessource(m: TeamMission): string {
    return TeamsComponent.LIBELLE_ACTION[m.engagementStatut ?? ''] ?? '';
  }

  avancerStatutRessource(offerId: string, statut: string): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.definirStatutRessource(this.selectedTeam.id, offerId, statut).subscribe({
      next: (updated) => {
        this.offerService.getAll().subscribe(offers => {
          this.offers = offers;
          this.selectedTeam = { ...updated, missions: this.buildMissions(updated) };
          this.reloadTeams();
        });
        this.showSuccess('Statut de la ressource mis à jour.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors de la mise à jour du statut.'),
    });
  }

  declinerRessource(offerId: string): void {
    this.avancerStatutRessource(offerId, 'DECLINE');
  }

  /** Résumé rapide sous le titre d'une mission : contact + statut, pour ne pas avoir à ouvrir
   * l'offre/la demande pour savoir qui l'a déclarée. */
  missionContact(m: TeamMission): string {
    if (m.kind === 'Offer') {
      const o = this.offers.find(o => o.id === m.id);
      return o ? `${o.first_name_offer} ${o.last_name_offer}` : '—';
    }
    if (m.kind === 'Request') {
      const r = this.requests.find(r => r.id === m.id);
      return r ? `${r.first_name_request} ${r.last_name_request}` : '—';
    }
    return '—';
  }

  get filteredTeams(): Team[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.teams;
    return this.teams.filter(t =>
      t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
    );
  }

  get teamMembers(): User[] {
    if (!this.selectedTeam) return [];
    return this.selectedTeam.member_ids.map(id => this.getUserById(id)).filter(Boolean) as User[];
  }

  /** Dossiers de suivi rattachés à l'équipe (créés automatiquement lors de l'affectation
   * d'une demande, voir Request.assign_team côté backend — ou manuellement depuis cette vue,
   * voir showCreateDossierForm/submitCreerDossier, pour une mission sans demande d'origine). */
  get dossiersForSelectedTeam(): Dossier[] {
    if (!this.selectedTeam) return [];
    return this.dossiers.filter(d => d.equipe === this.selectedTeam!.id);
  }

  // ── DOSSIER SANS DEMANDE D'ORIGINE ────────────────────────────
  showCreateDossierForm = false;
  createDossierTitre = '';
  createDossierDescription = '';
  createDossierCriseId: string | null = null;
  createDossierPriorite = 'NORMALE';

  ouvrirCreationDossier(): void {
    this.showCreateDossierForm = true;
    this.createDossierTitre = '';
    this.createDossierDescription = '';
    this.createDossierCriseId = this.selectedTeam?.mission_active_crise_id ?? null;
    this.createDossierPriorite = 'NORMALE';
  }

  submitCreerDossier(): void {
    if (!this.selectedTeam?.id || !this.createDossierTitre.trim() || !this.createDossierDescription.trim() || !this.createDossierCriseId) {
      this.showError('Titre, description et crise sont obligatoires.');
      return;
    }
    this.teamService.creerDossier(this.selectedTeam.id, {
      titre: this.createDossierTitre.trim(),
      description: this.createDossierDescription.trim(),
      crise_id: this.createDossierCriseId,
      priorite: this.createDossierPriorite,
    }).subscribe({
      next: (dossier) => {
        this.dossiers = [...this.dossiers, dossier];
        this.showCreateDossierForm = false;
        this.showSuccess('Dossier créé.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors de la création du dossier.'),
    });
  }

  // ── POINTS DE REGROUPEMENT DES MOYENS ────────────────────────
  showLinkPointForm = false;
  showPointModal = false;
  pointSearchQuery = '';

  /** Points déjà rattachés à l'équipe (regroupement des moyens, carburant, restauration...). */
  get pointsForSelectedTeam(): PointOperationnel[] {
    if (!this.selectedTeam) return [];
    return this.points.filter(p => p.equipe === this.selectedTeam!.id);
  }

  /** Points pas encore rattachés à une équipe, candidats à lier depuis cette fiche — filtrés
   * par la recherche libre pour ne pas dérouler une liste sans fin sur une grosse plateforme. */
  get pointsCandidatsALier(): PointOperationnel[] {
    const q = this.pointSearchQuery.trim().toLowerCase();
    return this.points
      .filter(p => !p.equipe)
      .filter(p => !q || p.nom.toLowerCase().includes(q));
  }

  ouvrirLiaisonPoint(): void {
    this.showLinkPointForm = true;
    this.showPointModal = false;
    this.pointSearchQuery = '';
  }

  /** Ouvre la même modale de création que la vue crise (app-point-modal) — mêmes champs
   * (thème, titre, description, capacité, adresse, dates), avec l'équipe pré-sélectionnée et
   * sans crise obligatoire (un point de regroupement des moyens n'est pas forcément lié à une
   * crise précise). */
  ouvrirCreationPoint(): void {
    this.showPointModal = true;
    this.showLinkPointForm = false;
  }

  onPointCreated(point: PointOperationnel): void {
    this.points = [...this.points, point];
    this.showPointModal = false;
    this.showSuccess('Point créé et lié à l\'équipe.');
  }

  lierPoint(pointId: string): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.lierPoint(this.selectedTeam.id, pointId).subscribe({
      next: (point) => {
        this.points = [...this.points.filter(p => p.id !== point.id), point];
        this.showLinkPointForm = false;
        this.showSuccess('Point lié à l\'équipe.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors de la liaison du point.'),
    });
  }

  delierPoint(pointId: string): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.delierPoint(this.selectedTeam.id, pointId).subscribe({
      next: () => {
        this.points = this.points.map(p => p.id === pointId ? { ...p, equipe: null, equipe_nom: null } : p);
        this.showSuccess('Point délié.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors du retrait du point.'),
    });
  }


  // ── HIÉRARCHIE D'ÉQUIPES (rattachement comme ressource) ──────
  showAttachTeamForm = false;
  attachTeamSearchQuery = '';

  ouvrirAttacheEquipe(): void {
    this.showAttachTeamForm = true;
    this.attachTeamSearchQuery = '';
  }

  /** Tous les descendants connus côté client (sous-équipes, sous-sous-équipes...) d'une équipe
   * — sert uniquement à ne pas proposer un choix qui créerait un cycle évident dans le
   * sélecteur ; la garde anti-cycle qui fait foi reste côté serveur. */
  private getDescendantIds(teamId: string): Set<string> {
    const descendants = new Set<string>();
    const queue = [teamId];
    while (queue.length > 0) {
      const currentId = queue.pop()!;
      const current = this.teams.find(t => t.id === currentId);
      for (const sous of current?.sous_equipes_info ?? []) {
        if (!descendants.has(sous.id)) {
          descendants.add(sous.id);
          queue.push(sous.id);
        }
      }
    }
    return descendants;
  }

  /** Équipes proposables comme sous-équipe : ni l'équipe elle-même, ni ses descendants déjà
   * connus, ni une équipe déjà rattachée ailleurs (le serveur refuserait, autant filtrer tout
   * de suite) — filtrées par la recherche libre. */
  get equipesCandidatesARattacher(): Team[] {
    if (!this.selectedTeam) return [];
    const excludedIds = this.getDescendantIds(this.selectedTeam.id!);
    excludedIds.add(this.selectedTeam.id!);
    const q = this.attachTeamSearchQuery.trim().toLowerCase();
    return this.teams
      .filter(t => !excludedIds.has(t.id!) && !t.equipe_parente)
      .filter(t => !q || t.name.toLowerCase().includes(q));
  }

  rattacherEquipe(equipeId: string): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.rattacherEquipe(this.selectedTeam.id, equipeId).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.showAttachTeamForm = false;
        this.reloadTeams();
        this.showSuccess('Équipe rattachée.');
      },
      error: (err) => this.showError(err?.error?.error || "Erreur lors du rattachement de l'équipe."),
    });
  }

  detacherSousEquipe(equipeId: string): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.detacherEquipe(this.selectedTeam.id, equipeId).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.reloadTeams();
        this.showSuccess('Équipe détachée.');
      },
      error: (err) => this.showError(err?.error?.error || "Erreur lors du détachement de l'équipe."),
    });
  }

  seDetacherDeParente(): void {
    if (!this.selectedTeam?.id || !this.selectedTeam.equipe_parente) return;
    this.teamService.detacherEquipe(this.selectedTeam.equipe_parente, this.selectedTeam.id).subscribe({
      next: () => {
        this.selectedTeam = { ...this.selectedTeam!, equipe_parente: null, equipe_parente_nom: null };
        this.reloadTeams();
        this.showSuccess('Équipe détachée de sa parente.');
      },
      error: (err) => this.showError(err?.error?.error || "Erreur lors du détachement de l'équipe."),
    });
  }

  /** Résumé rapide de disponibilité d'un membre, affiché directement dans la liste plutôt que
   * de devoir ouvrir le planning complet pour savoir qui est là. */
  memberAvailability(userId: string): { hasAny: boolean; label: string } {
    const dispos = this.disposForMember(userId);
    if (dispos.length === 0) {
      return { hasAny: false, label: 'Aucune disponibilité déclarée' };
    }
    const next = [...dispos].sort((a, b) => a.date.localeCompare(b.date))[0];
    const jourLabel = new Date(next.date).toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' });
    const creneauLabel = this.CRENEAUX.find(c => c.creneau === next.creneau)?.label ?? next.creneau;
    return { hasAny: true, label: `Dispo. ${jourLabel} ${creneauLabel}` };
  }

  get leaderName(): string {
    return this.selectedTeam?.leader ? this.userName(this.selectedTeam.leader) : '—';
  }

  // ── PLANNING DISPONIBILITÉS ─────────────────────────────────────
  openPlanning(): void {
    this.modal = 'planning';
  }

  private readonly CRENEAUX: { creneau: string; label: string }[] = [
    { creneau: 'MATIN', label: 'Matin' },
    { creneau: 'MIDI', label: 'Midi' },
    { creneau: 'SOIR', label: 'Soir' },
    { creneau: 'NUIT', label: 'Nuit' },
  ];

  /** Disponibilités déclarées par un membre : celles de toutes les offres d'aide dont il est
   * l'auteur (les disponibilités sont rattachées à une offre, pas directement à l'utilisateur). */
  private disposForMember(userId: string): DisponibiliteOffre[] {
    const offerIds = new Set(this.offers.filter(o => o.author === userId).map(o => o.id));
    return this.disponibilites.filter(d => offerIds.has(d.offer));
  }

  /** Colonnes du planning : une par (date, créneau) réellement déclaré par au moins un membre,
   * triées par date puis par ordre matin→nuit. */
  get planningColonnes(): { date: string; creneau: string; label: string; jourLabel: string }[] {
    if (!this.selectedTeam) return [];
    const dateSet = new Set<string>();
    for (const member of this.teamMembers) {
      for (const d of this.disposForMember(member.id)) dateSet.add(d.date);
    }
    const dates = [...dateSet].sort();
    const colonnes: { date: string; creneau: string; label: string; jourLabel: string }[] = [];
    for (const date of dates) {
      const jourLabel = new Date(date).toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' });
      for (const c of this.CRENEAUX) {
        colonnes.push({ date, creneau: c.creneau, label: c.label, jourLabel });
      }
    }
    return colonnes;
  }

  planningDisponible(memberId: string, date: string, creneau: string): boolean {
    return this.disposForMember(memberId).some(d => d.date === date && d.creneau === creneau);
  }
  private showSuccess(msg: string): void {
    this.successMessage = msg;
    setTimeout(() => this.successMessage = '', 3000);
  }
  private showError(msg: string): void {
    this.errorMessage = msg;
    setTimeout(() => this.errorMessage = '', 5000);
  }

  fmtDate(d?: string): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  // Helpers

  get filteredUsers() {
    const q = this.memberSearchQuery.trim().toLowerCase();
    if (!q) return this.candidateMembers;
    return this.candidateMembers.filter(u =>
      u.first_name?.toLowerCase().includes(q) ||
      u.last_name?.toLowerCase().includes(q)  ||
      u.username?.toLowerCase().includes(q)
    );
  }
  get filteredRequests() {
    const q = this.missionSearchQuery.trim().toLowerCase();
    if (!q) return this.requests;
    return this.requests.filter(d => d.title?.toLowerCase().includes(q));
  }
}