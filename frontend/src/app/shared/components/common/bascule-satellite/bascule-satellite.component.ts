import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BasculeSatelliteService, SatelliteLocal } from '../../../../services/bascule-satellite.service';

/**
 * « Le serveur central ne répond pas » : un bouton par satellite connu, et l'adresse IP à
 * saisir sinon (23/11/2026). Sur le site d'un satellite : un rappel discret pour revenir au
 * central. Monté une fois, dans le composant racine.
 */
@Component({
  selector: 'app-bascule-satellite',
  standalone: true,
  imports: [FormsModule],
  template: `
    @if (bascule.centralInjoignable() && !masque) {
      <div class="bascule" role="alertdialog" aria-labelledby="titre-bascule">
        <h2 id="titre-bascule"><span class="material-icons" aria-hidden="true">cloud_off</span> Le serveur central ne répond pas</h2>
        <p>Sur le site, ouvrez le <strong>satellite</strong> : vous y retrouvez la plateforme avec vos identifiants habituels.</p>
        @for (s of satellites; track s.id) {
          <div class="satellite">
            <strong>{{ s.nom }}</strong>
            @for (u of s.urls; track u) {
              <button type="button" (click)="bascule.ouvrir(u)">Ouvrir {{ u.replace('http://', '').replace('/', '') }}</button>
            }
          </div>
        }
        <label class="saisie">
          {{ satellites.length ? 'Ou saisissez l’adresse IP du satellite' : 'Adresse IP du satellite' }}
          <span class="ligne">
            <input type="text" inputmode="url" [(ngModel)]="saisie" placeholder="192.168.1.20 ou assista-crise.local"
                   (keydown.enter)="ouvrirSaisie()">
            <button type="button" [disabled]="!adresse()" (click)="ouvrirSaisie()">Ouvrir</button>
          </span>
          @if (saisie && !adresse()) { <span class="erreur">Adresse IP (ex. 192.168.1.20) ou nom en .local</span> }
        </label>
        <p class="aide">L’adresse est affichée sur l’écran du satellite, ou par la commande <code>./installer.sh acces-web</code>.
          Le téléphone doit être sur le Wi-Fi du site.</p>
        <button type="button" class="discret" (click)="masque = true">Continuer sans réseau</button>
      </div>
    }
    @if (surSatellite && central) {
      <a class="retour" [href]="central">Sur le satellite · revenir au central</a>
    }
  `,
  styles: [`
    .bascule { position: fixed; inset: auto 12px 12px 12px; z-index: 1000; max-width: 34rem; margin: 0 auto;
      display: flex; flex-direction: column; gap: .5rem; padding: 1rem; border-radius: 12px;
      background: var(--ac-surface, #fff); color: var(--ac-text, #111827); box-shadow: 0 10px 30px rgba(0, 0, 0, .25);
      border-top: 4px solid #b45309; }
    h2 { display: flex; align-items: center; gap: .4rem; margin: 0; font-size: 1.05rem; }
    p { margin: 0; font-size: .9rem; }
    .satellite { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; }
    .satellite button, .ligne button { border: none; border-radius: 8px; padding: .5rem .8rem; min-height: 40px;
      background: #2563eb; color: #fff; font: inherit; font-size: .9rem; cursor: pointer; }
    .ligne button:disabled { opacity: .5; cursor: default; }
    .saisie { display: flex; flex-direction: column; gap: .3rem; font-size: .85rem; }
    .ligne { display: flex; gap: .4rem; }
    .ligne input { flex: 1; min-width: 0; font: inherit; font-size: 16px; padding: .45rem .6rem; border-radius: 8px;
      border: 1px solid var(--ac-border, #d1d5db); }
    .erreur { color: #b91c1c; font-size: .8rem; }
    .aide { font-size: .78rem; color: var(--ac-text-muted, #6b7280); }
    .discret { align-self: flex-start; border: none; background: none; text-decoration: underline; cursor: pointer;
      color: var(--ac-text-muted, #6b7280); font: inherit; font-size: .85rem; }
    .retour { position: fixed; right: 12px; bottom: 12px; z-index: 999; padding: .35rem .7rem; border-radius: 999px;
      background: #fef3c7; color: #92400e; font-size: .8rem; text-decoration: none; box-shadow: 0 2px 8px rgba(0, 0, 0, .15); }
  `],
})
export class BasculeSatelliteComponent implements OnInit {
  readonly bascule = inject(BasculeSatelliteService);
  satellites: SatelliteLocal[] = [];
  saisie = '';
  masque = false;
  surSatellite = false;
  central: string | null = null;
  adresse(): string | null { return BasculeSatelliteService.adresseValide(this.saisie); }

  ngOnInit(): void {
    this.satellites = this.bascule.satellitesConnus();
    this.saisie = this.bascule.ipSaisie();
    this.surSatellite = this.bascule.surUnSatellite();
    this.central = this.surSatellite ? this.bascule.centralRetenu() : null;
    this.bascule.rafraichir();
  }

  ouvrirSaisie(): void {
    const url = BasculeSatelliteService.adresseValide(this.saisie);
    if (url) this.bascule.ouvrir(url, this.saisie);
  }
}
