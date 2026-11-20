import { Component, OnInit, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { BrandingService } from '../services/branding.service';
import { AuthService } from '../auth/services/auth.service';
import { BoutonFormationComponent } from '../shared/components/common/bouton-formation/bouton-formation.component';
import { NotificationsPousseesService } from './notifications-poussees.service';

/**
 * L'espace terrain, pensé pour le téléphone (DOSSIER-PWA-INTERVENANTS.md, lot 2) : un en-tête
 * court et cinq onglets en bas, à portée de pouce, qui évitent l'encoche et la barre d'accueil
 * de l'iPhone. C'est la page où s'ouvre l'application « Terrain » installée.
 */
@Component({
  selector: 'app-terrain-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, BoutonFormationComponent],
  template: `
    <div class="terrain">
      <header class="entete">
        <img [src]="logo()" alt="" class="logo">
        <span class="marque">{{ nom() }}</span>
        <span class="espace">Terrain</span>
        <app-bouton-formation />
      </header>
      @if (enFormation()) {
        <div class="bandeau-formation" role="status">
          <span class="material-icons" aria-hidden="true">school</span>
          Formation — données fictives de démonstration
        </div>
      }
      <main class="contenu"><router-outlet /></main>
      <nav class="onglets" aria-label="Espace terrain">
        @for (o of onglets; track o.lien) {
          <a [routerLink]="o.lien" routerLinkActive="actif" [attr.aria-label]="o.libelle">
            <span class="material-icons" aria-hidden="true">{{ o.icone }}</span>
            <span class="libelle">{{ o.libelle }}</span>
          </a>
        }
      </nav>
    </div>
  `,
  styles: [`
    :host { display: block; }
    .terrain {
      min-height: 100dvh; display: flex; flex-direction: column;
      background: var(--ac-bg, #f3f4f6); color: var(--ac-text, #1f2937);
    }
    .entete {
      position: sticky; top: 0; z-index: 10;
      display: flex; align-items: center; gap: 8px;
      padding: calc(8px + env(safe-area-inset-top, 0px)) 14px 8px;
      background: var(--ac-surface, #fff); border-bottom: 1px solid var(--ac-border, #e5e7eb);
    }
    .logo { height: 28px; width: auto; }
    .marque { font-weight: 700; }
    .espace {
      margin-left: auto; font-size: .75rem; letter-spacing: .04em; text-transform: uppercase;
      color: var(--ac-text-muted, #6b7280);
    }
    .bandeau-formation {
      position: sticky; top: calc(44px + env(safe-area-inset-top, 0px)); z-index: 9;
      display: flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 12px;
      background: #f97316; color: #fff; font-size: .82rem; font-weight: 600;
    }
    .bandeau-formation .material-icons { font-size: 1.05rem; }
    .contenu { flex: 1; padding: 12px 12px calc(76px + env(safe-area-inset-bottom, 0px)); }
    .onglets {
      position: fixed; left: 0; right: 0; bottom: 0; z-index: 20;
      display: grid; grid-template-columns: repeat(5, 1fr);
      padding-bottom: env(safe-area-inset-bottom, 0px);
      background: var(--ac-surface, #fff); border-top: 1px solid var(--ac-border, #e5e7eb);
    }
    .onglets a {
      display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 0 6px;
      color: var(--ac-text-muted, #6b7280); text-decoration: none; font-size: .7rem;
    }
    .onglets a.actif { color: var(--brand-primary, #2563eb); font-weight: 600; }
    .onglets a:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: -2px; }
  `],
})
export class TerrainLayoutComponent implements OnInit {
  private branding = inject(BrandingService);
  private notifications = inject(NotificationsPousseesService);
  private auth = inject(AuthService);

  enFormation(): boolean { return this.auth.getEnvironment() === 'DEMO'; }

  readonly onglets = [
    { lien: 'missions', libelle: 'Missions', icone: 'assignment' },
    { lien: 'equipes', libelle: 'Équipes', icone: 'groups' },
    { lien: 'carte', libelle: 'Carte', icone: 'map' },
    { lien: 'alertes', libelle: 'Alertes', icone: 'notifications' },
    { lien: 'moi', libelle: 'Moi', icone: 'person' },
  ];

  private marque = toSignal(this.branding.branding$);
  nom(): string { return this.marque()?.nom_affichage ?? 'Assista-Crise'; }
  logo(): string { return this.marque()?.logo_url ?? '/logo.png'; }

  ngOnInit(): void {
    // Joignable par l'application dès l'ouverture de l'espace terrain, abonnement compris.
    this.notifications.actualiser().catch(() => {});
  }
}
