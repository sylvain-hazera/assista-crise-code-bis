import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';

import { PlanService } from '../../../services/plan.service';
import { PlanMissionModeleService } from '../../../services/plan-mission-modele.service';
import { ZoneService } from '../../../services/zone.service';
import { TeamService } from '../../../services/team.service';
import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { PointTypeService } from '../../../services/point-type.service';
import { UserService } from '../../../services/user.service';
import { AuthService } from '../../../auth/services/auth.service';
import { RisqueMajeurTypeService, RisqueCommunalService } from '../../../services/risque-majeur.service';
import { ContactInstitutionService } from '../../../services/contact-institution.service';
import { InterlocuteurAlertePCSService } from '../../../services/interlocuteur-alerte-pcs.service';
import { MaterielPointService } from '../../../services/materiel-point.service';
import { Plan, PlanMissionModele } from '../../../shared/models/plan.model';
import { Zone } from '../../../shared/models/zone.model';
import { Team, teamDisplayName } from '../../../shared/models/team.model';
import { PointOperationnel, PointType } from '../../../shared/models/point-operationnel.model';
import { User } from '../../../shared/models/user.model';
import { RisqueMajeurType, RisqueCommunal } from '../../../shared/models/risque-majeur.model';
import { ContactInstitution } from '../../../shared/models/institution.model';
import { InterlocuteurAlertePCS } from '../../../shared/models/interlocuteur-alerte-pcs.model';
import { MaterielPoint } from '../../../shared/models/materiel-point.model';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { PointModalComponent } from '../../crises/point-modal/point-modal.component';
import { ZoneModalComponent } from '../../zones/zone-modal/zone-modal.component';

/** Création/édition d'un plan (dispositif pré-enregistré) : sélection d'éléments existants de
 * l'institution, accumulée localement puis soumise en une fois (comme ZoneModalComponent).
 * Risques et interlocuteurs : même « chercher ou créer » que la fiche Institution. */
@Component({
  selector: 'app-plan-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, FormsModule, TagSearchInputComponent, PointModalComponent, ZoneModalComponent],
  templateUrl: './plan-modal.component.html',
  styleUrl: './plan-modal.component.scss',
})
export class PlanModalComponent implements OnChanges {
  teamDisplayName = teamDisplayName;

  @Input() plan: Plan | null = null; // null = création

  @Output() saved = new EventEmitter<Plan>();
  @Output() closed = new EventEmitter<void>();

  form!: FormGroup;
  zones: Zone[] = [];
  teams: Team[] = [];
  points: PointOperationnel[] = [];
  users: User[] = [];
  risquesCommunaux: RisqueCommunal[] = [];
  contactsInstitution: ContactInstitution[] = [];
  interlocuteursPCS: InterlocuteurAlertePCS[] = [];
  pointTypes: PointType[] = [];

  selectedZoneIds: string[] = [];
  selectedTeamIds: string[] = [];
  selectedPointIds: string[] = [];
  selectedRisqueIds: string[] = [];
  selectedContactIds: string[] = [];
  selectedInterlocuteurIds: string[] = [];

  saving = false;
  errorMessage = '';

  // Missions modèles (édition seulement) : instanciées en Mission + Dossier à l'activation
  // (PlanViewSet.activer).
  missionsModeles: PlanMissionModele[] = [];
  missionForm!: FormGroup;
  showMissionForm = false;
  missionReferentQuery = '';
  showMissionReferentResults = false;
  missionSaving = false;
  missionError = '';

  private myInstitutionId: string | null = null;

  constructor(
    private fb: FormBuilder,
    private planService: PlanService,
    private missionModeleService: PlanMissionModeleService,
    private zoneService: ZoneService,
    private teamService: TeamService,
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private userService: UserService,
    private authService: AuthService,
    private risqueMajeurTypeService: RisqueMajeurTypeService,
    private risqueCommunalService: RisqueCommunalService,
    private contactInstitutionService: ContactInstitutionService,
    private interlocuteurAlertePCSService: InterlocuteurAlertePCSService,
    private materielPointService: MaterielPointService,
  ) {
    this.buildForm();
    this.buildMissionForm();
    this.myInstitutionId = this.authService.getCurrentUser()?.institution_id ?? null;
    this.zoneService.getAll().subscribe(zones => this.zones = zones);
    this.teamService.getAll().subscribe(teams => {
      this.teams = this.myInstitutionId ? teams.filter(t => t.institution === this.myInstitutionId) : teams;
    });
    this.pointService.getMine().subscribe(points => this.points = points);
    this.userService.getAll().subscribe(users => this.users = users);
    this.pointTypeService.getAll().subscribe(types => this.pointTypes = types);
    if (this.myInstitutionId) {
      this.risqueCommunalService.getForInstitution(this.myInstitutionId).subscribe(r => this.risquesCommunaux = r);
      this.interlocuteurAlertePCSService.getForInstitution(this.myInstitutionId).subscribe(i => this.interlocuteursPCS = i);
    }
    this.contactInstitutionService.getAll().subscribe(contacts => {
      this.contactsInstitution = this.myInstitutionId
        ? contacts.filter(c => c.institution === this.myInstitutionId)
        : contacts;
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['plan']) {
      this.buildForm();
      this.loadMissionsModeles();
    }
  }

  private buildMissionForm(): void {
    this.missionForm = this.fb.group({
      equipe: [null, Validators.required],
      titre: ['', Validators.required],
      description: [''],
      referent: [null],
    });
  }

  private loadMissionsModeles(): void {
    this.missionsModeles = [];
    if (!this.plan?.id) return;
    this.missionModeleService.getByPlan(this.plan.id).subscribe(modeles => this.missionsModeles = modeles);
  }

  // Équipes sélectionnées, recalculées à chaque affichage.
  get selectableTeamsForMission(): Team[] {
    return this.teams.filter(t => !!t.id && this.selectedTeamIds.includes(t.id));
  }

  get missionReferentResults(): User[] {
    const q = this.missionReferentQuery.trim().toLowerCase();
    if (!q) return [];
    return this.users.filter(u =>
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) || u.username.toLowerCase().includes(q)
    );
  }

  selectMissionReferent(user: User): void {
    this.missionForm.get('referent')?.setValue(user.id);
    this.missionReferentQuery = `${user.first_name} ${user.last_name}`.trim() || user.username;
    this.showMissionReferentResults = false;
  }

  onMissionReferentQueryChange(): void {
    this.missionForm.get('referent')?.setValue(null);
    this.showMissionReferentResults = true;
  }

  hideMissionReferentResultsDelayed(): void {
    setTimeout(() => this.showMissionReferentResults = false, 150);
  }

  submitMission(): void {
    if (!this.plan?.id || this.missionForm.invalid) { this.missionForm.markAllAsTouched(); return; }

    const { equipe, titre, description, referent } = this.missionForm.value;
    this.missionSaving = true;
    this.missionError = '';
    this.missionModeleService.create({
      plan: this.plan.id, equipe, titre, description: description || undefined, referent: referent || undefined,
    }).subscribe({
      next: () => {
        this.missionSaving = false;
        this.loadMissionsModeles();
        this.missionForm.reset();
        this.missionReferentQuery = '';
        this.showMissionForm = false;
      },
      error: (err) => {
        this.missionSaving = false;
        this.missionError = err.error?.detail || err.error?.equipe?.[0] || "Impossible d'enregistrer cette mission.";
      },
    });
  }

  deleteMission(modele: PlanMissionModele): void {
    this.missionModeleService.delete(modele.id).subscribe({
      next: () => this.loadMissionsModeles(),
      error: () => this.missionError = 'Impossible de retirer cette mission.',
    });
  }

  private buildForm(): void {
    this.form = this.fb.group({
      nom: [this.plan?.nom ?? '', Validators.required],
      description: [this.plan?.description ?? ''],
    });
    this.selectedZoneIds = [...(this.plan?.zones_ids ?? [])];
    this.selectedTeamIds = [...(this.plan?.equipes_ids ?? [])];
    this.selectedPointIds = [...(this.plan?.points_ids ?? [])];
    this.selectedRisqueIds = [...(this.plan?.risques_ids ?? [])];
    this.selectedContactIds = [...(this.plan?.contacts_internes_ids ?? [])];
    this.selectedInterlocuteurIds = [...(this.plan?.interlocuteurs_ids ?? [])];
  }

  get isEdit(): boolean {
    return !!this.plan;
  }

  toggleZone(id: string): void {
    this.selectedZoneIds = this.selectedZoneIds.includes(id)
      ? this.selectedZoneIds.filter(i => i !== id)
      : [...this.selectedZoneIds, id];
  }

  // ── Création d'une zone depuis ce flux (app-zone-modal) ──────
  showZoneModal = false;

  onZoneCreated(zone: Zone): void {
    this.showZoneModal = false;
    this.zones = [...this.zones, zone];
    this.toggleZone(zone.id);
  }

  // ── Cellules standards PCS ──────────────────
  // Raccourci qui crée 4 équipes nommées comme les cellules d'un PCS type (COM/LOG/POP/SECU),
  // renommables. Plan ne crée jamais d'équipe lui-même.
  creantCellulesStandards = false;

  private readonly CELLULES_STANDARDS: { name: string; description: string; color: string }[] = [
    { name: 'Cellule communication', description: "Assurer la diffusion des informations officielles, l'accueil téléphonique et physique du public.", color: '#2563eb' },
    { name: 'Cellule logistique', description: 'Mobiliser les moyens humains et matériels, organiser transport et évacuation.', color: '#d97706' },
    { name: 'Cellule population', description: "Assurer l'assistance à la population évacuée : accueil, recensement, soutien.", color: '#16a34a' },
    { name: 'Cellule sécurité', description: 'Participer au maintien de l\'ordre et à la protection des biens et des personnes sur le terrain.', color: '#dc2626' },
  ];

  creerCellulesStandards(): void {
    const aCreer = this.CELLULES_STANDARDS.filter(c => !this.teams.some(t => t.name === c.name));
    if (aCreer.length === 0) return;
    this.creantCellulesStandards = true;
    let restant = aCreer.length;
    for (const cellule of aCreer) {
      this.teamService.create(cellule).subscribe({
        next: (created) => {
          this.teams = [...this.teams, created];
          if (created.id) this.toggleTeam(created.id);
          if (--restant === 0) this.creantCellulesStandards = false;
        },
        error: () => { if (--restant === 0) this.creantCellulesStandards = false; },
      });
    }
  }

  toggleTeam(id: string): void {
    this.selectedTeamIds = this.selectedTeamIds.includes(id)
      ? this.selectedTeamIds.filter(i => i !== id)
      : [...this.selectedTeamIds, id];
  }

  // ── Création libre d'une équipe (nom + responsable facultatif) ──────────
  showTeamForm = false;
  teamNom = '';
  teamLeaderId: string | null = null;
  teamLeaderQuery = '';
  showTeamLeaderResults = false;
  teamSaving = false;
  teamError = '';

  get teamLeaderResults(): User[] {
    const q = this.teamLeaderQuery.trim().toLowerCase();
    if (!q) return [];
    return this.users.filter(u =>
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) || u.username.toLowerCase().includes(q)
    );
  }

  selectTeamLeader(user: User): void {
    this.teamLeaderId = user.id;
    this.teamLeaderQuery = `${user.first_name} ${user.last_name}`.trim() || user.username;
    this.showTeamLeaderResults = false;
  }

  onTeamLeaderQueryChange(): void {
    this.teamLeaderId = null;
    this.showTeamLeaderResults = true;
  }

  hideTeamLeaderResultsDelayed(): void {
    setTimeout(() => this.showTeamLeaderResults = false, 150);
  }

  creerEquipe(): void {
    const nom = this.teamNom.trim();
    if (!nom) return;
    this.teamSaving = true;
    this.teamError = '';
    this.teamService.create({ name: nom, leader: this.teamLeaderId || undefined }).subscribe({
      next: (created) => {
        this.teamSaving = false;
        this.teams = [...this.teams, created];
        if (created.id) this.toggleTeam(created.id);
        this.teamNom = '';
        this.teamLeaderId = null;
        this.teamLeaderQuery = '';
        this.showTeamForm = false;
      },
      error: (err) => {
        this.teamSaving = false;
        this.teamError = err.error?.name?.[0] || err.error?.detail || "Impossible de créer cette équipe.";
      },
    });
  }

  togglePoint(id: string): void {
    this.selectedPointIds = this.selectedPointIds.includes(id)
      ? this.selectedPointIds.filter(i => i !== id)
      : [...this.selectedPointIds, id];
  }

  // ── Création d'un point depuis ce flux (app-point-modal, hors crise) ──────
  showPointModal = false;

  onPointCreated(point: PointOperationnel): void {
    this.showPointModal = false;
    this.points = [...this.points, point];
    if (point.id) this.togglePoint(point.id);
  }

  // ── Stock de matériel d'un point sélectionné (chargé à la demande) ─────────
  expandedStockPointIds: string[] = [];
  stocksParPoint: Record<string, MaterielPoint[]> = {};
  stockLoadingPointId: string | null = null;

  toggleStockVisibility(pointId: string, event: Event): void {
    event.stopPropagation();
    if (this.expandedStockPointIds.includes(pointId)) {
      this.expandedStockPointIds = this.expandedStockPointIds.filter(id => id !== pointId);
      return;
    }
    this.expandedStockPointIds = [...this.expandedStockPointIds, pointId];
    if (this.stocksParPoint[pointId]) return;
    this.stockLoadingPointId = pointId;
    this.materielPointService.getByPoint(pointId).subscribe({
      next: (stocks) => {
        this.stocksParPoint = { ...this.stocksParPoint, [pointId]: stocks };
        if (this.stockLoadingPointId === pointId) this.stockLoadingPointId = null;
      },
      error: () => { if (this.stockLoadingPointId === pointId) this.stockLoadingPointId = null; },
    });
  }

  // ── Risques couverts : chercher/créer un type puis le déclarer (comme institutions.component) ──
  risqueSearchFn = (q: string) => this.risqueMajeurTypeService.search(q);
  risqueCreateLabelFn = (value: string) => `Créer « ${value} » comme nouveau type de risque`;
  risqueCreateFn = (nom: string) => this.risqueMajeurTypeService.create({ nom });

  onRisqueSelected(item: RisqueMajeurType): void {
    if (!this.myInstitutionId) return;
    const existant = this.risquesCommunaux.find(r => r.risque_type === item.id);
    if (existant) {
      if (existant.id) this.toggleRisque(existant.id);
      return;
    }
    this.risqueCommunalService.create({ institution: this.myInstitutionId, risque_type: item.id }).subscribe(created => {
      this.risquesCommunaux = [...this.risquesCommunaux, created];
      if (created.id) this.toggleRisque(created.id);
    });
  }

  toggleRisque(id: string): void {
    this.selectedRisqueIds = this.selectedRisqueIds.includes(id)
      ? this.selectedRisqueIds.filter(i => i !== id)
      : [...this.selectedRisqueIds, id];
  }

  // ── Contacts internes : sélection parmi l'existant uniquement ──
  toggleContact(id: string): void {
    this.selectedContactIds = this.selectedContactIds.includes(id)
      ? this.selectedContactIds.filter(i => i !== id)
      : [...this.selectedContactIds, id];
  }

  contactLabel(contact: ContactInstitution): string {
    return contact.utilisateur_nom || contact.fonction || 'Contact';
  }

  // ── Interlocuteurs externes (annuaire PCS) : chercher ou créer, comme institutions.component ──
  interlocuteurPCSSearchFn = (q: string) => this.interlocuteurAlertePCSService.search(q);
  interlocuteurPCSCreateLabelFn = (value: string) => `Créer « ${value} » comme nouvel interlocuteur`;
  interlocuteurPCSCreateFn = (organisme: string) =>
    this.interlocuteurAlertePCSService.create({ organisme, nom: organisme, categorie: 'AUTRE', mode_alerte: 'TELEPHONE' });

  onInterlocuteurPCSSelected(item: InterlocuteurAlertePCS): void {
    // Rattache toujours (no-op si déjà fait).
    this.interlocuteurAlertePCSService.rattacher(item.id).subscribe(rattache => {
      if (!this.interlocuteursPCS.some(i => i.id === rattache.id)) {
        this.interlocuteursPCS = [...this.interlocuteursPCS, rattache];
      }
      this.toggleInterlocuteur(rattache.id);
    });
  }

  toggleInterlocuteur(id: string): void {
    this.selectedInterlocuteurIds = this.selectedInterlocuteurIds.includes(id)
      ? this.selectedInterlocuteurIds.filter(i => i !== id)
      : [...this.selectedInterlocuteurIds, id];
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { nom, description } = this.form.getRawValue();
    const payload = {
      nom,
      description: description || undefined,
      zones_ids: this.selectedZoneIds,
      equipes_ids: this.selectedTeamIds,
      points_ids: this.selectedPointIds,
      risques_ids: this.selectedRisqueIds,
      contacts_internes_ids: this.selectedContactIds,
      interlocuteurs_ids: this.selectedInterlocuteurIds,
    };

    this.saving = true;
    this.errorMessage = '';

    const request$ = this.isEdit
      ? this.planService.update(this.plan!.id, payload)
      : this.planService.create(payload);

    request$.subscribe({
      next: (result) => {
        this.saving = false;
        this.saved.emit(result);
      },
      error: (err) => {
        this.saving = false;
        this.errorMessage = err.error?.detail || "Impossible d'enregistrer ce plan.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }
}
