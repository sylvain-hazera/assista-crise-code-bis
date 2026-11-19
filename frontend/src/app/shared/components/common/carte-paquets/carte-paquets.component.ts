import { Component, Input, OnChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface TypePaquets { type: string; nombre: number; }

/** Libellés français des types de paquets Meshtastic (portnum). */
export const LIBELLES_PAQUETS: Record<string, string> = {
  TEXT_MESSAGE_APP: 'Messages', POSITION_APP: 'Positions', NODEINFO_APP: 'Identités',
  TELEMETRY_APP: 'Télémétrie', ROUTING_APP: 'Routage (accusés)', TRACEROUTE_APP: 'Traceroutes',
  NEIGHBORINFO_APP: 'Voisinage', ADMIN_APP: 'Administration', WAYPOINT_APP: "Points d'intérêt",
  STORE_FORWARD_APP: 'Store & Forward', RANGE_TEST_APP: 'Test de portée', MAP_REPORT_APP: 'Rapports carte',
  DETECTION_SENSOR_APP: 'Capteurs', PAXCOUNTER_APP: 'Comptage', ALERT_APP: 'Alertes',
  CHIFFRE_CANAL_INCONNU: 'Chiffrés (canal inconnu)',
};

/** Répartition du trafic par type, en rectangles proportionnels (« treemap »).
 *
 * Idée reprise de l'intégration « Meshtastic UI » : ce qui occupe le canal se voit d'un coup
 * d'œil — un réseau saturé de positions ou d'identités n'a pas le même remède qu'un réseau saturé
 * de messages. Disposition « squarified » (Bruls, Huizing, van Wijk) : des rectangles aussi
 * carrés que possible, donc des libellés lisibles. */
@Component({
  selector: 'app-carte-paquets',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (!blocs.length) {
      <p class="vide">Aucun paquet compté sur la période.</p>
    } @else {
      <svg [attr.viewBox]="'0 0 ' + L + ' ' + H" role="img" aria-label="Répartition des paquets par type">
        @for (b of blocs; track b.type) {
          <g>
            <rect [attr.x]="b.x + 1" [attr.y]="b.y + 1" [attr.width]="b.l - 2" [attr.height]="b.h - 2"
                  rx="3" [attr.fill]="b.couleur"><title>{{ b.libelle }} : {{ b.nombre }} ({{ b.part }} %)</title></rect>
            @if (b.l > 70 && b.h > 30) {
              <text [attr.x]="b.x + 8" [attr.y]="b.y + 18" class="nom">{{ b.libelle }}</text>
              <text [attr.x]="b.x + 8" [attr.y]="b.y + 34" class="chiffre">{{ b.nombre }} · {{ b.part }} %</text>
            }
          </g>
        }
      </svg>
    }
  `,
  styles: [`
    svg { width: 100%; height: auto; display: block; }
    .nom { font-size: 13px; font-weight: 600; fill: #fff; }
    .chiffre { font-size: 12px; fill: rgba(255, 255, 255, .9); font-variant-numeric: tabular-nums; }
    .vide { color: var(--ac-text-subtle, #94a3b8); font-size: .9rem; }
  `],
})
export class CartePaquetsComponent implements OnChanges {
  @Input() types: TypePaquets[] = [];

  readonly L = 600;
  readonly H = 260;
  blocs: { type: string; libelle: string; nombre: number; part: number; x: number; y: number; l: number; h: number; couleur: string }[] = [];

  /** Couleurs foncées : le texte blanc reste lisible dessus, en thème clair comme sombre. */
  private static readonly COULEURS = ['#1d4ed8', '#047857', '#b45309', '#7c3aed', '#be123c', '#0e7490',
                                      '#4d7c0f', '#9333ea', '#c2410c', '#334155'];

  ngOnChanges(): void {
    const valides = this.types.filter(t => t.nombre > 0).sort((a, b) => b.nombre - a.nombre);
    const total = valides.reduce((s, t) => s + t.nombre, 0);
    if (!total) { this.blocs = []; return; }
    const aires = valides.map(t => ({ t, aire: (t.nombre / total) * this.L * this.H }));
    const rects = CartePaquetsComponent.squarifier(aires.map(a => a.aire), 0, 0, this.L, this.H);
    this.blocs = valides.map((t, i) => ({
      type: t.type, libelle: LIBELLES_PAQUETS[t.type] ?? t.type.replace(/_APP$/, '').toLowerCase(),
      nombre: t.nombre, part: Math.round((t.nombre / total) * 1000) / 10,
      ...rects[i], couleur: CartePaquetsComponent.COULEURS[i % CartePaquetsComponent.COULEURS.length],
    }));
  }

  /** Disposition squarified : on remplit des rangées le long du petit côté tant que le pire
   * rapport largeur/hauteur s'améliore. Renvoie un rectangle par aire, dans l'ordre. */
  static squarifier(aires: number[], x: number, y: number, l: number, h: number) {
    const resultat: { x: number; y: number; l: number; h: number }[] = [];
    let reste = [...aires];
    while (reste.length) {
      const cote = Math.min(l, h);
      let rangee: number[] = [];
      let pire = Infinity;
      while (reste.length) {
        const essai = [...rangee, reste[0]];
        const s = essai.reduce((a, b) => a + b, 0);
        const p = Math.max(...essai.map(a => Math.max((cote * cote * a) / (s * s), (s * s) / (cote * cote * a))));
        if (p > pire) { break; }
        pire = p; rangee = essai; reste = reste.slice(1);
      }
      const somme = rangee.reduce((a, b) => a + b, 0);
      if (l >= h) {           // rangée verticale à gauche
        const largeur = somme / h;
        let yy = y;
        for (const a of rangee) { const hh = a / largeur; resultat.push({ x, y: yy, l: largeur, h: hh }); yy += hh; }
        x += largeur; l -= largeur;
      } else {                // rangée horizontale en haut
        const hauteur = somme / l;
        let xx = x;
        for (const a of rangee) { const ll = a / hauteur; resultat.push({ x: xx, y, l: ll, h: hauteur }); xx += ll; }
        y += hauteur; h -= hauteur;
      }
    }
    return resultat;
  }
}
