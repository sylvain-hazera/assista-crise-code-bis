import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule, AbstractControl, ValidationErrors } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { UserRole } from '../../../shared/models/user.model';

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
    { value: 'Individual', label: 'Particulier' },
    { value: 'Organization', label: 'Institution' },
    { value: 'Rescue', label: 'Secours organisés' },
    { value: 'Admin', label: 'Admin' }
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
      userType: ['individual', Validators.required],
      lastName: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(50)]],
      firstName: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(50)]],
      pseudo: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(30)]],
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
    const firstNameControl = this.registerForm.get('firstName');
    const pseudoControl = this.registerForm.get('pseudo');

    if (userType === UserRole.Individual) {
       // Activer les champs pour les particuliers
      firstNameControl?.setValidators([
        Validators.required,
        Validators.minLength(2),
        Validators.maxLength(50)
      ]);
      firstNameControl?.enable();

      pseudoControl?.setValidators([
        Validators.required,
        Validators.minLength(3),
        Validators.maxLength(30)
      ]);
      pseudoControl?.enable();
    } else {
      // Désactiver et réinitialiser les champs pour les institutions
      firstNameControl?.clearValidators();
      firstNameControl?.setValue('');
      firstNameControl?.disable();

      pseudoControl?.clearValidators();
      pseudoControl?.setValue('');
      pseudoControl?.disable();
    }

    firstNameControl?.updateValueAndValidity();
    pseudoControl?.updateValueAndValidity();
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

    // Préparer les données en excluant les champs désactivés
    const formValue = this.registerForm.getRawValue();
    const registerData: any = {
      userType: formValue.userType,
      lastName: formValue.lastName,
      password: formValue.password,
      email: formValue.email,
      phone: formValue.phone,
      postalCode: formValue.postalCode,
      acceptTerms: formValue.acceptTerms
    };

    // Ajouter firstName et pseudo uniquement pour les particuliers
    if (formValue.userType === 'individual') {
      registerData.firstName = formValue.firstName;
      registerData.pseudo = formValue.pseudo;
    }

    this.authService.register(registerData)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          console.log('Inscription réussie:', response);
          // Rediriger vers le tableau de bord ou la page d'accueil
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
    return this.registerForm.get('userType')?.value === 'individual';
  }
}