import { Component, OnInit } from '@angular/core';
import { DatePipe } from '@angular/common';

import { FenetreMeshCore, TableauMeshCore, TableauMeshCoreService } from './tableau-meshcore.service';

/** Ce que veut dire chaque type de trame MeshCore, pour qui ne lit pas le protocole. */
const TYPES: Record<string, string> = {
  REQ: 'requêtes', RESPONSE: 'réponses', TXT_MSG: 'messages directs', ACK: 'accusés de réception',
  ADVERT: 'annonces de nœuds', GRP_TXT: 'messages de canal', GRP_DATA: 'données de canal',
  ANON_REQ: 'requêtes anonymes', PATH: 'chemins', TRACE: 'traces', MULTIPART: 'trames en plusieurs parties',
};

/**
 * Tableau radio MeshCore (23/11/2026) : trafic décodé, liaisons, relais publics et état des
 * observateurs — ce que rapportent les observateurs MQTT, le flux et la cartographie CoreScope
 * (meshstats) et nos companions (backend/core/tableau_meshcore.py).
 */
@Component({
  selector: 'app-tableau-meshcore',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './tableau-meshcore.component.html',
  styleUrl: './tableau-meshcore.component.scss',
})
export class TableauMeshCoreComponent implements OnInit {
  readonly fenetres: { valeur: FenetreMeshCore; libelle: string }[] = [
    { valeur: '6h', libelle: '6 h' }, { valeur: '24h', libelle: '24 h' }, { valeur: '7j', libelle: '7 jours' },
  ];
  fenetre: FenetreMeshCore = '24h';
  tableau: TableauMeshCore | null = null;
  chargement = false;
  erreur: string | null = null;

  constructor(private service: TableauMeshCoreService) {}

  ngOnInit(): void { this.charger(); }

  choisir(f: FenetreMeshCore): void {
    if (f !== this.fenetre) { this.fenetre = f; this.charger(); }
  }

  charger(): void {
    this.chargement = true;
    this.erreur = null;
    this.service.charger(this.fenetre).subscribe({
      next: t => { this.tableau = t; this.chargement = false; },
      error: e => {
        this.erreur = e?.status === 403 ? 'Le tableau radio est réservé aux comptes ayant accès à la radio.' : 'Impossible de charger le tableau MeshCore.';
        this.chargement = false;
      },
    });
  }

  /** 12 345 : séparateur de milliers à la française (Intl du navigateur). */
  nb(n: number): string { return (n ?? 0).toLocaleString('fr-FR'); }

  libelleType(t: string): string { return TYPES[t] ?? t.toLowerCase(); }

  /** Hauteur relative d'une barre de la courbe (le plus haut = 100 %). */
  hauteur(n: number): number {
    const max = Math.max(1, ...(this.tableau?.trafic.courbe.map(p => p.trames) ?? [1]));
    return Math.round((n / max) * 100);
  }

  part(n: number): number {
    const total = this.tableau?.trafic.total || 1;
    return Math.round((n / total) * 1000) / 10;
  }

  tension(mv: number | undefined): string { return mv === undefined ? '—' : `${(mv / 1000).toFixed(2)} V`; }

  duree(s: number | undefined): string {
    if (s === undefined) return '—';
    const j = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
    return j ? `${j} j ${h} h` : `${h} h ${Math.floor((s % 3600) / 60)} min`;
  }
}
