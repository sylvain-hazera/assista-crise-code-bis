import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule, AbstractControl, ValidationErrors, FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import { LocationService, Department, Commune } from '../../../services/location.service';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    FormsModule,
    RouterModule
  ],
  templateUrl: './register.component.html',
  styleUrls: ['./register.component.scss']
})
export class RegisterComponent implements OnInit, OnDestroy {
  registerForm!: FormGroup;
  isSubmitting = false;
  errorMessage = '';
  showPassword = false;
  
  private destroy$ = new Subject<void>();

  // Départements et communes
  departments: Department[] = [];
  filteredDepartments: Department[] = [];
  communes: Commune[] = [];
  filteredCommunes: Commune[] = [];
  departmentSearch: string = '';
  communeSearch: string = '';
  showDepartmentDropdown: boolean = false;
  showCommuneDropdown: boolean = false;

  userTypeOptions = [
    { value: UserRole.Individual, label: 'Particulier' },
    { value: UserRole.Organization, label: 'Authorité locale' },
    { value: UserRole.Rescue, label: 'Secours organisés (AASC)' },
    // { value: UserRole.Admin, label: 'Admin' }
  ];

  constructor(
    private formBuilder: FormBuilder,
    private authService: AuthService,
    private router: Router,
    private locationService: LocationService
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.setupUserTypeListener();
    this.loadDepartments();
  }

  private loadDepartments(): void {
    this.locationService.getDepartments().subscribe({
      next: (deps) => {
        this.departments = deps;
        this.filteredDepartments = deps;
      },
      error: (err) => console.error('Erreur chargement départements:', err)
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private initForm(): void {
    this.registerForm = this.formBuilder.group({
      userType: ['', Validators.required],
      lastName: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(50)]],
      firstName: [''],
      password: ['', [
        Validators.required,
        Validators.minLength(8),
        this.passwordStrengthValidator
      ]],
      phone: ['', [Validators.required, Validators.pattern(/^(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}$/)]],
      email: ['', [Validators.required, Validators.email]],
      department: ['', Validators.required],
      commune: ['', Validators.required],
      acceptTerms: [false, Validators.requiredTrue]
    });
  }

  private setupUserTypeListener(): void {
    this.registerForm.get('userType')?.valueChanges
      .pipe(takeUntil(this.destroy$))
      .subscribe(userType => {
        this.toggleFieldsBasedOnUserType(userType);
      });
  }

  private toggleFieldsBasedOnUserType(userType: string): void {
    console.log('Toggle fields for userType:', userType);
    const firstNameControl = this.registerForm.get('firstName');

    if (userType === 'Individual' || userType === 'individual') {  // Gérer les deux cas
       // Activer firstName pour les particuliers
      console.log('Activating firstName for individual');
      firstNameControl?.setValidators([
        Validators.required,
        Validators.minLength(2),
        Validators.maxLength(50)
      ]);
      firstNameControl?.enable();
    } else {
      // Désactiver firstName pour les organisations/secours
      console.log('Disabling firstName for non-individual');
      firstNameControl?.clearValidators();
      firstNameControl?.setValue('');
      firstNameControl?.disable();
    }

    firstNameControl?.updateValueAndValidity();
  }

  // Validateur personnalisé pour la force du mot de passe
  private passwordStrengthValidator(control: AbstractControl): ValidationErrors | null {
    const value = control.value;
    if (!value) return null;

    const hasUpperCase = /[A-Z]/.test(value);
    const hasLowerCase = /[a-z]/.test(value);
    const hasNumber = /[0-9]/.test(value);
    const hasSpecialChar = /[!@#$%^&*(),.?":{}|<>]/.test(value);

    const passwordValid = hasUpperCase && hasLowerCase && hasNumber && hasSpecialChar;

    return passwordValid ? null : { 
      passwordStrength: {
        hasUpperCase,
        hasLowerCase,
        hasNumber,
        hasSpecialChar
      }
    };
  }

  togglePasswordVisibility(): void {
    this.showPassword = !this.showPassword;
  }

  onDepartmentSearchChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.departmentSearch = input.value;
    this.filteredDepartments = this.locationService.searchDepartments(
      this.departmentSearch,
      this.departments
    );
    this.showDepartmentDropdown = true;
  }

  selectDepartment(department: Department): void {
    this.departmentSearch = department.nom;
    this.registerForm.patchValue({ department: department.code });
    this.showDepartmentDropdown = false;
    
    this.locationService.getCommunesByDepartment(department.code).subscribe({
      next: (communes) => {
        this.communes = communes;
        this.filteredCommunes = communes;
        this.communeSearch = '';
        this.registerForm.patchValue({ commune: '' });
      },
      error: (err) => console.error('Erreur chargement communes:', err)
    });
  }

  onCommuneSearchChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.communeSearch = input.value;
    this.filteredCommunes = this.locationService.searchCommunes(
      this.communeSearch,
      this.communes
    );
    this.showCommuneDropdown = true;
  }

  selectCommune(commune: Commune): void {
    this.communeSearch = commune.nom;
    this.registerForm.patchValue({ commune: commune.code });
    this.showCommuneDropdown = false;
  }

  onSubmit(): void {
    if (this.registerForm.invalid) {
      this.markFormAsTouched();
      return;
    }

    this.isSubmitting = true;
    this.errorMessage = '';

    const formValue = this.registerForm.getRawValue();
    const userType = formValue.userType;
    const communeCode = formValue.commune;
    const commune = this.communes.find(c => c.code === communeCode);
    const postalCode = commune?.codesPostaux[0] || '';
    
    // Vérifier si le compte nécessite une validation
    const requiresValidation = userType !== UserRole.Individual;
    
    const registerData: any = {
      username: formValue.email,  // Utiliser l'email complet comme username (unique)
      email: formValue.email,
      password: formValue.password,
      type: this.mapUserTypeToBackend(formValue.userType),
      telephone_utilisateur: formValue.phone,
      last_name: formValue.lastName,
      first_name: formValue.firstName || '',
      code_postal: postalCode,
      // Marquer le compte comme non validé si c'est Institution/Secours/Admin
      enable: !requiresValidation
    };
    
    console.log('Données envoyées:', registerData);

    this.authService.register(registerData)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          console.log('Inscription réussie:', response);
          
          // Vérifier si le compte nécessite validation (basé sur la réponse du serveur)
          if (response.requires_validation || !response.token) {
            // Afficher un message indiquant que le compte est en attente de validation
            alert(response.message || 'Votre compte a été créé avec succès ! Un administrateur doit valider votre compte avant que vous puissiez vous connecter. Vous recevrez un email de confirmation.');
            this.router.navigate(['/login']);
          } else {
            // Compte validé directement (token présent)
            alert(response.message || 'Inscription réussie !');
            this.router.navigate(['/accueil']);
          }
        },
        error: (error) => {
          this.errorMessage = error.message || 'Une erreur est survenue lors de l\'inscription';
          this.isSubmitting = false;
        },
        complete: () => {
          this.isSubmitting = false;
        }
      });
  }

  private markFormAsTouched(): void {
    Object.keys(this.registerForm.controls).forEach(key => {
      const control = this.registerForm.get(key);
      control?.markAsTouched();
      control?.updateValueAndValidity();
    });
  }

  // Helpers pour le template
  isFieldInvalid(fieldName: string): boolean {
    const field = this.registerForm.get(fieldName);
    return !!(field && field.invalid && field.touched);
  }

  getFieldError(fieldName: string): string {
    const field = this.registerForm.get(fieldName);
    if (!field || !field.errors) return '';

    if (field.errors['required']) return 'Ce champ est requis';
    if (field.errors['email']) return 'Email invalide';
    if (field.errors['minlength']) {
      return `Minimum ${field.errors['minlength'].requiredLength} caractères`;
    }
    if (field.errors['maxlength']) {
      return `Maximum ${field.errors['maxlength'].requiredLength} caractères`;
    }
    if (field.errors['pattern']) {
      if (fieldName === 'phone') return 'Numéro de téléphone invalide';
    }
    if (field.errors['passwordStrength']) {
      const errors = field.errors['passwordStrength'];
      const missing = [];
      if (!errors.hasUpperCase) missing.push('une majuscule');
      if (!errors.hasLowerCase) missing.push('une minuscule');
      if (!errors.hasNumber) missing.push('un chiffre');
      if (!errors.hasSpecialChar) missing.push('un caractère spécial');
      return `Le mot de passe doit contenir ${missing.join(', ')}`;
    }

    return 'Champ invalide';
  }

  // get isOrganization(): boolean {
  //   return this.registerForm.get('userType')?.value === 'organization';
  // }

  get isIndividual(): boolean {
    return this.registerForm.get('userType')?.value === UserRole.Individual;

  }

  /**
   * Convertit les valeurs UserRole du frontend vers les valeurs RoleUtilisateur de Django
   */
  private mapUserTypeToBackend(userType: string): string {
    const mapping: { [key: string]: string } = {
      'Individual': 'UTIL_SIMPLE',
      'individual': 'UTIL_SIMPLE',
      'Organization': 'AUT_LOCALE',
      'organization': 'AUT_LOCALE',
      'Rescue': 'SECOURS',
      'rescue': 'SECOURS',
      'Admin': 'ADMIN',
      'admin': 'ADMIN'
    };
    return mapping[userType] || 'UTIL_SIMPLE';
  }
}