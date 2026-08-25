import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { TeamService }       from '../../services/team.service';
import { UserService }       from '../../services/user.service';
import { CrisisService }     from '../../services/crisis.service';
import { OfferService }      from '../../services/offer.service';
import { RequestService }    from '../../services/request.service';

import { Team, TeamMission }  from '../../shared/models/team.model';
import { User }        from '../../shared/models/user.model';
import { Crisis }              from '../../shared/models/crisis.model';
import { Offer }              from '../../shared/models/offer.model';
import { Request }            from '../../shared/models/request.model';
import { Status }             from '../../shared/models/status.model';

type ModalView = 'none' | 'create' | 'detail' | 'edit' | 'delete' | 'assign';
type AssignTab = 'Crisis' | 'Offer' | 'Request';

const COLORS = ['#ef4444','#f97316','#eab308','#22c55e','#06b6d4','#3b82f6','#8b5cf6','#ec4899'];

@Component({
  selector: 'app-teams',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule],
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

  readonly COLORS = COLORS;
  selectedColor = COLORS[5];

  constructor(
    private fb:          FormBuilder,
    private teamService: TeamService,
    private userService: UserService,
    private crisisService:  CrisisService,
    private offerService:   OfferService,
    private requestService: RequestService,
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
    }).subscribe({
      next: ({ users, crisis, offers, requests, teams }) => {
        this.users    = users;
        this.crisis   = crisis;
        this.offers   = offers;
        this.requests = requests;
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
    };
    this.teamService.create(payload).subscribe({
      next: () => { this.reloadTeams(); this.showSuccess('Équipe créée.'); this.closeModal(); },
      error: () => this.showError('Erreur lors de la création.'),
    });
  }


  // ── DETAIL ────────────────────────────────────────────────────
  openDetail(team: Team): void {
    this.selectedTeam = team;
    this.modal = 'detail';
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

    this.teamService.patch(team.id!, {
      assigned_crisis_ids:  crisisIds,
      assigned_offer_ids:   offerIds,
      assigned_request_ids: requestIds,
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

  get leaderName(): string {
    return this.selectedTeam?.leader ? this.userName(this.selectedTeam.leader) : '—';
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
    if (!q) return this.users;
    return this.users.filter(u =>
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