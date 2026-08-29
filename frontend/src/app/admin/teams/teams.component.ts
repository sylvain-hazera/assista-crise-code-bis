import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { TeamService }       from '../../services/team.service';
import { UserService }       from '../../services/user.service';
import { CrisisService }     from '../../services/crisis.service';
import { OfferService }      from '../../services/offer.service';
import { RequestService }    from '../../services/request.service';
import { DisponibiliteOffreService } from '../../services/disponibilite-offre.service';
import { DossierService } from '../../services/dossier.service';
import { CompetenceService } from '../../services/competence.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { ZoneMapComponent } from '../../shared/components/common/zone-map/zone-map.component';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

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

type ModalView = 'none' | 'create' | 'detail' | 'edit' | 'delete' | 'assign' | 'planning';
type AssignTab = 'Crisis' | 'Offer' | 'Request';

const COLORS = ['#ef4444','#f97316','#eab308','#22c55e','#06b6d4','#3b82f6','#8b5cf6','#ec4899'];

@Component({
  selector: 'app-teams',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, ZoneMapComponent, TagSearchInputComponent],
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
  readonly assignTabs: AssignTab[] = ['Crisis', 'Offer', 'Request'];
  assignTab: AssignTab      = 'Crisis';

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
    private crisisService:  CrisisService,
    private offerService:   OfferService,
    private requestService: RequestService,
    private disponibiliteOffreService: DisponibiliteOffreService,
    private dossierService: DossierService,
    private competenceService: CompetenceService,
    private roleOperationnelService: RoleOperationnelService,
  ) {}

  ngOnInit(): void {
    this.buildForms();
    this.loadRemoteData();
  }

  // ── Load ─────────────────────────────────────────────────────
  private loadRemoteData(): void {
    this.isLoading = true;
    forkJoin({
      users:    this.userService.getAll(),
      crisis:   this.crisisService.getAll(),
      offers:   this.offerService.getAll(),
      requests: this.requestService.getAll(),
      teams:    this.teamService.getAll(),       // ← ajouté ici
      disponibilites: this.disponibiliteOffreService.getAll(),
      dossiers: this.dossierService.getAll(),
      competences: this.competenceService.getAll(),
      roles: this.roleOperationnelService.getAll(),
    }).subscribe({
      next: ({ users, crisis, offers, requests, teams, disponibilites, dossiers, competences, roles }) => {
        this.users    = users;
        this.crisis   = crisis;
        this.offers   = offers;
        this.requests = requests;
        this.disponibilites = disponibilites;
        this.dossiers = dossiers;
        this.competences = competences;
        this.roles = roles;
        this.teams    = teams.map(t => ({ ...t, missions: this.buildMissions(t) }));
        this.isLoading = false;
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
      if (o) missions.push({ id, kind: 'Offer', titre: o.title, statut: o.status, date: o.created_at });
    }
    for (const id of team.assigned_request_ids ?? []) {
      const r = this.requests.find(r => r.id === id);
      if (r) missions.push({ id, kind: 'Request', titre: r.title, statut: r.status, date: r.created_at });
    }
    return missions;
  }

  reloadTeams(): void {
    this.teamService.getAll().subscribe(teams => {
      this.teams = teams.map(t => ({ ...t, missions: this.buildMissions(t) }));
    });
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
    this.loadCandidateMembers(team);
  }

  /** Ne propose comme candidats à l'ajout QUE les membres de l'institution de cette équipe —
   * avant ce correctif, tous les comptes de la plateforme (admins, secours, particuliers sans
   * lien avec cette mairie...) apparaissaient dans le sélecteur. Vide si l'équipe n'a pas
   * d'institution (rien de pertinent à proposer). */
  private loadCandidateMembers(team: Team): void {
    if (!team.institution) {
      this.candidateMembers = [];
      return;
    }
    this.userService.getAll({ institution: team.institution }).subscribe({
      next: (users) => this.candidateMembers = users,
      error: () => this.candidateMembers = [],
    });
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
      next: () => { this.reloadTeams(); this.showSuccess('Équipe supprimée.'); this.closeModal(); },
      error: () => this.showError('Erreur lors de la suppression.'),
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
    this.assignTab    = 'Crisis';
    this.modal        = 'assign';
  }

  toggleMission(id: string, kind: AssignTab, titre: string, statut?: string, date?: string): void {
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

    // Affecter une offre à l'équipe y ajoute aussi la personne qui la propose : sinon on
    // affecte une "mission" sans jamais rattacher le bénévole lui-même à l'équipe.
    let memberIds = team.member_ids ?? [];
    if (!exists && kind === 'Offer') {
      const authorId = this.offers.find(o => o.id === id)?.author;
      if (authorId && !memberIds.includes(authorId)) {
        memberIds = [...memberIds, authorId];
      }
    }

    this.teamService.patch(team.id!, {
      assigned_crisis_ids:  crisisIds,
      assigned_offer_ids:   offerIds,
      assigned_request_ids: requestIds,
      member_ids:           memberIds,
    }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions };
      this.reloadTeams();
    });
  }

  isMissionAssigned(id: string, kind: AssignTab): boolean {
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

  /** Missions groupées par type (crises / offres / demandes) pour ne pas tout mélanger dans une
   * même liste plate. */
  get missionsByKind(): { kind: TeamMission['kind']; missions: TeamMission[] }[] {
    if (!this.selectedTeam) return [];
    return (['Crisis', 'Offer', 'Request'] as TeamMission['kind'][])
      .map(kind => ({ kind, missions: this.selectedTeam!.missions.filter(m => m.kind === kind) }))
      .filter(g => g.missions.length > 0);
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
   * d'une demande, voir Request.assign_team côté backend). */
  get dossiersForSelectedTeam(): Dossier[] {
    if (!this.selectedTeam) return [];
    return this.dossiers.filter(d => d.equipe === this.selectedTeam!.id);
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
  get filteredCrisis() {
    const q = this.missionSearchQuery.trim().toLowerCase();
    if (!q) return this.crisis;
    return this.crisis.filter(c => c.name?.toLowerCase().includes(q));
  }
  get filteredOffers() {
    const q = this.missionSearchQuery.trim().toLowerCase();
    if (!q) return this.offers;
    return this.offers.filter(o => o.title?.toLowerCase().includes(q));
  }
  get filteredRequests() {
    const q = this.missionSearchQuery.trim().toLowerCase();
    if (!q) return this.requests;
    return this.requests.filter(d => d.title?.toLowerCase().includes(q));
  }
}