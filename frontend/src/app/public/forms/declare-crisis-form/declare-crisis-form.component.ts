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

type ResponsableMode = 'moi' | 'contact' | 'email';

@Component({
  selector: 'app-declare-crisis-form',
  standalone: true,
  imports: [ReactiveFormsModule, FormsModule, CommonModule, ZoneMapComponent, AddressPickerComponent],
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

  selectedAddress: AddressResult | null = null;

  onAddressSelected(addr: AddressResult | null): void {
    this.selectedAddress = addr;
  }

    eventTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'INCEDIE', label: 'Incendie' },
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
        const myInstitutionIds = new Set(
          contacts.filter(c => c.utilisateur === me?.id && c.actif).map(c => c.institution)
        );
        this.myInstitutions = institutions.filter(i => myInstitutionIds.has(i.id!));
        if (!this.isAdmin && this.myInstitutions.length === 1) {
          this.onInstitutionChange(this.myInstitutions[0].id!);
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

  onSubmit(): void {
    if (this.crisisForm.valid && this.selectedAddress) {
      const formValue = this.crisisForm.value;

      const payload: CrisisPayload = {
        name: formValue.title,
        type: formValue.eventType,
        description: formValue.description,
        latitude: this.selectedAddress.latitude,
        longitude: this.selectedAddress.longitude,
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
          alert('Votre crise a été enregistrée avec succès !');
          this.router.navigate(['/accueil']);
        },
        error: (err) => {
          console.error('Erreur création crise:', err);

          let errorMessage = 'Erreur lors de l\'enregistrement. Veuillez réessayer.';

          if (err.status === 401) {
            errorMessage = 'Vous devez être connecté en tant qu\'administrateur ou autorité locale pour déclarer une crise.';
          } else if (err.status === 403) {
            errorMessage = 'Vous n\'avez pas les permissions nécessaires pour déclarer une crise.';
          } else if (err.status === 400 && err.error) {
            const details = Object.values(err.error).flat().join(' ');
            errorMessage = `Erreur de validation : ${details}`;
          }

          alert(errorMessage);
        }
      });
    } else {
      Object.keys(this.crisisForm.controls).forEach(key => {
        this.crisisForm.get(key)?.markAsTouched();
      });
      if (!this.selectedAddress) {
        alert('Veuillez sélectionner une adresse dans la liste proposée.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
    }
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }

  /** Déclare l'institution du déclarant comme acteur sur la crise qui vient d'être créée,
   * avec ses thèmes d'écoute et son responsable/régulateur. Un échec ici n'annule pas la
   * création de la crise (déjà faite) : l'utilisateur peut compléter depuis /admin/crises. */
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
