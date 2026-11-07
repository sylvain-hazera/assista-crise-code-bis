import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Subscription } from 'rxjs';

import { CouvertureRadioService } from '../../services/couverture-radio.service';
import { pollWhileVisible } from '../../shared/utils/polling.util';
import {
  BilanLiaison, CalibrationRadio, CouvertureRadioSite, PRESETS_RADIO,
} from '../../shared/models/couverture-radio.model';

/** Intervalle de relance tant qu'un calcul est en cours. Le calcul est borné par l'API
 * d'altimétrie IGN (2,5 requêtes/s) : inutile de demander plus souvent. */
const INTERVALLE_POLLING_MS = 10000;

/** Planification radio : jusqu'où porte un site, et est-ce que ça passe entre deux points.
 *
 * Deux outils de nature différente, et la page doit le faire sentir :
 *
 * - le **bilan de liaison** répond tout de suite (un profil de terrain) ; c'est l'outil du
 *   quotidien, celui qu'on utilise avant de monter sur un toit ;
 * - la **couverture d'un site** part en file (un balayage radial de plusieurs milliers de
 *   points) et revient au bout d'une minute environ.
 *
 * Le point qui décide de la confiance à accorder au reste : **la calibration**. Sans elle, la
 * perte d'environnement est une valeur par défaut et tout ce qui est affiché est une indication
 * de relief, pas une prévision. La page le dit en tête plutôt que de laisser croire à une
 * précision qu'elle n'a pas. */
@Component({
  selector: 'app-couverture-radio',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './couverture-radio.component.html',
  styleUrl: './couverture-radio.component.scss',
})
export class CouvertureRadioComponent implements OnInit, OnDestroy {

  readonly presets = PRESETS_RADIO;

  couvertures: CouvertureRadioSite[] = [];
  calibrations: CalibrationRadio[] = [];
  chargement = true;
  erreur: string | null = null;

  /** Formulaire du bilan de liaison. */
  liaison = {
    lat_a: null as number | null, lon_a: null as number | null,
    lat_b: null as number | null, lon_b: null as number | null,
    hauteur_a_m: 20, hauteur_b_m: 2, preset: 'LONG_FAST', puissance_dbm: 27,
  };
  bilan: BilanLiaison | null = null;
  bilanEnCours = false;
  erreurBilan: string | null = null;

  /** Formulaire de couverture. */
  site = {
    nom: '', latitude: null as number | null, longitude: null as number | null,
    hauteur_antenne_m: 10, rayon_max_km: 25, preset: 'LONG_FAST', puissance_dbm: 27,
  };
  calculEnCours = false;
  erreurCalcul: string | null = null;

  calibrationEnCours = false;

  private polling?: Subscription;

  constructor(private service: CouvertureRadioService) {}

  ngOnInit(): void {
    this.charger();
    // Tant qu'un calcul tourne, la liste se rafraîchit toute seule : l'état vit côté serveur,
    // donc changer de page puis revenir ne perd rien.
    this.polling = pollWhileVisible(() => this.service.couvertures(), INTERVALLE_POLLING_MS)
      .subscribe({
        next: (couvertures) => { this.couvertures = couvertures; },
        error: () => { /* la page reste utilisable : le bilan de liaison ne dépend pas de ça */ },
      });
  }

  ngOnDestroy(): void {
    this.polling?.unsubscribe();
  }

  charger(): void {
    this.chargement = true;
    this.service.couvertures().subscribe({
      next: (couvertures) => { this.couvertures = couvertures; this.chargement = false; },
      error: (e: HttpErrorResponse) => {
        this.erreur = e.status === 403
          ? 'La planification radio est réservée aux acteurs institutionnels.'
          : 'Impossible de charger les couvertures.';
        this.chargement = false;
      },
    });
    this.service.calibrations().subscribe({
      next: (calibrations) => { this.calibrations = calibrations; },
      error: () => { /* sans calibration la page fonctionne, elle le signale */ },
    });
  }

  get derniereCalibration(): CalibrationRadio | null {
    return this.calibrations.find((c) => c.perte_environnement_db !== null) ?? null;
  }

  get calcul_en_file(): boolean {
    return this.couvertures.some((c) => c.statut === 'EN_COURS');
  }

  analyser(): void {
    const { lat_a, lon_a, lat_b, lon_b } = this.liaison;
    if (lat_a === null || lon_a === null || lat_b === null || lon_b === null) { return; }
    this.bilanEnCours = true;
    this.erreurBilan = null;
    this.bilan = null;
    this.service.analyserLiaison({
      lat_a, lon_a, lat_b, lon_b,
      hauteur_a_m: this.liaison.hauteur_a_m, hauteur_b_m: this.liaison.hauteur_b_m,
      preset: this.liaison.preset, puissance_dbm: this.liaison.puissance_dbm,
    }).subscribe({
      next: (bilan) => { this.bilan = bilan; this.bilanEnCours = false; },
      error: (e: HttpErrorResponse) => {
        this.bilanEnCours = false;
        this.erreurBilan = this.messageDErreur(e) ?? 'Calcul impossible.';
      },
    });
  }

  lancerCouverture(): void {
    const { nom, latitude, longitude } = this.site;
    if (!nom.trim() || latitude === null || longitude === null) { return; }
    this.calculEnCours = true;
    this.erreurCalcul = null;
    this.service.calculer({
      nom: nom.trim(), latitude, longitude,
      hauteur_antenne_m: this.site.hauteur_antenne_m,
      rayon_max_km: this.site.rayon_max_km,
      preset: this.site.preset, puissance_dbm: this.site.puissance_dbm,
    }).subscribe({
      next: () => { this.calculEnCours = false; this.charger(); },
      error: (e: HttpErrorResponse) => {
        this.calculEnCours = false;
        this.erreurCalcul = this.messageDErreur(e) ?? 'Mise en file impossible.';
      },
    });
  }

  calibrer(): void {
    this.calibrationEnCours = true;
    this.service.calibrer().subscribe({
      next: () => { this.calibrationEnCours = false; this.charger(); },
      error: (e: HttpErrorResponse) => {
        this.calibrationEnCours = false;
        this.erreur = this.messageDErreur(e) ?? 'Calibration impossible.';
      },
    });
  }

  /** Verdict en clair. Le seuil de 6 dB n'est pas décoratif : c'est la marge d'évanouissement
   * déjà intégrée au budget, donc en dessous la liaison existe mais ne tient pas par mauvais
   * temps. */
  verdict(marge: number): { texte: string; classe: string } {
    if (marge < 0) { return { texte: 'ne passe pas', classe: 'mauvais' }; }
    if (marge < 6) { return { texte: 'passe de justesse', classe: 'limite' }; }
    if (marge < 20) { return { texte: 'passe', classe: 'bon' }; }
    return { texte: 'passe largement', classe: 'bon' };
  }

  private messageDErreur(e: HttpErrorResponse): string | null {
    const corps = e.error;
    if (typeof corps === 'string') { return corps; }
    if (Array.isArray(corps)) { return String(corps[0]); }
    if (corps && typeof corps === 'object') {
      if (corps['detail']) { return String(corps['detail']); }
      const premier = Object.values(corps)[0];
      if (Array.isArray(premier)) { return String(premier[0]); }
      if (premier) { return String(premier); }
    }
    return null;
  }
}
