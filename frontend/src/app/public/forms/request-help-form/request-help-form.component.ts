import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray } from '@angular/forms';
import { Router } from '@angular/router';
import { HelpRequestService } from '../../../services/help-request.service';
import { GeolocationService } from '../../../services/geolocation.service';
import { ApiService } from '../../../services/api.service';
import { CommonModule } from '@angular/common';
// import { NgSelectModule } from '@ng-select/ng-select';

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule],
  templateUrl: './request-help-form.component.html',
  styleUrl: './request-help-form.component.scss'
})
export class RequestHelpFormComponent implements OnInit {
  requestForm!: FormGroup;
  informationForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  state: number = 1;

  latitude: number | null = null;
  longitude: number | null = null;

  requestData: FormData = new FormData();
  typesDemandeMap: Map<string, string> = new Map(); // eventType -> UUID

  eventTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'incendie', label: 'Incendie' },
    { value: 'inondation', label: 'Inondation' },
    { value: 'accident', label: 'Accident' },
    { value: 'catastrophe-naturelle', label: 'Catastrophe naturelle' },
    { value: 'urgence-medicale', label: 'Urgence médicale' },
    { value: 'autre', label: 'Autre' }
  ];

  needTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'assistance-immediate', label: 'Assistance immédiate' },
    { value: 'hebergement', label: 'Hébergement' },
    { value: 'nourriture', label: 'Nourriture et eau' },
    { value: 'soins-medicaux', label: 'Soins médicaux' },
    { value: 'transport', label: 'Transport' },
    { value: 'materiel', label: 'Matériel' },
    { value: 'soutien-psychologique', label: 'Soutien psychologique' },
    { value: 'autre', label: 'Autre' }
  ];

  personTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'individual', label: 'Particulier' },
    { value: 'organization', label: 'Organisation' }
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private helpRequestService: HelpRequestService,
    private geolocationService: GeolocationService,
    private apiService: ApiService
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.loadTypesDemande();
  }

  loadTypesDemande(): void {
    this.apiService.getTypesDemande().subscribe({
      next: (types) => {
        // Mapper les valeurs du formulaire aux UUIDs des types
        types.forEach(t => {
          const normalizedType = t.type.toLowerCase().replace(/\s+/g, '-');
          this.typesDemandeMap.set(normalizedType, t.id!);
        });
        console.log('Types chargés:', this.typesDemandeMap);
      },
      error: (err) => console.error('Erreur chargement types:', err)
    });
  }

  initForm(): void {
    this.requestForm = this.formBuilder.group({
      eventType: ['', Validators.required],
      // needType: ['', Validators.required],
      // description: ['', [Validators.required, Validators.minLength(10)]],
      needsType: new FormArray([]),
      descriptions: new FormArray([]),
      streetNumber: ['', Validators.required],
      postalCode: ['', [Validators.required, Validators.pattern(/^\d{5}$/)]],
      addressVisible: [false],
      image: [null],
    });

    this.addNeed(); // Ajouter un besoin initial  

    this.informationForm = this.formBuilder.group({
      personType: ['individual', Validators.required],
      lastName: ['', Validators.required],
      firstName: ['', Validators.required],
      email: ['', [Validators.required, Validators.email]],
      phoneNumber: ['', [Validators.required, Validators.pattern(/^\+?\d{10,15}$/)]]
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
    alert('onSubmit appelé !');
    console.log('=== DEBUG SUBMIT ===');
    console.log('requestForm valid:', this.requestForm.valid);
    console.log('requestForm errors:', this.requestForm.errors);
    console.log('requestForm value:', this.requestForm.value);
    console.log('informationForm valid:', this.informationForm.valid);
    console.log('informationForm errors:', this.informationForm.errors);
    console.log('informationForm value:', this.informationForm.value);
    console.log('Latitude:', this.latitude, 'Longitude:', this.longitude);
    console.log('needsType controls:', this.needsType.controls.map((c, i) => ({index: i, valid: c.valid, value: c.value})));
    console.log('descriptions controls:', this.descriptions.controls.map((c, i) => ({index: i, valid: c.valid, value: c.value})));
    
    if (this.informationForm.valid && this.latitude && this.longitude) {
      console.log('Formulaire valide:', this.informationForm.value);

      // Préparer les données pour Django
      const formData = new FormData();
      
      // Champs du modèle Demande Django
      formData.append('prenom_demande', this.informationForm.get('firstName')?.value);
      formData.append('nom_demande', this.informationForm.get('lastName')?.value);
      formData.append('email_demande', this.informationForm.get('email')?.value);
      formData.append('telephone_demande', this.informationForm.get('phoneNumber')?.value);
      
      // Titre basé sur le type d'événement
      const eventType = this.requestForm.get('eventType')?.value;
      const titre = `Demande ${this.eventTypeOptions.find(e => e.value === eventType)?.label || 'aide'}`;
      formData.append('titre', titre);
      
      // Localisation au format GeoJSON Point
      const localisation = {
        type: 'Point',
        coordinates: [this.longitude, this.latitude]
      };
      formData.append('localisation', JSON.stringify(localisation));
      
      // Type demande - UUID récupéré depuis la map
      const typeDemandeId = this.typesDemandeMap.get(eventType);
      if (!typeDemandeId) {
        alert('Type de demande non trouvé. Veuillez réessayer ou contacter le support.');
        return;
      }
      formData.append('type_demande', typeDemandeId);
      
      formData.append('statut', 'NON_TRAITEE');
      
      // Photo si présente
      if (this.selectedFile) {
        formData.append('photo', this.selectedFile);
      }

      // Envoyer au backend Django
      this.helpRequestService.createRequest(formData).subscribe({
        next: (response) => {
          console.log('Demande créée:', response);
          alert('Votre demande a été enregistrée avec succès !');
          this.router.navigate(['/accueil']);
        },
        error: (err) => {
          console.error('Erreur création demande:', err);
          alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
        }
      });

    } else {
      Object.keys(this.informationForm.controls).forEach(key => {
        this.informationForm.get(key)?.markAsTouched();
      });
      
      if (!this.latitude || !this.longitude) {
        alert('Erreur de géolocalisation. Veuillez vérifier l\'adresse.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
    }
  }

  onContinue(): void {
    if (this.requestForm.valid) {

      const street = this.requestForm.get('streetNumber')?.value;
      const zip = this.requestForm.get('postalCode')?.value;
      const query = `${street} ${zip}`;

      console.log('Recherche GPS pour :', query);

      this.geolocationService.getCoordinates(query).subscribe({
        next: (response) => {
          if (response.features && response.features.length > 0) {
            const coords = response.features[0].geometry.coordinates;
            this.longitude = coords[0];
            this.latitude = coords[1];
            
            console.log(`Trouvé : ${this.latitude}, ${this.longitude}`);
            this.state = 2;
          } else {
            alert("Adresse introuvable. Vérifiez le numéro et le code postal.");
          }
        },
        error: (err) => {
          console.error(err);
          alert("Erreur de connexion au service d'adresse.");
        }
      });

      // this.requestData.append('eventType', this.requestForm.get('eventType')?.value);
      // for (const needType of this.requestForm.get('needsType')?.value) {
      //   this.requestData.append('needType', needType);
      // }
      // for (const description of this.requestForm.get('descriptions')?.value) {
      //   this.requestData.append('description', description);
      // }
      // // this.requestData.append('needType', this.requestForm.get('needType')?.value);
      // // this.requestData.append('description', this.requestForm.get('description')?.value);
      // this.requestData.append('streetNumber', this.requestForm.get('streetNumber')?.value);
      // this.requestData.append('postalCode', this.requestForm.get('postalCode')?.value);
      // this.requestData.append('addressVisible', this.requestForm.get('addressVisible')?.value);

      // if (this.selectedFile) {
      //   this.requestData.append('image', this.selectedFile);
      // }

      // this.state = 2;
  } else {
      // Marquer tous les champs comme touchés pour afficher les erreurs
      Object.keys(this.requestForm.controls).forEach(key => {
        this.requestForm.get(key)?.markAsTouched();
      });
      alert('Veuillez remplir tous les champs obligatoires');
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
    this.descriptions.push(this.formBuilder.control('', [Validators.required, Validators.minLength(10)]));
  }

  removeNeed(index: number): void {
    this.needsType.removeAt(index);
    this.descriptions.removeAt(index);
  }
}
