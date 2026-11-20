import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';

import { MapComponent } from '../../shared/components/common/map/map.component';
import { CelluleOrageComponent } from '../../shared/components/meteo/cellule-orage/cellule-orage.component';
import { CelluleOrage, FeuSuivi, FeuxSuivis, OragesRadar, PotentielOrageFeu } from '../../shared/models/veille.model';
import * as dessinFeux from '../../shared/components/common/map/feux-carte';
import { VeilleService } from '../../services/veille.service';
import { pollWhileVisible } from '../../shared/utils/polling.util';

type Perimetre = 'territoire' | 'france';

/** Carte météo (20/11/2026) : la carte avec les seuls calques météo — pluie observée par le
 * radar, cellules orageuses, éclairs, prévisions Météo-France — et, à côté, la RETRANSCRIPTION en
 * toutes lettres de ce qu'elle montre : chaque cellule avec ses trois natures d'information
 * (relevés, nos estimations, prévision Météo-France), la foudre et les cumuls de pluie.
 *
 * Les feux en cours suivis par le satellite MTG et le potentiel d'orage de feu (nos estimations)
 * y ont été ajoutés le 20/11/2026.
 *
 * Tout vient de notre serveur, comme la veille du territoire. Rien n'est annoncé d'ici. */
@Component({
  selector: 'app-carte-meteo',
  standalone: true,
  imports: [CommonModule, MapComponent, CelluleOrageComponent],
  templateUrl: './carte-meteo.component.html',
  styleUrl: './carte-meteo.component.scss',
})
export class CarteMeteoComponent implements OnInit, OnDestroy {
  @ViewChild(MapComponent) carte?: MapComponent;

  readonly FENETRES = ['1h', '3h', '24h'] as const;
  perimetre: Perimetre = 'territoire';
  orages: OragesRadar | null = null;
  erreur = false;
  feux: FeuxSuivis | null = null;
  potentiel: PotentielOrageFeu | null = null;
  readonly dessinFeux = dessinFeux;
  private suivi?: Subscription;
  private suiviFeux?: Subscription;
  private suiviPotentiel?: Subscription;
  private centree = false;

  constructor(private service: VeilleService) {}

  ngOnInit(): void { this.charger(); }

  ngOnDestroy(): void {
    this.suivi?.unsubscribe();
    this.suiviFeux?.unsubscribe();
    this.suiviPotentiel?.unsubscribe();
  }

  choisirPerimetre(perimetre: Perimetre): void {
    if (perimetre === this.perimetre) return;
    this.perimetre = perimetre;
    this.orages = null;
    this.feux = null;
    this.potentiel = null;
    this.charger();
  }

  private charger(): void {
    this.suivi?.unsubscribe();
    const lecture = () => this.perimetre === 'france' ? this.service.oragesFrance() : this.service.orages();
    this.suivi = pollWhileVisible(lecture, 120_000).subscribe({
      next: (orages) => {
        // Pas de commune connue pour l'institution : le territoire n'a pas de sens, on montre le pays.
        if (this.perimetre === 'territoire' && !orages.centre) {
          this.choisirPerimetre('france');
          return;
        }
        this.orages = orages;
        this.erreur = false;
        if (!this.centree && orages.centre) {
          this.centree = true;
          this.carte?.centrerSur(orages.centre.longitude, orages.centre.latitude, 8);
        }
      },
      error: () => { this.erreur = true; },
    });
    this.chargerFeux();
  }

  /** Rayon des feux autour du territoire : un grand feu se suit de loin. */
  static readonly RAYON_FEUX_KM = 100;

  private chargerFeux(): void {
    this.suiviFeux?.unsubscribe();
    this.suiviPotentiel?.unsubscribe();
    const france = this.perimetre === 'france';
    this.suiviFeux = pollWhileVisible(
      () => this.service.feuxSuivis(france ? 'france' : { rayon_km: CarteMeteoComponent.RAYON_FEUX_KM }), 120_000,
    ).subscribe({ next: (feux) => { this.feux = feux; }, error: () => { this.feux = null; } });
    this.suiviPotentiel = pollWhileVisible(() => this.service.potentielOrageFeu(), 3_600_000)
      .subscribe({ next: (potentiel) => { this.potentiel = potentiel; }, error: () => { this.potentiel = null; } });
  }

  /** Les heures où le potentiel n'est pas nul : autour du territoire, ou en France. */
  get heuresAPotentiel() {
    const parTerritoire = this.perimetre === 'territoire' && !!this.potentiel?.centre;
    return (this.potentiel?.echeances ?? [])
      .map(e => ({ ...e, palier: parTerritoire ? (e.palier_max_autour ?? 0) : e.palier_max_france }))
      .filter(e => e.palier > 0);
  }

  libellePalier(palier: number): string {
    return this.potentiel?.legende.find(p => p.palier === palier)?.libelle ?? '';
  }

  couleurPalier(palier: number): string {
    return this.potentiel?.legende.find(p => p.palier === palier)?.couleur ?? 'transparent';
  }

  voirFeu(feu: FeuSuivi): void {
    this.carte?.centrerSur(feu.longitude, feu.latitude, 10);
  }

  /** Cellules par intensité décroissante (le serveur les trie par distance autour d'un centre). */
  get cellules(): CelluleOrage[] {
    return [...(this.orages?.cellules ?? [])].sort((a, b) => b.releves.intensite_max_mmh - a.releves.intensite_max_mmh);
  }

  /** Le résumé en tête : ce qu'il faut voir d'abord. */
  get synthese() {
    const cellules = this.orages?.cellules ?? [];
    return {
      cellules: cellules.length,
      fortes: cellules.filter(c => c.releves.intensite_max_mmh >= 50).length,
      renforcement: cellules.filter(c => c.releves.suivi?.evolution === 'renforcement').length,
      rotations: cellules.filter(c => c.releves.doppler?.rotation).length,
      grele: cellules.filter(c => c.releves.doppler?.polarimetrie?.grele || c.releves.doppler?.grele?.probable
                              || c.prevision_meteo_france.grele || c.prevision_meteo_france.grele_niveau).length,
      lignes: cellules.filter(c => c.estimations.ligne_de_grain).length,
    };
  }

  /** Cellule mise en avant, sur la carte comme dans la liste. */
  choisie: string | null = null;

  /** « Voir » : la carte va chercher la cellule et la met en avant. */
  voirSurLaCarte(cellule: CelluleOrage): void {
    this.choisie = cellule.identifiant;
    this.carte?.choisirCellule(cellule.identifiant, true);
  }

  /** Une cellule cliquée sur la carte : sa fiche défile jusqu'à l'écran. */
  surCelluleChoisie(identifiant: string | null): void {
    this.choisie = identifiant;
    if (identifiant && typeof document !== 'undefined') {
      setTimeout(() => document.getElementById(`cellule-${identifiant}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    }
  }
}
