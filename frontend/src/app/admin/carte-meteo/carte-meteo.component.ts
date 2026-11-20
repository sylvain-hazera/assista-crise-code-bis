import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';

import { MapComponent } from '../../shared/components/common/map/map.component';
import { CelluleOrageComponent } from '../../shared/components/meteo/cellule-orage/cellule-orage.component';
import { CelluleOrage, OragesRadar } from '../../shared/models/veille.model';
import { VeilleService } from '../../services/veille.service';
import { pollWhileVisible } from '../../shared/utils/polling.util';

type Perimetre = 'territoire' | 'france';

/** Carte météo (20/11/2026) : la carte avec les seuls calques météo — pluie observée par le
 * radar, cellules orageuses, éclairs, prévisions Météo-France — et, à côté, la RETRANSCRIPTION en
 * toutes lettres de ce qu'elle montre : chaque cellule avec ses trois natures d'information
 * (relevés, nos estimations, prévision Météo-France), la foudre et les cumuls de pluie.
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
  private suivi?: Subscription;
  private centree = false;

  constructor(private service: VeilleService) {}

  ngOnInit(): void { this.charger(); }

  ngOnDestroy(): void { this.suivi?.unsubscribe(); }

  choisirPerimetre(perimetre: Perimetre): void {
    if (perimetre === this.perimetre) return;
    this.perimetre = perimetre;
    this.orages = null;
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

  /** Centre approximatif d'une cellule (moyenne des sommets de son contour). */
  voirSurLaCarte(cellule: CelluleOrage): void {
    const anneau = cellule.contour.coordinates[0] ?? [];
    if (!anneau.length) return;
    const lon = anneau.reduce((s, p) => s + p[0], 0) / anneau.length;
    const lat = anneau.reduce((s, p) => s + p[1], 0) / anneau.length;
    this.carte?.centrerSur(lon, lat, 9);
  }
}
