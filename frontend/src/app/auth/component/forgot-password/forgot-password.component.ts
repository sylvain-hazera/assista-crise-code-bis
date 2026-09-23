import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { AuthService } from '../../services/auth.service';

type ForgotPasswordState = 'form' | 'submitting' | 'sent' | 'error';

@Component({
  selector: 'app-forgot-password',
  standalone: true,
  imports: [CommonModule, RouterModule, ReactiveFormsModule],
  templateUrl: './forgot-password.component.html',
  styleUrls: ['./forgot-password.component.scss']
})
export class ForgotPasswordComponent {
  state: ForgotPasswordState = 'form';
  errorMessage = '';
  form: FormGroup;

  constructor(private authService: AuthService, private fb: FormBuilder) {
    this.form = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
    });
  }

  onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.state = 'submitting';
    // Le backend renvoie toujours 200 avec le même message générique, que l'email corresponde
    // à un compte ou non (voir PasswordResetRequestView) -- 'sent' ne révèle donc jamais si
    // l'adresse est inscrite. Une vraie erreur HTTP ici est un problème d'infra (backend
    // injoignable...), pas un signal sur l'email : on peut donc l'afficher distinctement sans
    // réintroduire d'énumération.
    this.authService.requestPasswordReset(this.form.value.email).subscribe({
      next: () => (this.state = 'sent'),
      error: (error) => {
        this.state = 'error';
        this.errorMessage = error.message || 'Une erreur est survenue, réessayez plus tard.';
      },
    });
  }
}
