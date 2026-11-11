import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { AuthService } from '../../services/auth.service';

type ActivationState = 'loading' | 'success' | 'error';

@Component({
  selector: 'app-activate-account',
  standalone: true,
  imports: [CommonModule, RouterModule],
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

    this.authService.activateAccount(uidb64, token).subscribe({
      next: (response) => {
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
        this.state = 'error';
        this.errorMessage = error.message || "Ce lien d'activation est invalide ou a expiré";
      }
    });
  }

  goToDashboard(): void {
    this.router.navigate([this.returnUrl]);
  }
}
