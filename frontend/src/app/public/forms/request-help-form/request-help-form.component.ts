import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray } from '@angular/forms';
import { Router } from '@angular/router';
// import { NgSelectModule } from '@ng-select/ng-select';

@Component({
  selector: 'app-request-help-form',
  imports: [ReactiveFormsModule],
  templateUrl: './request-help-form.component.html',
  styleUrl: './request-help-form.component.scss'
})
export class RequestHelpFormComponent implements OnInit {
  requestForm!: FormGroup;
  informationForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  state: number = 1;

  requestData: FormData = new FormData();

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
    private router: Router
  ) {}

  ngOnInit(): void {
    this.initForm();
  }

  initForm(): void {
    this.requestForm = this.formBuilder.group({
      eventType: ['', Validators.required],
      // needType: ['', Validators.required],
      // description: ['', [Validators.required, Validators.minLength(10)]],
      needsType: new FormArray([], Validators.required),
      descriptions: new FormArray([], [Validators.required, Validators.minLength(10)]),
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
    if (this.informationForm.valid) {
      console.log('Formulaire valide:', this.informationForm.value);

      const formData = new FormData();
      formData.append('personType', this.informationForm.get('personType')?.value);
      formData.append('firstName', this.informationForm.get('firstName')?.value);
      formData.append('lastName', this.informationForm.get('lastName')?.value);
      formData.append('email', this.informationForm.get('email')?.value);
      formData.append('phoneNumber', this.informationForm.get('phoneNumber')?.value);

      // Combiner les deux FormData
      formData.forEach((value, key) => {
        this.requestData.append(key, value);
      });

      // TODO: Envoyer au backend
      // this.helpService.createRequest(formData).subscribe(...)

    } else {
      // Marquer tous les champs comme touchés pour afficher les erreurs
      Object.keys(this.informationForm.controls).forEach(key => {
        this.informationForm.get(key)?.markAsTouched();
      });
      alert('Veuillez remplir tous les champs obligatoires');
    }
  }

  onContinue(): void {
    if (this.requestForm.valid) {
      // Créer FormData pour l'envoi avec image
      this.requestData.append('eventType', this.requestForm.get('eventType')?.value);
      for (const needType of this.requestForm.get('needsType')?.value) {
        this.requestData.append('needType', needType);
      }
      for (const description of this.requestForm.get('descriptions')?.value) {
        this.requestData.append('description', description);
      }
      // this.requestData.append('needType', this.requestForm.get('needType')?.value);
      // this.requestData.append('description', this.requestForm.get('description')?.value);
      this.requestData.append('streetNumber', this.requestForm.get('streetNumber')?.value);
      this.requestData.append('postalCode', this.requestForm.get('postalCode')?.value);
      this.requestData.append('addressVisible', this.requestForm.get('addressVisible')?.value);

      if (this.selectedFile) {
        this.requestData.append('image', this.selectedFile);
      }

      this.state = 2;
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
