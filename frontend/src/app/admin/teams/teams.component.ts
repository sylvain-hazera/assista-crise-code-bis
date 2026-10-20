import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin, Observable, of, map } from 'rxjs';
import { catchError } from 'rxjs/operators';
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from 'geojson';

import { TeamService }       from '../../services/team.service';
import { UserService }       from '../../services/user.service';
import { InstitutionService } from '../../services/institution.service';
import { LocationService, Commune, Department } from '../../services/location.service';
import { CrisisService }     from '../../services/crisis.service';
import { OfferService }      from '../../services/offer.service';
import { RequestService }    from '../../services/request.service';
import { DisponibiliteOffreService } from '../../services/disponibilite-offre.service';
import { DossierService } from '../../services/dossier.service';
import { CompetenceService } from '../../services/competence.service';
import { BesoinService } from '../../services/besoin.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { AffectationRoleOperationnelService } from '../../services/affectation-role-operationnel.service';
import { AuditLogService, AuditLogEntry } from '../../services/audit-log.service';
import { DossierHistoriqueService } from '../../services/dossier-historique.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { MissionService } from '../../services/mission.service';
import { AuthService } from '../../auth/services/auth.service';
import { ZoneMapComponent } from '../../shared/components/common/zone-map/zone-map.component';
import { MinimapComponent } from '../../shared/components/common/minimap/minimap.component';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';
import { PointModalComponent } from '../crises/point-modal/point-modal.component';
import { MatrixSalonChatComponent } from './matrix-salon-chat/matrix-salon-chat.component';
import { environment } from '../../../environments/environment';

import { Team, TeamMission }  from '../../shared/models/team.model';
import { User }        from '../../shared/models/user.model';
import { RoleOperationnel, AffectationRoleOperationnel } from '../../shared/models/institution.model';
import { Crisis }              from '../../shared/models/crisis.model';
import { Offer }              from '../../shared/models/offer.model';
import { Request }            from '../../shared/models/request.model';
import { Status }             from '../../shared/models/status.model';
import { DisponibiliteOffre } from '../../shared/models/disponibilite-offre.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Competence } from '../../shared/models/competence.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Institution } from '../../shared/models/institution.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';

type ModalView = 'none' | 'create' | 'detail' | 'edit' | 'delete' | 'assign' | 'planning';

const COLORS = ['#ef4444','#f97316','#eab308','#22c55e','#06b6d4','#3b82f6','#8b5cf6','#ec4899'];

/** Élément de la recherche « Savoir-faire » du bloc Mission : une compétence ou une
 * spécialité (Besoin), distinguées par estSpecialite. */
type SavoirFaire = (Competence | Besoin) & { sorte?: string; estSpecialite?: boolean };

@Component({
  selector: 'app-teams',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink, ZoneMapComponent, MinimapComponent, TagSearchInputComponent, PointModalComponent, MatrixSalonChatComponent],
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
  besoins: Besoin[] = [];
  roles: RoleOperationnel[] = [];
  affectationsRoles: AffectationRoleOperationnel[] = [];
  institutions: Institution[] = [];
  points: PointOperationnel[] = [];
  pointTypes: PointType[] = [];

  /** Candidats de l'équipe sélectionnée (scopés sur son institution) ; `users` reste la liste
   * globale pour afficher les membres déjà affectés. */
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
    private locationService: LocationService,
    private crisisService:  CrisisService,
    private offerService:   OfferService,
    private requestService: RequestService,
    private disponibiliteOffreService: DisponibiliteOffreService,
    private dossierService: DossierService,
    private competenceService: CompetenceService,
    private besoinService: BesoinService,
    private roleOperationnelService: RoleOperationnelService,
    private affectationRoleService: AffectationRoleOperationnelService,
    private auditLogService: AuditLogService,
    private dossierHistoriqueService: DossierHistoriqueService,
    private pointOperationnelService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private missionService: MissionService,
    public authService: AuthService,
    private route: ActivatedRoute,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.buildForms();
    this.loadRemoteData();
  }

  /** Retour depuis le tableau des offres (mode picker) : rouvre le détail de l'équipe. */
  private openTeamFromQueryParam(): void {
    const openTeamId = this.route.snapshot.queryParamMap.get('openTeam');
    if (!openTeamId) return;
    const team = this.teams.find(t => t.id === openTeamId);
    if (team) {
      this.openDetail(team);
      this.router.navigate([], { relativeTo: this.route, queryParams: {} });
    }
  }

  // Les équipes désactivées sont masquées par le backend ; ?actif=all les fait réapparaître.
  showDesactives = false;

  // ── Load ─────────────────────────────────────────────────────
  /** En deux temps (page lente, demande utilisateur du 20/10/2026) : la page s'affiche dès que
   * les équipes et les petites listes dont dépendent les cartes sont là ; offres, demandes,
   * dossiers et points -- de loin le plus lourd, ~1,9 Mo en démo -- arrivent ensuite, puis les
   * missions affichées sont recalculées (voir chargerDonneesSecondaires). */
  private loadRemoteData(): void {
    this.isLoading = true;
    forkJoin({
      users:    this.userService.getAll(),
      crisis:   this.crisisService.getAll(),
      teams:    this.teamService.getAll(this.showDesactives),
      competences: this.competenceService.getAll(),
      besoins: this.besoinService.getAll(),
      roles: this.roleOperationnelService.getAll(),
      affectationsRoles: this.affectationRoleService.getAll(),
      institutions: this.institutionService.getAll(),
      pointTypes: this.pointTypeService.getAll(),
    }).subscribe({
      next: ({ users, crisis, teams, competences, besoins, roles, affectationsRoles, institutions, pointTypes }) => {
        this.users    = users;
        this.crisis   = crisis;
        this.competences = competences;
        this.besoins = besoins;
        this.roles = roles;
        this.affectationsRoles = affectationsRoles;
        this.institutions = institutions;
        this.pointTypes = pointTypes;
        this.teams    = teams.map(t => ({ ...t, missions: this.buildMissions(t) }));
        this.isLoading = false;
        this.openTeamFromQueryParam();
        this.chargerDonneesSecondaires();
      },
      error: () => {
        this.showError('Impossible de charger les données.');
        this.isLoading = false;
      },
    });
  }

  /** Vrai tant que offres/demandes/dossiers/points ne sont pas arrivés : les pastilles de
   * mission des cartes et les ressources de la fiche équipe se complètent à leur arrivée. */
  donneesSecondairesEnCours = false;

  private chargerDonneesSecondaires(): void {
    this.donneesSecondairesEnCours = true;
    forkJoin({
      // exclude_type=Bénévolat : l'annuaire permanent de bénévoles n'a pas vocation à être
      // proposé comme ressource affectable à une équipe (voir ReportingComponent.loadAll).
      offers:   this.offerService.getAll({ exclude_type: 'Bénévolat' }),
      requests: this.requestService.getAll(),
      dossiers: this.dossierService.getAll(),
      points: this.pointOperationnelService.getAll(),
    }).subscribe({
      next: ({ offers, requests, dossiers, points }) => {
        this.offers = offers;
        this.requests = requests;
        this.dossiers = dossiers;
        this.points = points;
        this.teams = this.teams.map(t => ({ ...t, missions: this.buildMissions(t) }));
        if (this.selectedTeam) {
          this.selectedTeam = { ...this.selectedTeam, missions: this.buildMissions(this.selectedTeam) };
        }
        this.donneesSecondairesEnCours = false;
        // Scopé aux offres déjà chargées ci-dessus plutôt qu'un getAll() séparé (27k+ lignes
        // mesurées sur cette table, sans rapport avec le nombre d'offres réellement affichées
        // ici) -- voir DisponibiliteOffreService.getByOffers.
        this.disponibiliteOffreService.getByOffers(offers.map(o => o.id!)).subscribe({
          next: (disponibilites) => { this.disponibilites = disponibilites; },
          error: () => {},
        });
      },
      error: () => {
        this.donneesSecondairesEnCours = false;
        this.showError('Impossible de charger les offres, demandes et dossiers des équipes.');
      },
    });
  }

  /** `missions` n'est pas renvoyé par l'API : projection locale des assigned_*_ids. */
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
      mission:   [''],   // facultative (non bloquante en crise), définie juste après la création
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
    const { name, description, leader, mission } = this.createForm.value;
    const missionTitre = (mission ?? '').trim();
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
      next: (team) => {
        this.closeModal();
        if (!missionTitre) {
          this.reloadTeams();
          this.showSuccess('Équipe créée — pensez à définir sa mission.');
          return;
        }
        // Équipe déjà créée à ce stade : un échec ne concerne que la mission, à redéfinir
        // depuis la fiche (et non « erreur lors de la création », trompeur).
        this.teamService.definirMission(team.id!, missionTitre).subscribe({
          next: () => { this.reloadTeams(); this.showSuccess('Équipe créée avec sa mission.'); },
          error: () => { this.reloadTeams(); this.showError("Équipe créée, mais la mission n'a pas pu être définie : redéfinissez-la depuis sa fiche."); },
        });
      },
      error: () => this.showError('Erreur lors de la création.'),
    });
  }

  // ── DETAIL ────────────────────────────────────────────────────
  openDetail(team: Team): void {
    this.selectedTeam = team;
    this.communeNoms = {};
    this.departementNoms = {};
    this.loadZoneCodeLabels(team);
    this.syncZoneMapCommunes(team);
    if (team.commune_centre?.latitude != null && team.commune_centre?.longitude != null) {
      this.zoneMapCenter = [team.commune_centre.longitude, team.commune_centre.latitude];
    }
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
    this.loadInstitutionsDelegables(team);
    this.loadHistory(team);
  }

  // ── HISTORIQUE ────────────────────────────────────────────────
  auditEntries: AuditLogEntry[] = [];
  dossierHistoriqueEntries: any[] = [];
  historyLoading = false;

  /** Timeline fusionnée : main courante de l'équipe + historique de ses dossiers. */
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

  /** Candidats à l'ajout : membres de l'institution responsable, de la délégataire et des
   * institutions liées (TeamViewSet.institutions_liees). Vide sans institution. */
  private loadCandidateMembers(team: Team): void {
    const ownInstitutionIds = [team.institution, team.institution_delegataire].filter((id): id is string => !!id);
    if (ownInstitutionIds.length === 0 || !team.id) {
      this.candidateMembers = [];
      return;
    }
    this.teamService.institutionsLiees(team.id).pipe(
      catchError(() => of([] as { id: string; nom: string }[])),
    ).subscribe(liees => {
      const institutionIds = [...new Set([...ownInstitutionIds, ...liees.map(i => i.id)])];
      this.userService.getAll({ institution: institutionIds }).subscribe({
        next: (users) => this.candidateMembers = users,
        error: () => this.candidateMembers = [],
      });
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

  /** Bascule est_equipe_rcsc : ouvre le registre des personnes vulnérables à l'institution
   * (core/vulnerabilites.py). Le contrôle réel est côté serveur. */
  designerRcsc(): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.designerRcsc(this.selectedTeam.id).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.reloadTeams();
        this.showSuccess(updated.est_equipe_rcsc ? 'Équipe désignée comme RCSC.' : 'Désignation RCSC retirée.');
      },
      error: (err) => this.showError(err?.error?.detail || 'Erreur lors de la désignation RCSC.'),
    });
  }

  /** Délégataires possibles : institutions ACTEUR d'une crise où l'institution de l'équipe est
   * impliquée (institutions_liees?type=acteur). */
  institutionsDelegables: { id: string; nom: string }[] = [];

  private loadInstitutionsDelegables(team: Team): void {
    if (!team.id) { this.institutionsDelegables = []; return; }
    this.teamService.institutionsLiees(team.id, 'acteur').pipe(
      catchError(() => of([] as { id: string; nom: string }[])),
    ).subscribe(institutions => this.institutionsDelegables = institutions);
  }

  // ── ZONE D'INTERVENTION ─────────────────────────────────────────
  communeNoms: Record<string, string> = {};
  communePostaux: Record<string, string> = {};
  departementNoms: Record<string, string> = {};
  pendingZoneWkt: string | null = null;
  /** Contours des communes de la zone, pour la carte « Zone d'intervention ». */
  zoneMapCommunesGeojson: FeatureCollection<Polygon | MultiPolygon> | null = null;
  /** Recentré sur la commune de l'équipe à l'ouverture du détail. */
  zoneMapCenter: [number, number] = [2.2137, 46.2276];
  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);
  departementSearchFn = (q: string) => {
    const query = q.trim().toLowerCase();
    return this.locationService.getDepartments().pipe(
      map(deps => deps.filter(d => d.name.toLowerCase().includes(query) || d.code === query).slice(0, 10)),
    );
  };

  /** Le backend ne stocke que des codes : résout les noms pour les chips (lecture seule). */
  private loadZoneCodeLabels(team: Team): void {
    (team.communes ?? []).forEach(code => {
      this.locationService.getCommuneName(code).subscribe(c => {
        this.communeNoms[c.code] = c.name;
        if (c.codePostal) this.communePostaux[c.code] = c.codePostal;
      });
    });
    (team.departements ?? []).forEach(code => {
      this.locationService.getDepartementName(code).subscribe(d => this.departementNoms[d.code] = d.name);
    });
  }

  /** Chaque contour est ajouté dès réception (pas de forkJoin) : une commune en échec ne bloque
   * pas les autres. */
  private syncZoneMapCommunes(team: Team): void {
    const codes = team.communes ?? [];
    const features: Feature<Polygon | MultiPolygon>[] = [];
    this.zoneMapCommunesGeojson = codes.length ? { type: 'FeatureCollection', features: [] } : null;
    codes.forEach(code => {
      this.locationService.getCommuneContour(code).subscribe(c => {
        if (!c.contour) return;
        features.push({ type: 'Feature', properties: {}, geometry: c.contour });
        this.zoneMapCommunesGeojson = { type: 'FeatureCollection', features: [...features] };
      });
    });
  }

  addZoneCommune(commune: Commune): void {
    const team = this.selectedTeam;
    if (!team?.id || (team.communes ?? []).includes(commune.code)) return;
    this.communeNoms[commune.code] = commune.name;
    if (commune.codePostal) this.communePostaux[commune.code] = commune.codePostal;
    this.teamService.patch(team.id, { communes: [...(team.communes ?? []), commune.code] }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.syncZoneMapCommunes(this.selectedTeam);
      this.reloadTeams();
    });
  }

  removeZoneCommune(code: string): void {
    const team = this.selectedTeam;
    if (!team?.id) return;
    this.teamService.patch(team.id, { communes: (team.communes ?? []).filter(c => c !== code) }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.syncZoneMapCommunes(this.selectedTeam);
      this.reloadTeams();
    });
  }

  addZoneDepartement(dept: Department): void {
    const team = this.selectedTeam;
    if (!team?.id || (team.departements ?? []).includes(dept.code)) return;
    this.departementNoms[dept.code] = dept.name;
    this.teamService.patch(team.id, { departements: [...(team.departements ?? []), dept.code] }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
    });
  }

  removeZoneDepartement(code: string): void {
    const team = this.selectedTeam;
    if (!team?.id) return;
    this.teamService.patch(team.id, { departements: (team.departements ?? []).filter(c => c !== code) }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
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
    this.confirmerSuppressionDefinitive = false;
    this.modal = 'delete';
  }

  confirmDelete(): void {
    if (!this.selectedTeam?.id) return;
    this.teamService.delete(this.selectedTeam.id).subscribe({
      next: () => { this.reloadTeams(); this.showSuccess('Équipe désactivée.'); this.closeModal(); },
      error: () => this.showError('Erreur lors de la désactivation.'),
    });
  }

  /** Suppression définitive (demande utilisateur du 20/10) : 2e confirmation dans la modale,
   * réservée côté serveur à l'institution responsable ou à un administrateur. */
  confirmerSuppressionDefinitive = false;

  supprimerDefinitivement(): void {
    if (!this.selectedTeam?.id || !this.confirmerSuppressionDefinitive) return;
    const nom = this.selectedTeam.name;
    this.isSaving = true;
    this.teamService.supprimer(this.selectedTeam.id).subscribe({
      next: () => {
        this.isSaving = false;
        this.reloadTeams();
        this.showSuccess(`Équipe « ${nom} » supprimée définitivement.`);
        this.closeModal();
      },
      error: (err) => {
        this.isSaving = false;
        this.showError(err?.error?.error || 'Erreur lors de la suppression.');
      },
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

  /** Rôle opérationnel actif du membre dans l'institution de l'équipe (le rôle appartient à
   * l'institution, pas à l'équipe : AffectationRoleOperationnel). null si aucun. */
  private memberRoleAffectation(userId: string): AffectationRoleOperationnel | null {
    if (!this.selectedTeam?.institution) return null;
    return this.affectationsRoles.find(a =>
      a.utilisateur === userId && a.institution === this.selectedTeam!.institution && a.actif
    ) ?? null;
  }

  memberRoleId(userId: string): string {
    return this.memberRoleAffectation(userId)?.role ?? '';
  }

  /** Crée ou modifie le rôle d'un membre ; roleId vide désactive l'affectation (sans suppression). */
  setMemberRole(userId: string, roleId: string): void {
    if (!this.selectedTeam?.institution) return;
    const institutionId = this.selectedTeam.institution;
    const existing = this.memberRoleAffectation(userId);

    if (existing?.id) {
      // PUT : utilisateur/institution/role sont requis même pour ne changer que actif ou role.
      this.affectationRoleService.update(existing.id, {
        utilisateur: userId, institution: institutionId,
        role: roleId || existing.role, actif: !!roleId,
      }).subscribe(updated => {
        this.affectationsRoles = this.affectationsRoles.map(a => a.id === updated.id ? updated : a);
      });
    } else if (roleId) {
      this.affectationRoleService.create({
        utilisateur: userId, institution: institutionId, role: roleId, actif: true,
      }).subscribe(created => {
        this.affectationsRoles = [...this.affectationsRoles, created];
      });
    }
  }

  /** Invite un membre dans l'institution et l'ajoute à l'équipe, même avant activation du compte. */
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
  competencesDropdownOpen = false;   // panneau « Parcourir » du savoir-faire (bloc Mission)

  /** Groupe les compétences par parent ; chaque thème reste sélectionnable. */
  get competenceGroups(): { parent: Competence; children: Competence[] }[] {
    const topLevel = this.competences.filter(c => !c.parent);
    return topLevel.map(parent => ({
      parent,
      children: this.competences.filter(c => c.parent === parent.id),
    }));
  }

  get selectedCompetences(): Competence[] {
    return this.competences.filter(c => this.hasCompetence(c.id));
  }

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

  // Sous-thèmes repliés par défaut.
  expandedCompetenceGroups = new Set<string>();

  toggleCompetenceGroupExpand(parentId: string): void {
    if (this.expandedCompetenceGroups.has(parentId)) this.expandedCompetenceGroups.delete(parentId);
    else this.expandedCompetenceGroups.add(parentId);
  }

  isCompetenceGroupExpanded(parentId: string): boolean {
    return this.expandedCompetenceGroups.has(parentId);
  }

  /** État de la case parent (coché / indéterminé / décoché) selon ses sous-thèmes. */
  competenceGroupState(group: { parent: Competence; children: Competence[] }): 'all' | 'some' | 'none' {
    const ids = [group.parent.id, ...group.children.map(c => c.id)];
    const selected = ids.filter(id => this.hasCompetence(id)).length;
    if (selected === 0) return 'none';
    return selected === ids.length ? 'all' : 'some';
  }

  /** Coche ou décoche le thème parent et tous ses sous-thèmes. */
  toggleCompetenceGroup(group: { parent: Competence; children: Competence[] }): void {
    if (!this.selectedTeam) return;
    const groupIds = [group.parent.id, ...group.children.map(c => c.id)];
    const current = new Set(this.selectedTeam.competence_ids ?? []);
    const tout = groupIds.every(id => current.has(id));
    for (const id of groupIds) {
      if (tout) current.delete(id);
      else current.add(id);
    }
    this.teamService.patch(this.selectedTeam.id!, { competence_ids: Array.from(current) }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
    });
  }

  libelleCreerCompetence = (nom: string) => `Créer la compétence « ${nom} »`;

  /** Domaines proposables à une équipe : les besoins qualifiés (nature posée), groupe puis
   * éléments -- sans les signalements de situation (« Route barrée », « Danger imminent »…),
   * qui ne sont pas un domaine qu'une équipe prend en charge. */
  get domainesProposables(): Besoin[] {
    const qualifies = this.besoins.filter(b => b.nature);
    const racines = qualifies.filter(b => !b.parent).sort((a, b) => a.nom.localeCompare(b.nom));
    return racines.flatMap(r => [r, ...qualifies.filter(b => b.parent === r.id).sort((a, b) => a.nom.localeCompare(b.nom))]);
  }

  /** Recherche du bloc Mission : domaines d'abord (liste courte déjà chargée), puis
   * compétences précises (serveur) -- `sorte` les distingue dans le menu. */
  savoirFaireSearchFn = (q: string): Observable<SavoirFaire[]> => {
    const terme = q.trim().toLowerCase();
    const domaines = this.domainesProposables
      .filter(b => b.nom.toLowerCase().includes(terme))
      .map(b => ({ ...b, sorte: 'domaine', estSpecialite: true }));
    return this.competenceService.search(q).pipe(
      map(competences => [...domaines, ...competences.map(c => ({ ...c, sorte: 'compétence précise', estSpecialite: false }))]),
    );
  };

  savoirFaireCreateFn = (nom: string): Observable<SavoirFaire> => this.competenceService.create({ nom });

  onSavoirFaireSelected(item: SavoirFaire): void {
    if (item.estSpecialite) {
      if (!this.hasTheme(item.id)) this.toggleTheme(item.id);
      return;
    }
    const competence = item as Competence;
    if (!this.competences.find(c => c.id === competence.id)) {
      this.competences = [...this.competences, competence];
    }
    if (!this.hasCompetence(competence.id)) {
      this.toggleCompetence(competence.id);
    }
  }

  // ── DOMAINES D'INTERVENTION (Team.themes, des Besoin, ex: "Hébergement") ────
  // Ce que l'équipe prend en charge : ouvre les vues dédiées (voir HebergementMatchingComponent)
  // et, côté serveur, ajoute/retire les compétences liées (_synchroniser_competences_des_domaines)
  // -- la réponse du PATCH porte donc aussi les competence_ids à jour.
  toggleTheme(themeId: string): void {
    if (!this.selectedTeam) return;
    const ids = this.selectedTeam.theme_ids ?? [];
    const newIds = ids.includes(themeId) ? ids.filter(id => id !== themeId) : [...ids, themeId];
    this.teamService.patch(this.selectedTeam.id!, { theme_ids: newIds }).subscribe(updated => {
      this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
      this.reloadTeams();
    });
  }

  hasTheme(themeId: string): boolean {
    return this.selectedTeam?.theme_ids?.includes(themeId) ?? false;
  }

  get selectedThemes(): Besoin[] {
    return this.besoins.filter(b => this.hasTheme(b.id));
  }

  besoinHebergementId(): string {
    return this.besoins.find(b => b.nom === 'Hébergement')?.id ?? '';
  }

  // ── ASSIGN MISSIONS ───────────────────────────────────────────
  openAssign(team: Team, e?: Event): void {
    e?.stopPropagation();
    this.selectedTeam = team;
    this.modal        = 'assign';
    // Sélection locale initialisée sur l'état réellement assigné.
    this.stagedRequestIds = new Set(team.missions.filter(m => m.kind === 'Request').map(m => m.id));
  }

  // Sélection en attente : aucun appel réseau avant « Valider la sélection » (voir DOCUMENTATION.md, § 6.2).
  stagedRequestIds = new Set<string>();
  savingSelection = false;

  toggleStagedRequest(id: string): void {
    if (this.stagedRequestIds.has(id)) this.stagedRequestIds.delete(id);
    else this.stagedRequestIds.add(id);
  }

  isRequestStaged(id: string): boolean {
    return this.stagedRequestIds.has(id);
  }

  get stagedSelectionChanged(): boolean {
    if (!this.selectedTeam) return false;
    const current = new Set(this.selectedTeam.missions.filter(m => m.kind === 'Request').map(m => m.id));
    if (current.size !== this.stagedRequestIds.size) return true;
    for (const id of current) if (!this.stagedRequestIds.has(id)) return true;
    return false;
  }

  /** Applique la sélection en un appel : c'est ici que se font la création de dossier, les
   * notifications et l'email au demandeur. Crises et offres sont renvoyées inchangées. */
  validerSelectionDemandes(): void {
    if (!this.selectedTeam || this.savingSelection) return;
    const team = this.selectedTeam;
    const crisisIds = team.missions.filter(m => m.kind === 'Crisis').map(m => m.id);
    const offerIds  = team.missions.filter(m => m.kind === 'Offer').map(m => m.id);
    const requestIds = Array.from(this.stagedRequestIds);

    this.savingSelection = true;
    this.teamService.patch(team.id!, {
      assigned_crisis_ids:  crisisIds,
      assigned_offer_ids:   offerIds,
      assigned_request_ids: requestIds,
    }).subscribe({
      next: (updated) => {
        const missions = [
          ...team.missions.filter(m => m.kind !== 'Request'),
          ...requestIds.map(id => {
            const r = this.requests.find(r => r.id === id);
            return { id, kind: 'Request' as const, titre: r?.title ?? '', statut: r?.status, date: r?.created_at };
          }),
        ];
        this.selectedTeam = { ...updated, missions };
        this.savingSelection = false;
        this.reloadTeams();
        this.showSuccess(
          requestIds.length > 0
            ? `${requestIds.length} demande${requestIds.length > 1 ? 's' : ''} affectée${requestIds.length > 1 ? 's' : ''} à l'équipe.`
            : 'Sélection mise à jour : aucune demande affectée.'
        );
      },
      error: () => { this.savingSelection = false; },
    });
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

    // Les offres passent par assignerRessource/retirerRessource ; offerIds est recalculé pour ne
    // pas écraser les ressources affectées.
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

  // ── DÉTAIL D'UNE DEMANDE (modal assign) ─────────────────────────
  // Détail repliable d'une demande (minimap, photo, coordonnées), une seule dépliée à la fois.
  expandedRequestId: string | null = null;
  requestPhotoUrls: Record<string, string> = {};

  toggleExpandRequest(request: Request, e: Event): void {
    e.stopPropagation();
    if (this.expandedRequestId === request.id) {
      this.expandedRequestId = null;
      return;
    }
    this.expandedRequestId = request.id;
    if (request.has_photo && !this.requestPhotoUrls[request.id]) {
      this.requestService.preview(request.id).subscribe({
        next: (blob) => this.requestPhotoUrls[request.id] = URL.createObjectURL(blob),
        error: () => {},
      });
    }
  }

  // ── HELPERS ───────────────────────────────────────────────────
  closeModal(): void {
    this.modal = 'none';
    this.selectedTeam = null;
    this.expandedRequestId = null;
    Object.values(this.requestPhotoUrls).forEach(url => URL.revokeObjectURL(url));
    this.requestPhotoUrls = {};
  }

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

  /** Demandes assignées à l'équipe (la crise est portée par la mission, les offres par
   * resourcesForSelectedTeam). */
  get missionsByKind(): { kind: TeamMission['kind']; missions: TeamMission[] }[] {
    if (!this.selectedTeam) return [];
    return (['Request'] as TeamMission['kind'][])
      .map(kind => ({ kind, missions: this.selectedTeam!.missions.filter(m => m.kind === kind) }))
      .filter(g => g.missions.length > 0);
  }

  get missionsCount(): number {
    return this.missionsByKind.reduce((sum, g) => sum + g.missions.length, 0);
  }

  /** Ressources (offres) affectées : bénévoles seuls, bénévoles + matériel, ou matériel seul. */
  get resourcesForSelectedTeam(): TeamMission[] {
    return this.selectedTeam?.missions.filter(m => m.kind === 'Offer') ?? [];
  }

  /** Répartition des ressources affectées, calculée sur les offres déjà chargées. */
  get resourcesSummary(): { seul: number; avecMateriel: number; materielSeul: number } {
    let seul = 0, avecMateriel = 0, materielSeul = 0;
    for (const m of this.resourcesForSelectedTeam) {
      const o = this.offers.find(o => o.id === m.id);
      if (!o) continue;
      const estMateriel = o.materiel_type != null || o.materiel_livraison != null;
      // presence_physique null (offres anciennes) est compté comme présence.
      const estEnPersonne = !!o.author && o.presence_physique !== false;
      if (estMateriel && estEnPersonne) avecMateriel++;
      else if (estMateriel) materielSeul++;
      else seul++;
    }
    return { seul, avecMateriel, materielSeul };
  }

  // Dupliqué de propose-help-form (materielTypeOptions) : six libellés fixes.
  private readonly MATERIEL_TYPE_LABELS: Record<string, string> = {
    CUVE: 'Cuve / citerne mobile', POMPE: 'Pompe', ETUVE: 'Étuve',
    CHAMBRE_FROIDE: 'Chambre froide', REMORQUE: 'Remorque', AUTRE: 'Autre',
  };

  offerFor(m: TeamMission): Offer | undefined {
    return this.offers.find(o => o.id === m.id);
  }

  resourceCompetencesLabel(m: TeamMission): string | null {
    const libelles = this.offerFor(m)?.competences_libelles;
    return libelles?.length ? libelles.join(', ') : null;
  }

  /** Le nom libre du catalogue prime sur le type générique (cas « Autre »). */
  resourceMaterielLabel(m: TeamMission): string | null {
    const o = this.offerFor(m);
    if (!o) return null;
    if (o.materiel_catalogue_nom) return o.materiel_catalogue_nom;
    if (o.materiel_type) return this.MATERIEL_TYPE_LABELS[o.materiel_type] || o.materiel_type;
    return null;
  }

  // ── Ressources : mission active + ajout/retrait ──────────────
  missionTitreInput = '';

  /** Passe la mission active en « En cours » (déclenche le suivi de position MeshCore). */
  demarrerMissionActive(): void {
    if (!this.selectedTeam?.mission_active) return;
    this.missionService.patch(this.selectedTeam.mission_active, { statut: 'EN_COURS' }).subscribe({
      next: () => {
        this.selectedTeam = { ...this.selectedTeam!, mission_active_statut: 'EN_COURS' };
        this.reloadTeams();
        this.showSuccess('Mission passée en cours.');
      },
      error: () => this.showError('Erreur lors du changement de statut de la mission.'),
    });
  }

  /** Bouton unique du bloc Mission : un titre définit (ou remplace) la mission, sur la crise
   * choisie s'il y en a une (definir_mission la rattache aussi à l'équipe) ; une crise seule
   * rattache l'équipe sans toucher à sa mission. */
  get libelleValiderMission(): string {
    if (this.missionTitreInput.trim()) {
      return this.selectedTeam?.mission_active_titre ? 'Changer la mission' : 'Définir la mission';
    }
    return 'Rattacher à la crise';
  }

  validerMission(): void {
    if (this.missionTitreInput.trim()) this.submitDefinirMission();
    else if (this.rattacherCriseId) this.submitRattacherCrise();
  }

  submitDefinirMission(): void {
    if (!this.selectedTeam?.id || !this.missionTitreInput.trim()) return;
    // Réutilise le sélecteur de crise de « Rattacher » (un seul sélecteur pour la section).
    this.teamService.definirMission(this.selectedTeam.id, this.missionTitreInput.trim(), this.rattacherCriseId ?? undefined).subscribe({
      next: (updated) => {
        this.selectedTeam = { ...updated, missions: this.selectedTeam!.missions };
        this.missionTitreInput = '';
        this.rattacherCriseId = null;
        this.reloadTeams();
        this.showSuccess('Mission de l\'équipe définie.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors de la définition de la mission.'),
    });
  }

  // ── Crises rattachées : rattacher/afficher (Team.assigned_crises) ────
  // Team.assigned_crises est distinct de la mission active : plusieurs vues en dépendent
  // (recrutement, ressources mobilisées, hébergement). Voir DOCUMENTATION.md, § 6.2.
  rattacherCriseId: string | null = null;

  get crisesRattacheesTeam(): Crisis[] {
    if (!this.selectedTeam) return [];
    const ids = new Set(this.selectedTeam.assigned_crisis_ids ?? []);
    return this.crisis.filter(c => ids.has(c.id));
  }

  submitRattacherCrise(): void {
    if (!this.selectedTeam?.id || !this.rattacherCriseId) return;
    this.teamService.assignerCrise(this.selectedTeam.id, this.rattacherCriseId).subscribe({
      next: (updated) => {
        this.rattacherCriseId = null;
        this.selectedTeam = { ...updated, missions: this.buildMissions(updated) };
        this.reloadTeams();
        this.showSuccess('Crise rattachée à l\'équipe.');
      },
      error: (err) => this.showError(err?.error?.error || 'Erreur lors du rattachement de la crise.'),
    });
  }

  // ── Canal MeshCore de l'équipe ────────────────────────────────────────
  provisionnantCanal = false;

  provisionnerCanal(): void {
    if (!this.selectedTeam?.id) return;
    this.provisionnantCanal = true;
    this.teamService.provisionnerCanalMeshCore(this.selectedTeam.id).subscribe({
      next: (resultat) => {
        this.provisionnantCanal = false;
        this.reloadTeams();
        if (this.selectedTeam) {
          this.selectedTeam = {
            ...this.selectedTeam,
            canal_meshcore_id: resultat.canal_id, canal_meshcore_nom: resultat.nom,
          };
        }
        this.showSuccess(
          resultat.compagnon_disponible
            ? `Canal « ${resultat.nom} » prêt — infos envoyées à ${resultat.destinataires} membre(s) équipé(s) d'un nœud MeshCore.`
            : `Canal « ${resultat.nom} » créé, mais aucun companion actif pour envoyer les infos aux membres pour l'instant.`,
        );
      },
      error: () => { this.provisionnantCanal = false; this.showError('Erreur lors du provisionnement du canal MeshCore.'); },
    });
  }

  regenererCanal(): void {
    if (!this.selectedTeam?.id) return;
    if (!confirm("Régénérer la clé du canal ? Les anciens détenteurs de la clé (y compris un membre retiré) ne pourront plus l'utiliser — la nouvelle clé n'est renvoyée qu'aux membres actuels.")) return;
    this.provisionnantCanal = true;
    this.teamService.provisionnerCanalMeshCore(this.selectedTeam.id, true).subscribe({
      next: (resultat) => {
        this.provisionnantCanal = false;
        this.showSuccess(`Clé régénérée et renvoyée à ${resultat.destinataires} membre(s).`);
      },
      error: () => { this.provisionnantCanal = false; this.showError('Erreur lors de la régénération du canal.'); },
    });
  }

  // ── Canal Meshtastic de l'équipe ──────────────────────────────────────
  provisionnantCanalMeshtastic = false;

  provisionnerCanalMeshtastic(): void {
    if (!this.selectedTeam?.id) return;
    this.provisionnantCanalMeshtastic = true;
    this.teamService.provisionnerCanalMeshtastic(this.selectedTeam.id).subscribe({
      next: (resultat) => {
        this.provisionnantCanalMeshtastic = false;
        this.reloadTeams();
        if (this.selectedTeam) {
          this.selectedTeam = {
            ...this.selectedTeam,
            canal_meshtastic_id: resultat.canal_id, canal_meshtastic_nom: resultat.nom,
          };
        }
        this.showSuccess(
          resultat.compagnon_disponible
            ? `Canal « ${resultat.nom} » prêt — infos envoyées à ${resultat.destinataires} membre(s) équipé(s) d'un nœud Meshtastic.`
            : `Canal « ${resultat.nom} » créé, mais aucun companion actif pour envoyer les infos aux membres pour l'instant.`,
        );
      },
      error: () => { this.provisionnantCanalMeshtastic = false; this.showError('Erreur lors du provisionnement du canal Meshtastic.'); },
    });
  }

  regenererCanalMeshtastic(): void {
    if (!this.selectedTeam?.id) return;
    if (!confirm("Régénérer la clé du canal Meshtastic ? Les anciens détenteurs (y compris un membre retiré) ne pourront plus l'utiliser — la nouvelle clé n'est renvoyée qu'aux membres actuels.")) return;
    this.provisionnantCanalMeshtastic = true;
    this.teamService.provisionnerCanalMeshtastic(this.selectedTeam.id, true).subscribe({
      next: (resultat) => {
        this.provisionnantCanalMeshtastic = false;
        this.showSuccess(`Clé régénérée et renvoyée à ${resultat.destinataires} membre(s).`);
      },
      error: () => { this.provisionnantCanalMeshtastic = false; this.showError('Erreur lors de la régénération du canal Meshtastic.'); },
    });
  }

  // ── Salon Matrix de l'équipe (messagerie Element, positionnement permanent) ───────────
  provisionnantSalonMatrix = false;
  readonly elementWebUrl = environment.elementWebUrl;

  provisionnerSalonMatrix(): void {
    if (!this.selectedTeam?.id) return;
    this.provisionnantSalonMatrix = true;
    this.teamService.provisionnerSalonMatrix(this.selectedTeam.id).subscribe({
      next: (resultat) => {
        this.provisionnantSalonMatrix = false;
        this.reloadTeams();
        if (this.selectedTeam) {
          this.selectedTeam = { ...this.selectedTeam, salon_matrix_id: resultat.id, salon_matrix_room_id: resultat.room_id };
        }
        this.showSuccess("Salon Matrix activé — le pont le crée côté serveur sous quelques dizaines de secondes.");
      },
      error: () => { this.provisionnantSalonMatrix = false; this.showError('Erreur lors de l\'activation du salon Matrix.'); },
    });
  }

  lienSalonMatrix(roomId: string): string {
    return `${this.elementWebUrl}/#/room/${encodeURIComponent(roomId)}`;
  }

  // Fonctions fléchées : passées en [Input] à MatrixSalonChatComponent, qui les appelle sans `this`.
  // Messagerie unifiée Matrix + MeshCore + Meshtastic (TeamViewSet.messagerie_unifiee).
  chargerMessagesSalonEquipe = () => this.teamService.getMessagerieUnifiee(this.selectedTeam!.id!);
  envoyerMessageSalonEquipe = (texte: string, urgent: boolean = false) => this.teamService.envoyerMessageUnifie(this.selectedTeam!.id!, texte, urgent);

  /** Seules les crises ouvertes sont proposées (validate_crisis_open côté backend). */
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

  /** Prochaine étape d'engagement ; null si aucun engagement ou statut terminal (ARRIVE/DECLINE). */
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
        // Seule cette offre a changé : la relire elle seule, pas toute la liste (~1 Mo en démo).
        this.offerService.getById(offerId).subscribe(offer => {
          this.offers = this.offers.map(o => o.id === offer.id ? offer : o);
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

  /** Résumé sous le titre d'une mission : contact + statut. */
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

  /** Dossiers de l'équipe : créés à l'affectation d'une demande ou manuellement (mission sans demande). */
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

  /** Points sans équipe, candidats à lier, filtrés par la recherche. */
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

  /** Ouvre la modale de création de point (app-point-modal), équipe pré-sélectionnée, crise facultative. */
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

  /** Descendants connus côté client, pour masquer les choix créant un cycle (la garde réelle est
   * côté serveur). */
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

  /** Sous-équipes possibles : ni l'équipe, ni ses descendants, ni une équipe déjà rattachée. */
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

  /** Résumé de disponibilité affiché dans la liste des membres. */
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

  /** Disponibilités d'un membre : celles des offres dont il est l'auteur. */
  private disposForMember(userId: string): DisponibiliteOffre[] {
    const offerIds = new Set(this.offers.filter(o => o.author === userId).map(o => o.id));
    return this.disponibilites.filter(d => offerIds.has(d.offer));
  }

  /** Colonnes du planning : une par (date, créneau) déclaré, triées par date puis matin→nuit. */
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