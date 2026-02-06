import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { InformationService } from '../../../services/information.service';
import { Router } from '@angular/router';
import { GeolocationService } from '../../../services/geolocation.service';

enum StateForm {
  DeclareSafe,
  OtherDeclaration
}

@Component({
  selector: 'app-other-declaration-form',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './other-declaration-form.component.html',
  styleUrl: './other-declaration-form.component.scss'
})
export class OtherDeclarationFormComponent implements OnInit {
  declareSafeForm!: FormGroup;
  otherInformationForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  state: StateForm = StateForm.DeclareSafe;

  latitude: number | null = null;
  longitude: number | null = null;

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private informationService: InformationService,
    private geolocationService: GeolocationService,

  ) {}

  ngOnInit(): void {
    this.initForm();
  }

  initForm(): void {
    this.declareSafeForm = this.formBuilder.group({
      eventType: ['', Validators.required],
      streetNumber: ['', Validators.required],
      postalCode: ['', [Validators.required, Validators.pattern(/^\d{5}$/)]],
      addressVisible: [false],
      image: [null],

      personType: ['individual', Validators.required],
      lastName: ['', Validators.required],
      firstName: ['', Validators.required],
      email: ['', [Validators.required, Validators.email]],
      phoneNumber: ['', [Validators.required, Validators.pattern(/^\+?\d{10,15}$/)]]
    });

    this.otherInformationForm = this.formBuilder.group({
      eventType: ['', Validators.required],
      informationType: ['', Validators.required],
      description: ['', [Validators.required, Validators.minLength(10)]],
      image: [null],
      streetNumber: ['', Validators.required],
      postalCode: ['', [Validators.required, Validators.pattern(/^\d{5}$/)]],
      addressVisible: [false],
    })
  }

  onDeclareSafe(): void {
    this.state = StateForm.DeclareSafe;
  }

  onOtherDeclaration(): void {
    this.state = StateForm.OtherDeclaration;
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

      if(this.state == StateForm.DeclareSafe)
        this.declareSafeForm.patchValue({ image: this.selectedFile });
      else if(this.state == StateForm.OtherDeclaration)
        this.otherInformationForm.patchValue({ image: this.selectedFile });
    }
  }

  onSubmit(): void {
    const formData = new FormData();
    let localisation = {};

    if(this.state == StateForm.DeclareSafe && this.declareSafeForm.valid) {
      formData.append('type_evenement', this.declareSafeForm.get('eventType')?.value);
      formData.append('prenom_information', this.declareSafeForm.get('firstName')?.value);
      formData.append('nom_information', this.declareSafeForm.get('lastName')?.value);
      formData.append('email_information', this.declareSafeForm.get('email')?.value);
      formData.append('telephone_information', this.declareSafeForm.get('phoneNumber')?.value);

      const street = this.declareSafeForm.get('streetNumber')?.value;
      const zip = this.declareSafeForm.get('postalCode')?.value;
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

      localisation = {
        type: 'Point',
        coordinates: [this.longitude, this.latitude]
      };
      formData.append('localisation', JSON.stringify(localisation));
      if (this.selectedFile) {
        formData.append('photo', this.selectedFile);
      }
      formData.append('statut', 'NON_TRAITEE');
    } else if(this.state == StateForm.OtherDeclaration && this.otherInformationForm.valid) {
      formData.append('type_evenement', this.otherInformationForm.get('eventType')?.value);
      formData.append('type_information', this.otherInformationForm.get('informationType')?.value);
      formData.append('description', this.otherInformationForm.get('description')?.value);
      // formData.append('streetNumber', this.otherInformationForm.get('streetNumber')?.value);
      // formData.append('postalCode', this.otherInformationForm.get('postalCode')?.value);
      formData.append('addressVisible', this.otherInformationForm.get('addressVisible')?.value);

      const street = this.otherInformationForm.get('streetNumber')?.value;
      const zip = this.otherInformationForm.get('postalCode')?.value;
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

      localisation = {
        type: 'Point',
        coordinates: [this.longitude, this.latitude]
      };
      formData.append('localisation', JSON.stringify(localisation));
      if (this.selectedFile) {
        formData.append('photo', this.selectedFile);
      }
      formData.append('statut', 'NON_TRAITEE');
    }

    this.informationService.createInformation(formData).subscribe({
        next: (response) => {
          console.log('Information créée:', response);
          alert('Votre information a été enregistrée avec succès !');
          this.router.navigate(['/accueil']);
        },
        error: (err) => {
          console.error('Erreur création information:', err);
          alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
        }
      });
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }
}
