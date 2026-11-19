import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Subscription, interval } from 'rxjs';
import { startWith, switchMap } from 'rxjs/operators';

import { CompagnonMeshtasticService } from '../../services/compagnon-meshtastic.service';
import { AdministrationMeshtasticService } from '../../services/administration-meshtastic.service';
import { CompagnonMeshtastic } from '../../shared/models/compagnon-meshtastic.model';
import { FenetreTableauRadio, NoeudTableau, TableauRadio } from '../../shared/models/tableau-radio.model';
import { SerieCompacteComponent } from '../../shared/components/common/serie-compacte/serie-compacte.component';
import { CartePaquetsComponent } from '../../shared/components/common/carte-paquets/carte-paquets.component';

type TriNoeuds = 'dernier_entendu' | 'nom' | 'batterie' | 'snr' | 'sauts';

/** Tableau radio d'une passerelle Meshtastic (19/11/2026).
 *
 * Rendu inspiré de l'intégration Home Assistant « Meshtastic UI » : séries compactes empilées
 * (occupation du canal, temps d'antenne, batterie, paquets), répartition du trafic par type,
 * tableau des nœuds entendus, traceroutes avec le SNR de chaque saut. Rafraîchi chaque minute,
 * au rythme où le pont rapporte. */
@Component({
  selector: 'app-tableau-radio',
  standalone: true,
  imports: [CommonModule, FormsModule, SerieCompacteComponent, CartePaquetsComponent],
  templateUrl: './tableau-radio.component.html',
  styleUrls: ['./tableau-radio.component.scss'],
})
export class TableauRadioComponent implements OnInit, OnDestroy {
  readonly fenetres: { valeur: FenetreTableauRadio; libelle: string; duree_s: number }[] = [
    { valeur: '1h', libelle: '1 heure', duree_s: 3600 },
    { valeur: '6h', libelle: '6 heures', duree_s: 21600 },
    { valeur: '24h', libelle: '24 heures', duree_s: 86400 },
    { valeur: '7j', libelle: '7 jours', duree_s: 604800 },
  ];

  passerelles: CompagnonMeshtastic[] = [];
  passerelleId = '';
  fenetre: FenetreTableauRadio = '6h';
  tableau: TableauRadio | null = null;
  chargement = false;
  erreur: string | null = null;

  filtre = '';
  tri: TriNoeuds = 'dernier_entendu';
  traceroutesDemandes = new Set<number>();
  messageTraceroute: string | null = null;

  private abonnement?: Subscription;

  constructor(
    private readonly passerellesService: CompagnonMeshtasticService,
    private readonly administration: AdministrationMeshtasticService,
  ) {}

  ngOnInit(): void {
    this.passerellesService.getAll().subscribe({
      next: liste => {
        this.passerelles = liste;
        if (liste.length) { this.passerelleId = liste[0].id; this.recharger(); }
      },
      error: () => { this.erreur = 'Liste des passerelles indisponible.'; },
    });
  }

  ngOnDestroy(): void { this.abonnement?.unsubscribe(); }

  get dureeS(): number {
    return this.fenetres.find(f => f.valeur === this.fenetre)?.duree_s ?? 21600;
  }

  /** Recharge tout de suite, puis chaque minute. */
  recharger(): void {
    this.abonnement?.unsubscribe();
    if (!this.passerelleId) { return; }
    this.chargement = !this.tableau;
    this.abonnement = interval(60_000).pipe(
      startWith(0),
      switchMap(() => this.passerellesService.tableau(this.passerelleId, this.fenetre)),
    ).subscribe({
      next: t => { this.tableau = t; this.chargement = false; this.erreur = null; },
      error: (e: HttpErrorResponse) => {
        this.chargement = false;
        this.erreur = e.status === 403 ? "Vous n'avez pas accès au tableau de cette passerelle."
          : 'Tableau radio indisponible pour le moment.';
      },
    });
  }

  choisirFenetre(f: FenetreTableauRadio): void {
    this.fenetre = f;
    this.recharger();
  }

  get noeudsAffiches(): NoeudTableau[] {
    const f = this.filtre.trim().toLowerCase();
    const liste = (this.tableau?.noeuds ?? []).filter(n => !f
      || n.nom.toLowerCase().includes(f) || n.id.includes(f) || n.nom_court.toLowerCase().includes(f));
    const valeur = (n: NoeudTableau): number | string => {
      switch (this.tri) {
        case 'nom': return n.nom.toLowerCase();
        case 'batterie': return n.batterie ?? -1;
        case 'snr': return n.snr ?? -999;
        case 'sauts': return n.sauts ?? 99;
        default: return n.dernier_entendu ?? '';
      }
    };
    const croissant = this.tri === 'nom' || this.tri === 'sauts';
    return [...liste].sort((a, b) => {
      const va = valeur(a), vb = valeur(b);
      const c = va < vb ? -1 : va > vb ? 1 : 0;
      return croissant ? c : -c;
    });
  }

  /** « il y a 3 min », « il y a 2 h », « il y a 4 j ». */
  depuis(iso: string | null): string {
    if (!iso) { return 'jamais'; }
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    if (s < 90) { return "à l'instant"; }
    if (s < 3600) { return `il y a ${Math.round(s / 60)} min`; }
    if (s < 86400 * 2) { return `il y a ${Math.round(s / 3600)} h`; }
    return `il y a ${Math.round(s / 86400)} j`;
  }

  /** Vert au-dessus de 0 dB, orange jusqu'à -10 dB, rouge en dessous (limite LongFast ≈ -20 dB). */
  classeSnr(snr: number | null): string {
    if (snr === null) { return ''; }
    return snr >= 0 ? 'bon' : snr >= -10 ? 'moyen' : 'faible';
  }

  classeBatterie(b: number | null): string {
    if (b === null) { return ''; }
    return b > 100 ? 'secteur' : b >= 50 ? 'bon' : b >= 20 ? 'moyen' : 'faible';
  }

  lancerTraceroute(noeud: NoeudTableau): void {
    if (!this.tableau) { return; }
    this.traceroutesDemandes.add(noeud.node_num);
    this.messageTraceroute = null;
    this.administration.creer({
      compagnon: this.tableau.passerelle.id, node_num_cible: noeud.node_num,
      type_tache: 'TRACEROUTE', parametres: {},
    }).subscribe({
      next: () => {
        this.messageTraceroute = `Traceroute vers ${noeud.nom} demandé : le résultat apparaît ici `
          + "d'ici deux minutes, et chaque saut s'ajoute à la carte radio.";
      },
      error: (e: HttpErrorResponse) => {
        this.traceroutesDemandes.delete(noeud.node_num);
        this.messageTraceroute = e.status === 403
          ? "Vous n'avez pas le droit de lancer un traceroute depuis cette passerelle."
          : 'Traceroute refusé par le serveur.';
      },
    });
  }

  snrLisible(v: number | null | undefined): string {
    return v === null || v === undefined ? '?' : `${v > 0 ? '+' : ''}${v.toFixed(1)} dB`;
  }
}
