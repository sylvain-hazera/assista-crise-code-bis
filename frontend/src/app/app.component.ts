import { Component, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { SuiviPositionPermanentService } from './services/suivi-position-permanent.service';
import { BrandingService } from './services/branding.service';
import { ThemeService } from './services/theme.service';

@Component({
  selector: 'app-root',
  imports: [
    RouterOutlet,
    CommonModule
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit {
  title = 'assista-crise-front';

  constructor(
    private suiviPosition: SuiviPositionPermanentService,
    private branding: BrandingService,
    // Injecté dès le démarrage : pose le thème (clair/sombre) avant le premier rendu.
    private theme: ThemeService,
  ) {}

  ngOnInit(): void {
    // Cas "session déjà valide au chargement de la page" (token encore en localStorage) --
    // AuthService.setSession couvre le cas "connexion vient d'avoir lieu dans cette session
    // SPA", celui-ci couvre le rechargement complet de page avec une session existante.
    this.suiviPosition.demarrerSiConsentement();

    // Marque blanche (voir BrandingService) : résolu une fois au démarrage, avant que le
    // header/footer ne se rendent avec le logo par défaut -- un léger flash du branding par
    // défaut reste possible le temps de la réponse API (décision assumée : résolution au
    // runtime plutôt qu'un build par marque, voir le plan de conception).
    this.branding.charger();
  }
}
