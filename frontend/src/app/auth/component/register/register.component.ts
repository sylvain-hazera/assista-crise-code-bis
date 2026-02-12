import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule, AbstractControl, ValidationErrors } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { RoleUtilisateur } from '../../../shared/models/user.model';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
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

  userTypeOptions = [
    { value: RoleUtilisateur.UTIL_SIMPLE, label: 'Particulier' },
    { value: RoleUtilisateur.AUT_LOCALE, label: 'Institution' },
    { value: RoleUtilisateur.SECOURS, label: 'Secours organisés' },
    { value: RoleUtilisateur.ADMIN, label: 'Admin' }
  ];

  constructor(
    private formBuilder: FormBuilder,
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.setupUserTypeListener();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private initForm(): void {
    this.registerForm = this.formBuilder.group({
      userType: ['', Validators.required],  // Pas de valeur par défaut
      lastName: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(50)]],
      firstName: [''],  // Optionnel, requis seulement si particulier
      password: ['', [
        Validators.required,
        Validators.minLength(8),
        this.passwordStrengthValidator
      ]],
      phone: ['', [Validators.required, Validators.pattern(/^(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}$/)]],
      email: ['', [Validators.required, Validators.email]],
      postalCode: ['', [Validators.required, Validators.pattern(/^\d{5}$/)]],
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

  onSubmit(): void {
    if (this.registerForm.invalid) {
      this.markFormAsTouched();
      return;
    }

    this.isSubmitting = true;
    this.errorMessage = '';

    // Préparer les données pour Django
    const formValue = this.registerForm.getRawValue();
    const registerData: any = {
      username: formValue.pseudo || formValue.email.split('@')[0],  
      email: formValue.email,
      password: formValue.password,
      // type: this.mapUserTypeToBackend(formValue.userType),  // Convertir en valeur Django
      type: formValue.userType,
      postal_code: formValue.postalCode,
      telephone_utilisateur: formValue.phone,
      last_name: formValue.lastName,
      first_name: formValue.firstName || '',  
    };
    
    console.log('Données envoyées:', registerData);

    this.authService.register(registerData)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          console.log('Inscription réussie:', response);
          this.router.navigate(['/accueil']);
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
      if (fieldName === 'postalCode') return 'Code postal invalide (5 chiffres)';
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
    return this.registerForm.get('userType')?.value === RoleUtilisateur.UTIL_SIMPLE;

  }

  /**
   * Convertit les valeurs RoleUtilisateur du frontend vers les valeurs RoleUtilisateur de Django
   */
  // private mapUserTypeToBackend(userType: string): string {
  //   const mapping: { [key: string]: string } = {
  //     'Individual': 'UTIL_SIMPLE',
  //     'individual': 'UTIL_SIMPLE',
  //     'Organization': 'AUT_LOCALE',
  //     'organization': 'AUT_LOCALE',
  //     'Rescue': 'SECOURS',
  //     'rescue': 'SECOURS',
  //     'Admin': 'ADMIN',
  //     'admin': 'ADMIN'
  //   };
  //   return mapping[userType] || 'UTIL_SIMPLE';
  // }
}