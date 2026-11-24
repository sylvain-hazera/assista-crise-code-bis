import { DatePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
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
  imports: [RouterOutlet, RouterLink, RouterLinkActive, BoutonFormationComponent, DatePipe],
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
        @if (pilotage.crise()?.start_date) {
          <span class="horloge" [title]="'Crise ouverte le ' + (pilotage.crise()!.start_date | date:'dd/MM à HH:mm')">H+{{ depuis() }}</span>
        }
        @if (pilotage.pointDu()?.du) {
          <a class="point-du" routerLink="decisions" [queryParams]="{ onglet: 'points' }" title="Le point de situation est dû">
            <span class="material-icons" aria-hidden="true">schedule</span><span class="libelle-point">Point dû</span>
          </a>
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
          @for (o of onglets; track o.lien; let i = $index) {
            <a [routerLink]="o.lien" routerLinkActive="actif" [queryParams]="o.avecCrise ? { crise: pilotage.criseId() } : null"
               [class.secondaire]="i >= NB_PRINCIPAUX" (click)="plusOuvert = false">
              <span class="icone-onglet">
                <span class="material-icons" aria-hidden="true">{{ o.icone }}</span>
                @if (o.lien === 'terrain' && pilotage.alertesTerrain()) {
                  <span class="pastille-alerte" [attr.aria-label]="pilotage.alertesTerrain() + ' alerte(s) à prendre en compte'">{{ pilotage.alertesTerrain() }}</span>
                } @else if (o.lien === 'terrain' && pilotage.aTrier()) {
                  <span class="pastille-alerte a-trier" [attr.aria-label]="pilotage.aTrier() + ' message(s) radio à trier'">{{ pilotage.aTrier() }}</span>
                } @else if (o.lien === 'centres' && pilotage.alertesCentres()) {
                  <span class="pastille-alerte a-trier" [attr.aria-label]="pilotage.alertesCentres() + ' centre(s) presque plein(s) ou en manque'">{{ pilotage.alertesCentres() }}</span>
                } @else if (o.lien === 'eau' && pilotage.circuitEau()?.codis_sans_accuse) {
                  <span class="pastille-alerte" [attr.aria-label]="'CODIS sans accusé de réception'">!</span>
                } @else if (o.lien === 'eau' && (pilotage.circuitEau()?.propose || pilotage.pointsEauActifs())) {
                  <span class="pastille-alerte a-trier" [attr.aria-label]="pilotage.pointsEauActifs() + ' point(s) d’eau actif(s)'">{{ pilotage.circuitEau()?.propose ? '!' : pilotage.pointsEauActifs() }}</span>
                } @else if (o.lien === 'carte' && pilotage.peiAValider()) {
                  <span class="pastille-alerte a-trier" [attr.aria-label]="pilotage.peiAValider() + ' signalement(s) de point d’eau à valider'">{{ pilotage.peiAValider() }}</span>
                }
              </span>
              <span class="libelle">{{ o.libelle }}</span>
            </a>
          }
          <button type="button" class="plus" (click)="plusOuvert = !plusOuvert" [attr.aria-expanded]="plusOuvert">
            <span class="material-icons" aria-hidden="true">more_horiz</span><span class="libelle">Plus</span>
          </button>
          @if (plusOuvert) {
            <div class="menu-plus" role="menu">
              @for (o of onglets.slice(NB_PRINCIPAUX); track o.lien) {
                <a role="menuitem" [routerLink]="o.lien" [queryParams]="o.avecCrise ? { crise: pilotage.criseId() } : null" (click)="plusOuvert = false">
                  <span class="material-icons" aria-hidden="true">{{ o.icone }}</span> {{ o.libelle }}
                </a>
              }
            </div>
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
    .horloge { flex: none; font-variant-numeric: tabular-nums; font-weight: 700; font-size: .85rem; padding: 4px 8px; border-radius: 6px;
               background: var(--ac-bg-muted, #f3f4f6); color: var(--ac-text, #1f2937); white-space: nowrap; }
    .point-du { flex: none; display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 6px; text-decoration: none;
                background: #fef3c7; color: #92400e; font-size: .82rem; font-weight: 700; .material-icons { font-size: 1.05rem; } }
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
    .icone-onglet { position: relative; display: inline-flex; }
    .pastille-alerte { position: absolute; top: -6px; right: -10px; min-width: 18px; height: 18px; padding: 0 4px;
                       border-radius: 9px; background: #b91c1c; color: #fff; font-size: .68rem; font-weight: 700;
                       display: inline-flex; align-items: center; justify-content: center; }
    .pastille-alerte.a-trier { background: #b45309; }
    .plus { display: none; border: none; background: none; color: var(--ac-text-muted, #6b7280); font: inherit;
            font-size: .72rem; font-weight: 600; flex-direction: column; align-items: center; gap: 3px; cursor: pointer; }
    .menu-plus { position: fixed; right: 8px; bottom: calc(64px + env(safe-area-inset-bottom, 0px)); z-index: 30;
                 display: flex; flex-direction: column; min-width: 12rem; padding: 6px; border-radius: 12px;
                 background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb); box-shadow: 0 8px 24px rgba(0, 0, 0, .18);
                 a { display: flex; align-items: center; gap: 8px; padding: 10px; border-radius: 8px; text-decoration: none;
                     color: var(--ac-text, #1f2937); font-size: .9rem; } }
    .rail a:focus-visible, .administration:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: 2px; }
    .contenu { flex: 1; min-width: 0; padding: 16px calc(16px + env(safe-area-inset-right, 0px)) calc(16px + env(safe-area-inset-bottom, 0px)) 16px; }

    @media (max-width: 1100px) {
      .espace, .libelle-admin, .libelle-point { display: none; }
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
      .rail a.secondaire { display: none; }
      .plus { display: flex; flex: 1; min-height: 56px; justify-content: center; }
      .contenu { padding-bottom: calc(76px + env(safe-area-inset-bottom, 0px)); }
    }
  `],
})
export class PilotageLayoutComponent implements OnInit, OnDestroy {
  readonly pilotage = inject(PilotageService);
  private branding = inject(BrandingService);
  private auth = inject(AuthService);
  readonly erreurCrises = signal<string | null>(null);
  readonly accesAdministration = this.auth.canEnterAdminArea();
  readonly onglets: Onglet[] = [
    { lien: 'situation', libelle: 'Situation', icone: 'dashboard' },
    { lien: 'cellule', libelle: 'Cellule', icone: 'hub', avecCrise: true },
    { lien: 'terrain', libelle: 'Terrain', icone: 'directions_run' },
    // Centres d'accueil, de transit, de regroupement des moyens (23/11/2026) : 4e sur téléphone.
    { lien: 'centres', libelle: 'Centres', icone: 'night_shelter' },
    // Circuit réflexe feu → points d'eau → binômes → CODIS (24/11/2026).
    { lien: 'eau', libelle: 'Eau', icone: 'fire_hydrant_alt' },
    { lien: 'decisions', libelle: 'Décisions', icone: 'gavel' },
    { lien: 'carte', libelle: 'Carte', icone: 'map' },
    { lien: 'dossiers', libelle: 'Dossiers', icone: 'folder_open' },
    // C'est le standard téléphonique de la crise (« Quelqu'un appelle pour… ») : nommé ainsi.
    { lien: 'point', libelle: 'Standard', icone: 'call' },
    { lien: 'alertes', libelle: 'Alertes', icone: 'notifications' },
  ];
  /** L'heure de la crise, relue chaque minute : « H+ 12 h 05 », « H+ 2 j 03 h ». */
  private readonly maintenant = signal(Date.now());
  private minuterieHorloge = setInterval(() => this.maintenant.set(Date.now()), 60_000);
  depuis(): string {
    const debut = this.pilotage.crise()?.start_date;
    if (!debut) return '';
    const minutes = Math.max(0, Math.floor((this.maintenant() - new Date(debut).getTime()) / 60000));
    const j = Math.floor(minutes / 1440), h = Math.floor((minutes % 1440) / 60), m = minutes % 60;
    return j ? `${j} j ${String(h).padStart(2, '0')} h` : `${h} h ${String(m).padStart(2, '0')}`;
  }

  /** Sur téléphone, la barre du bas garde quatre onglets ; les autres sont sous « Plus ». */
  readonly NB_PRINCIPAUX = 4;
  plusOuvert = false;
  private minuterieTerrain?: ReturnType<typeof setInterval>;
  private marque = toSignal(this.branding.branding$);
  nom(): string { return this.marque()?.nom_affichage ?? 'Assista-Crise'; }
  logo(): string { return this.marque()?.logo_url ?? '/logo.png'; }
  enFormation(): boolean { return this.auth.getEnvironment() === 'DEMO'; }

  ngOnInit(): void {
    this.pilotage.chargerCrises()
      .then(() => this.pilotage.rafraichirTerrain())
      .catch(() => this.erreurCrises.set('Crises indisponibles : vérifiez le réseau.'));
    // Le terrain en direct : l'onglet affiche le nombre d'alertes non prises en compte.
    this.minuterieTerrain = setInterval(() => this.pilotage.rafraichirTerrain(), 30_000);
  }

  ngOnDestroy(): void {
    if (this.minuterieTerrain) clearInterval(this.minuterieTerrain);
    clearInterval(this.minuterieHorloge);
  }

  choisir(evenement: Event): void {
    this.pilotage.choisir((evenement.target as HTMLSelectElement).value || null);
    this.pilotage.rafraichirTerrain();
  }
}
