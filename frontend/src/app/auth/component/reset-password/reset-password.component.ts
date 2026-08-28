import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { AuthService } from '../../services/auth.service';

type ResetPasswordState = 'form' | 'submitting' | 'success' | 'error';

@Component({
  selector: 'app-reset-password',
  standalone: true,
  imports: [CommonModule, RouterModule, ReactiveFormsModule],
  templateUrl: './reset-password.component.html',
  styleUrls: ['./reset-password.component.scss']
})
export class ResetPasswordComponent implements OnInit {
  state: ResetPasswordState = 'form';
  errorMessage = '';
  form!: FormGroup;

  private uidb64 = '';
  private token = '';

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private authService: AuthService,
    private fb: FormBuilder
  ) {}

  ngOnInit(): void {
    const { uidb64, token } = this.route.snapshot.params;
    this.uidb64 = uidb64;
    this.token = token;

    if (!uidb64 || !token) {
      this.state = 'error';
      this.errorMessage = 'Lien de réinitialisation incomplet.';
      return;
    }

    this.form = this.fb.group({
      newPassword: ['', [Validators.required, Validators.minLength(8)]],
      confirmPassword: ['', Validators.required],
    });
  }

  get passwordsMismatch(): boolean {
    const { newPassword, confirmPassword } = this.form.value;
    return !!confirmPassword && newPassword !== confirmPassword;
  }

  onSubmit(): void {
    if (this.form.invalid || this.passwordsMismatch) {
      this.form.markAllAsTouched();
      return;
    }

    this.state = 'submitting';
    this.authService.resetPasswordConfirm(this.uidb64, this.token, this.form.value.newPassword).subscribe({
      next: () => {
        this.state = 'success';
        setTimeout(() => this.router.navigate(['/login']), 2000);
      },
      error: (error) => {
        this.state = 'error';
        this.errorMessage = error.message || 'Ce lien est invalide ou a expiré';
      }
    });
  }
}
