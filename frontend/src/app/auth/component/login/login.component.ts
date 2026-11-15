// src/app/auth/login/login.component.ts
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterModule, ActivatedRoute } from '@angular/router';
import { AuthService, ErreurConnexion, SECOND_FACTEUR_A_ACTIVER } from '../../services/auth.service';

/** Où en est la personne. Le code n'est demandé qu'aux comptes qui en ont un. */
type EtapeConnexion = 'adresse' | 'code' | 'mot_de_passe';

/**
 * Connexion en étapes (demande de Sylvain du 15/11/2026) : l'adresse, puis le code de
 * sécurité si le compte est protégé, puis le mot de passe.
 *
 * L'ordre est voulu : tant que le code n'a pas été donné, le serveur ne regarde pas le mot de
 * passe. Un mot de passe fuité seul ne permet donc ni d'entrer, ni de savoir s'il est bon.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterModule],
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.scss']
})
export class LoginComponent implements OnInit {
  loginForm!: FormGroup;
  etape: EtapeConnexion = 'adresse';
  isSubmitting = false;
  errorMessage = '';
  showPassword = false;
  returnUrl = '/accueil';
  /** Preuve que le code a été donné, à joindre au mot de passe. Valable cinq minutes. */
  private jetonEtape = '';

  constructor(
    private formBuilder: FormBuilder,
    private authService: AuthService,
    private router: Router,
    private route: ActivatedRoute
  ) {}

  ngOnInit(): void {
    // Récupérer l'URL de retour
    this.returnUrl = this.route.snapshot.queryParams['returnUrl'] || '/accueil';

    // Rediriger si déjà connecté
    if (this.authService.isLoggedIn()) {
      this.router.navigate([this.returnUrl]);
    }

    this.initForm();
  }

  private initForm(): void {
    this.loginForm = this.formBuilder.group({
      email: ['', [Validators.required, Validators.email]],
      code: [''],
      password: [''],
      rememberMe: [false]
    });
  }

  togglePasswordVisibility(): void {
    this.showPassword = !this.showPassword;
  }

  /** Le champ de l'étape en cours est-il rempli ? */
  get peutContinuer(): boolean {
    const v = this.loginForm.value;
    if (this.etape === 'adresse') return this.loginForm.get('email')!.valid;
    if (this.etape === 'code') return (v.code || '').trim().length >= 6;
    return !!v.password;
  }

  get libelleBouton(): string {
    if (this.isSubmitting) return this.etape === 'mot_de_passe' ? 'Connexion...' : 'Vérification...';
    return this.etape === 'mot_de_passe' ? 'Se connecter' : 'Continuer';
  }

  onSubmit(): void {
    if (!this.peutContinuer) {
      this.markFormAsTouched();
      return;
    }
    this.isSubmitting = true;
    this.errorMessage = '';
    const { email, code, password } = this.loginForm.value;

    if (this.etape === 'adresse') {
      this.authService.debutConnexion(email.trim()).subscribe({
        next: (suite) => this.allerA(suite),
        error: (error) => this.echec(error),
      });
    } else if (this.etape === 'code') {
      this.authService.verifierCode(email.trim(), code.trim()).subscribe({
        next: (jeton) => {
          this.jetonEtape = jeton;
          this.allerA('mot_de_passe');
        },
        error: (error) => {
          this.loginForm.patchValue({ code: '' });
          this.echec(error);
        },
      });
    } else {
      this.authService.login(email.trim(), password, this.jetonEtape).subscribe({
        next: () => this.router.navigateByUrl(this.returnUrl),
        error: (error) => {
          if (error instanceof ErreurConnexion && error.code === SECOND_FACTEUR_A_ACTIVER) {
            // Identité prouvée, mais le délai d'activation est passé : on l'emmène activer.
            this.router.navigate(['/securite-du-compte'], { queryParams: { returnUrl: this.returnUrl } });
            return;
          }
          this.loginForm.patchValue({ password: '' });
          this.echec(error);
        },
      });
    }
  }

  private allerA(etape: EtapeConnexion): void {
    this.etape = etape;
    this.isSubmitting = false;
    this.errorMessage = '';
  }

  private echec(error: unknown): void {
    this.errorMessage = (error as Error)?.message || 'Une erreur est survenue, réessayez.';
    this.isSubmitting = false;
  }

  /** Message après « renvoyer le code » : le serveur répond la même chose pour toute adresse. */
  messageEnvoi = '';
  envoiEnCours = false;

  /** « Recevoir un code par e-mail » : pour tout compte protégé, avec ou sans application
   *  d'authentification (un envoi par minute). */
  renvoyerCode(): void {
    if (this.envoiEnCours) return;
    this.envoiEnCours = true;
    this.messageEnvoi = '';
    this.authService.renvoyerCode(this.loginForm.value.email.trim()).subscribe({
      next: (detail) => { this.messageEnvoi = detail; this.envoiEnCours = false; },
      error: () => { this.messageEnvoi = "Impossible d'envoyer le code pour l'instant."; this.envoiEnCours = false; },
    });
  }

  /** Revenir à l'adresse : tout ce qui a été saisi ensuite est oublié. */
  recommencer(): void {
    this.jetonEtape = '';
    this.messageEnvoi = '';
    this.loginForm.patchValue({ code: '', password: '' });
    this.allerA('adresse');
  }

  private markFormAsTouched(): void {
    Object.keys(this.loginForm.controls).forEach(key => {
      this.loginForm.get(key)?.markAsTouched();
    });
  }

  isFieldInvalid(fieldName: string): boolean {
    const field = this.loginForm.get(fieldName);
    return !!(field && field.invalid && field.touched);
  }
}
