import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { CrisisService } from '../../../services/crisis.service';
import { Router } from '@angular/router';
import { Status } from '../../../shared/models/status.model';
import { CommonModule } from '@angular/common';
import { CrisisPayload } from '../../../shared/models/crisis.model';
import { forkJoin } from 'rxjs';
import { AuthService } from '../../../auth/services/auth.service';
import { ZoneMapComponent } from '../../../shared/components/common/zone-map/zone-map.component';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { ContactInstitutionService } from '../../../services/contact-institution.service';
import { InstitutionService } from '../../../services/institution.service';
import { BesoinService } from '../../../services/besoin.service';
import { ImplicationService } from '../../../services/implication.service';
import { ContactInstitution, Institution } from '../../../shared/models/institution.model';
import { Besoin } from '../../../shared/models/besoin.model';
import { UserRole } from '../../../shared/models/user.model';
import { AddressResult } from '../../../shared/models/address-result.model';
import { ValidationSummaryComponent } from '../../../shared/components/public/validation-summary/validation-summary.component';

type ResponsableMode = 'moi' | 'contact' | 'email';

@Component({
  selector: 'app-declare-crisis-form',
  standalone: true,
  imports: [ReactiveFormsModule, FormsModule, CommonModule, ZoneMapComponent, AddressPickerComponent, ValidationSummaryComponent],
  templateUrl: './declare-crisis-form.component.html',
  styleUrl: './declare-crisis-form.component.scss'
})
export class DeclareCrisisFormComponent implements OnInit{
  crisisForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  zoneWkt: string | null = null;

  onZoneChange(wkt: string | null): void {
    this.zoneWkt = wkt;
  }

  // ── Institution déclarante / thèmes / responsable ──────────────
  isAdmin = false;
  myInstitutions: Institution[] = [];
  allInstitutions: Institution[] = [];
  private allContacts: ContactInstitution[] = [];
  institutionContacts: ContactInstitution[] = [];
  besoins: Besoin[] = [];

  /** Un admin (pas rattaché à une institution) peut déclarer pour n'importe laquelle ;
   * un acteur institutionnel reste limité aux siennes. */
  get selectableInstitutions(): Institution[] {
    return this.isAdmin ? this.allInstitutions : this.myInstitutions;
  }

  selectedInstitutionId: string | null = null;
  selectedThemes: string[] = [];
  responsableMode: ResponsableMode = 'moi';
  responsableContactId: string | null = null;
  responsableEmail = '';

  onInstitutionChange(id: string): void {
    this.selectedInstitutionId = id || null;
    this.institutionContacts = this.selectedInstitutionId
      ? this.allContacts.filter(c => c.institution === this.selectedInstitutionId && c.actif)
      : [];
    this.responsableContactId = null;
  }

  toggleTheme(besoinId: string, checked: boolean): void {
    this.selectedThemes = checked
      ? [...this.selectedThemes, besoinId]
      : this.selectedThemes.filter(id => id !== besoinId);
  }

  // ── Thèmes à l'écoute : menu pliable, local jusqu'à la soumission ──
  besoinsDropdownOpen = false;
  expandedBesoinGroups = new Set<string>();

  get besoinGroups(): { parent: Besoin; children: Besoin[] }[] {
    const topLevel = this.besoins.filter(b => !b.parent);
    return topLevel.map(parent => ({
      parent,
      children: this.besoins.filter(b => b.parent === parent.id),
    }));
  }

  toggleBesoinGroupExpand(parentId: string): void {
    if (this.expandedBesoinGroups.has(parentId)) this.expandedBesoinGroups.delete(parentId);
    else this.expandedBesoinGroups.add(parentId);
  }

  isBesoinGroupExpanded(parentId: string): boolean {
    return this.expandedBesoinGroups.has(parentId);
  }

  besoinGroupState(group: { parent: Besoin; children: Besoin[] }): 'all' | 'some' | 'none' {
    const ids = [group.parent.id, ...group.children.map(c => c.id)];
    const selected = ids.filter(id => this.selectedThemes.includes(id)).length;
    if (selected === 0) return 'none';
    return selected === ids.length ? 'all' : 'some';
  }

  /** Coche ou décoche le thème parent et tous ses sous-thèmes. */
  toggleBesoinGroup(group: { parent: Besoin; children: Besoin[] }): void {
    const groupIds = [group.parent.id, ...group.children.map(c => c.id)];
    const tout = groupIds.every(id => this.selectedThemes.includes(id));
    this.selectedThemes = tout
      ? this.selectedThemes.filter(id => !groupIds.includes(id))
      : [...new Set([...this.selectedThemes, ...groupIds])];
  }

  /** Tout cocher / tout décocher. */
  get allBesoinsChecked(): boolean {
    return this.besoins.length > 0 && this.besoins.every(b => this.selectedThemes.includes(b.id));
  }

  toggleAllBesoins(): void {
    this.selectedThemes = this.allBesoinsChecked ? [] : this.besoins.map(b => b.id);
  }

  selectedAddress: AddressResult | null = null;

  // Centre de la minimap : champs mis à jour seulement quand selectedAddress change (un getter
  // recréerait le tableau et relancerait flyTo en boucle).
  zoneMapCenter: [number, number] = [2.2137, 46.2276];
  zoneMapZoom = 6;

  onAddressSelected(addr: AddressResult | null): void {
    this.selectedAddress = addr;
    if (addr) {
      this.zoneMapCenter = [addr.longitude, addr.latitude];
      this.zoneMapZoom = 13;
    }
  }

    eventTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'INCENDIE', label: 'Incendie' },
    { value: 'INONDATION', label: 'Inondation' },
    { value: 'ACCIDENT', label: 'Accident' },
    { value: 'CATASTROPHE_NATURELLE', label: 'Catastrophe naturelle' },
    { value: 'AUTRE', label: 'Autre' }
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private crisisService: CrisisService,
    private authService: AuthService,
    private contactInstitutionService: ContactInstitutionService,
    private institutionService: InstitutionService,
    private besoinService: BesoinService,
    private implicationService: ImplicationService,
  ) {}

  ngOnInit() {
    this.initForm();
    this.loadInstitutionContext();
  }

  private loadInstitutionContext(): void {
    forkJoin({
      contacts: this.contactInstitutionService.getAll(),
      institutions: this.institutionService.getAll(),
      besoins: this.besoinService.getAll(),
    }).subscribe({
      next: ({ contacts, institutions, besoins }) => {
        this.allContacts = contacts;
        this.allInstitutions = institutions;
        this.besoins = besoins;
        const me = this.authService.getCurrentUser();
        this.isAdmin = me?.type === UserRole.ADMIN;
        const mesContacts = contacts.filter(c => c.utilisateur === me?.id && c.actif);
        const myInstitutionIds = new Set(mesContacts.map(c => c.institution));
        this.myInstitutions = institutions.filter(i => myInstitutionIds.has(i.id!));
        // Un non-admin ne choisit pas son institution : contact principal en priorité, sinon la première.
        if (!this.isAdmin && this.myInstitutions.length > 0) {
          const principal = mesContacts.find(c => c.contact_principal);
          this.onInstitutionChange(principal?.institution ?? this.myInstitutions[0].id!);
        }
      },
      error: (err) => console.error('Erreur chargement contexte institution:', err),
    });
  }

  initForm(): void {
    this.crisisForm = this.formBuilder.group({
      eventType: ['', Validators.required],
      title: ['', Validators.required],
      description: ['', [Validators.minLength(10)]],
      addressVisible: [false],
      image: [null],
    });

  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files[0]) {
      this.selectedFile = input.files[0];
      this.fileName = this.selectedFile.name;

      // Vérifier le type de fichier
      const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif'];
      if (!validTypes.includes(this.selectedFile.type)) {
        alert('Veuillez sélectionner une image valide (JPEG, PNG, GIF)');
        this.selectedFile = null;
        this.fileName = 'Select';
        return;
      }

      // Vérifier la taille (max 5MB)
      if (this.selectedFile.size > 5 * 1024 * 1024) {
        alert('L\'image ne doit pas dépasser 5MB');
        this.selectedFile = null;
        this.fileName = 'Select';
        return;
      }

      this.crisisForm.patchValue({ image: this.selectedFile });
    }
  }

  // Résumé des erreurs au-dessus du bouton d'envoi.
  formErrors: string[] = [];

  private validationErrors(): string[] {
    const errors: string[] = [];
    const f = this.crisisForm;
    if (f.get('eventType')?.invalid) errors.push("Le type d'événement est obligatoire.");
    if (f.get('title')?.invalid) errors.push('Le titre est obligatoire.');
    if (f.get('description')?.invalid) errors.push('La description doit contenir au moins 10 caractères.');
    if (!this.selectedAddress) errors.push('Sélectionnez une adresse dans la liste proposée.');
    return errors;
  }

  onSubmit(): void {
    this.crisisForm.markAllAsTouched();
    this.formErrors = this.validationErrors();
    if (this.formErrors.length === 0) {
      const formValue = this.crisisForm.value;

      const payload: CrisisPayload = {
        name: formValue.title,
        type: formValue.eventType,
        description: formValue.description,
        latitude: this.selectedAddress!.latitude,
        longitude: this.selectedAddress!.longitude,
        zone: this.zoneWkt,
        author: this.authService.getCurrentUser()?.id,
        status: 'NON_TRAITEE'
      };

      const formData = this.crisisService.buildFormData(
        payload,
        this.selectedFile!
      );

      this.crisisService.create(formData).subscribe({
        next: (response: any) => {
          console.log('Crisis créée:', response);
          this.declareInstitutionImplication(response.id);
          // Propose d'enchaîner sur le démarrage de crise (CriseDemarrageComponent).
          const configurerMaintenant = confirm(
            "Votre crise a été enregistrée avec succès !\n\n" +
            "Voulez-vous configurer maintenant ses éléments stratégiques (cellule de crise, " +
            "centre d'accueil, centre de regroupement des moyens) ?"
          );
          if (configurerMaintenant) {
            this.router.navigate(['/admin/crises', response.id, 'demarrage']);
          } else {
            this.router.navigate(['/accueil']);
          }
        },
        error: (err) => {
          console.error('Erreur création crise:', err);

          let errorMessage = 'Erreur lors de l\'enregistrement. Veuillez réessayer.';

          if (err.status === 401) {
            errorMessage = 'Vous devez être connecté en tant qu\'administrateur ou autorité locale pour déclarer une crise.';
          } else if (err.status === 400 && err.error?.onboarding) {
            // Rattachement à l'institution non finalisé (_verifier_onboarding_termine) : redirection.
            alert(err.error.onboarding);
            this.router.navigate(['/completer-inscription']);
            return;
          } else if (err.status === 403) {
            errorMessage = 'Vous n\'avez pas les permissions nécessaires pour déclarer une crise.';
          } else if (err.status === 400 && err.error) {
            const details = Object.values(err.error).flat().join(' ');
            errorMessage = `Erreur de validation : ${details}`;
          }

          alert(errorMessage);
        }
      });
    }
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }

  /** Déclare l'institution comme acteur de la nouvelle crise ; un échec n'annule pas la crise. */
  private declareInstitutionImplication(crisisId: string): void {
    if (!this.selectedInstitutionId) {
      return;
    }

    const payload: any = {
      crise: crisisId,
      institution: this.selectedInstitutionId,
      type_implication: 'ACTEUR',
      themes: this.selectedThemes,
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
      error: (err) => console.error("Erreur lors de la déclaration de l'implication :", err),
    });
  }

}
