import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin, map, of } from 'rxjs';

import { CrisisService } from '../../services/crisis.service';
import { ImplicationService } from '../../services/implication.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { InstitutionService } from '../../services/institution.service';
import { InstitutionTypeService } from '../../services/institution-type.service';
import { BesoinService } from '../../services/besoin.service';
import { CompetenceService } from '../../services/competence.service';
import { DelegationCompetenceService } from '../../services/delegation-competence.service';
import { LocationService, Commune, GeoContour } from '../../services/location.service';
import { AuthService } from '../../auth/services/auth.service';

import { Crisis } from '../../shared/models/crisis.model';
import { ImplicationInstitution } from '../../shared/models/implication.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { ContactInstitution, Institution, InstitutionType } from '../../shared/models/institution.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Competence } from '../../shared/models/competence.model';
import { DelegationCompetence } from '../../shared/models/delegation-competence.model';
import { UserRole } from '../../shared/models/user.model';
import { ZoneMapComponent } from '../../shared/components/common/zone-map/zone-map.component';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';
import { PointModalComponent } from './point-modal/point-modal.component';
import { composeZoneSecteurs, toMultiPolygonWkt } from '../../shared/utils/crisis-zone-secteurs.util';

type ResponsableMode = 'moi' | 'contact' | 'email';

type ModalView = 'none' | 'detail';

@Component({
  selector: 'app-crises',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink, ZoneMapComponent, TagSearchInputComponent, PointModalComponent],
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
  delegations: DelegationCompetence[] = [];
  institutionTypes: InstitutionType[] = [];

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

  // ── Délégation de compétence par secteur ───────────────────────
  showDelegationForm = false;
  delegationSourceId: string | null = null;
  delegationCibleId: string | null = null;
  delegationCompetenceId: string | null = null;
  delegationCompetenceLabel = '';
  delegationRestreindre = false;
  delegationDepartements = '';
  delegationCommunes = '';
  delegationZoneWkt: string | null = null;

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  // ── Création rapide d'institution (depuis l'écran crise) ────────
  showQuickCreateInstitution = false;
  quickCreateNom = '';
  quickCreateTypeId: string | null = null;
  quickCreateSaving = false;

  // ── Zone de crise : secteurs (communes/départements + rayon) ───
  zoneCommuneNoms: Record<string, string> = {};
  zoneDepartementNoms: Record<string, string> = {};
  zoneSecteursLoading = false;
  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);
  departementSearchFn = (q: string) => {
    const query = q.trim().toLowerCase();
    return this.locationService.getDepartments().pipe(
      map(deps => deps.filter(d => d.name.toLowerCase().includes(query) || d.code === query).slice(0, 10)),
    );
  };

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private crisisService: CrisisService,
    private implicationService: ImplicationService,
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private contactService: ContactInstitutionService,
    private institutionService: InstitutionService,
    private institutionTypeService: InstitutionTypeService,
    private besoinService: BesoinService,
    private competenceService: CompetenceService,
    private delegationService: DelegationCompetenceService,
    private locationService: LocationService,
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
      delegations: this.delegationService.getAll(),
      institutionTypes: this.institutionTypeService.getAll(),
    }).subscribe({
      next: ({ crises, implications, points, pointTypes, institutions, contacts, besoins, delegations, institutionTypes }) => {
        this.crises = crises;
        this.implications = implications;
        this.points = points;
        this.pointTypes = pointTypes;
        this.institutions = institutions;
        this.allContacts = contacts;
        this.besoins = besoins;
        this.delegations = delegations;
        this.institutionTypes = institutionTypes;
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

  reloadDelegations(): void {
    this.delegationService.getAll().subscribe(data => this.delegations = data);
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

  delegationsFor(crisisId: string): DelegationCompetence[] {
    return this.delegations.filter(d => d.crise === crisisId);
  }

  /** Une institution ne peut déléguer une compétence que si elle est déjà impliquée
   * (acteur ou simple impliquée) sur cette crise — cohérent avec la règle backend. */
  delegableInstitutionsFor(crisisId: string): Institution[] {
    const ids = new Set(this.implicationsFor(crisisId).map(i => i.institution));
    return this.institutions.filter(i => ids.has(i.id!));
  }

  secteurResume(d: DelegationCompetence): string {
    if (d.departements?.length) return `Départements : ${d.departements.join(', ')}`;
    if (d.communes?.length) return `Communes : ${d.communes.join(', ')}`;
    if (d.zone_precise) return 'Secteur dessiné';
    return 'Toute la crise';
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
    this.resetDelegationForm();
    this.showQuickCreateInstitution = false;
    this.quickCreateNom = '';
    this.quickCreateTypeId = null;
    this.zoneCommuneNoms = {};
    this.zoneDepartementNoms = {};
    this.modal = 'detail';
    this.loadZoneSecteurLabels();
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

  // ── Zone de crise : secteurs (communes/départements + rayon) ───
  /** Résout les noms des communes/départements déjà enregistrés sur la crise, pour
   * l'affichage des chips (le backend ne stocke que des codes). N'écrit rien : appelé au
   * chargement de l'écran, avant toute modification par l'utilisateur. */
  private loadZoneSecteurLabels(): void {
    const crisis = this.selectedCrisis;
    if (!crisis || (!crisis.zone_communes?.length && !crisis.zone_departements?.length)) return;

    forkJoin({
      communes: this.fetchContours(crisis.zone_communes ?? [], code => this.locationService.getCommuneContour(code)),
      departements: this.fetchContours(crisis.zone_departements ?? [], code => this.locationService.getDepartementContour(code)),
    }).subscribe(({ communes, departements }) => {
      communes.forEach(c => this.zoneCommuneNoms[c.code] = c.name);
      departements.forEach(d => this.zoneDepartementNoms[d.code] = d.name);
    });
  }

  /** forkJoin([]) ne complète jamais avec une valeur (RxJS) : indispensable de retomber sur
   * of([]) quand la liste de codes est vide, sinon le forkJoin englobant ne se déclenche
   * jamais dès qu'une des deux listes (communes/départements) est vide. */
  private fetchContours(codes: string[], fetchFn: (code: string) => import('rxjs').Observable<GeoContour>) {
    return codes.length ? forkJoin(codes.map(fetchFn)) : of([] as GeoContour[]);
  }

  updateZoneRadius(radius: number): void {
    const crisis = this.selectedCrisis;
    if (!crisis || !radius || radius === crisis.radius) return;
    this.crisisService.patch(crisis.id, { radius }).subscribe({
      next: (updated) => {
        this.selectedCrisis = updated;
        const idx = this.crises.findIndex(c => c.id === updated.id);
        if (idx !== -1) this.crises[idx] = updated;
        if ((updated.zone_communes?.length || updated.zone_departements?.length)) {
          this.recomputeAndSaveZoneSecteurs(updated.zone_communes ?? [], updated.zone_departements ?? []);
        }
      },
      error: () => this.showError('Impossible de mettre à jour le rayon.'),
    });
  }

  addZoneCommune(commune: Commune): void {
    const crisis = this.selectedCrisis;
    if (!crisis || (crisis.zone_communes ?? []).includes(commune.code)) return;
    this.zoneCommuneNoms[commune.code] = commune.name;
    const zone_communes = [...(crisis.zone_communes ?? []), commune.code];
    this.recomputeAndSaveZoneSecteurs(zone_communes, crisis.zone_departements ?? []);
  }

  removeZoneCommune(code: string): void {
    const crisis = this.selectedCrisis;
    if (!crisis) return;
    const zone_communes = (crisis.zone_communes ?? []).filter(c => c !== code);
    this.recomputeAndSaveZoneSecteurs(zone_communes, crisis.zone_departements ?? []);
  }

  addZoneDepartement(dept: { code: string; name: string }): void {
    const crisis = this.selectedCrisis;
    if (!crisis || (crisis.zone_departements ?? []).includes(dept.code)) return;
    this.zoneDepartementNoms[dept.code] = dept.name;
    const zone_departements = [...(crisis.zone_departements ?? []), dept.code];
    this.recomputeAndSaveZoneSecteurs(crisis.zone_communes ?? [], zone_departements);
  }

  removeZoneDepartement(code: string): void {
    const crisis = this.selectedCrisis;
    if (!crisis) return;
    const zone_departements = (crisis.zone_departements ?? []).filter(c => c !== code);
    this.recomputeAndSaveZoneSecteurs(crisis.zone_communes ?? [], zone_departements);
  }

  private recomputeAndSaveZoneSecteurs(zone_communes: string[], zone_departements: string[]): void {
    const crisis = this.selectedCrisis;
    if (!crisis) return;
    this.zoneSecteursLoading = true;

    forkJoin({
      communes: this.fetchContours(zone_communes, code => this.locationService.getCommuneContour(code)),
      departements: this.fetchContours(zone_departements, code => this.locationService.getDepartementContour(code)),
    }).subscribe({
      next: ({ communes, departements }) => {
        const contours = [...communes, ...departements].map(c => c.contour);
        const composed = composeZoneSecteurs(contours, crisis.radius ?? 10);

        this.crisisService.patch(crisis.id, {
          zone_communes,
          zone_departements,
          zone_secteurs: composed ? toMultiPolygonWkt(composed) : null,
        }).subscribe({
          next: (updated) => {
            this.selectedCrisis = updated;
            const idx = this.crises.findIndex(c => c.id === updated.id);
            if (idx !== -1) this.crises[idx] = updated;
            this.zoneSecteursLoading = false;
            this.showSuccess('Zone de crise mise à jour.');
          },
          error: () => {
            this.zoneSecteursLoading = false;
            this.showError("Impossible d'enregistrer la zone.");
          },
        });
      },
      error: () => {
        this.zoneSecteursLoading = false;
        this.showError("Impossible de récupérer le contour de cette commune/ce département.");
      },
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

  get canExportCrisis(): boolean {
    if (!this.selectedCrisis) return false;
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

  exportCrisis(): void {
    if (!this.selectedCrisis) return;
    const crisis = this.selectedCrisis;
    this.crisisService.export(crisis.id).subscribe({
      next: (blob) => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `crise-${crisis.name}-main-courante.zip`;
        a.click();
        window.URL.revokeObjectURL(url);
      },
      error: () => this.showError("Impossible d'exporter la main courante de cette crise."),
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

  // ── Suppression de crise ────────────────────────────────────
  supprimerCrisis(): void {
    if (!this.selectedCrisis) return;
    const crisis = this.selectedCrisis;

    if (!confirm(`Supprimer définitivement la crise « ${crisis.name} » ? Cette action supprime aussi toutes les institutions, points, délégations et dossiers qui y sont rattachés, et ne peut pas être annulée.`)) {
      return;
    }
    const saisie = prompt(`Pour confirmer, retapez le nom exact de la crise : « ${crisis.name} »`);
    if (saisie !== crisis.name) {
      if (saisie !== null) this.showError('Le nom saisi ne correspond pas : suppression annulée.');
      return;
    }

    this.crisisService.delete(crisis.id).subscribe({
      next: () => {
        this.crises = this.crises.filter(c => c.id !== crisis.id);
        this.closeModal();
        this.showSuccess(`Crise « ${crisis.name} » supprimée.`);
      },
      error: () => this.showError('Impossible de supprimer cette crise.'),
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

  // ── Création rapide d'institution (depuis l'écran crise) ────────
  submitQuickCreateInstitution(): void {
    if (!this.quickCreateNom.trim() || !this.quickCreateTypeId) return;
    this.quickCreateSaving = true;
    this.institutionService.create({
      nom: this.quickCreateNom.trim(),
      type: this.quickCreateTypeId,
      actif: true,
    }).subscribe({
      next: (created) => {
        this.institutions = [...this.institutions, created];
        this.quickCreateSaving = false;
        this.quickCreateNom = '';
        this.quickCreateTypeId = null;
        this.showQuickCreateInstitution = false;
        this.showSuccess(`Institution « ${created.nom} » créée — sélectionnable dans les listes ci-dessous.`);
      },
      error: () => {
        this.quickCreateSaving = false;
        this.showError("Impossible de créer cette institution.");
      },
    });
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

  /** Autorisé au déclarant, à un contact de l'institution, ou à un admin — même règle que
   * le backend (voir ImplicationInstitutionViewSet._can_manage). */
  canManageImplication(implication: ImplicationInstitution): boolean {
    if (this.isAdmin) return true;
    if (this.isMine(implication)) return true;
    return this.myInstitutions.some(i => i.id === implication.institution);
  }

  toggleImplicationTheme(implication: ImplicationInstitution, besoinId: string, checked: boolean): void {
    const current = implication.themes ?? [];
    const themes = checked ? [...current, besoinId] : current.filter(id => id !== besoinId);
    this.implicationService.update(implication.id, { themes }).subscribe({
      next: (updated) => {
        const idx = this.implications.findIndex(i => i.id === updated.id);
        if (idx !== -1) this.implications[idx] = updated;
        this.showSuccess('Thèmes mis à jour.');
      },
      error: () => this.showError('Impossible de modifier les thèmes.'),
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

  /** Le backend autorise tout acteur institutionnel à gérer n'importe quel point (voir
   * PointOperationnelViewSet) — le frontend n'a donc pas besoin d'être plus restrictif que
   * "admin ou moi-même" pour afficher le bouton de retrait. */
  canManagePoint(point: PointOperationnel): boolean {
    return this.isAdmin || this.isMine(point);
  }

  // ── Délégation de compétence par secteur ───────────────────────
  resetDelegationForm(): void {
    this.showDelegationForm = false;
    this.delegationSourceId = null;
    this.delegationCibleId = null;
    this.delegationCompetenceId = null;
    this.delegationCompetenceLabel = '';
    this.delegationRestreindre = false;
    this.delegationDepartements = '';
    this.delegationCommunes = '';
    this.delegationZoneWkt = null;
  }

  onDelegationCompetenceSelected(item: Competence): void {
    this.delegationCompetenceId = item.id;
    this.delegationCompetenceLabel = item.nom;
  }

  onDelegationZoneChange(wkt: string | null): void {
    this.delegationZoneWkt = wkt;
  }

  submitDelegation(): void {
    if (!this.selectedCrisis || !this.delegationSourceId || !this.delegationCibleId || !this.delegationCompetenceId) return;

    const payload: any = {
      crise: this.selectedCrisis.id,
      institution_source: this.delegationSourceId,
      institution_cible: this.delegationCibleId,
      competence: this.delegationCompetenceId,
    };

    if (this.delegationRestreindre) {
      const departements = this.delegationDepartements.split(',').map(s => s.trim()).filter(Boolean);
      const communes = this.delegationCommunes.split(',').map(s => s.trim()).filter(Boolean);
      if (departements.length) payload.departements = departements;
      if (communes.length) payload.communes = communes;
      if (this.delegationZoneWkt) payload.zone_precise = this.delegationZoneWkt;
    }

    this.delegationService.create(payload).subscribe({
      next: () => {
        this.reloadDelegations();
        this.showSuccess('Compétence déléguée.');
        this.resetDelegationForm();
      },
      error: (err) => this.showError(err.error?.institution_source?.[0] || "Impossible d'enregistrer cette délégation."),
    });
  }

  canManageDelegation(delegation: DelegationCompetence): boolean {
    if (this.isAdmin) return true;
    return this.myInstitutions.some(i => i.id === delegation.institution_source);
  }

  retirerDelegation(delegation: DelegationCompetence): void {
    if (!confirm(`Retirer la délégation « ${delegation.competence_libelle} » vers ${delegation.institution_cible_nom} ?`)) return;
    this.delegationService.delete(delegation.id).subscribe({
      next: () => { this.reloadDelegations(); this.showSuccess('Délégation retirée.'); },
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
