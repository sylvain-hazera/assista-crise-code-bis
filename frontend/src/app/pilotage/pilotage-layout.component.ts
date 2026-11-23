import { Component, OnInit, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { BrandingService } from '../services/branding.service';
import { AuthService } from '../auth/services/auth.service';
import { BoutonFormationComponent } from '../shared/components/common/bouton-formation/bouton-formation.component';
import { PilotageService } from './pilotage.service';

interface Onglet { lien: string; libelle: string; icone: string; avecCrise?: boolean; }

/**
 * Le poste de pilotage : l'application « Pilotage », pensée pour le directeur des opérations sur
 * iPad (décision du 21/11/2026 : un espace à part, et non l'administration retouchée).
 *
 * Six écrans, pas soixante : la situation d'un coup d'œil, la cellule de crise, la carte, les
 * dossiers, le point de situation et les alertes. La crise suivie se choisit une fois dans
 * l'en-tête et vaut partout. Tout le reste est dans l'administration complète, à un geste.
 *
 * Sur iPad, un rail à gauche (le pouce y tombe en paysage) ; sur un écran étroit, des onglets en
 * bas. Les bords arrondis et la barre d'accueil sont respectés.
 */
@Component({
  selector: 'app-pilotage-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, BoutonFormationComponent],
  template: `
    <div class="pilotage">
      <header class="entete entete-compacte">
        <img [src]="logo()" alt="" class="logo">
        <span class="marque">{{ nom() }}</span>
        <span class="espace">Pilotage</span>
        @if (pilotage.crises().length) {
          <label class="crise">
            <span class="masque">Crise suivie</span>
            <select [value]="pilotage.criseId() ?? ''" (change)="choisir($event)">
              @for (c of pilotage.crises(); track c.id) {
                <option [value]="c.id" [selected]="c.id === pilotage.criseId()">{{ c.name }}</option>
              }
            </select>
          </label>
        } @else if (erreurCrises()) {
          <span class="erreur-crises">{{ erreurCrises() }}</span>
        }
        <span class="outils">
          <app-bouton-formation />
          @if (accesAdministration) {
            <a class="administration" routerLink="/admin" title="Administration complète">
              <span class="material-icons" aria-hidden="true">tune</span><span class="libelle-admin">Administration</span>
            </a>
          }
        </span>
      </header>
      @if (enFormation()) {
        <div class="bandeau-formation" role="status">
          <span class="material-icons" aria-hidden="true">school</span>
          Formation — données fictives de démonstration
        </div>
      }
      <div class="corps">
        <nav class="rail" aria-label="Poste de pilotage">
          @for (o of onglets; track o.lien) {
            <a [routerLink]="o.lien" routerLinkActive="actif" [queryParams]="o.avecCrise ? { crise: pilotage.criseId() } : null">
              <span class="material-icons" aria-hidden="true">{{ o.icone }}</span>
              <span class="libelle">{{ o.libelle }}</span>
            </a>
          }
        </nav>
        <main class="contenu"><router-outlet /></main>
      </div>
    </div>
  `,
  styles: [`
    :host { display: block; }
    .pilotage { min-height: 100dvh; display: flex; flex-direction: column;
                background: var(--ac-bg, #f3f4f6); color: var(--ac-text, #1f2937); }
    /* Une seule ligne, toujours (23/11/2026, téléphone en paysage : la barre passait sur deux
       lignes). Le sélecteur de crise prend la place qui reste et se tronque ; sur écran étroit,
       « Pilotage » disparaît, et Formation et Administration gardent leur seule icône. */
    .entete {
      position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 10px; flex-wrap: nowrap;
      padding: calc(8px + env(safe-area-inset-top, 0px)) calc(16px + env(safe-area-inset-right, 0px)) 8px
               calc(16px + env(safe-area-inset-left, 0px));
      background: var(--ac-surface, #fff); border-bottom: 1px solid var(--ac-border, #e5e7eb);
    }
    .logo { height: 30px; width: auto; flex: none; }
    .marque { font-weight: 700; white-space: nowrap; }
    .espace { white-space: nowrap; }
    .crise { flex: 1 1 auto; min-width: 0; display: flex; }
    .espace { font-size: .75rem; letter-spacing: .05em; text-transform: uppercase; color: var(--ac-text-muted, #6b7280); }
    .crise select {
      min-height: 40px; width: 100%; max-width: 32rem; min-width: 0; padding: 0 28px 0 10px; border-radius: 8px;
      font: inherit; font-size: 16px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;
      border: 1px solid var(--ac-border, #d1d5db); background: var(--ac-surface, #fff); color: var(--ac-text, #1f2937);
    }
    .erreur-crises { font-size: .82rem; color: var(--ac-red-text, #b91c1c); }
    .outils { margin-left: auto; display: flex; align-items: center; gap: 8px; flex: none; }
    .administration { display: inline-flex; align-items: center; gap: 4px; min-height: 40px; padding: 0 10px; border-radius: 8px;
                      color: var(--ac-text-muted, #6b7280); text-decoration: none; font-size: .85rem; font-weight: 600;
                      border: 1px solid var(--ac-border, #e5e7eb); }
    .masque { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
    .bandeau-formation { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 12px;
                         background: #f97316; color: #fff; font-size: .85rem; font-weight: 600; }
    .corps { flex: 1; display: flex; min-height: 0; }
    .rail {
      position: sticky; top: 57px; align-self: flex-start; height: calc(100dvh - 57px);
      display: flex; flex-direction: column; gap: 4px; width: 92px; flex: none;
      padding: 10px 6px calc(10px + env(safe-area-inset-bottom, 0px)) calc(6px + env(safe-area-inset-left, 0px));
      background: var(--ac-surface, #fff); border-right: 1px solid var(--ac-border, #e5e7eb);
    }
    .rail a {
      display: flex; flex-direction: column; align-items: center; gap: 3px; min-height: 60px; justify-content: center;
      padding: 6px 2px; border-radius: 12px; text-decoration: none; text-align: center;
      color: var(--ac-text-muted, #6b7280); font-size: .72rem; font-weight: 600;
    }
    .rail a.actif { background: var(--ac-blue-bg, #dbeafe); color: var(--brand-primary, #2563eb); }
    .rail a:focus-visible, .administration:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: 2px; }
    .contenu { flex: 1; min-width: 0; padding: 16px calc(16px + env(safe-area-inset-right, 0px)) calc(16px + env(safe-area-inset-bottom, 0px)) 16px; }

    @media (max-width: 1100px) {
      .espace, .libelle-admin { display: none; }
      .administration { padding: 0 8px; }
    }
    @media (max-width: 520px) {
      .marque { display: none; }
    }

    /* Écran étroit (téléphone, iPad en Split View) : onglets en bas, comme Terrain. */
    @media (max-width: 700px) {
      .rail {
        position: fixed; top: auto; left: 0; right: 0; bottom: 0; z-index: 20; height: auto; width: auto;
        flex-direction: row; padding: 0 0 env(safe-area-inset-bottom, 0px); border-right: 0;
        border-top: 1px solid var(--ac-border, #e5e7eb);
      }
      .rail a { flex: 1; min-height: 56px; border-radius: 0; }
      .contenu { padding-bottom: calc(76px + env(safe-area-inset-bottom, 0px)); }
    }
  `],
})
export class PilotageLayoutComponent implements OnInit {
  readonly pilotage = inject(PilotageService);
  private branding = inject(BrandingService);
  private auth = inject(AuthService);
  readonly erreurCrises = signal<string | null>(null);
  readonly accesAdministration = this.auth.canEnterAdminArea();
  readonly onglets: Onglet[] = [
    { lien: 'situation', libelle: 'Situation', icone: 'dashboard' },
    { lien: 'cellule', libelle: 'Cellule', icone: 'hub', avecCrise: true },
    { lien: 'carte', libelle: 'Carte', icone: 'map' },
    { lien: 'dossiers', libelle: 'Dossiers', icone: 'folder_open' },
    { lien: 'point', libelle: 'Point de situation', icone: 'summarize' },
    { lien: 'alertes', libelle: 'Alertes', icone: 'notifications' },
  ];
  private marque = toSignal(this.branding.branding$);
  nom(): string { return this.marque()?.nom_affichage ?? 'Assista-Crise'; }
  logo(): string { return this.marque()?.logo_url ?? '/logo.png'; }
  enFormation(): boolean { return this.auth.getEnvironment() === 'DEMO'; }

  ngOnInit(): void {
    this.pilotage.chargerCrises().catch(() => this.erreurCrises.set('Crises indisponibles : vérifiez le réseau.'));
  }

  choisir(evenement: Event): void {
    this.pilotage.choisir((evenement.target as HTMLSelectElement).value || null);
  }
}
