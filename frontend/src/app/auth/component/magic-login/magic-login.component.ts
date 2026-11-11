import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { AuthService } from '../../services/auth.service';

type MagicLoginState = 'loading' | 'success' | 'error';

@Component({
  selector: 'app-magic-login',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './magic-login.component.html',
  styleUrls: ['./magic-login.component.scss']
})
export class MagicLoginComponent implements OnInit {
  state: MagicLoginState = 'loading';
  errorMessage = '';

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    const { uidb64, token } = this.route.snapshot.params;

    if (!uidb64 || !token) {
      this.state = 'error';
      this.errorMessage = 'Lien de connexion incomplet.';
      return;
    }

    this.authService.magicLogin(uidb64, token).subscribe({
      next: () => {
        this.state = 'success';
        // `next` porté par le lien : c'est ainsi qu'une campagne de disponibilité emmène le
        // bénévole sur la grille de SA période (voir campagnes_disponibilite).
        //
        // Restreint aux chemins INTERNES, comme à l'activation : un lien magique circule par
        // email et vaut identité pendant sept jours. Un `next` absolu en ferait une
        // redirection ouverte avec la caution du domaine. « //ailleurs » est une URL de
        // protocole relatif, pas un chemin local.
        const demande = this.route.snapshot.queryParamMap.get('next');
        const interne = !!demande && demande.startsWith('/') && !demande.startsWith('//');
        this.router.navigateByUrl(interne ? demande! : '/accueil');
      },
      error: (error) => {
        this.state = 'error';
        this.errorMessage = error.message || 'Ce lien de connexion est invalide ou a expiré';
      }
    });
  }
}
