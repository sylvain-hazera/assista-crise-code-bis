import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

import { CelluleOrage } from '../../../models/veille.model';

/** Une cellule orageuse et ses trois natures d'information, sans les mélanger : ce que le radar
 * a vu (« selon les relevés », suivi tobac et Doppler compris), NOS estimations — qui ne sont pas
 * des prévisions —, et la prévision Météo-France. Partagé par la veille du territoire et la carte
 * météo, pour qu'une cellule se lise partout dans les mêmes mots. */
@Component({
  selector: 'app-cellule-orage',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './cellule-orage.component.html',
  styleUrl: './cellule-orage.component.scss',
})
export class CelluleOrageComponent {
  @Input({ required: true }) cellule!: CelluleOrage;

  /** Communes sous la pluie, les premières seulement si elles sont nombreuses. */
  communesOrage(max = 12): string {
    const noms = this.cellule.releves.communes_sous_la_pluie.map(c => c.nom);
    return noms.length > max ? `${noms.slice(0, max).join(', ')} et ${noms.length - max} autre(s)` : noms.join(', ');
  }

  /** Communes atteintes, regroupées par délai : « dans 15 min : A, B ; dans 30 min : C ». */
  atteintesParDelai(): { delai: number; noms: string }[] {
    const groupes = new Map<number, string[]>();
    for (const c of this.cellule.estimations.communes_atteintes) {
      const tranche = Math.ceil((c.dans_min ?? 0) / 15) * 15;
      groupes.set(tranche, [...(groupes.get(tranche) ?? []), c.nom]);
    }
    return [...groupes].sort((a, b) => a[0] - b[0]).map(([delai, noms]) => ({
      delai, noms: noms.length > 10 ? `${noms.slice(0, 10).join(', ')} et ${noms.length - 10} autre(s)` : noms.join(', '),
    }));
  }
}
