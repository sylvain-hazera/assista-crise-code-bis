import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { CrisisService } from '../../services/crisis.service';
import { ImplicationService } from '../../services/implication.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { InstitutionService } from '../../services/institution.service';
import { BesoinService } from '../../services/besoin.service';
import { AuthService } from '../../auth/services/auth.service';

import { Crisis } from '../../shared/models/crisis.model';
import { ImplicationInstitution } from '../../shared/models/implication.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { ContactInstitution, Institution } from '../../shared/models/institution.model';
import { Besoin } from '../../shared/models/besoin.model';
import { UserRole } from '../../shared/models/user.model';
import { ZoneMapComponent } from '../../shared/components/common/zone-map/zone-map.component';
import { PointModalComponent } from './point-modal/point-modal.component';

type ResponsableMode = 'moi' | 'contact' | 'email';

type ModalView = 'none' | 'detail';

@Component({
  selector: 'app-crises',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink, ZoneMapComponent, PointModalComponent],
  templateUrl: './crises.component.html',
  styleUrls: ['./crises.component.scss']
})
export class CrisesComponent implements OnInit {

  crises: Crisis[] = [];
  implications: ImplicationInstitution[] = [];
  points: PointOperationnel[] = [];
  pointTypes: PointType[] = [];
  institutions: Institution[] = [];
  myContacts: ContactInstitution[] = [];
  allContacts: ContactInstitution[] = [];
  besoins: Besoin[] = [];

  isLoading = true;
  errorMessage = '';
  successMessage = '';
  searchQuery = '';

  modal: ModalView = 'none';
  selectedCrisis: Crisis | null = null;

  showImpliqueForm = false;
  showActeurDirectForm = false;
  showZoneEditor = false;
  pendingZoneWkt: string | null = null;
  impliqueForm!: FormGroup;

  pointModalOpen = false;
  editingPoint: PointOperationnel | null = null;

  // ── Déclarer une institution actrice (thèmes + responsable) ────
  acteurDirectInstitutionId: string | null = null;
  acteurDirectThemes: string[] = [];
  acteurDirectContacts: ContactInstitution[] = [];
  responsableMode: ResponsableMode = 'moi';
  responsableContactId: string | null = null;
  responsableEmail = '';

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private crisisService: CrisisService,
    private implicationService: ImplicationService,
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private contactService: ContactInstitutionService,
    private institutionService: InstitutionService,
    private besoinService: BesoinService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.buildForms();
    this.loadAll();
  }

  private buildForms(): void {
    this.impliqueForm = this.fb.group({
      institution: [null, Validators.required],
      commentaire: [''],
    });
  }

  private loadAll(): void {
    this.isLoading = true;
    forkJoin({
      crises: this.crisisService.getAll(),
      implications: this.implicationService.getAll(),
      points: this.pointService.getAll(),
      pointTypes: this.pointTypeService.getAll(),
      institutions: this.institutionService.getAll(),
      contacts: this.contactService.getAll(),
      besoins: this.besoinService.getAll(),
    }).subscribe({
      next: ({ crises, implications, points, pointTypes, institutions, contacts, besoins }) => {
        this.crises = crises;
        this.implications = implications;
        this.points = points;
        this.pointTypes = pointTypes;
        this.institutions = institutions;
        this.allContacts = contacts;
        this.besoins = besoins;
        const me = this.authService.getCurrentUser();
        this.myContacts = me ? contacts.filter(c => c.utilisateur === me.id && c.actif) : [];
        this.isLoading = false;

        const targetId = this.route.snapshot.queryParamMap.get('id');
        const target = targetId ? this.crises.find(c => c.id === targetId) : null;
        if (target) this.openDetail(target);
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les crises.';
        this.isLoading = false;
      },
    });
  }

  private reloadImplications(): void {
    this.implicationService.getAll().subscribe(data => this.implications = data);
  }

  reloadPoints(): void {
    this.pointService.getAll().subscribe(data => this.points = data);
  }

  // ── Liste ────────────────────────────────────────────────────
  get filteredCrises(): Crisis[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.crises;
    return this.crises.filter(c => c.name.toLowerCase().includes(q));
  }

  implicationsFor(crisisId: string): ImplicationInstitution[] {
    return this.implications.filter(i => i.crise === crisisId);
  }

  impliquesFor(crisisId: string): ImplicationInstitution[] {
    return this.implications.filter(i => i.crise === crisisId && i.type_implication === 'IMPLIQUE');
  }

  acteursFor(crisisId: string): ImplicationInstitution[] {
    return this.implications.filter(i => i.crise === crisisId && i.type_implication === 'ACTEUR');
  }

  pointsFor(crisisId: string): PointOperationnel[] {
    return this.points.filter(p => p.crise === crisisId);
  }

  // ── Détail ───────────────────────────────────────────────────
  openDetail(crisis: Crisis): void {
    this.selectedCrisis = crisis;
    this.showImpliqueForm = false;
    this.showActeurDirectForm = false;
    this.showZoneEditor = false;
    this.pendingZoneWkt = crisis.zone ?? null;
    this.impliqueForm.reset({ institution: this.defaultInstitutionId() });
    this.pointModalOpen = false;
    this.editingPoint = null;
    this.acteurDirectInstitutionId = null;
    this.acteurDirectThemes = [];
    this.acteurDirectContacts = [];
    this.responsableMode = 'moi';
    this.responsableContactId = null;
    this.responsableEmail = '';
    this.modal = 'detail';
  }

  closeModal(): void {
    this.modal = 'none';
    this.selectedCrisis = null;
  }

  private defaultInstitutionId(): string | null {
    return this.myContacts.length === 1 ? this.myContacts[0].institution : null;
  }

  // ── Zone précise (polygone) ────────────────────────────────────
  onZoneChange(wkt: string | null): void {
    this.pendingZoneWkt = wkt;
  }

  saveZone(): void {
    if (!this.selectedCrisis) return;
    this.crisisService.patch(this.selectedCrisis.id, { zone: this.pendingZoneWkt }).subscribe({
      next: (updated) => {
        this.selectedCrisis = updated;
        const idx = this.crises.findIndex(c => c.id === updated.id);
        if (idx !== -1) this.crises[idx] = updated;
        this.showZoneEditor = false;
        this.showSuccess('Zone enregistrée.');
      },
      error: () => this.showError("Impossible d'enregistrer la zone."),
    });
  }

  get myInstitutions(): Institution[] {
    const ids = new Set(this.myContacts.map(c => c.institution));
    return this.institutions.filter(i => ids.has(i.id!));
  }

  get isAdmin(): boolean {
    return this.authService.getCurrentUser()?.type === UserRole.ADMIN;
  }

  // ── Clôture de crise ─────────────────────────────────────────
  get canCloturerCrisis(): boolean {
    if (!this.selectedCrisis || this.selectedCrisis.is_open === false) return false;
    if (this.isAdmin) return true;
    const me = this.authService.getCurrentUser();
    if (!me) return false;
    return this.implicationsFor(this.selectedCrisis.id)
      .some(i => i.responsable === me.id && i.actif);
  }

  cloturerCrisis(): void {
    if (!this.selectedCrisis) return;
    if (!confirm(`Clôturer la crise « ${this.selectedCrisis.name} » ? Plus aucune institution, point ou délégation ne pourra y être ajouté.`)) {
      return;
    }
    this.crisisService.cloturer(this.selectedCrisis.id).subscribe({
      next: () => {
        this.selectedCrisis = { ...this.selectedCrisis!, is_open: false, end_date: new Date().toISOString() };
        const idx = this.crises.findIndex(c => c.id === this.selectedCrisis!.id);
        if (idx !== -1) this.crises[idx] = this.selectedCrisis!;
        this.showSuccess('Crise clôturée.');
      },
      error: (err) => this.showError(err.error?.error || 'Impossible de clôturer cette crise.'),
    });
  }

  reouvrirCrisis(): void {
    if (!this.selectedCrisis) return;
    if (!confirm(`Réouvrir la crise « ${this.selectedCrisis.name} » ?`)) {
      return;
    }
    this.crisisService.reouvrir(this.selectedCrisis.id).subscribe({
      next: () => {
        this.selectedCrisis = { ...this.selectedCrisis!, is_open: true, end_date: null };
        const idx = this.crises.findIndex(c => c.id === this.selectedCrisis!.id);
        if (idx !== -1) this.crises[idx] = this.selectedCrisis!;
        this.showSuccess('Crise réouverte.');
      },
      error: (err) => this.showError(err.error?.error || 'Impossible de réouvrir cette crise.'),
    });
  }

  /** Un admin peut déclarer/désigner un responsable pour n'importe quelle institution ; un
   * acteur institutionnel reste limité aux siennes. */
  get selectableInstitutions(): Institution[] {
    return this.isAdmin ? this.institutions : this.myInstitutions;
  }

  institutionName(id: string): string {
    return this.institutions.find(i => i.id === id)?.nom ?? id.slice(0, 8);
  }

  // ── Déclarer une institution actrice (thèmes + responsable) ────
  onActeurDirectInstitutionChange(id: string): void {
    this.acteurDirectInstitutionId = id || null;
    this.acteurDirectContacts = this.acteurDirectInstitutionId
      ? this.allContacts.filter(c => c.institution === this.acteurDirectInstitutionId && c.actif)
      : [];
    this.responsableContactId = null;
  }

  toggleActeurDirectTheme(besoinId: string, checked: boolean): void {
    this.acteurDirectThemes = checked
      ? [...this.acteurDirectThemes, besoinId]
      : this.acteurDirectThemes.filter(id => id !== besoinId);
  }

  submitActeurDirect(): void {
    if (!this.selectedCrisis || !this.acteurDirectInstitutionId) return;

    const payload: any = {
      crise: this.selectedCrisis.id,
      institution: this.acteurDirectInstitutionId,
      type_implication: 'ACTEUR',
      themes: this.acteurDirectThemes,
    };

    const me = this.authService.getCurrentUser();
    if (this.responsableMode === 'moi' && me) {
      payload.responsable = me.id;
    } else if (this.responsableMode === 'contact' && this.responsableContactId) {
      payload.responsable = this.responsableContactId;
    } else if (this.responsableMode === 'email' && this.responsableEmail.trim()) {
      payload.responsable_email = this.responsableEmail.trim();
    }

    this.implicationService.create(payload).subscribe({
      next: () => {
        this.reloadImplications();
        this.showSuccess('Institution déclarée actrice.');
        this.showActeurDirectForm = false;
      },
      error: () => this.showError("Impossible d'enregistrer cette déclaration."),
    });
  }

  // ── Je suis impliqué ─────────────────────────────────────────
  submitImplique(): void {
    if (!this.selectedCrisis || this.impliqueForm.invalid) { this.impliqueForm.markAllAsTouched(); return; }
    const { institution, commentaire } = this.impliqueForm.value;
    this.implicationService.create({
      crise: this.selectedCrisis.id,
      institution,
      type_implication: 'IMPLIQUE',
      commentaire: commentaire || undefined,
    }).subscribe({
      next: () => {
        this.reloadImplications();
        this.showSuccess('Institution déclarée impliquée.');
        this.showImpliqueForm = false;
      },
      error: () => this.showError("Impossible d'enregistrer cette déclaration."),
    });
  }

  retirerImplication(implication: ImplicationInstitution): void {
    this.implicationService.delete(implication.id).subscribe({
      next: () => { this.reloadImplications(); this.showSuccess('Déclaration retirée.'); },
      error: () => this.showError('Erreur lors du retrait.'),
    });
  }

  // ── Je suis acteur (point opérationnel) ─────────────────────
  openPointModal(point: PointOperationnel | null): void {
    this.editingPoint = point;
    this.pointModalOpen = true;
  }

  onPointModalClosed(): void {
    this.pointModalOpen = false;
    this.editingPoint = null;
  }

  onPointSaved(_point: PointOperationnel): void {
    this.reloadPoints();
    this.reloadImplications();
    this.showSuccess(this.editingPoint ? 'Point opérationnel modifié.' : 'Point opérationnel créé, institution déclarée acteur.');
    this.pointModalOpen = false;
    this.editingPoint = null;
  }

  retirerPoint(point: PointOperationnel): void {
    this.pointService.delete(point.id).subscribe({
      next: () => { this.reloadPoints(); this.showSuccess('Point opérationnel retiré.'); },
      error: () => this.showError('Erreur lors du retrait.'),
    });
  }

  isMine(item: { utilisateur?: string | null; responsable?: string | null }): boolean {
    const me = this.authService.getCurrentUser();
    if (!me) return false;
    return item.utilisateur === me.id || item.responsable === me.id;
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
}
