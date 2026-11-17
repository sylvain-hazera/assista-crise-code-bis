import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnChanges, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { StockService } from '../../../services/stock.service';
import {
  AppareilStock, DisponibiliteStock, EtatStock, LotTypeStock, ReservationStock, VerificationLot,
} from '../../../shared/models/stock.model';

export type VueLogistique = 'reservations' | 'dotations' | 'appareils';

/**
 * Trois vues de la page Stocks : « où en a-t-on, et pour qui c'est réservé », les dotations types
 * (sac d'intervention, caisse du véhicule) et les appareils suivis à l'unité.
 *
 * Un contrôle périodique en retard se signale, il ne bloque rien : en pleine crise on sort un
 * groupe dont la révision a huit jours de retard — en le sachant.
 */
@Component({
  selector: 'app-stocks-logistique',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './stocks-logistique.component.html',
  styleUrl: '../stocks.component.scss',
})
export class StocksLogistiqueComponent implements OnChanges {
  @Input() vue: VueLogistique = 'reservations';
  @Input() etat: EtatStock | null = null;
  /** Le stock a bougé : la page doit relire son état. */
  @Output() stockChange = new EventEmitter<void>();

  erreur = '';
  message = '';
  envoi = false;

  // Réservations
  reservations: ReservationStock[] = [];
  recherche = '';
  trouve: DisponibiliteStock | null = null;
  /** Quantité et bénéficiaire saisis pour réserver dans un lieu (clé : article + dépôt). */
  aReserver: Record<string, { quantite: number | null; pour: string }> = {};

  // Dotations
  lots: LotTypeStock[] = [];
  lot: { id?: string; nom: string; description: string; lignes: { article: string; quantite: number }[] } | null = null;
  depotLot = '';
  verification: { lot: LotTypeStock; resultat: VerificationLot } | null = null;

  // Appareils
  appareils: AppareilStock[] = [];
  appareil: Partial<AppareilStock> | null = null;

  constructor(private stocks: StockService) {}

  ngOnChanges(): void {
    this.erreur = this.message = '';
    if (!this.depotLot && this.depots.length === 1) this.depotLot = this.depots[0].id;
    const lire = <T>(source: { subscribe: Function }, poser: (v: T) => void) =>
      source.subscribe({ next: poser, error: (e: unknown) => this.erreur = this.lire(e, 'La lecture a échoué.') });
    if (this.vue === 'reservations') lire<ReservationStock[]>(this.stocks.reservations(), (r) => this.reservations = r);
    if (this.vue === 'dotations') lire<LotTypeStock[]>(this.stocks.lotsTypes(), (l) => this.lots = l);
    if (this.vue === 'appareils') lire<AppareilStock[]>(this.stocks.appareils(), (a) => this.appareils = a);
  }

  get depots() { return (this.etat?.depots ?? []).filter(d => d.actif && !d.point); }
  get articles() { return (this.etat?.articles ?? []).filter(a => a.actif); }
  nombre(valeur: string | number | null | undefined): string { return valeur === null || valeur === undefined || valeur === '' ? '' : (+valeur).toLocaleString('fr-FR', { maximumFractionDigits: 3 }); }

  // ── Où en a-t-on ? Réserver ─────────────────────────────────────────────────────────────
  chercher(): void {
    if (!this.recherche.trim()) { this.trouve = null; return; }
    this.stocks.disponibilite({ recherche: this.recherche.trim() }).subscribe({
      next: (d) => this.trouve = d, error: (e) => this.erreur = this.lire(e, 'La recherche a échoué.') });
  }

  saisie(article: string, depot: string) { return this.aReserver[`${article}|${depot}`] ??= { quantite: null, pour: '' }; }

  reserver(article: string, depot: string): void {
    const s = this.saisie(article, depot);
    if (!s.quantite || s.quantite <= 0) return;
    this.erreur = this.message = '';
    this.stocks.reserver({ article, depot, quantite: s.quantite, pour: s.pour }).subscribe({
      next: (r) => { this.reservations = [r, ...this.reservations]; delete this.aReserver[`${article}|${depot}`];
        this.message = `Mis de côté : ${this.nombre(r.quantite)} ${r.unite} de ${r.article_designation}, dans ${r.depot_nom}.`; this.chercher(); this.stockChange.emit(); },
      error: (e) => this.erreur = this.lire(e, 'Cette réservation n’a pas pu être faite.'),
    });
  }

  clore(r: ReservationStock, geste: 'servir' | 'liberer'): void {
    this.erreur = this.message = '';
    this.stocks.cloreReservation(r.id, geste).subscribe({
      next: () => { this.reservations = this.reservations.filter(x => x.id !== r.id);
        this.message = geste === 'servir' ? 'Remis : le stock est sorti du dépôt.' : 'Réservation annulée : le stock est de nouveau libre.';
        if (this.trouve) this.chercher(); this.stockChange.emit(); },
      error: (e) => this.erreur = this.lire(e, 'Ce geste n’a pas abouti.'),
    });
  }

  // ── Dotations types ─────────────────────────────────────────────────────────────────────
  nouveauLot(): void { this.verification = null; this.lot = { nom: '', description: '', lignes: [{ article: '', quantite: 1 }] }; }
  modifierLot(l: LotTypeStock): void {
    this.verification = null;
    this.lot = { id: l.id, nom: l.nom, description: l.description, lignes: l.lignes.map(x => ({ article: x.article, quantite: +x.quantite })) };
  }
  get lotComplet(): boolean { return !!this.lot && !!this.lot.nom.trim() && this.lot.lignes.length > 0 && this.lot.lignes.every(l => !!l.article && l.quantite > 0); }

  enregistrerLot(): void {
    if (!this.lot || !this.lotComplet) return;
    this.envoi = true;
    this.stocks.enregistrerLot(this.lot).subscribe({
      next: (l) => { this.envoi = false; this.lot = null; this.lots = this.lots.some(x => x.id === l.id) ? this.lots.map(x => x.id === l.id ? l : x) : [...this.lots, l];
        this.message = `Dotation « ${l.nom} » enregistrée.`; },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cette dotation n’a pas pu être enregistrée.'); },
    });
  }

  verifier(l: LotTypeStock): void {
    if (!this.depotLot) { this.erreur = 'Choisissez d’abord le dépôt.'; return; }
    this.erreur = this.message = '';
    this.stocks.verifierLot(l.id, this.depotLot).subscribe({
      next: (resultat) => this.verification = { lot: l, resultat }, error: (e) => this.erreur = this.lire(e, 'La vérification a échoué.') });
  }

  gesteLot(l: LotTypeStock, geste: 'sortir' | 'rentrer'): void {
    if (!this.depotLot) { this.erreur = 'Choisissez d’abord le dépôt.'; return; }
    this.erreur = this.message = '';
    this.stocks.gesteLot(l.id, geste, this.depotLot).subscribe({
      next: () => { this.verification = null; this.message = geste === 'sortir' ? `Dotation « ${l.nom} » sortie, complète.` : `Dotation « ${l.nom} » rentrée au dépôt.`; this.stockChange.emit(); },
      error: (e) => this.erreur = this.lire(e, 'Ce geste n’a pas abouti.'),
    });
  }

  // ── Appareils ───────────────────────────────────────────────────────────────────────────
  nouvelAppareil(): void { this.appareil = { designation: '', numero: '', etat: 'EN_SERVICE', depot: this.depots.length === 1 ? this.depots[0].id : null,
    controle_libelle: '', controle_periodicite_mois: null, controle_dernier_le: null, commentaire: '' }; }
  modifierAppareil(a: AppareilStock): void { this.appareil = { ...a }; }

  enregistrerAppareil(): void {
    const a = this.appareil;
    if (!a || !a.designation?.trim()) return;
    this.envoi = true;
    const corps: Partial<AppareilStock> = { id: a.id, designation: a.designation, numero: a.numero ?? '', etat: a.etat, depot: a.depot || null,
      controle_libelle: a.controle_libelle ?? '', controle_periodicite_mois: a.controle_periodicite_mois || null,
      controle_dernier_le: a.controle_dernier_le || null, commentaire: a.commentaire ?? '' };
    this.stocks.enregistrerAppareil(corps).subscribe({
      next: (maj) => { this.envoi = false; this.appareil = null; this.poserAppareil(maj); this.message = `« ${maj.designation} » enregistré.`; },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cet appareil n’a pas pu être enregistré.'); },
    });
  }

  controler(a: AppareilStock, conforme: boolean): void {
    this.stocks.controlerAppareil(a.id, conforme).subscribe({
      next: (maj) => { this.poserAppareil(maj); this.message = `Contrôle noté pour « ${maj.designation} »` + (maj.controle_prochain_le ? ' : la prochaine échéance est repoussée.' : '.'); },
      error: (e) => this.erreur = this.lire(e, 'Ce contrôle n’a pas pu être noté.'),
    });
  }

  libelleControle(a: AppareilStock): string {
    return { '': 'sans contrôle périodique', a_jour: 'à jour', bientot: 'à prévoir', en_retard: 'en retard' }[a.controle];
  }

  private poserAppareil(a: AppareilStock): void { this.appareils = this.appareils.some(x => x.id === a.id) ? this.appareils.map(x => x.id === a.id ? a : x) : [...this.appareils, a]; }

  private lire(e: any, defaut: string): string {
    const corps = e?.error;
    if (!corps || typeof corps !== 'object') return defaut;
    if (typeof corps.detail === 'string') return corps.detail;
    const premier = Object.values(corps)[0];
    return (Array.isArray(premier) ? premier[0] : premier) as string || defaut;
  }
}
