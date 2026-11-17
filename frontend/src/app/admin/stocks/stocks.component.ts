import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CrisisService } from '../../services/crisis.service';
import { StockService } from '../../services/stock.service';
import { Crisis } from '../../shared/models/crisis.model';
import {
  ArticleStock, BilanImportStock, DepotStock, EtatStock, LABELS_CATEGORIE_STOCK, LABELS_CONSERVATION, LABELS_CUISSON, LABELS_PREPARATION,
  LABELS_TYPE_MOUVEMENT, LigneEtatStock, LigneInventaire, MouvementStock, SaisieMouvement, TypeMouvementStock,
} from '../../shared/models/stock.model';

import { StocksCommandesComponent } from './stocks-commandes/stocks-commandes.component';
import { StocksPretsComponent } from './stocks-prets/stocks-prets.component';
import { StocksLogistiqueComponent } from './stocks-logistique/stocks-logistique.component';

type Onglet = 'etat' | 'journal' | 'depots' | 'commandes' | 'prets' | 'reservations' | 'dotations' | 'appareils';

/**
 * Gestion des stocks de l'institution : ce qu'elle possède, où, combien, et ce qui en est sorti.
 *
 * Le stock ne se saisit pas, il se déduit des mouvements : on enregistre une entrée, une sortie,
 * un transfert ou un inventaire, jamais une quantité. Une erreur se rattrape par un mouvement
 * contraire ou un inventaire — c'est ce qui permet de dire où est passé un carton.
 */
@Component({
  selector: 'app-stocks',
  standalone: true,
  imports: [CommonModule, FormsModule, StocksCommandesComponent, StocksPretsComponent, StocksLogistiqueComponent],
  templateUrl: './stocks.component.html',
  styleUrl: './stocks.component.scss',
})
export class StocksComponent implements OnInit {
  readonly typesMouvement = LABELS_TYPE_MOUVEMENT;
  readonly categories = LABELS_CATEGORIE_STOCK;
  readonly conservations = LABELS_CONSERVATION;
  readonly preparations = LABELS_PREPARATION;
  readonly cuissons = LABELS_CUISSON;
  readonly ordreTypes: TypeMouvementStock[] = ['ENTREE', 'SORTIE', 'TRANSFERT', 'INVENTAIRE'];

  onglet: Onglet = 'etat';
  etat: EtatStock | null = null;
  chargement = false;
  erreur = '';
  message = '';

  // Filtres de l'état du stock.
  depotFiltre = '';
  recherche = '';
  alertesSeulement = false;

  // Saisies en cours (une seule à la fois).
  mouvement: SaisieMouvement | null = null;
  article: Partial<ArticleStock> | null = null;
  depot: Partial<DepotStock> | null = null;
  envoi = false;

  journal: MouvementStock[] = [];
  journalArticle: LigneEtatStock | null = null;
  crises: Crisis[] = [];

  // Reprise d'un fichier.
  importOuvert = false;
  fichierImport: File | null = null;
  depotImport = '';
  bilanImport: BilanImportStock | null = null;

  constructor(private stocks: StockService, private crisisService: CrisisService) {}

  ngOnInit(): void {
    this.charger();
    this.crisisService.getAll().subscribe({ next: (c) => this.crises = c.filter(x => x.is_open !== false), error: () => {} });
  }

  charger(): void {
    this.chargement = true;
    this.stocks.etat(this.depotFiltre || undefined).subscribe({
      next: (etat) => { this.etat = etat; this.chargement = false; },
      error: (e) => { this.chargement = false; this.erreur = this.lire(e, 'Le stock n’a pas pu être lu.'); },
    });
  }

  get depots(): DepotStock[] { return this.etat?.depots ?? []; }
  get depotsActifs(): DepotStock[] { return this.depots.filter(d => d.actif); }
  get articlesActifs(): LigneEtatStock[] { return (this.etat?.articles ?? []).filter(a => a.actif); }

  get lignes(): LigneEtatStock[] {
    const cherche = this.recherche.trim().toLowerCase();
    return (this.etat?.articles ?? []).filter(a =>
      (!cherche || `${a.reference} ${a.designation} ${a.code_barres}`.toLowerCase().includes(cherche))
      && (!this.alertesSeulement || this.enAlerte(a)));
  }

  enAlerte(a: LigneEtatStock): boolean { return a.sous_seuil || +a.perime > 0 || +a.bientot_perime > 0 || a.mal_range.length > 0; }

  /** « Local : à garder au frais, et ce lieu n'a pas de réfrigérateur ». */
  malRange(a: LigneEtatStock): string { return a.mal_range.map(m => `${m.nom} : ${m.manques.join(' ; ')}`).join(' — '); }

  /** « 12.000 » -> « 12 », « 2.500 » -> « 2,5 ». */
  nombre(valeur: string | number | null | undefined): string {
    if (valeur === null || valeur === undefined || valeur === '') return '';
    return (+valeur).toLocaleString('fr-FR', { maximumFractionDigits: 3 });
  }

  euros(valeur: string | null | undefined): string {
    return valeur === null || valeur === undefined ? '' : (+valeur).toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' });
  }

  nomDepot(id: string): string { return this.depots.find(d => d.id === id)?.nom ?? ''; }

  repartition(a: LigneEtatStock): string {
    const parts = Object.entries(a.par_depot);
    if (parts.length < 2 && !this.depotFiltre) return parts.length ? this.nomDepot(parts[0][0]) : '';
    return parts.map(([depot, quantite]) => `${this.nomDepot(depot)} : ${this.nombre(quantite)}`).join(' · ');
  }

  // ── Code-barres : un raccourci, jamais une condition ────────────────────────────────────
  // Dans l'urgence tout n'a pas de code-barres, et tout se fait sans. Quand il y en a un, une
  // douchette (elle tape comme un clavier) ou la photo du téléphone évitent de chercher l'article.
  codeSaisi = '';
  readonly photoPossible = typeof window !== 'undefined' && 'BarcodeDetector' in window;

  /** Trouve l'article par son code-barres ou sa référence, et ouvre une sortie préremplie. */
  surCode(code: string = this.codeSaisi): void {
    const cherche = code.trim().toLowerCase();
    if (!cherche) return;
    const article = (this.etat?.articles ?? []).find(a => a.code_barres.toLowerCase() === cherche || a.reference.toLowerCase() === cherche);
    this.codeSaisi = '';
    if (!article) { this.erreur = `Aucun article ne porte le code « ${code.trim()} ». Cherchez-le par son nom, ou ajoutez ce code à sa fiche.`; return; }
    this.ouvrirMouvement('SORTIE', article);
    this.message = `${article.designation} : ${this.nombre(article.total)} ${article.unite} en stock. Choisissez entrée, sortie ou inventaire.`;
  }

  /** Lit un code sur une photo prise au téléphone, quand le navigateur sait le faire. */
  async surPhotoDeCode(evenement: Event): Promise<void> {
    const champ = evenement.target as HTMLInputElement;
    const photo = champ.files?.[0];
    champ.value = '';
    if (!photo) return;
    try {
      const detecteur = new (window as any).BarcodeDetector();
      const codes = await detecteur.detect(await createImageBitmap(photo));
      if (codes.length) this.surCode(codes[0].rawValue); else this.erreur = 'Aucun code lisible sur cette photo : rapprochez-vous, ou saisissez-le.';
    } catch { this.erreur = 'Ce téléphone ne sait pas lire les codes-barres : saisissez le code, ou cherchez l’article par son nom.'; }
  }

  // ── Mouvements ──────────────────────────────────────────────────────────────────────────
  ouvrirMouvement(type: TypeMouvementStock, a?: LigneEtatStock): void {
    this.fermerSaisies();
    const depots = a ? Object.keys(a.par_depot) : [];
    this.mouvement = {
      type, article: a?.id ?? '', quantite: '',
      depot: this.depotFiltre || (depots.length === 1 ? depots[0] : (this.depotsActifs.length === 1 ? this.depotsActifs[0].id : '')),
    };
  }

  get articleDuMouvement(): LigneEtatStock | undefined {
    return this.etat?.articles.find(a => a.id === this.mouvement?.article);
  }

  /** Ce qu'il y a, d'après le serveur, dans le dépôt choisi pour l'article choisi. */
  get disponible(): string {
    const a = this.articleDuMouvement;
    return a && this.mouvement?.depot ? (a.par_depot[this.mouvement.depot] ?? '0') : '';
  }

  get libelleQuantite(): string {
    switch (this.mouvement?.type) {
      case 'INVENTAIRE': return 'Quantité comptée';
      case 'SORTIE': return 'Quantité sortie';
      case 'TRANSFERT': return 'Quantité déplacée';
      default: return 'Quantité entrée';
    }
  }

  get mouvementComplet(): boolean {
    const m = this.mouvement;
    if (!m || !m.article || !m.depot || m.quantite === '' || m.quantite === null || +m.quantite < 0) return false;
    if (m.type !== 'INVENTAIRE' && +m.quantite === 0) return false;
    return m.type !== 'TRANSFERT' || (!!m.depot_destination && m.depot_destination !== m.depot);
  }

  enregistrerMouvement(): void {
    if (!this.mouvement || !this.mouvementComplet) return;
    const m = this.mouvement;
    const saisie: SaisieMouvement = { article: m.article, depot: m.depot, type: m.type, quantite: m.quantite };
    (['depot_destination', 'lot', 'date_peremption', 'motif', 'tiers', 'crise'] as const).forEach(c => { if (m[c]) saisie[c] = m[c]; });
    if (m.type === 'ENTREE' && m.prix_unitaire !== undefined && m.prix_unitaire !== '' && m.prix_unitaire !== null) saisie.prix_unitaire = m.prix_unitaire;
    this.envoi = true;
    this.erreur = '';
    this.stocks.enregistrer(saisie).subscribe({
      next: (reponse) => {
        this.envoi = false;
        this.message = (reponse.detail || `${this.typesMouvement[m.type]} enregistré${m.type === 'INVENTAIRE' ? '' : 'e'}.`
          .replace('Transfert enregistrée', 'Transfert enregistré')) + (reponse.avertissement ? ' ' + reponse.avertissement : '');
        this.mouvement = null;
        this.charger();
        if (this.onglet === 'journal') this.chargerJournal(this.journalArticle ?? undefined);
      },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Ce mouvement n’a pas pu être enregistré.'); },
    });
  }

  // ── Articles ────────────────────────────────────────────────────────────────────────────
  nouvelArticle(): void { this.fermerSaisies(); this.article = { reference: '', designation: '', unite: 'unité', categorie: '', perissable: false, actif: true, conservation: 'AMBIANT', preparation: '' }; }
  modifierArticle(a: LigneEtatStock): void {
    this.fermerSaisies();
    this.article = { id: a.id, reference: a.reference, designation: a.designation, unite: a.unite, categorie: a.categorie,
      seuil_alerte: a.seuil_alerte, perissable: a.perissable, prix_unitaire: a.prix_unitaire, code_barres: a.code_barres,
      description: a.description, actif: a.actif, conservation: a.conservation, preparation: a.preparation };
  }

  enregistrerArticle(): void {
    const a = this.article;
    if (!a || !a.reference?.trim() || !a.designation?.trim()) return;
    const corps: Partial<ArticleStock> = { ...a, seuil_alerte: this.vide(a.seuil_alerte), prix_unitaire: this.vide(a.prix_unitaire) };
    this.envoi = true;
    this.erreur = '';
    (a.id ? this.stocks.modifierArticle(a.id, corps) : this.stocks.creerArticle(corps)).subscribe({
      next: (article) => { this.envoi = false; this.article = null; this.message = `Article « ${article.designation} » enregistré.`; this.charger(); },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cet article n’a pas pu être enregistré.'); },
    });
  }

  private vide(valeur: string | null | undefined): string | null {
    return valeur === undefined || valeur === null || `${valeur}`.trim() === '' ? null : `${valeur}`.replace(',', '.');
  }

  // ── Dépôts ──────────────────────────────────────────────────────────────────────────────
  nouveauDepot(): void { this.fermerSaisies(); this.onglet = 'depots'; this.depot = { nom: '', adresse: '', commentaire: '', actif: true, froid_positif: false, froid_negatif: false, cuisson: 'AUCUNE' }; }
  modifierDepot(d: DepotStock): void { this.fermerSaisies(); this.depot = { ...d }; }

  enregistrerDepot(): void {
    const d = this.depot;
    if (!d || !d.nom?.trim()) return;
    const corps = { nom: d.nom, adresse: d.adresse ?? '', commentaire: d.commentaire ?? '', actif: d.actif,
      froid_positif: !!d.froid_positif, froid_negatif: !!d.froid_negatif, cuisson: d.cuisson ?? 'AUCUNE' };
    this.envoi = true;
    this.erreur = '';
    (d.id ? this.stocks.modifierDepot(d.id, corps) : this.stocks.creerDepot(corps)).subscribe({
      next: (depot) => { this.envoi = false; this.depot = null; this.message = `Dépôt « ${depot.nom} » enregistré.`; this.charger(); },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Ce dépôt n’a pas pu être enregistré.'); },
    });
  }

  // ── Inventaire d'un dépôt : la feuille à imprimer, puis la saisie d'un bloc ─────────────
  inventaire: { depot: DepotStock; lignes: LigneInventaire[] } | null = null;

  feuilleInventaire(d: DepotStock, aveugle: boolean): void {
    this.stocks.feuilleInventaire(d.id, aveugle).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = `feuille-inventaire-${d.nom.replace(/[^A-Za-z0-9]+/g, '-')}.pdf`;
        lien.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      },
      error: (e) => this.erreur = this.lire(e, 'La feuille n’a pas pu être éditée.'),
    });
  }

  ouvrirInventaire(d: DepotStock): void {
    this.fermerSaisies();
    this.stocks.lignesInventaire(d.id).subscribe({
      next: (r) => this.inventaire = { depot: d, lignes: r.lignes.map(l => ({ ...l, compte: null })) },
      error: (e) => this.erreur = this.lire(e, 'L’inventaire n’a pas pu être préparé.'),
    });
  }

  get lignesComptees(): number { return (this.inventaire?.lignes ?? []).filter(l => l.compte !== null && l.compte !== undefined && `${l.compte}` !== '').length; }

  enregistrerInventaire(): void {
    const inv = this.inventaire;
    if (!inv || !this.lignesComptees) return;
    const comptes = inv.lignes.filter(l => l.compte !== null && l.compte !== undefined && `${l.compte}` !== '')
      .map(l => ({ article: l.article, quantite: +l.compte!, ...(l.lot ? { lot: l.lot } : {}), ...(l.date_peremption ? { date_peremption: l.date_peremption } : {}) }));
    this.envoi = true;
    this.erreur = '';
    this.stocks.saisirInventaire(inv.depot.id, comptes).subscribe({
      next: (bilan) => {
        this.envoi = false;
        this.inventaire = null;
        this.message = `Inventaire de « ${inv.depot.nom} » enregistré : ${bilan.comptees} ligne(s) comptée(s), ${bilan.corrections.length} correction(s) portée(s) au journal.`;
        this.charger();
      },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cet inventaire n’a pas pu être enregistré.'); },
    });
  }

  // ── Journal ─────────────────────────────────────────────────────────────────────────────
  ouvrirOnglet(onglet: Onglet): void {
    this.onglet = onglet;
    if (onglet === 'journal') this.chargerJournal();
  }

  chargerJournal(a?: LigneEtatStock): void {
    this.onglet = 'journal';
    this.journalArticle = a ?? null;
    this.stocks.mouvements({ article: a?.id, depot: this.depotFiltre || undefined }).subscribe({
      next: (m) => this.journal = m,
      error: (e) => this.erreur = this.lire(e, 'Le journal n’a pas pu être lu.'),
    });
  }

  // ── Reprise d'un fichier, export ────────────────────────────────────────────────────────
  ouvrirImport(): void { this.fermerSaisies(); this.importOuvert = true; this.bilanImport = null; this.fichierImport = null; }
  surFichier(evenement: Event): void {
    this.fichierImport = (evenement.target as HTMLInputElement).files?.[0] ?? null;
    this.bilanImport = null;
  }

  importer(simuler: boolean): void {
    if (!this.fichierImport) return;
    this.envoi = true;
    this.erreur = '';
    this.stocks.importer(this.fichierImport, this.depotImport, simuler).subscribe({
      next: (bilan) => { this.envoi = false; this.bilanImport = bilan; if (!simuler) this.charger(); },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Ce fichier n’a pas pu être lu.'); },
    });
  }

  exporter(): void {
    this.stocks.exporter().subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = `etat-du-stock-${new Date().toISOString().slice(0, 10)}.csv`;
        lien.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      },
      error: (e) => this.erreur = this.lire(e, 'L’export n’a pas pu être produit.'),
    });
  }

  fermerSaisies(): void {
    this.mouvement = null; this.article = null; this.depot = null; this.inventaire = null; this.importOuvert = false; this.erreur = ''; this.message = '';
  }

  private lire(e: any, defaut: string): string {
    const corps = e?.error;
    if (!corps || typeof corps !== 'object') return defaut;
    if (typeof corps.detail === 'string') return corps.detail;
    const premier = Object.values(corps)[0];
    return (Array.isArray(premier) ? premier[0] : premier) as string || defaut;
  }
}
