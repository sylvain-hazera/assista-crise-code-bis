import { Component, OnInit } from '@angular/core';
import { SlicePipe } from '@angular/common';
import { RouterLink } from '@angular/router';

import { CarteOuverteService, PointSerie, SanteReseau } from '../../services/carte-ouverte.service';
import { BandeauOuvertComponent } from '../bandeau-ouvert.component';

/** Une courbe compacte : le tracé, l'aire et le dernier point, sur une échelle donnée. */
export interface Courbe { trace: string; aire: string; dernier: { x: number; y: number } | null; max: number }

const LARGEUR = 300;
const HAUTEUR = 64;

/** Tracé SVG d'une série, de 0 à `plafond` (ou au maximum de la série s'il est plus haut). */
export function courbe(points: PointSerie[], plafond = 0): Courbe {
  const max = Math.max(plafond, ...points.map(p => p.v), 1);
  if (points.length < 2) return { trace: '', aire: '', dernier: null, max };
  const t0 = new Date(points[0].t).getTime();
  const t1 = new Date(points[points.length - 1].t).getTime();
  const xy = points.map(p => ({
    x: t1 > t0 ? (new Date(p.t).getTime() - t0) / (t1 - t0) * LARGEUR : 0,
    y: HAUTEUR - p.v / max * (HAUTEUR - 4) - 2,
  }));
  const trace = xy.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  return { trace, aire: `${trace} L${LARGEUR},${HAUTEUR} L0,${HAUTEUR} Z`, dernier: xy[xy.length - 1], max };
}

/**
 * `/ouvert/reseau` (28/11/2026) : la santé du réseau radio, agrégée sur 24 heures. Ni nom, ni
 * position, ni nombre exact de passerelles, ni liste des nœuds : ce que le réseau vit, pas qui
 * le porte.
 */
@Component({
  selector: 'app-ouvert-reseau',
  standalone: true,
  imports: [RouterLink, SlicePipe, BandeauOuvertComponent],
  templateUrl: './ouvert-reseau.component.html',
  styleUrl: './ouvert-reseau.component.scss',
})
export class OuvertReseauComponent implements OnInit {
  sante: SanteReseau | null = null;
  erreur = false;
  readonly largeur = LARGEUR;
  readonly hauteur = HAUTEUR;
  /** Au-delà, le réseau est chargé : les messages se perdent davantage. */
  readonly seuilOccupation = 25;

  constructor(private service: CarteOuverteService) {}

  ngOnInit(): void {
    this.service.sante().subscribe({ next: s => this.sante = s, error: () => this.erreur = true });
  }

  courbe(points: PointSerie[], plafond = 0): Courbe { return courbe(points, plafond); }

  /** Ordonnée du seuil sur la courbe d'occupation (échelle de 0 à 50 % au moins). */
  ySeuil(max: number): number { return HAUTEUR - this.seuilOccupation / max * (HAUTEUR - 4) - 2; }

  get totalPaquets(): number { return (this.sante?.meshtastic.par_type ?? []).reduce((t, x) => t + x.nombre, 0); }

  part(n: number, total: number): number { return total ? Math.round(n / total * 100) : 0; }

  libelleType(type: string): string {
    const libelles: Record<string, string> = {
      TEXT_MESSAGE_APP: 'Messages', POSITION_APP: 'Positions', NODEINFO_APP: 'Présentations de nœuds',
      TELEMETRY_APP: 'Télémétrie', ROUTING_APP: 'Acquittements', TRACEROUTE_APP: 'Traceroutes',
      NEIGHBORINFO_APP: 'Voisinage', ADMIN_APP: 'Administration', STORE_FORWARD_APP: 'Stockage et relais',
    };
    return libelles[type] ?? type.replace(/_APP$/, '').toLowerCase();
  }

  occupation(v: number | null): string { return v === null ? '—' : `${v.toLocaleString('fr-FR')} %`; }
}
