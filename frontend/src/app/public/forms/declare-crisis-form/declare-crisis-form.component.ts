import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { CrisisService } from '../../../services/crisis.service';
import { Router } from '@angular/router';
import { GeolocationService } from '../../../services/geolocation.service';
import { Status } from '../../../shared/models/status.model';

@Component({
  selector: 'app-declare-crisis-form',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './declare-crisis-form.component.html',
  styleUrl: './declare-crisis-form.component.scss'
})
export class DeclareCrisisFormComponent implements OnInit{
  crisisForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  
  latitude: number | null = null;
  longitude: number | null = null;

    eventTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'incendie', label: 'Incendie' },
    { value: 'inondation', label: 'Inondation' },
    { value: 'accident', label: 'Accident' },
    { value: 'catastrophe-naturelle', label: 'Catastrophe naturelle' },
    { value: 'urgence-medicale', label: 'Urgence médicale' },
    { value: 'autre', label: 'Autre' }
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private crisisService: CrisisService,
    private geolocationService: GeolocationService,
  ) {}

  ngOnInit() {
    this.initForm();
  }

  initForm(): void {
    this.crisisForm = this.formBuilder.group({
      eventType: ['', Validators.required],
      title: ['', Validators.required],
      description: ['', [Validators.required, Validators.minLength(10)]],
      streetNumber: ['', Validators.required],
      postalCode: ['', [Validators.required, Validators.pattern(/^\d{5}$/)]],
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
    if(this.crisisForm.valid) {
      const formData = new FormData();

      formData.append('type_evenement', this.crisisForm.get('eventType')?.value);
      formData.append('titre', this.crisisForm.get('title')?.value);
      formData.append('description', this.crisisForm.get('description')?.value);

      const street = this.crisisForm.get('streetNumber')?.value;
      const zip = this.crisisForm.get('postalCode')?.value;
      const query = `${street} ${zip}`;
      this.geolocationService.getCoordinates(query).subscribe({
        next: (response) => {
          if (response.features && response.features.length > 0) {
            const coords = response.features[0].geometry.coordinates;
            this.longitude = coords[0];
            this.latitude = coords[1];
            
          } else {
            alert("Adresse introuvable. Vérifiez le numéro et le code postal.");
          }
        },
        error: (err) => {
          console.error(err);
          alert("Erreur de connexion au service d'adresse.");
        }
      });

      const localisation = {
        type: 'Point',
        coordinates: [this.longitude, this.latitude]
      };
      formData.append('localisation', JSON.stringify(localisation));
      if (this.selectedFile) {
        formData.append('photo', this.selectedFile);
      }
      formData.append('statut', 'NON_TRAITEE');
      // formData.append('statut', Status.NON_TRAITEE.toString());

      this.crisisService.createCrisis(formData).subscribe({
        next: (response) => {
          console.log('Crisis créée:', response);
          alert('Votre crisis a été enregistrée avec succès !');
          this.router.navigate(['/accueil']);
        },
        error: (err) => {
          console.error('Erreur création crisis:', err);
          alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
        }
      });

    } else {
      Object.keys(this.crisisForm.controls).forEach(key => {
        this.crisisForm.get(key)?.markAsTouched();
      });
      
      if (!this.latitude || !this.longitude) {
        alert('Erreur de géolocalisation. Veuillez vérifier l\'adresse.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
    }
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }
}
