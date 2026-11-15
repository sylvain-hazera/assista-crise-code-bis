import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { DomSanitizer, SafeHtml, SafeUrl } from '@angular/platform-browser';
import { HttpErrorResponse } from '@angular/common/http';
import { AuthService, PreparationSecondFacteur } from '../../services/auth.service';
import { EtatSecondFacteur } from '../../../shared/models/user.model';

/** Ce que la page montre. `obligatoire` = la personne s'est identifiée mais ne peut pas
 * entrer avant d'avoir activé son code (délai de quinze jours passé). */
type Ecran = 'chargement' | 'etat' | 'choix' | 'installer' | 'codes' | 'indisponible';

/**
 * Sécurité du compte : activer, vérifier ou retirer le code de sécurité (application
 * d'authentification), et ses codes de secours.
 *
 * Deux entrées : depuis son espace (session ouverte, le mot de passe est redemandé pour
 * activer), ou depuis la connexion quand l'activation est devenue obligatoire.
 */
@Component({
  selector: 'app-securite-compte',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './securite-compte.component.html',
  styleUrls: ['./securite-compte.component.scss'],
})
export class SecuriteCompteComponent implements OnInit {
  ecran: Ecran = 'chargement';
  obligatoire = false;
  etat: EtatSecondFacteur | null = null;
  returnUrl = '/accueil';

  motDePasse = '';
  code = '';
  enCours = false;
  erreur = '';
  message = '';

  preparation: PreparationSecondFacteur | null = null;
  qr: SafeHtml | null = null;
  lienApplication: SafeUrl | null = null;
  codesSecours: string[] = [];
  copie = false;
  /** Action en attente d'un code sur l'écran d'état : retirer, ou renouveler les codes. */
  action: 'retirer' | 'renouveler' | null = null;

  constructor(
    private authService: AuthService,
    private router: Router,
    private route: ActivatedRoute,
    private sanitizer: DomSanitizer,
  ) {}

  ngOnInit(): void {
    const demande = this.route.snapshot.queryParamMap.get('returnUrl');
    if (demande && demande.startsWith('/') && !demande.startsWith('//')) this.returnUrl = demande;

    if (this.authService.doitActiverSonCode()) {
      // Identité prouvée à l'instant : pas de mot de passe à redonner, il reste à choisir
      // d'où viendra le code.
      this.obligatoire = true;
      this.ecran = 'choix';
    } else if (this.authService.isLoggedIn()) {
      this.chargerEtat();
    } else {
      this.router.navigate(['/login'], { queryParams: { returnUrl: '/securite-du-compte' } });
    }
  }

  private chargerEtat(): void {
    this.authService.etatSecondFacteur().subscribe({
      next: (etat) => {
        this.etat = etat;
        this.ecran = etat.applicable ? 'etat' : 'indisponible';
      },
      error: () => { this.ecran = 'indisponible'; },
    });
  }

  get dateLimite(): Date | null {
    return this.etat?.date_limite ? new Date(this.etat.date_limite) : null;
  }

  private dire(error: HttpErrorResponse, parDefaut: string): void {
    this.enCours = false;
    this.erreur = error.error?.detail || parDefaut;
    if (error.status === 401 && this.obligatoire) {
      this.erreur = 'Le délai pour activer est écoulé. Reconnectez-vous pour recommencer.';
    }
  }

  // ── Activer ────────────────────────────────────────────────────────────────

  /** `application` : un code donné par le téléphone. `email` : un code envoyé par le site à
   * chaque connexion, valable cinq minutes. */
  preparer(mode: 'application' | 'email' = 'application'): void {
    this.enCours = true;
    this.erreur = '';
    this.message = '';
    this.authService.preparerSecondFacteur(this.motDePasse, mode).subscribe({
      next: (preparation) => {
        this.enCours = false;
        this.motDePasse = '';
        this.code = '';
        this.preparation = preparation;
        if (preparation.mode === 'application') {
          // Le QR code et le lien viennent de NOTRE serveur, fabriqués à l'instant pour ce
          // compte : c'est ce qui autorise à les afficher tels quels.
          this.qr = this.sanitizer.bypassSecurityTrustHtml(preparation.qr_svg || '');
          this.lienApplication = this.sanitizer.bypassSecurityTrustUrl(preparation.adresse);
        }
        this.ecran = 'installer';
      },
      error: (error: HttpErrorResponse) => this.dire(error, "Impossible de préparer l'activation."),
    });
  }

  /** Revenir au choix du mode (on s'est trompé, ou le message n'arrive pas). */
  changerDeMode(): void {
    this.preparation = null;
    this.qr = null;
    this.code = '';
    this.erreur = '';
    this.message = '';
    this.ecran = this.obligatoire ? 'choix' : 'etat';
  }

  /** « Je n'ai rien reçu » en mode e-mail, ou un code pour confirmer un acte — y compris
   *  pour un compte à application dont le téléphone n'est plus là. */
  recevoirUnCode(): void {
    this.erreur = '';
    this.authService.envoyerCodeSecondFacteur().subscribe({
      next: (reponse) => { this.message = reponse.detail; },
      error: (error: HttpErrorResponse) => this.dire(error, "Impossible d'envoyer le code."),
    });
  }

  /** Le secret par groupes de quatre : plus facile à recopier à la main. */
  get secretLisible(): string {
    return (this.preparation?.secret || '').replace(/(.{4})/g, '$1 ').trim();
  }

  confirmer(): void {
    if (this.code.trim().length < 6) return;
    this.enCours = true;
    this.erreur = '';
    this.authService.confirmerSecondFacteur(this.code.trim()).subscribe({
      next: (reponse) => {
        this.enCours = false;
        this.code = '';
        this.codesSecours = reponse.codes_secours;
        this.etat = reponse.etat;
        this.preparation = null;
        this.qr = null;
        this.ecran = 'codes';
      },
      error: (error: HttpErrorResponse) => {
        this.code = '';
        this.dire(error, 'Code incorrect.');
      },
    });
  }

  // ── Codes de secours ───────────────────────────────────────────────────────

  copierCodes(): void {
    navigator.clipboard?.writeText(this.codesSecours.join('\n')).then(() => {
      this.copie = true;
      setTimeout(() => (this.copie = false), 2500);
    }).catch(() => undefined);
  }

  terminer(): void {
    this.codesSecours = [];
    if (this.obligatoire) {
      // La session vient de s'ouvrir avec l'activation : on reprend là où la personne allait.
      this.router.navigateByUrl(this.returnUrl);
    } else {
      this.message = 'Votre compte est protégé par un code de sécurité.';
      this.ecran = 'etat';
    }
  }

  // ── Retirer, renouveler ────────────────────────────────────────────────────

  demander(action: 'retirer' | 'renouveler'): void {
    this.action = action;
    this.code = '';
    this.erreur = '';
    this.message = '';
    // Un compte qui reçoit ses codes par e-mail n'en a pas sous la main : on lui en envoie un.
    if (this.etat?.mode === 'email') this.recevoirUnCode();
  }

  annuler(): void {
    this.action = null;
    this.code = '';
    this.erreur = '';
  }

  valider(): void {
    if (this.code.trim().length < 6 || !this.action) return;
    this.enCours = true;
    this.erreur = '';
    const code = this.code.trim();
    if (this.action === 'retirer') {
      this.authService.retirerSecondFacteur(code).subscribe({
        next: (reponse) => {
          this.enCours = false;
          this.etat = reponse.etat;
          this.action = null;
          this.code = '';
          this.message = reponse.etat.requis
            ? "Code de sécurité retiré. Votre compte doit en avoir un : activez-en un nouveau maintenant, sans quoi votre prochaine connexion vous le demandera avant d'entrer."
            : 'Code de sécurité retiré.';
        },
        error: (error: HttpErrorResponse) => { this.code = ''; this.dire(error, 'Code incorrect.'); },
      });
    } else {
      this.authService.renouvelerCodesSecours(code).subscribe({
        next: (reponse) => {
          this.enCours = false;
          this.etat = reponse.etat;
          this.action = null;
          this.code = '';
          this.codesSecours = reponse.codes_secours;
          this.ecran = 'codes';
        },
        error: (error: HttpErrorResponse) => { this.code = ''; this.dire(error, 'Code incorrect.'); },
      });
    }
  }
}
