import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray, AbstractControl } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { forkJoin, Observable } from 'rxjs';
import { CommonModule } from '@angular/common';
import { OfferService } from '../../../services/offer.service';
import { DisponibiliteOffreService } from '../../../services/disponibilite-offre.service';
import { CrisisService } from '../../../services/crisis.service';
import { Crisis } from '../../../shared/models/crisis.model';
import { Offer } from '../../../shared/models/offer.model';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole, User } from '../../../shared/models/user.model';
import { Creneau } from '../../../shared/models/disponibilite-offre.model';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { AddressResult } from '../../../shared/models/address-result.model';

interface JourDispo {
  date: string;       // YYYY-MM-DD
  label: string;       // ex: "lun. 25/08"
  creneaux: { creneau: Creneau; label: string; checked: boolean }[];
}

// Labels exacts des OfferType côté backend (backend/entrypoint.sh) — utilisés pour savoir
// quels champs complémentaires afficher pour une ligne donnée.
const TYPE_HEBERGEMENT = 'Hébergement';
const TYPE_SOINS = 'Soins médicaux et paramédicaux';
const TYPE_TRANSPORT = 'Transport';
const TYPE_MATERIEL = 'Matériel';
const TYPE_SOUTIEN = 'Soutien psychologique';
const TYPE_AUTRE = 'Autre';

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule, AddressPickerComponent],
  templateUrl: './propose-help-form.component.html',
  styleUrl: './propose-help-form.component.scss'
})
export class ProposeHelpFormComponent implements OnInit {
  currentUser : User | null = null;
  requestForm!: FormGroup;
  informationForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  state: number = 1;

  latitude: number | null = null;
  longitude: number | null = null;

  typesOffreMap: Map<string, string> = new Map(); // offerType (label) -> UUID

  readonly TYPE_HEBERGEMENT = TYPE_HEBERGEMENT;
  readonly TYPE_SOINS = TYPE_SOINS;
  readonly TYPE_TRANSPORT = TYPE_TRANSPORT;
  readonly TYPE_MATERIEL = TYPE_MATERIEL;
  readonly TYPE_SOUTIEN = TYPE_SOUTIEN;
  readonly TYPE_AUTRE = TYPE_AUTRE;

  readonly materielTypeOptions: { value: string; label: string }[] = [
    { value: '', label: '— Choisir —' },
    { value: 'CUVE', label: 'Cuve' },
    { value: 'POMPE', label: 'Pompe' },
    { value: 'ETUVE', label: 'Étuve' },
    { value: 'CHAMBRE_FROIDE', label: 'Chambre froide' },
    { value: 'REMORQUE', label: 'Remorque' },
    { value: 'AUTRE', label: 'Autre' },
  ];

  selectedAddress: AddressResult | null = null;

  onAddressSelected(addr: AddressResult | null): void {
    this.selectedAddress = addr;
    this.latitude = addr?.latitude ?? null;
    this.longitude = addr?.longitude ?? null;
  }

  crisisOptions: { value: string; label: string }[] = [];
  filteredCrisisOptions: { value: string; label: string }[] = [];
  crisisSearch: string = 'Aucune crise en rapport';
  showCrisisDropdown: boolean = false;

  offerTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

  personTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: UserRole.SIMPLE_USER, label: 'Particulier' },
    { value: UserRole.LOCAL_AUTH , label: 'Organisation' },
    { value: UserRole.RESCUE , label: 'Secours organisés' },
  ];

  // ── Disponibilités (8 jours x matin/midi/soir/nuit) ────────────
  joursDispo: JourDispo[] = [];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private offerService: OfferService,
    private disponibiliteOffreService: DisponibiliteOffreService,
    private crisisService: CrisisService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.initForm();
    this.loadTypesOffre();
    this.loadActiveCrises();
    this.buildJoursDispo();
  }

  private buildJoursDispo(): void {
    const CRENEAUX: { creneau: Creneau; label: string }[] = [
      { creneau: 'MATIN', label: 'Matin' },
      { creneau: 'MIDI', label: 'Midi' },
      { creneau: 'SOIR', label: 'Soir' },
      { creneau: 'NUIT', label: 'Nuit' },
    ];
    const jours: JourDispo[] = [];
    for (let i = 0; i < 8; i++) {
      const d = new Date();
      d.setDate(d.getDate() + i);
      jours.push({
        date: d.toISOString().slice(0, 10),
        label: d.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' }),
        creneaux: CRENEAUX.map(c => ({ ...c, checked: false })),
      });
    }
    this.joursDispo = jours;
  }

  toggleDispo(jour: JourDispo, slot: { checked: boolean }): void {
    slot.checked = !slot.checked;
  }

  loadTypesOffre(): void {
    this.offerService.getTypes().subscribe({
      next: (types: any[]) => {
        types.forEach(type => {
          this.typesOffreMap.set(type.type, type.id);
        });
        this.offerTypeOptions = [
          { value: '', label: 'Dropdown' },
          ...types.map(t => ({ value: t.type, label: t.type }))
        ];
      },
      error: (err: any) => console.error('Erreur chargement types offre:', err)
    });
  }

  loadActiveCrises(): void {
    this.crisisService.getAll().subscribe({
      next: (crises: Crisis[]) => {
        const activeCrises = crises.filter(c => c.is_open !== false);
        this.crisisOptions = [
          { value: '', label: 'Aucune crise en rapport' },
          ...activeCrises.map(c => ({
            value: c.id,
            label: `${c.name} - ${c.type}`
          }))
        ];
        this.filteredCrisisOptions = [...this.crisisOptions];
      },
      error: (err) => console.error('Erreur chargement crises:', err)
    });
  }

  initForm(): void {
    this.requestForm = this.formBuilder.group({
      crisisId: [''],
      offerRows: new FormArray([]),
      addressVisible: [false],
      image: [null],
    });

    this.addOffer(); // Ajouter une ligne d'offre initiale

    this.informationForm = this.formBuilder.group({
      lastName: [this.currentUser?.last_name, Validators.required],
      firstName: [this.currentUser?.first_name, Validators.required],
      email: [this.currentUser?.email, [Validators.required, Validators.email]],
      phoneNumber: [this.currentUser?.phone_number, [Validators.required, Validators.pattern(/^\+?\d{10,15}$/)]]
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

      this.requestForm.patchValue({ image: this.selectedFile });
    }
  }

  onSubmit(): void {
    if (!this.informationForm.valid) {
      Object.keys(this.informationForm.controls).forEach(key => {
        this.informationForm.get(key)?.markAsTouched();
      });
      alert('Veuillez remplir tous les champs obligatoires');
      return;
    }
    if (this.offerRows.invalid) {
      this.offerRows.markAllAsTouched();
      alert('Veuillez compléter les informations sur votre offre.');
      return;
    }

    const crisisId = this.requestForm.get('crisisId')?.value;
    const crisisLabel = this.crisisOptions.find(c => c.value === crisisId)?.label || 'non liée à une crise';
    const addressVisible = this.requestForm.get('addressVisible')?.value;
    const hasLocation = !!(addressVisible && this.latitude != null && this.longitude != null);

    const creations: Observable<Offer>[] = this.offerRows.controls.map(row => {
      const v = row.value;
      const formData = new FormData();

      formData.append('title', `Offre d'aide - ${crisisLabel} - ${v.type}`);
      formData.append('first_name_offer', this.informationForm.get('firstName')?.value);
      formData.append('last_name_offer', this.informationForm.get('lastName')?.value);
      formData.append('email_offer', this.informationForm.get('email')?.value);

      const typeId = this.typesOffreMap.get(v.type);
      if (typeId) formData.append('offer_type', typeId);
      if (crisisId) formData.append('crisis', crisisId);

      if (hasLocation) {
        formData.append('location', JSON.stringify({
          type: 'Point', coordinates: [this.longitude, this.latitude],
        }));
      }

      formData.append('description', this.buildDescription(v));
      formData.append('renouvelable', String(!!v.renouvelable));
      if (v.type === TYPE_HEBERGEMENT && v.hebergementDuree) formData.append('hebergement_duree', v.hebergementDuree);
      if (v.type === TYPE_SOINS && v.numeroAdeliRpps) formData.append('numero_adeli_rpps', v.numeroAdeliRpps);
      if (v.type === TYPE_TRANSPORT && v.transportType) formData.append('transport_type', v.transportType);
      if (v.type === TYPE_MATERIEL && v.materielType) formData.append('materiel_type', v.materielType);
      if (v.type === TYPE_SOUTIEN && v.soutienType) formData.append('soutien_type', v.soutienType);

      formData.append('status', 'DISPONIBLE');
      if (this.currentUser?.id) formData.append('author', this.currentUser.id);
      if (this.selectedFile) formData.append('photo', this.selectedFile);

      return this.offerService.create(formData);
    });

    forkJoin(creations).subscribe({
      next: (offers) => {
        offers.forEach(o => this.declareDisponibilites(o.id));
        alert('Votre offre a été enregistrée avec succès !');
        this.router.navigate(['/accueil']);
      },
      error: (err) => {
        console.error('Erreur création offre:', err);
        if (err.status === 400 && err.error) {
          const errors = Object.entries(err.error).map(([key, value]) => `${key}: ${value}`).join('\n');
          alert(`Erreur de validation:\n${errors}`);
        } else {
          alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
        }
      }
    });
  }

  private buildDescription(rowValue: any): string {
    if (rowValue.type === TYPE_AUTRE) {
      return `[Bénévolat] ${rowValue.description || ''}`.trim();
    }
    return rowValue.description || '';
  }

  onCrisisSearchChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.crisisSearch = input.value;
    this.filteredCrisisOptions = this.crisisOptions.filter(crisis =>
      crisis.label.toLowerCase().includes(this.crisisSearch.toLowerCase())
    );
    this.showCrisisDropdown = true;
  }

  selectCrisis(crisis: { value: string; label: string }): void {
    this.crisisSearch = crisis.label;
    this.requestForm.patchValue({ crisisId: crisis.value });
    this.showCrisisDropdown = false;
  }

  /** L'adresse est optionnelle pour un offreur d'aide : le sélecteur résout déjà les
   * coordonnées au moment du choix, aucun géocodage à refaire ici. */
  onContinue(): void {
    this.state = 2;
  }

  goBack(): void {
    if(this.state == 1) {
      this.router.navigate(['/accueil']);
    } else {
      this.state = 1;
    }
  }

  /** Envoie les créneaux de disponibilité cochés, liés à l'offre qui vient d'être créée. Un
   * échec ici n'annule pas la création de l'offre (déjà faite). */
  private declareDisponibilites(offerId: string): void {
    for (const jour of this.joursDispo) {
      for (const slot of jour.creneaux) {
        if (slot.checked) {
          this.disponibiliteOffreService.create({
            offer: offerId, date: jour.date, creneau: slot.creneau,
          }).subscribe({
            error: (err) => console.error('Erreur enregistrement disponibilité:', err),
          });
        }
      }
    }
  }

  // ── Lignes "Quelle aide proposez-vous" ─────────────────────────
  get offerRows(): FormArray {
    return this.requestForm.get('offerRows') as FormArray;
  }

  rowGroup(control: AbstractControl): FormGroup {
    return control as FormGroup;
  }

  addOffer(): void {
    this.offerRows.push(this.formBuilder.group({
      type: ['', Validators.required],
      description: ['', [Validators.minLength(10)]],
      hebergementDuree: [''],
      numeroAdeliRpps: [''],
      transportType: [''],
      materielType: [''],
      soutienType: [''],
      renouvelable: [false],
    }));
  }

  removeOffer(index: number): void {
    this.offerRows.removeAt(index);
  }
}
