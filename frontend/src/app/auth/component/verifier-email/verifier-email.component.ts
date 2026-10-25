import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';

/** Écran affiché juste après une inscription (25/10/2026) : jusqu'ici la personne était
 * renvoyée directement sur /login avec un message qui disparaissait au changement de page, donc
 * sans jamais savoir qu'un email l'attendait. C'est précisément ce qui a rendu invisible le bug
 * des comptes créés sans email d'activation.
 *
 * L'adresse transite par l'état de navigation plutôt que par l'URL : elle n'a pas à finir dans
 * l'historique du navigateur ni dans les journaux du serveur. Si elle manque (page rechargée,
 * ouverte directement), le texte reste juste, simplement moins précis. */
@Component({
  selector: 'app-verifier-email',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './verifier-email.component.html',
  styleUrls: ['./verifier-email.component.scss'],
})
export class VerifierEmailComponent {
  readonly email: string;

  constructor(private router: Router) {
    this.email = (this.router.getCurrentNavigation()?.extras.state
      ?? history.state ?? {})['email'] ?? '';
  }
}
