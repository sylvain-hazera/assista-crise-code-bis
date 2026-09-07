import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule, AbstractControl, ValidationErrors, FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import { LocationService, Department, Commune } from '../../../services/location.service';
import { InstitutionTypeService } from '../../../services/institution-type.service';
import { InstitutionType } from '../../../shared/models/institution.model';

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
  successMessage = '';
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
    { value: UserRole.SIMPLE_USER, label: 'Particulier' },
    { value: UserRole.LOCAL_AUTH, label: 'Institution' },
    { value: UserRole.RESCUE, label: 'Secours organisés' },
  ];

  // Peuplé depuis la vraie table InstitutionType (voir ngOnInit) — remplace un ancien tableau
  // codé en dur, déconnecté de la base, qui manquait "association"/"aasc" et dont plusieurs
  // codes ne correspondaient même plus à ceux réellement en base (ex: sous_prefecture vs
  // sous_pref, conseil_departemental/conseil_regional vs cg/cr, cc/metropole vs epci unique).
  // "aasc" est exclu ici : sélectionné via la case à cocher dédiée (userType RESCUE), pas via
  // ce sélecteur générique (voir toggleFieldsBasedOnUserType/onSubmit).
  institutionTypeOptions: InstitutionType[] = [];

  constructor(
    private formBuilder: FormBuilder,
    private authService: AuthService,
    private router: Router,
    private locationService: LocationService,
    private institutionTypeService: InstitutionTypeService
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.setupUserTypeListener();
    this.loadDepartments();
    this.loadInstitutionTypes();
  }

  private loadInstitutionTypes(): void {
    this.institutionTypeService.getAll().subscribe({
      next: (types) => {
        this.institutionTypeOptions = types.filter(t => t.code !== 'aasc');
      },
      error: (err) => console.error('Erreur chargement types d\'institution:', err)
    });
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
      userType: [UserRole.SIMPLE_USER, Validators.required],
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
      institutionName: [''],
      institutionType: [''],
      // AASC/RCSC : uniquement pour userType === RESCUE, remplacent le sélecteur générique
      // institutionType (qui n'a jamais eu de sens pour un compte "Secours organisés" — voir
      // toggleFieldsBasedOnUserType). Mutuellement exclusives.
      isAasc: [false],
      isRcsc: [false],
      acceptTerms: [false, Validators.requiredTrue]
    });
  }

  /** AASC/RCSC sont mutuellement exclusives — cocher l'une décoche l'autre. */
  onAascChange(checked: boolean): void {
    this.registerForm.patchValue({ isAasc: checked, isRcsc: checked ? false : this.registerForm.get('isRcsc')?.value });
    this.toggleFieldsBasedOnUserType(this.registerForm.get('userType')?.value);
  }

  onRcscChange(checked: boolean): void {
    this.registerForm.patchValue({ isRcsc: checked, isAasc: checked ? false : this.registerForm.get('isAasc')?.value });
    this.toggleFieldsBasedOnUserType(this.registerForm.get('userType')?.value);
  }

  get isRescue(): boolean {
    return this.registerForm?.get('userType')?.value === UserRole.RESCUE;
  }

  private setupUserTypeListener(): void {
    this.registerForm.get('userType')?.valueChanges
      .pipe(takeUntil(this.destroy$))
      .subscribe(userType => {
        this.toggleFieldsBasedOnUserType(userType);
      });
  }

  private toggleFieldsBasedOnUserType(userType: string): void {
    const firstNameControl = this.registerForm.get('firstName');
    const institutionNameControl = this.registerForm.get('institutionName');
    const institutionTypeControl = this.registerForm.get('institutionType');

    if (userType === UserRole.SIMPLE_USER) {
      firstNameControl?.setValidators([
        Validators.required,
        Validators.minLength(2),
        Validators.maxLength(50)
      ]);
      firstNameControl?.enable();
      institutionNameControl?.clearValidators();
      institutionNameControl?.setValue('');
      institutionNameControl?.disable();
      institutionTypeControl?.clearValidators();
      institutionTypeControl?.setValue('');
      institutionTypeControl?.disable();
    } else {
      firstNameControl?.clearValidators();
      firstNameControl?.setValue('');
      firstNameControl?.disable();

      const isRcsc = userType === UserRole.RESCUE && this.registerForm.get('isRcsc')?.value;
      if (isRcsc) {
        // RCSC : rattachement automatique à la mairie de la commune déclarée (déjà collectée
        // ci-dessous), pas de nom/type/email d'institution à saisir — ce n'est pas sa propre
        // institution.
        institutionNameControl?.clearValidators();
        institutionNameControl?.setValue('');
        institutionNameControl?.disable();
        institutionTypeControl?.clearValidators();
        institutionTypeControl?.setValue('');
        institutionTypeControl?.disable();
      } else {
        institutionNameControl?.setValidators([Validators.required, Validators.minLength(2)]);
        institutionNameControl?.enable();

        const isAasc = userType === UserRole.RESCUE && this.registerForm.get('isAasc')?.value;
        if (isAasc) {
          // AASC : type forcé côté submit (voir onSubmit), le sélecteur générique ne
          // s'applique pas à ce cas.
          institutionTypeControl?.clearValidators();
          institutionTypeControl?.setValue('');
          institutionTypeControl?.disable();
        } else {
          institutionTypeControl?.setValidators([Validators.required]);
          institutionTypeControl?.enable();
        }
      }
    }

    firstNameControl?.updateValueAndValidity();
    institutionNameControl?.updateValueAndValidity();
    institutionTypeControl?.updateValueAndValidity();
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
    this.departmentSearch = department.name;
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
    this.communeSearch = commune.name;
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
    this.successMessage = '';

    const formValue = this.registerForm.getRawValue();
    const userType = formValue.userType;
    const communeCode = formValue.commune;
    const commune = this.communes.find(c => c.code === communeCode);
    const postalCode = commune?.codesPostaux[0] || '';
    const requiresValidation = userType !== UserRole.SIMPLE_USER;

    // AASC/RCSC : le type d'institution n'est plus choisi dans le sélecteur générique pour ce
    // cas (voir toggleFieldsBasedOnUserType) mais déduit directement des cases cochées. RCSC
    // n'a pas de nom propre à envoyer (rattachement automatique à la mairie de la commune,
    // résolu côté serveur).
    const effectiveInstitutionType = userType === UserRole.RESCUE && formValue.isAasc ? 'aasc'
      : userType === UserRole.RESCUE && formValue.isRcsc ? 'rcsc'
      : formValue.institutionType || '';
    const effectiveInstitutionName = userType === UserRole.RESCUE && formValue.isRcsc ? '' : (formValue.institutionName || '');

    const registerData: any = {
      username: formValue.email,
      email: formValue.email,
      password: formValue.password,
      type: formValue.userType,
      phone_number: formValue.phone,
      last_name: formValue.lastName,
      first_name: formValue.firstName || '',
      postal_code: postalCode,
      enabled: !requiresValidation
    };

    if (formValue.userType !== UserRole.SIMPLE_USER) {
      registerData.institution_name = effectiveInstitutionName;
      registerData.institution_type = effectiveInstitutionType;
      registerData.commune_name = commune?.name || '';
      registerData.commune_code = communeCode;
    }

    const proceedToRegister = () => {
      this.authService.register(registerData)
        .pipe(takeUntil(this.destroy$))
        .subscribe({
          next: (response: any) => {
            if (response.requires_validation || !response.token) {
              this.successMessage = response.message || 'Votre compte a été créé. Un email vous a été envoyé avec les liens d’activation et de connexion.';
              this.router.navigate(['/login']);
            } else {
              this.successMessage = response.message || 'Inscription réussie !';
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
    };

    if (formValue.userType !== UserRole.SIMPLE_USER) {
      this.authService.validateInstitution({
        email: formValue.email,
        institution_name: effectiveInstitutionName,
        institution_type: effectiveInstitutionType,
        commune_name: commune?.name || '',
        commune_code: communeCode
      }).pipe(takeUntil(this.destroy$)).subscribe({
        next: (validationResponse) => {
          if (!validationResponse.valid) {
            this.errorMessage = validationResponse.message || 'Validation institutionnelle impossible';
            this.isSubmitting = false;
            return;
          }
          proceedToRegister();
        },
        error: () => {
          this.errorMessage = 'Impossible de valider l’institution. Veuillez vérifier les informations saisies.';
          this.isSubmitting = false;
        }
      });
    } else {
      proceedToRegister();
    }
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

  get isIndividual(): boolean {
    return this.registerForm.get('userType')?.value === UserRole.SIMPLE_USER;
  }
}