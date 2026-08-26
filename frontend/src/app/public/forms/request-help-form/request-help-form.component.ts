import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { forkJoin, Observable } from 'rxjs';
import { RequestService } from '../../../services/request.service';
import { CrisisService } from '../../../services/crisis.service';
import { Crisis } from '../../../shared/models/crisis.model';
import { Request } from '../../../shared/models/request.model';
import { User } from '../../../shared/models/user.model';
import { AuthService } from '../../../auth/services/auth.service';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { AddressResult } from '../../../shared/models/address-result.model';

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule, AddressPickerComponent],
  templateUrl: './request-help-form.component.html',
  styleUrl: './request-help-form.component.scss'
})
export class RequestHelpFormComponent implements OnInit {
  currentUser: User | null = null;
  requestForm!: FormGroup;
  informationForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  state: number = 1;

  latitude: number | null = null;
  longitude: number | null = null;

  typesDemandeMap: Map<string, string> = new Map();

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

  needTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

  personTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'individual', label: 'Particulier' },
    { value: 'organization', label: 'Organisation' },
    { value: 'rescue', label: 'Secours organisés' },
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private helpRequestService: RequestService,
    private crisisService: CrisisService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.initForm();
    this.loadTypesDemande();
    this.loadActiveCrises();
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

  loadTypesDemande(): void {
    this.helpRequestService.getTypes().subscribe({
      next: (types: any[]) => {
        types.forEach(type => {
          this.typesDemandeMap.set(type.type, type.id);
        });

        const byId = new Map(types.map(t => [t.id, t]));
        const topLevel = types.filter(t => !t.parent);

        this.childrenByParentType.clear();
        types.filter(t => t.parent).forEach(child => {
          const parent = byId.get(child.parent);
          if (!parent) return;
          const list = this.childrenByParentType.get(parent.type) ?? [];
          list.push({ value: child.type, label: child.type });
          this.childrenByParentType.set(parent.type, list);
        });

        this.needTypeOptions = [
          { value: '', label: 'Dropdown' },
          ...topLevel.map(t => ({ value: t.type, label: t.type }))
        ];
      },
      error: (err: any) => console.error('Erreur chargement types:', err)
    });
  }

  // Sous-catégorie (précision optionnelle) par index de besoin — ex: "Matériel" >
  // "Groupe électrogène", "Interprétariat / traduction" > "Anglais".
  childrenByParentType: Map<string, { value: string; label: string }[]> = new Map();
  subCategorySelections: string[] = [];

  childrenFor(index: number): { value: string; label: string }[] {
    const topLevel = this.needsType.at(index)?.value;
    return topLevel ? (this.childrenByParentType.get(topLevel) ?? []) : [];
  }

  onTopLevelTypeChange(index: number): void {
    // Un changement de besoin principal invalide toute précision déjà choisie pour l'ancien.
    this.subCategorySelections[index] = '';
  }

  onSubCategoryChange(index: number, value: string): void {
    this.subCategorySelections[index] = value;
  }

  /** Type réellement à envoyer pour ce besoin : la précision si choisie, sinon le besoin
   * principal — cf. usage dans onSubmit(). */
  private effectiveNeedType(index: number): string {
    return this.subCategorySelections[index] || this.needsType.at(index).value;
  }

  initForm(): void {
    this.requestForm = this.formBuilder.group({
      crisisId: [''],
      needsType: new FormArray([]),
      descriptions: new FormArray([]),
      addressVisible: [false],
      image: [null],
    });

    this.addNeed(); // Ajouter un besoin initial  

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
    if (!this.informationForm.valid || !this.latitude || !this.longitude) {
      Object.keys(this.informationForm.controls).forEach(key => {
        this.informationForm.get(key)?.markAsTouched();
      });
      if (!this.latitude || !this.longitude) {
        alert('Erreur de géolocalisation. Veuillez vérifier l\'adresse.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
      return;
    }
    if (this.needsType.invalid) {
      this.needsType.markAllAsTouched();
      alert('Veuillez préciser chaque besoin.');
      return;
    }

    const crisisId = this.requestForm.get('crisisId')?.value;
    const crisisLabel = this.crisisOptions.find(c => c.value === crisisId)?.label || 'non liée à une crise';
    const localisation = { type: 'Point', coordinates: [this.longitude, this.latitude] };

    const creations: Observable<Request>[] = this.needsType.controls.map((needControl, i) => {
      const needType = this.effectiveNeedType(i);
      const description = this.descriptions.at(i).value;
      const formData = new FormData();

      formData.append('title', `Demande d'aide - ${crisisLabel} - ${needType}`);
      formData.append('first_name_request', this.informationForm.get('firstName')?.value);
      formData.append('last_name_request', this.informationForm.get('lastName')?.value);
      formData.append('email_request', this.informationForm.get('email')?.value);
      formData.append('phone_request', this.informationForm.get('phoneNumber')?.value);
      formData.append('location', JSON.stringify(localisation));
      if (this.selectedAddress?.citycode) formData.append('commune_code', this.selectedAddress.citycode);

      const typeId = this.typesDemandeMap.get(needType);
      if (typeId) formData.append('request_type', typeId);
      if (crisisId) formData.append('crisis', crisisId);
      if (description) formData.append('description', description);

      formData.append('status', 'NON_TRAITEE');
      if (this.currentUser?.id) formData.append('author', this.currentUser.id);
      if (this.selectedFile) formData.append('photo', this.selectedFile);

      return this.helpRequestService.create(formData);
    });

    forkJoin(creations).subscribe({
      next: () => {
        alert('Votre demande a été enregistrée avec succès !');
        this.router.navigate(['/accueil']);
      },
      error: (err) => {
        console.error('Erreur création demande:', err);
        if (err.status === 400) {
          if (err.error && err.error.photo) {
            alert("ERREUR PHOTO : " + err.error.photo[0]);
          } else {
            alert("Erreur de validation : Vérifiez les champs du formulaire.");
          }
        } else {
          alert("Une erreur technique est survenue. Veuillez réessayer.");
        }
      }
    });
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

  onContinue(): void {
    if (this.requestForm.valid && this.selectedAddress) {
      this.state = 2;
    } else {
      Object.keys(this.requestForm.controls).forEach(key => {
        this.requestForm.get(key)?.markAsTouched();
      });
      if (!this.selectedAddress) {
        alert('Veuillez sélectionner une adresse dans la liste proposée.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
    }
  }

  goBack(): void {
    if(this.state == 1) {
      this.router.navigate(['/accueil']);
    } else {
      this.state = 1;
    }
  }

  get needsType(): FormArray {
    return this.requestForm.get('needsType') as FormArray;
  }

  get descriptions(): FormArray {
    return this.requestForm.get('descriptions') as FormArray;
  }

  addNeed(): void {
    this.needsType.push(this.formBuilder.control('', Validators.required));
    this.descriptions.push(this.formBuilder.control('', [Validators.minLength(10)]));
    this.subCategorySelections.push('');
  }

  removeNeed(index: number): void {
    this.needsType.removeAt(index);
    this.descriptions.removeAt(index);
    this.subCategorySelections.splice(index, 1);
  }
}
