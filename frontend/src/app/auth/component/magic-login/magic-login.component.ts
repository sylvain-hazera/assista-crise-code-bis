import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { AuthService, CODE_REQUIS, ErreurConnexion, MOT_DE_PASSE_REQUIS, SECOND_FACTEUR_A_ACTIVER } from '../../services/auth.service';

type MagicLoginState = 'loading' | 'success' | 'error' | 'code' | 'mot_de_passe';

@Component({
  selector: 'app-magic-login',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
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

  /** Code de sécurité, demandé seulement si le compte est protégé : le lien prouve l'accès à
   * la boîte aux lettres, pas davantage. */
  code = '';
  /** Demandé à la place du code quand le compte reçoit ses codes par e-mail : le lien et
   * le code arriveraient dans la même boîte, ils prouveraient deux fois la même chose. */
  motDePasse = '';
  envoiEnCours = false;
  private uidb64 = '';
  private token = '';

  ngOnInit(): void {
    const { uidb64, token } = this.route.snapshot.params;

    if (!uidb64 || !token) {
      this.state = 'error';
      this.errorMessage = 'Lien de connexion incomplet.';
      return;
    }
    this.uidb64 = uidb64;
    this.token = token;
    this.connecter();
  }

  /** `next` porté par le lien : c'est ainsi qu'une campagne de disponibilité emmène le
   * bénévole sur la grille de SA période (voir campagnes_disponibilite).
   *
   * Restreint aux chemins INTERNES, comme à l'activation : un lien magique circule par email
   * et vaut identité pendant sept jours. Un `next` absolu en ferait une redirection ouverte
   * avec la caution du domaine. « //ailleurs » est une URL de protocole relatif, pas un
   * chemin local. */
  private get suite(): string {
    const demande = this.route.snapshot.queryParamMap.get('next');
    const interne = !!demande && demande.startsWith('/') && !demande.startsWith('//');
    return interne ? demande! : '/accueil';
  }

  connecter(): void {
    const avecCode = this.state === 'code';
    const avecMotDePasse = this.state === 'mot_de_passe';
    if (avecCode && this.code.trim().length < 6) return;
    if (avecMotDePasse && !this.motDePasse) return;
    this.envoiEnCours = true;
    this.authService.magicLogin(
      this.uidb64, this.token, avecCode ? this.code.trim() : '', avecMotDePasse ? this.motDePasse : '',
    ).subscribe({
      next: () => {
        this.state = 'success';
        this.router.navigateByUrl(this.suite);
      },
      error: (error) => {
        this.envoiEnCours = false;
        const code = error instanceof ErreurConnexion ? error.code : '';
        if (code === SECOND_FACTEUR_A_ACTIVER) {
          this.router.navigate(['/securite-du-compte'], { queryParams: { returnUrl: this.suite } });
        } else if (code === MOT_DE_PASSE_REQUIS || (avecMotDePasse && code === 'TROP_D_ESSAIS')) {
          this.errorMessage = this.state === 'mot_de_passe' ? error.message : '';
          this.state = 'mot_de_passe';
          this.motDePasse = '';
        } else if (code === CODE_REQUIS || (avecCode && code === 'TROP_D_ESSAIS')) {
          // Premier passage : on demande le code. Code faux ou attente : on reste là, avec
          // le message du serveur.
          this.errorMessage = this.state === 'code' ? error.message : '';
          this.state = 'code';
          this.code = '';
        } else {
          this.state = 'error';
          this.errorMessage = error.message || 'Ce lien de connexion est invalide ou a expiré';
        }
      }
    });
  }
}
