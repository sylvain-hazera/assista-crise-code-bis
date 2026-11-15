import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { AuthService, CODE_REQUIS, ErreurConnexion, MOT_DE_PASSE_REQUIS, SECOND_FACTEUR_A_ACTIVER } from '../../services/auth.service';

type ActivationState = 'loading' | 'success' | 'error' | 'code' | 'mot_de_passe';

@Component({
  selector: 'app-activate-account',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './activate-account.component.html',
  styleUrls: ['./activate-account.component.scss']
})
export class ActivateAccountComponent implements OnInit {
  state: ActivationState = 'loading';
  errorMessage = '';
  successMessage = '';
  returnUrl = '/accueil';

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    const { uidb64, token } = this.route.snapshot.params;

    if (!uidb64 || !token) {
      this.state = 'error';
      this.errorMessage = "Lien d'activation incomplet.";
      return;
    }
    this.uidb64 = uidb64;
    this.token = token;
    this.activer();
  }

  /** Code de sécurité : un lien d'activation reste valable sept jours et rouvre une session
   * à chaque clic. Sur un compte protégé, il ne suffit donc pas. */
  code = '';
  /** Demandé à la place du code quand le compte reçoit ses codes par e-mail : le lien et
   * le code arriveraient dans la même boîte, ils prouveraient deux fois la même chose. */
  motDePasse = '';
  envoiEnCours = false;
  private uidb64 = '';
  private token = '';

  activer(): void {
    const avecCode = this.state === 'code';
    const avecMotDePasse = this.state === 'mot_de_passe';
    if (avecCode && this.code.trim().length < 6) return;
    if (avecMotDePasse && !this.motDePasse) return;
    this.envoiEnCours = true;
    this.authService.activateAccount(
      this.uidb64, this.token, avecCode ? this.code.trim() : '', avecMotDePasse ? this.motDePasse : '',
    ).subscribe({
      next: (response) => {
        this.envoiEnCours = false;
        this.state = 'success';
        this.successMessage = response.message || 'Compte activé avec succès.';
        // Compte Autorité locale pas encore rattaché à une institution : on l'emmène
        // directement finaliser son inscription plutôt que de le laisser filer vers l'accueil
        // (voir CompleterInscriptionComponent).
        if (response.user?.needs_institution_setup) {
          this.returnUrl = '/completer-inscription';
        } else {
          // `next` porté par le lien d'activation : c'est ainsi qu'un bénévole importé arrive
          // sur sa fiche à compléter plutôt que sur l'accueil, où rien ne lui dirait qu'une
          // fiche l'attend (voir send_benevole_account_email).
          //
          // Restreint aux chemins INTERNES : un `next` absolu transformerait le lien
          // d'activation, qui est public et circule par email, en redirection ouverte vers
          // n'importe quel site — avec la caution du domaine. On exige donc un chemin qui
          // commence par une seule barre oblique (« //ailleurs » est une URL de protocole
          // relatif, pas un chemin local).
          const demande = this.route.snapshot.queryParamMap.get('next');
          if (demande && demande.startsWith('/') && !demande.startsWith('//')) {
            this.returnUrl = demande;
          }
        }
      },
      error: (error) => {
        this.envoiEnCours = false;
        const code = error instanceof ErreurConnexion ? error.code : '';
        if (code === SECOND_FACTEUR_A_ACTIVER) {
          this.router.navigate(['/securite-du-compte'], { queryParams: { returnUrl: this.returnUrl } });
        } else if (code === MOT_DE_PASSE_REQUIS || (avecMotDePasse && code === 'TROP_D_ESSAIS')) {
          this.errorMessage = this.state === 'mot_de_passe' ? error.message : '';
          this.state = 'mot_de_passe';
          this.motDePasse = '';
        } else if (code === CODE_REQUIS || (avecCode && code === 'TROP_D_ESSAIS')) {
          this.errorMessage = this.state === 'code' ? error.message : '';
          this.state = 'code';
          this.code = '';
        } else {
          this.state = 'error';
          this.errorMessage = error.message || "Ce lien d'activation est invalide ou a expiré";
        }
      }
    });
  }

  goToDashboard(): void {
    this.router.navigate([this.returnUrl]);
  }
}
