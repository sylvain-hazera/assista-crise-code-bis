import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { InstitutionService } from '../../services/institution.service';
import { InstitutionTypeService } from '../../services/institution-type.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { InstitutionDomaineService } from '../../services/institution-domaine.service';
import { UserService } from '../../services/user.service';

import {
  Institution,
  InstitutionType,
  RoleOperationnel,
  ContactInstitution,
  InstitutionDomaine,
} from '../../shared/models/institution.model';
import { User } from '../../shared/models/user.model';

type MainTab = 'institutions' | 'types' | 'roles';
type ModalView = 'none' | 'create' | 'edit' | 'delete' | 'detail';
type RefModalView = 'none' | 'create' | 'edit' | 'delete';

@Component({
  selector: 'app-institutions',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule],
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

  isLoading = true;
  isSaving = false;
  errorMessage = '';
  successMessage = '';
  searchQuery = '';

  // ── Institution ──
  modal: ModalView = 'none';
  selectedInstitution: Institution | null = null;
  institutionForm!: FormGroup;

  detailTab: 'contacts' | 'domaines' = 'contacts';
  showContactForm = false;
  showDomaineForm = false;
  contactForm!: FormGroup;
  domaineForm!: FormGroup;

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
      fonction: [''],
      contact_principal: [false],
    });

    this.domaineForm = this.fb.group({
      domaine: ['', Validators.required],
      valide: [true],
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
    }).subscribe({
      next: ({ institutions, types, roles, users, contacts, domaines }) => {
        this.institutions = institutions;
        this.types = types;
        this.roles = roles;
        this.users = users;
        this.contacts = contacts;
        this.domaines = domaines;
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
      error: () => { this.showError('Erreur lors de la création.'); this.isSaving = false; },
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
      actif: institution.actif,
    });
    this.modal = 'edit';
  }

  submitEdit(): void {
    if (!this.selectedInstitution?.id || this.institutionForm.invalid) { this.institutionForm.markAllAsTouched(); return; }
    this.isSaving = true;
    this.institutionService.patch(this.selectedInstitution.id, this.institutionForm.value).subscribe({
      next: () => { this.reloadInstitutions(); this.showSuccess('Institution modifiée.'); this.closeModal(); this.isSaving = false; },
      error: () => { this.showError('Erreur lors de la modification.'); this.isSaving = false; },
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
      error: () => this.showError('Erreur lors de la suppression.'),
    });
  }

  openDetail(institution: Institution): void {
    this.selectedInstitution = institution;
    this.detailTab = 'contacts';
    this.showContactForm = false;
    this.showDomaineForm = false;
    this.contactForm.reset({ contact_principal: false });
    this.domaineForm.reset({ valide: true });
    this.modal = 'detail';
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
    const payload = { ...this.contactForm.value, institution: this.selectedInstitution.id, actif: true };
    this.contactService.create(payload).subscribe({
      next: () => {
        this.reloadContacts();
        this.showSuccess('Contact ajouté.');
        this.contactForm.reset({ contact_principal: false });
        this.showContactForm = false;
      },
      error: () => this.showError("Erreur lors de l'ajout du contact (un seul contact principal par institution)."),
    });
  }

  deleteContact(contact: ContactInstitution): void {
    if (!contact.id) return;
    this.contactService.delete(contact.id).subscribe({
      next: () => { this.reloadContacts(); this.showSuccess('Contact supprimé.'); },
      error: () => this.showError('Erreur lors de la suppression du contact.'),
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
      error: () => this.showError("Erreur lors de l'ajout du domaine (peut-être déjà utilisé)."),
    });
  }

  deleteDomaine(domaine: InstitutionDomaine): void {
    if (domaine.id === undefined) return;
    this.domaineService.delete(domaine.id).subscribe({
      next: () => { this.reloadDomaines(); this.showSuccess('Domaine supprimé.'); },
      error: () => this.showError('Erreur lors de la suppression du domaine.'),
    });
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
      error: () => this.showError('Erreur lors de la création.'),
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
      error: () => this.showError('Erreur lors de la modification.'),
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
      error: () => this.showError('Erreur lors de la suppression (probablement encore utilisé par une institution).'),
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
      error: () => this.showError('Erreur lors de la création.'),
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
      error: () => this.showError('Erreur lors de la modification.'),
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
      error: () => this.showError('Erreur lors de la suppression.'),
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

  private showError(msg: string): void {
    this.errorMessage = msg;
    setTimeout(() => this.errorMessage = '', 5000);
  }

  fmtDate(d?: string): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
}
