import { Component, Input, OnChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface PointSerie { t: string; v: number; }

/** Une série temporelle en une bande basse : une colonne par pas de temps, sur toute la fenêtre.
 *
 * Principe repris de l'onglet Radio de l'intégration Home Assistant « Meshtastic UI » (ses
 * « horizon charts ») : beaucoup de séries lisibles d'un coup d'œil, empilées, sur la même
 * échelle de temps. Deux modes de couleur :
 * - `uni` : une couleur, la hauteur dit la valeur (occupation du canal, paquets…) ;
 * - `valeur` : la couleur suit la valeur, du rouge au vert (batterie).
 * Un trou dans les données reste un trou : pas d'interpolation qui ferait croire à une mesure. */
@Component({
  selector: 'app-serie-compacte',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="serie">
      <div class="entete">
        <span class="libelle">{{ libelle }}</span>
        <span class="derniere">
          @if (derniere !== null) { {{ derniere | number:'1.0-1' }} {{ unite }} } @else { — }
        </span>
      </div>
      <svg [attr.viewBox]="'0 0 ' + largeur + ' ' + hauteur" preserveAspectRatio="none" role="img"
           [attr.aria-label]="libelle + ' : ' + (derniere ?? 'aucune mesure')">
        <rect class="fond" x="0" y="0" [attr.width]="largeur" [attr.height]="hauteur"></rect>
        @for (b of barres; track b.x) {
          <rect [attr.x]="b.x" [attr.y]="hauteur - b.h" [attr.width]="b.l" [attr.height]="b.h"
                [attr.fill]="b.couleur"><title>{{ b.titre }}</title></rect>
        }
      </svg>
      @if (!points.length) { <span class="vide">aucune mesure sur la période</span> }
    </div>
  `,
  styles: [`
    .serie { display: flex; flex-direction: column; gap: .2rem; position: relative; }
    .entete { display: flex; justify-content: space-between; font-size: .8rem; }
    .libelle { color: var(--ac-text-muted, #475569); text-transform: uppercase; letter-spacing: .04em; font-size: .72rem; }
    .derniere { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--ac-text, #0f172a); }
    svg { width: 100%; height: 34px; display: block; border-radius: 4px; }
    .fond { fill: var(--ac-surface-2, #f1f5f9); }
    .vide { position: absolute; left: .5rem; bottom: .55rem; font-size: .74rem; color: var(--ac-text-subtle, #94a3b8); }
  `],
})
export class SerieCompacteComponent implements OnChanges {
  @Input() libelle = '';
  @Input() unite = '';
  @Input() points: PointSerie[] = [];
  /** Début de la fenêtre (ISO) et pas de regroupement, en secondes : fixent l'axe du temps. */
  @Input() debut = '';
  @Input() pasS = 600;
  @Input() dureeS = 21600;
  @Input() couleur = '#2563eb';
  @Input() mode: 'uni' | 'valeur' = 'uni';
  /** Valeur pleine hauteur ; absente, c'est le maximum observé. */
  @Input() max: number | null = null;

  readonly largeur = 600;
  readonly hauteur = 34;
  barres: { x: number; l: number; h: number; couleur: string; titre: string }[] = [];
  derniere: number | null = null;

  ngOnChanges(): void {
    const debut = Date.parse(this.debut);
    const nb = Math.max(1, Math.round(this.dureeS / this.pasS));
    const l = this.largeur / nb;
    const plafond = this.max ?? Math.max(1, ...this.points.map(p => p.v));
    this.derniere = this.points.length ? this.points[this.points.length - 1].v : null;
    this.barres = this.points.map(p => {
      const rang = Math.min(nb - 1, Math.max(0, Math.floor((Date.parse(p.t) - debut) / 1000 / this.pasS)));
      const part = Math.max(0, Math.min(1, p.v / plafond));
      return {
        x: rang * l + 0.5, l: Math.max(1, l - 1), h: Math.max(1.5, part * this.hauteur),
        couleur: this.mode === 'valeur' ? SerieCompacteComponent.rougeAuVert(part) : this.couleur,
        titre: `${new Date(p.t).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })} : ${p.v} ${this.unite}`,
      };
    });
  }

  /** 0 → rouge, 0,5 → orange, 1 → vert : lisible sur fond clair comme sombre. */
  static rougeAuVert(part: number): string {
    const teinte = Math.round(part * 120);
    return `hsl(${teinte}, 70%, 45%)`;
  }
}
