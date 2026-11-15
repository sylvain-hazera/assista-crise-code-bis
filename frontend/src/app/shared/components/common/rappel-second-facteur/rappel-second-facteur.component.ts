import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NavigationEnd, Router, RouterModule } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import { AuthService } from '../../../../auth/services/auth.service';
import { EtatSecondFacteur } from '../../../models/user.model';

/**
 * Rappel affiché aux comptes à pouvoir qui n'ont pas encore activé leur code de sécurité :
 * ils ont quinze jours (décision de Sylvain du 15/11/2026), après quoi le site ne les
 * connecte plus sans activation. Mieux vaut le leur dire à chaque page que les bloquer par
 * surprise un matin de crise.
 */
@Component({
  selector: 'app-rappel-second-facteur',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    @if (dateLimite) {
      <div class="rappel" role="status">
        <span class="material-icons" aria-hidden="true">shield</span>
        <span class="texte">
          Protégez votre compte par un code de sécurité
          @if (joursRestants > 1) { avant le <strong>{{ dateLimite | date:'dd/MM/yyyy' }}</strong> (dans {{ joursRestants }} jours). }
          @else if (joursRestants === 1) { avant <strong>demain</strong>. }
          @else { <strong>dès maintenant</strong>. }
          Ensuite, il sera exigé pour se connecter.
        </span>
        <a routerLink="/securite-du-compte" class="action">Activer</a>
      </div>
    }
  `,
  styles: [`
    .rappel {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: .5rem .75rem;
      padding: .55rem 1rem;
      background: var(--ac-amber-bg, #fef3c7);
      color: var(--ac-orange-text, #92400e);
      font-size: .9rem;
      line-height: 1.4;
    }
    .texte { flex: 1 1 16rem; }
    .action {
      padding: .3rem .8rem;
      border-radius: 6px;
      border: 1px solid currentColor;
      color: inherit;
      font-weight: 600;
      text-decoration: none;
    }
    .action:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
  `],
})
export class RappelSecondFacteurComponent implements OnInit, OnDestroy {
  dateLimite: Date | null = null;
  joursRestants = 0;
  private navigation?: Subscription;

  constructor(private authService: AuthService, private router: Router) {}

  ngOnInit(): void {
    this.lire();
    // Relu à chaque changement de page : après une activation, ou une connexion, le rappel
    // doit suivre sans attendre un rechargement.
    this.navigation = this.router.events
      .pipe(filter(evenement => evenement instanceof NavigationEnd))
      .subscribe(() => this.lire());
  }

  ngOnDestroy(): void {
    this.navigation?.unsubscribe();
  }

  private lire(): void {
    // Pour son propre compte, le serveur rend l'état complet ; `{ actif }` seul ne concerne
    // que le compte d'un autre, vu par un administrateur.
    const brut = this.authService.isLoggedIn() ? this.authService.getCurrentUser()?.second_facteur : null;
    const etat = brut && 'requis' in brut ? (brut as EtatSecondFacteur) : null;
    if (!etat || !etat.applicable || !etat.requis || etat.actif || !etat.date_limite
        || this.router.url.startsWith('/securite-du-compte')) {
      this.dateLimite = null;
      return;
    }
    this.dateLimite = new Date(etat.date_limite);
    this.joursRestants = Math.ceil((this.dateLimite.getTime() - Date.now()) / 86_400_000);
  }
}
