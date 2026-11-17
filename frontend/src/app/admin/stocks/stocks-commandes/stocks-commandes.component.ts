import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { StockService } from '../../../services/stock.service';
import { CommandeStock, EtatStock, FactureStock, LigneCommandeStock, TiersStock } from '../../../shared/models/stock.model';

/**
 * Commandes aux fournisseurs et leurs factures. Une commande part, puis se reçoit, en une fois
 * ou en plusieurs : chaque réception entre en stock au prix commandé. La facture se range avec
 * sa commande. Ce n'est pas une comptabilité : de quoi retrouver ce qu'on a payé pour quoi.
 */
@Component({
  selector: 'app-stocks-commandes',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './stocks-commandes.component.html',
  styleUrl: '../stocks.component.scss',
})
export class StocksCommandesComponent implements OnInit {
  @Input() etat: EtatStock | null = null;
  /** Une réception a fait entrer du stock : la page doit relire son état. */
  @Output() stockChange = new EventEmitter<void>();

  commandes: CommandeStock[] = [];
  factures: FactureStock[] = [];
  tiers: TiersStock[] = [];
  erreur = '';
  message = '';
  envoi = false;

  brouillon: { id?: string; tiers: string; depot: string; livraison_prevue: string; commentaire: string; lignes: LigneCommandeStock[] } | null = null;
  nouveauFournisseur: { nom: string; telephone: string; email: string } | null = null;
  /** Réception en cours : quantité reçue, lot et péremption par ligne. */
  reception: { commande: CommandeStock; depot: string; lignes: { ligne: string; libelle: string; reste: number; quantite: number; lot: string; date_peremption: string }[] } | null = null;
  facture: { tiers: string; commande: string; numero: string; date_facture: string; montant_ht: string; montant_ttc: string; echeance: string } | null = null;
  pieceFacture: File | null = null;

  constructor(private stocks: StockService) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.stocks.commandes().subscribe({ next: (c) => this.commandes = c, error: (e) => this.erreur = this.lire(e, 'Les commandes n’ont pas pu être lues.') });
    this.stocks.factures().subscribe({ next: (f) => this.factures = f, error: () => {} });
    this.stocks.tiers().subscribe({ next: (t) => this.tiers = t, error: () => {} });
  }

  get fournisseurs(): TiersStock[] { return this.tiers.filter(t => t.actif); }
  get depots() { return (this.etat?.depots ?? []).filter(d => d.actif && !d.point); }
  get articles() { return (this.etat?.articles ?? []).filter(a => a.actif); }
  get facturesEnRetard(): number { return this.factures.filter(f => f.en_retard).length; }

  nombre(valeur: string | number | null | undefined): string { return valeur === null || valeur === undefined || valeur === '' ? '' : (+valeur).toLocaleString('fr-FR', { maximumFractionDigits: 3 }); }
  euros(valeur: string | null | undefined): string { return valeur === null || valeur === undefined ? '' : (+valeur).toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' }); }

  // ── Commande ────────────────────────────────────────────────────────────────────────────
  nouvelle(): void {
    this.fermer();
    this.brouillon = { tiers: '', depot: this.depots.length === 1 ? this.depots[0].id : '', livraison_prevue: '', commentaire: '',
      lignes: [{ article: '', quantite: 1, prix_unitaire: null }] };
  }

  modifier(c: CommandeStock): void {
    this.fermer();
    this.brouillon = { id: c.id, tiers: c.tiers, depot: c.depot ?? '', livraison_prevue: c.livraison_prevue ?? '', commentaire: c.commentaire,
      lignes: c.lignes.map(l => ({ article: l.article, quantite: +l.quantite, prix_unitaire: l.prix_unitaire === null ? null : +l.prix_unitaire })) };
  }

  ajouterLigne(): void { this.brouillon?.lignes.push({ article: '', quantite: 1, prix_unitaire: null }); }
  retirerLigne(i: number): void { this.brouillon?.lignes.splice(i, 1); }

  get totalBrouillon(): number {
    return (this.brouillon?.lignes ?? []).reduce((somme, l) => somme + (+l.quantite || 0) * (+(l.prix_unitaire ?? 0) || 0), 0);
  }

  get brouillonComplet(): boolean {
    const b = this.brouillon;
    return !!b && !!b.tiers && b.lignes.length > 0 && b.lignes.every(l => !!l.article && +l.quantite > 0);
  }

  creerFournisseur(): void {
    const f = this.nouveauFournisseur;
    if (!f || !f.nom.trim()) return;
    this.stocks.enregistrerTiers({ ...f, type: 'PROFESSIONNEL', est_fournisseur: true }).subscribe({
      next: (cree) => { this.tiers = [cree, ...this.tiers]; if (this.brouillon) this.brouillon.tiers = cree.id; this.nouveauFournisseur = null; },
      error: (e) => this.erreur = this.lire(e, 'Ce fournisseur n’a pas pu être enregistré.'),
    });
  }

  enregistrer(): void {
    const b = this.brouillon;
    if (!b || !this.brouillonComplet) return;
    this.envoi = true;
    this.erreur = '';
    this.stocks.enregistrerCommande({ id: b.id, tiers: b.tiers, depot: b.depot || null, livraison_prevue: b.livraison_prevue || null,
      commentaire: b.commentaire, lignes: b.lignes }).subscribe({
      next: (c) => { this.envoi = false; this.brouillon = null; this.poser(c); this.message = `Commande ${c.numero} enregistrée en brouillon.`; },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cette commande n’a pas pu être enregistrée.'); },
    });
  }

  geste(c: CommandeStock, geste: 'passer' | 'annuler'): void {
    if (geste === 'annuler' && !confirm(`Annuler la commande ${c.numero} ?`)) return;
    this.erreur = this.message = '';
    this.stocks.gesteCommande(c.id, geste).subscribe({
      next: (maj) => { this.poser(maj); this.message = geste === 'passer' ? `Commande ${maj.numero} passée : ses lignes ne bougent plus.` : `Commande ${maj.numero} annulée.`; },
      error: (e) => this.erreur = this.lire(e, 'Ce geste n’a pas abouti.'),
    });
  }

  // ── Réception ───────────────────────────────────────────────────────────────────────────
  ouvrirReception(c: CommandeStock): void {
    this.fermer();
    this.reception = { commande: c, depot: c.depot ?? (this.depots.length === 1 ? this.depots[0].id : ''),
      lignes: c.lignes.map(l => {
        const reste = Math.max(+l.quantite - +(l.quantite_recue ?? 0), 0);
        return { ligne: l.id!, libelle: `${l.article_designation} — ${this.nombre(reste)} ${l.unite} attendu(s)`, reste, quantite: reste, lot: '', date_peremption: '' };
      }).filter(l => l.reste > 0) };
  }

  recevoir(): void {
    const r = this.reception;
    if (!r || !r.depot) return;
    const receptions = r.lignes.filter(l => +l.quantite > 0).map(l => ({ ligne: l.ligne, quantite: l.quantite,
      ...(l.lot ? { lot: l.lot } : {}), ...(l.date_peremption ? { date_peremption: l.date_peremption } : {}) }));
    this.envoi = true;
    this.erreur = '';
    this.stocks.gesteCommande(r.commande.id, 'recevoir', { depot: r.depot, receptions }).subscribe({
      next: (c) => { this.envoi = false; this.reception = null; this.poser(c); this.message = `Réception enregistrée : le stock est entré (${c.statut_libelle.toLowerCase()}).`; this.stockChange.emit(); },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cette réception n’a pas pu être enregistrée.'); },
    });
  }

  // ── Factures ────────────────────────────────────────────────────────────────────────────
  nouvelleFacture(c?: CommandeStock): void {
    this.fermer();
    this.facture = { tiers: c?.tiers ?? '', commande: c?.id ?? '', numero: '', date_facture: new Date().toISOString().slice(0, 10),
      montant_ht: '', montant_ttc: c?.total ?? '', echeance: '' };
    this.pieceFacture = null;
  }

  surPiece(evenement: Event): void { this.pieceFacture = (evenement.target as HTMLInputElement).files?.[0] ?? null; }

  enregistrerFacture(): void {
    const f = this.facture;
    if (!f || !f.tiers || !f.numero.trim() || !f.date_facture || f.montant_ttc === '') return;
    this.envoi = true;
    this.erreur = '';
    this.stocks.creerFacture({ ...f, montant_ht: `${f.montant_ht}`.replace(',', '.'), montant_ttc: `${f.montant_ttc}`.replace(',', '.') }, this.pieceFacture).subscribe({
      next: (cree) => { this.envoi = false; this.facture = null; this.factures = [cree, ...this.factures]; this.message = `Facture ${cree.numero} rangée.`; },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cette facture n’a pas pu être enregistrée.'); },
    });
  }

  payer(f: FactureStock): void {
    this.stocks.payerFacture(f.id, f.payee_le ? null : new Date().toISOString().slice(0, 10)).subscribe({
      next: (maj) => this.factures = this.factures.map(x => x.id === maj.id ? maj : x),
      error: (e) => this.erreur = this.lire(e, 'Le paiement n’a pas pu être noté.'),
    });
  }

  piece(f: FactureStock): void {
    this.stocks.pieceFacture(f.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = `facture-${f.numero}`;
        lien.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      },
      error: (e) => this.erreur = this.lire(e, 'La pièce n’a pas pu être lue.'),
    });
  }

  private fermer(): void { this.brouillon = null; this.reception = null; this.facture = null; this.erreur = this.message = ''; }
  private poser(c: CommandeStock): void { this.commandes = this.commandes.some(x => x.id === c.id) ? this.commandes.map(x => x.id === c.id ? c : x) : [c, ...this.commandes]; }

  private lire(e: any, defaut: string): string {
    const corps = e?.error;
    if (!corps || typeof corps !== 'object') return defaut;
    if (typeof corps.detail === 'string') return corps.detail;
    const premier = Object.values(corps)[0];
    return (Array.isArray(premier) ? premier[0] : premier) as string || defaut;
  }
}
