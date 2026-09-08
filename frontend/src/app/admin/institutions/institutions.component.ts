import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { InstitutionService } from '../../services/institution.service';
import { InstitutionTypeService } from '../../services/institution-type.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { InstitutionDomaineService } from '../../services/institution-domaine.service';
import { UserService } from '../../services/user.service';
import { CompetenceService } from '../../services/competence.service';
import { AffectationRoleOperationnelService } from '../../services/affectation-role-operationnel.service';
import { LocationService, Commune } from '../../services/location.service';
import { ZoneService } from '../../services/zone.service';
import { Zone } from '../../shared/models/zone.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

import {
  Institution,
  InstitutionType,
  RoleOperationnel,
  ContactInstitution,
  InstitutionDomaine,
  AffectationRoleOperationnel,
} from '../../shared/models/institution.model';
import { User } from '../../shared/models/user.model';
import { Competence } from '../../shared/models/competence.model';

type MainTab = 'institutions' | 'types' | 'roles';
type ModalView = 'none' | 'create' | 'edit' | 'delete' | 'detail';
type RefModalView = 'none' | 'create' | 'edit' | 'delete';
type DetailTab = 'contacts' | 'domaines' | 'regulateurs';

@Component({
  selector: 'app-institutions',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink, TagSearchInputComponent],
  templateUrl: './institutions.component.html',
  styleUrls: ['./institutions.component.scss'],
})
export class InstitutionsComponent implements OnInit {

  activeTab: MainTab = 'institutions';

  institutions: Institution[] = [];
  types: InstitutionType[] = [];
  roles: RoleOperationnel[] = [];
  users: User[] = [];
  contacts: ContactInstitution[] = [];
  domaines: InstitutionDomaine[] = [];
  competences: Competence[] = [];
  affectationsRoles: AffectationRoleOperationnel[] = [];
  /** Zones (catalogue) de l'institution actuellement ouverte — chargées à l'ouverture du
   * détail (openDetail), pas dans le forkJoin initial (scopées à une seule institution). */
  zones: Zone[] = [];

  isLoading = true;
  isSaving = false;
  errorMessage = '';
  successMessage = '';
  searchQuery = '';

  // ── Institution ──
  modal: ModalView = 'none';
  selectedInstitution: Institution | null = null;
  institutionForm!: FormGroup;

  detailTab: DetailTab = 'contacts';
  showContactForm = false;
  showDomaineForm = false;
  showRegulateurForm = false;
  contactForm!: FormGroup;
  domaineForm!: FormGroup;
  regulateurForm!: FormGroup;

  contactUserQuery = '';
  showContactUserResults = false;

  // ── Type d'institution (référentiel) ──
  typeModal: RefModalView = 'none';
  selectedType: InstitutionType | null = null;
  typeForm!: FormGroup;

  // ── Rôle opérationnel (référentiel) ──
  roleModal: RefModalView = 'none';
  selectedRole: RoleOperationnel | null = null;
  roleForm!: FormGroup;

  constructor(
    private fb: FormBuilder,
    private institutionService: InstitutionService,
    private institutionTypeService: InstitutionTypeService,
    private roleOperationnelService: RoleOperationnelService,
    private contactService: ContactInstitutionService,
    private domaineService: InstitutionDomaineService,
    private userService: UserService,
    private competenceService: CompetenceService,
    private affectationRoleService: AffectationRoleOperationnelService,
    private locationService: LocationService,
    private zoneService: ZoneService,
  ) {}

  ngOnInit(): void {
    this.buildForms();
    this.loadAll();
  }

  private buildForms(): void {
    this.institutionForm = this.fb.group({
      nom: ['', [Validators.required, Validators.minLength(2)]],
      type: [null, Validators.required],
      description: [''],
      telephone: [''],
      email: ['', Validators.email],
      adresse: [''],
      commune_code: [null],
      commune_nom: [null],
      commune_code_postal: [null],
      actif: [true],
    });

    this.typeForm = this.fb.group({
      code: ['', Validators.required],
      libelle: ['', Validators.required],
      description: [''],
      actif: [true],
    });

    this.roleForm = this.fb.group({
      code: ['', Validators.required],
      libelle: ['', Validators.required],
      description: [''],
      actif: [true],
    });

    this.contactForm = this.fb.group({
      utilisateur: [null, Validators.required],
      fonction: ['', Validators.required],
      contact_principal: [false],
      // Optionnels : renseignés ici, ils créent en plus une affectation rôle/thème pour
      // éviter d'avoir à ressaisir le même utilisateur dans l'onglet "Régulateurs / thèmes".
      role: [null],
      competence: [null],
    });

    this.domaineForm = this.fb.group({
      domaine: ['', Validators.required],
      valide: [true],
    });

    this.regulateurForm = this.fb.group({
      utilisateur: [null, Validators.required],
      role: [null, Validators.required],
      competence: [null],
      zone: [null],
      responsabilite: [''],
      actif: [true],
    });
  }

  private loadAll(): void {
    this.isLoading = true;
    forkJoin({
      institutions: this.institutionService.getAll(),
      types: this.institutionTypeService.getAll(),
      roles: this.roleOperationnelService.getAll(),
      users: this.userService.getAll(),
      contacts: this.contactService.getAll(),
      domaines: this.domaineService.getAll(),
      competences: this.competenceService.getAll(),
      affectationsRoles: this.affectationRoleService.getAll(),
    }).subscribe({
      next: ({ institutions, types, roles, users, contacts, domaines, competences, affectationsRoles }) => {
        this.institutions = institutions;
        this.types = types;
        this.roles = roles;
        this.users = users;
        this.contacts = contacts;
        this.domaines = domaines;
        this.competences = competences;
        this.affectationsRoles = affectationsRoles;
        this.isLoading = false;
      },
      error: () => {
        this.showError('Impossible de charger les données.');
        this.isLoading = false;
      },
    });
  }

  reloadInstitutions(): void { this.institutionService.getAll().subscribe(data => this.institutions = data); }
  reloadTypes(): void { this.institutionTypeService.getAll().subscribe(data => this.types = data); }
  reloadRoles(): void { this.roleOperationnelService.getAll().subscribe(data => this.roles = data); }
  reloadContacts(): void { this.contactService.getAll().subscribe(data => this.contacts = data); }
  reloadDomaines(): void { this.domaineService.getAll().subscribe(data => this.domaines = data); }
  reloadAffectationsRoles(): void { this.affectationRoleService.getAll().subscribe(data => this.affectationsRoles = data); }

  // ══ Institutions — CRUD ═══════════════════════════════════════
  openCreate(): void {
    this.institutionForm.reset({ actif: true });
    this.modal = 'create';
  }

  submitCreate(): void {
    if (this.institutionForm.invalid) { this.institutionForm.markAllAsTouched(); return; }
    this.isSaving = true;
    this.institutionService.create(this.institutionForm.value).subscribe({
      next: () => { this.reloadInstitutions(); this.showSuccess('Institution créée.'); this.closeModal(); this.isSaving = false; },
      error: (err) => { this.showError('Erreur lors de la création.', err); this.isSaving = false; },
    });
  }

  openEdit(institution: Institution, e?: Event): void {
    e?.stopPropagation();
    this.selectedInstitution = institution;
    this.institutionForm.patchValue({
      nom: institution.nom,
      type: institution.type,
      description: institution.description,
      telephone: institution.telephone,
      email: institution.email,
      adresse: institution.adresse,
      commune_code: institution.commune_code,
      commune_nom: institution.commune_nom,
      commune_code_postal: institution.commune_code_postal,
      actif: institution.actif,
    });
    this.modal = 'edit';
  }

  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);

  onCommuneSelected(commune: Commune): void {
    this.institutionForm.patchValue({
      commune_code: commune.code,
      commune_nom: commune.name,
      commune_code_postal: commune.codePostal ?? null,
    });
  }

  clearCommune(): void {
    this.institutionForm.patchValue({ commune_code: null, commune_nom: null, commune_code_postal: null });
  }

  submitEdit(): void {
    if (!this.selectedInstitution?.id || this.institutionForm.invalid) { this.institutionForm.markAllAsTouched(); return; }
    this.isSaving = true;
    this.institutionService.patch(this.selectedInstitution.id, this.institutionForm.value).subscribe({
      next: () => { this.reloadInstitutions(); this.showSuccess('Institution modifiée.'); this.closeModal(); this.isSaving = false; },
      error: (err) => { this.showError('Erreur lors de la modification.', err); this.isSaving = false; },
    });
  }

  openDelete(institution: Institution, e?: Event): void {
    e?.stopPropagation();
    this.selectedInstitution = institution;
    this.modal = 'delete';
  }

  confirmDelete(): void {
    if (!this.selectedInstitution?.id) return;
    this.institutionService.delete(this.selectedInstitution.id).subscribe({
      next: () => { this.reloadInstitutions(); this.showSuccess('Institution supprimée.'); this.closeModal(); },
      error: (err) => this.showError('Erreur lors de la suppression.', err),
    });
  }

  openDetail(institution: Institution): void {
    this.selectedInstitution = institution;
    this.detailTab = 'contacts';
    this.showContactForm = false;
    this.showDomaineForm = false;
    this.showRegulateurForm = false;
    this.contactForm.reset({ contact_principal: false });
    this.contactUserQuery = '';
    this.domaineForm.reset({ valide: true });
    this.regulateurForm.reset({ actif: true });
    this.modal = 'detail';
    this.zones = [];
    if (institution.id) {
      this.zoneService.getAll(institution.id).subscribe(zones => this.zones = zones);
    }
  }

  closeModal(): void {
    this.modal = 'none';
    this.selectedInstitution = null;
  }

  // ══ Contacts (détail institution) ═════════════════════════════
  get institutionContacts(): ContactInstitution[] {
    if (!this.selectedInstitution?.id) return [];
    return this.contacts.filter(c => c.institution === this.selectedInstitution!.id);
  }

  submitContact(): void {
    if (!this.selectedInstitution?.id || this.contactForm.invalid) { this.contactForm.markAllAsTouched(); return; }
    const institution = this.selectedInstitution.id;
    const { utilisateur, fonction, contact_principal, role, competence } = this.contactForm.value;

    this.contactService.create({ utilisateur, fonction, contact_principal, institution, actif: true }).subscribe({
      next: () => {
        this.reloadContacts();

        // Rôle optionnel : évite de ressaisir le même utilisateur dans l'onglet
        // "Régulateurs / thèmes" pour lui donner un rôle opérationnel dans la foulée.
        if (role) {
          this.affectationRoleService.create({ utilisateur, role, competence, institution, actif: true }).subscribe({
            next: () => {
              this.reloadAffectationsRoles();
              this.showSuccess('Contact et affectation ajoutés.');
            },
            error: (err) => this.showError("Contact ajouté, mais l'affectation du rôle a échoué.", err),
          });
        } else {
          this.showSuccess('Contact ajouté.');
        }

        this.contactForm.reset({ contact_principal: false });
        this.contactUserQuery = '';
        this.showContactForm = false;
      },
      error: (err) => this.showError("Erreur lors de l'ajout du contact.", err),
    });
  }

  onContactCompetenceSearchSelected(item: Competence): void {
    if (!this.competences.find(c => c.id === item.id)) {
      this.competences = [...this.competences, item];
    }
    this.contactForm.get('competence')?.setValue(item.id);
  }

  isContactFieldInvalid(field: string): boolean {
    const control = this.contactForm.get(field);
    return !!control && control.invalid && control.touched;
  }

  get contactUserResults(): User[] {
    const q = this.contactUserQuery.trim().toLowerCase();
    if (!q) return [];
    return this.users.filter(u =>
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q)
      || u.username.toLowerCase().includes(q)
    );
  }

  selectContactUser(user: User): void {
    this.contactForm.get('utilisateur')?.setValue(user.id);
    this.contactUserQuery = `${user.first_name} ${user.last_name}`.trim() || user.username;
    this.showContactUserResults = false;
  }

  onContactUserQueryChange(): void {
    // Retaper dans le champ après une sélection invalide le choix précédent : il faut
    // re-sélectionner explicitement un résultat pour que le formulaire redevienne valide.
    this.contactForm.get('utilisateur')?.setValue(null);
    this.showContactUserResults = true;
  }

  hideContactUserResultsDelayed(): void {
    // Délai court pour laisser le (click) sur un résultat s'exécuter avant que le blur
    // ne referme la liste — sans ce délai, le clic sur un résultat n'a jamais lieu.
    setTimeout(() => this.showContactUserResults = false, 150);
  }

  deleteContact(contact: ContactInstitution): void {
    if (!contact.id) return;
    this.contactService.delete(contact.id).subscribe({
      next: () => { this.reloadContacts(); this.showSuccess('Contact supprimé.'); },
      error: (err) => this.showError('Erreur lors de la suppression du contact.', err),
    });
  }

  userName(id: string): string {
    const u = this.users.find(user => user.id === id);
    return u ? (`${u.first_name} ${u.last_name}`.trim() || u.username) : id.slice(0, 8);
  }

  // ══ Domaines email (détail institution) ═══════════════════════
  get institutionDomaines(): InstitutionDomaine[] {
    if (!this.selectedInstitution?.id) return [];
    return this.domaines.filter(d => d.institution === this.selectedInstitution!.id);
  }

  submitDomaine(): void {
    if (!this.selectedInstitution?.id || this.domaineForm.invalid) { this.domaineForm.markAllAsTouched(); return; }
    const payload = { ...this.domaineForm.value, institution: this.selectedInstitution.id };
    this.domaineService.create(payload).subscribe({
      next: () => {
        this.reloadDomaines();
        this.showSuccess('Domaine ajouté.');
        this.domaineForm.reset({ valide: true });
        this.showDomaineForm = false;
      },
      error: (err) => this.showError("Erreur lors de l'ajout du domaine.", err),
    });
  }

  deleteDomaine(domaine: InstitutionDomaine): void {
    if (domaine.id === undefined) return;
    this.domaineService.delete(domaine.id).subscribe({
      next: () => { this.reloadDomaines(); this.showSuccess('Domaine supprimé.'); },
      error: (err) => this.showError('Erreur lors de la suppression du domaine.', err),
    });
  }

  // ══ Régulateurs / responsables — thèmes (détail institution) ═══
  get institutionAffectationsRoles(): AffectationRoleOperationnel[] {
    if (!this.selectedInstitution?.id) return [];
    return this.affectationsRoles.filter(a => a.institution === this.selectedInstitution!.id);
  }

  submitRegulateur(): void {
    if (!this.selectedInstitution?.id || this.regulateurForm.invalid) { this.regulateurForm.markAllAsTouched(); return; }
    const payload = { ...this.regulateurForm.value, institution: this.selectedInstitution.id };
    this.affectationRoleService.create(payload).subscribe({
      next: () => {
        this.reloadAffectationsRoles();
        this.showSuccess('Affectation ajoutée.');
        this.regulateurForm.reset({ actif: true });
        this.showRegulateurForm = false;
      },
      error: (err) => this.showError("Erreur lors de l'affectation.", err),
    });
  }

  deleteAffectationRole(affectation: AffectationRoleOperationnel): void {
    if (!affectation.id) return;
    this.affectationRoleService.delete(affectation.id).subscribe({
      next: () => { this.reloadAffectationsRoles(); this.showSuccess('Affectation supprimée.'); },
      error: (err) => this.showError("Erreur lors de la suppression de l'affectation.", err),
    });
  }

  roleLabel(id: string): string {
    return this.roles.find(r => r.id === id)?.libelle ?? id.slice(0, 8);
  }

  competenceLabel(id: string | null): string {
    if (!id) return 'Aucun thème précisé';
    return this.competences.find(c => c.id === id)?.nom ?? id.slice(0, 8);
  }

  zoneLabel(id: string | null): string {
    if (!id) return '—';
    return this.zones.find(z => z.id === id)?.nom ?? id.slice(0, 8);
  }

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  onRegulateurCompetenceSearchSelected(item: Competence): void {
    if (!this.competences.find(c => c.id === item.id)) {
      this.competences = [...this.competences, item];
    }
    this.regulateurForm.get('competence')?.setValue(item.id);
  }

  // ══ Types d'institution (référentiel) ═════════════════════════
  openCreateType(): void {
    this.typeForm.reset({ actif: true });
    this.typeModal = 'create';
  }

  submitCreateType(): void {
    if (this.typeForm.invalid) { this.typeForm.markAllAsTouched(); return; }
    this.institutionTypeService.create(this.typeForm.value).subscribe({
      next: () => { this.reloadTypes(); this.showSuccess("Type d'institution créé."); this.closeTypeModal(); },
      error: (err) => this.showError('Erreur lors de la création.', err),
    });
  }

  openEditType(type: InstitutionType, e?: Event): void {
    e?.stopPropagation();
    this.selectedType = type;
    this.typeForm.patchValue(type);
    this.typeModal = 'edit';
  }

  submitEditType(): void {
    if (!this.selectedType?.id || this.typeForm.invalid) { this.typeForm.markAllAsTouched(); return; }
    this.institutionTypeService.update(this.selectedType.id, this.typeForm.value).subscribe({
      next: () => { this.reloadTypes(); this.showSuccess('Type modifié.'); this.closeTypeModal(); },
      error: (err) => this.showError('Erreur lors de la modification.', err),
    });
  }

  openDeleteType(type: InstitutionType, e?: Event): void {
    e?.stopPropagation();
    this.selectedType = type;
    this.typeModal = 'delete';
  }

  confirmDeleteType(): void {
    if (!this.selectedType?.id) return;
    this.institutionTypeService.delete(this.selectedType.id).subscribe({
      next: () => { this.reloadTypes(); this.showSuccess('Type supprimé.'); this.closeTypeModal(); },
      error: (err) => this.showError('Erreur lors de la suppression (probablement encore utilisé par une institution).', err),
    });
  }

  closeTypeModal(): void { this.typeModal = 'none'; this.selectedType = null; }

  // ══ Rôles opérationnels (référentiel) ═════════════════════════
  openCreateRole(): void {
    this.roleForm.reset({ actif: true });
    this.roleModal = 'create';
  }

  submitCreateRole(): void {
    if (this.roleForm.invalid) { this.roleForm.markAllAsTouched(); return; }
    this.roleOperationnelService.create(this.roleForm.value).subscribe({
      next: () => { this.reloadRoles(); this.showSuccess('Rôle opérationnel créé.'); this.closeRoleModal(); },
      error: (err) => this.showError('Erreur lors de la création.', err),
    });
  }

  openEditRole(role: RoleOperationnel, e?: Event): void {
    e?.stopPropagation();
    this.selectedRole = role;
    this.roleForm.patchValue(role);
    this.roleModal = 'edit';
  }

  submitEditRole(): void {
    if (!this.selectedRole?.id || this.roleForm.invalid) { this.roleForm.markAllAsTouched(); return; }
    this.roleOperationnelService.update(this.selectedRole.id, this.roleForm.value).subscribe({
      next: () => { this.reloadRoles(); this.showSuccess('Rôle modifié.'); this.closeRoleModal(); },
      error: (err) => this.showError('Erreur lors de la modification.', err),
    });
  }

  openDeleteRole(role: RoleOperationnel, e?: Event): void {
    e?.stopPropagation();
    this.selectedRole = role;
    this.roleModal = 'delete';
  }

  confirmDeleteRole(): void {
    if (!this.selectedRole?.id) return;
    this.roleOperationnelService.delete(this.selectedRole.id).subscribe({
      next: () => { this.reloadRoles(); this.showSuccess('Rôle supprimé.'); this.closeRoleModal(); },
      error: (err) => this.showError('Erreur lors de la suppression.', err),
    });
  }

  closeRoleModal(): void { this.roleModal = 'none'; this.selectedRole = null; }

  // ══ Helpers ════════════════════════════════════════════════════
  get filteredInstitutions(): Institution[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.institutions;
    return this.institutions.filter(i => i.nom.toLowerCase().includes(q));
  }

  typeLabel(institution: Institution): string {
    return institution.type_libelle ?? this.types.find(t => t.id === institution.type)?.libelle ?? '—';
  }

  private showSuccess(msg: string): void {
    this.successMessage = msg;
    setTimeout(() => this.successMessage = '', 3000);
  }

  private showError(fallback: string, err?: unknown): void {
    this.errorMessage = this.extractErrorMessage(err) ?? fallback;
    setTimeout(() => this.errorMessage = '', 5000);
  }

  // Le backend renvoie le détail exact de la validation (ex: contrainte violée, champ
  // invalide) — l'afficher plutôt qu'un message générique deviné évite d'induire l'utilisateur
  // en erreur sur la vraie cause d'un échec (ex: un message toujours affiché en cas d'échec de
  // création de contact, même quand la cause réelle n'a rien à voir avec le contact principal).
  private extractErrorMessage(err: unknown): string | null {
    const body = (err as any)?.error;
    if (!body) return null;
    if (typeof body === 'string') return body;
    if (typeof body.detail === 'string') return body.detail;
    const messages = Object.values(body)
      .map(v => Array.isArray(v) ? v.join(' ') : v)
      .filter((v): v is string => typeof v === 'string' && v.length > 0);
    return messages.length ? messages.join(' ') : null;
  }

  fmtDate(d?: string): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
}
