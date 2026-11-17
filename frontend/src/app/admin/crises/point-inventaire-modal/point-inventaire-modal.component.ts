import { Component, EventEmitter, Input, OnInit, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MaterielPointService } from '../../../services/materiel-point.service';
import { MaterielCatalogueService } from '../../../services/materiel-catalogue.service';
import { ContributionMaterielService } from '../../../services/contribution-materiel.service';
import { PointTypeService } from '../../../services/point-type.service';
import { StockService } from '../../../services/stock.service';
import { CuissonLieu, DemandeTransfertStock, EtatStock, EtatStockPoint, GesteStockPoint, LABELS_CONSERVATION, LABELS_CUISSON, LABELS_PREPARATION } from '../../../shared/models/stock.model';
import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { PointOperationnel } from '../../../shared/models/point-operationnel.model';
import { MaterielPoint, NiveauStock } from '../../../shared/models/materiel-point.model';
import { MaterielCatalogue } from '../../../shared/models/materiel-catalogue.model';
import { ContributionMateriel } from '../../../shared/models/contribution-materiel.model';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { MaterielCategoriePickerComponent } from '../../../shared/components/common/materiel-categorie-picker/materiel-categorie-picker.component';

const NIVEAUX: { value: NiveauStock; label: string }[] = [
  { value: 'NUL', label: 'Nul' },
  { value: 'FAIBLE', label: 'Faible' },
  { value: 'OK', label: 'OK' },
  { value: 'EN_TROP', label: 'En trop' },
];

/** Besoins/stocks d'un point. Catalogue matériel partagé : un item ajouté ici apparaît à
 * niveau nul dans tous les centres (PointOperationnelViewSet.stocks). */
@Component({
  selector: 'app-point-inventaire-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent, MaterielCategoriePickerComponent],
  templateUrl: './point-inventaire-modal.component.html',
  styleUrl: './point-inventaire-modal.component.scss'
})
export class PointInventaireModalComponent implements OnInit {
  @Input({ required: true }) point!: PointOperationnel;
  @Output() closed = new EventEmitter<void>();
  @Output() compareRequested = new EventEmitter<void>();

  niveaux = NIVEAUX;
  stocks: MaterielPoint[] = [];
  loading = true;
  savingItemId: string | null = null;
  // Catégories masquées pour ce centre, lues sur son type (PointType.categories_materiel_exclues).
  categoriesExclues: string[] = [];

  constructor(
    private materielService: MaterielPointService,
    private catalogueService: MaterielCatalogueService,
    private contributionService: ContributionMaterielService,
    private pointTypeService: PointTypeService,
    private router: Router,
  ) {}

  // ── Mouvements de stock du point (voir core/stocks_points.py côté serveur) ──────────────
  // La quantité d'une ligne se déduit du journal : on distribue, on compte, on dote le point
  // depuis un dépôt, on rapatrie le reste — on ne retape jamais un nombre.
  private stockService = inject(StockService);
  suivi: EtatStockPoint | null = null;
  /** Geste en cours sur une ligne : distribuer ou compter. */
  geste: { item: string; type: 'distribuer' | 'compter' | 'transferer'; quantite: number | null; tiers: string; motif: string; destination: string } | null = null;
  private pointService = inject(PointOperationnelService);
  /** Les autres points de la crise, pour un transfert de point à point. */
  autresPoints: PointOperationnel[] = [];
  readonly conservations = LABELS_CONSERVATION;
  readonly preparations = LABELS_PREPARATION;
  readonly cuissons = LABELS_CUISSON;

  /** Ce qu'il faut pour garder et servir cette ligne, et ce qui manque au point pour cela. */
  denree(entry: MaterielPoint): { libelle: string; manques: string[] } | null {
    const ligne = this.suivi?.lignes.find(l => l.item === entry.item);
    if (!ligne || (ligne.conservation === 'AMBIANT' && !ligne.preparation)) return null;
    const mots = [ligne.conservation !== 'AMBIANT' ? this.conservations[ligne.conservation] : '', ligne.preparation ? this.preparations[ligne.preparation] : ''];
    return { libelle: mots.filter(Boolean).join(' · '), manques: ligne.manques };
  }

  /** Le point dit ce qu'il a : réfrigérateur, congélateur, de quoi chauffer. */
  changerMoyens(champ: 'froid_positif' | 'froid_negatif' | 'cuisson', valeur: boolean | CuissonLieu): void {
    this.envoyerGeste('moyens', { [champ]: valeur }, 'Moyens du point mis à jour.');
  }

  /** Dotation en cours depuis un dépôt de mon institution. */
  dotation: { article: string; depot: string; quantite: number | null } | null = null;
  monStock: EtatStock | null = null;
  depotRetour = '';
  journalOuvert = false;
  gesteEnCours = false;
  erreurStock = '';
  messageStock = '';

  // ── Demandes de transfert qui touchent ce point ─────────────────────────────────────────
  demandes: DemandeTransfertStock[] = [];
  /** Quantité que j'accorde sur chaque demande reçue (par défaut : ce qui est demandé). */
  accordees: Record<string, number> = {};

  get demandesRecues(): DemandeTransfertStock[] { return this.demandes.filter(d => d.source === this.point.id && d.statut === 'DEMANDEE'); }
  get demandesFaites(): DemandeTransfertStock[] { return this.demandes.filter(d => d.destination === this.point.id); }

  private chargerDemandes(): void {
    this.stockService.transferts(this.point.id).subscribe({ next: (d) => this.demandes = d, error: () => {} });
  }

  repondre(demande: DemandeTransfertStock, geste: 'accepter' | 'refuser' | 'annuler', reponse = ''): void {
    this.gesteEnCours = true;
    this.erreurStock = this.messageStock = '';
    const corps = geste === 'accepter' ? { quantite: this.accordees[demande.id] ?? demande.quantite, reponse } : { reponse };
    this.stockService.repondreTransfert(demande.id, geste, corps).subscribe({
      next: (maj) => {
        this.gesteEnCours = false;
        this.demandes = this.demandes.map(d => d.id === maj.id ? maj : d);
        this.messageStock = geste === 'accepter' ? `Accepté : ${maj.quantite_accordee} × ${maj.item_nom} sont partis vers « ${maj.destination_nom} ».`
          : geste === 'refuser' ? 'Demande refusée : rien ne part.' : 'Demande retirée.';
        if (geste === 'accepter') { this.chargerSuivi(); this.load(); }
      },
      error: (e) => { this.gesteEnCours = false; this.erreurStock = e?.error?.detail || 'Cette réponse n’a pas pu être enregistrée.'; },
    });
  }

  private chargerSuivi(): void {
    this.stockService.point(this.point.id).subscribe({ next: (s) => this.suivi = s, error: () => this.suivi = null });
  }

  /** Quantité d'une ligne d'après le journal ; null tant qu'aucun mouvement ne la concerne. */
  quantiteSuivie(entry: MaterielPoint): number | null {
    const ligne = this.suivi?.lignes.find(l => l.item === entry.item);
    return ligne?.suivi && ligne.quantite !== null ? +ligne.quantite : null;
  }

  ouvrirGeste(entry: MaterielPoint, type: 'distribuer' | 'compter' | 'transferer'): void {
    this.erreurStock = this.messageStock = '';
    this.geste = { item: entry.item, type, quantite: null, tiers: '', motif: '', destination: '' };
    if (type === 'transferer' && !this.autresPoints.length && this.point.crise) {
      this.pointService.getByCrise(this.point.crise).subscribe({
        next: (points) => this.autresPoints = points.filter(p => p.id !== this.point.id), error: () => {} });
    }
  }

  validerGeste(): void {
    const g = this.geste;
    if (!g || g.quantite === null || g.quantite < 0 || (g.type === 'distribuer' && g.quantite === 0)) return;
    const corps: Record<string, unknown> = { item: g.item, quantite: g.quantite };
    if (g.tiers) corps['tiers'] = g.tiers;
    if (g.motif) corps['motif'] = g.motif;
    if (g.type === 'transferer') {
      // On DEMANDE au point choisi de nous en envoyer : rien ne part tant qu'il n'a pas accepté.
      if (!g.destination || !g.quantite) return;
      this.gesteEnCours = true;
      this.erreurStock = '';
      this.stockService.demanderTransfert(g.destination, this.point.id, g.item, Math.floor(g.quantite), g.motif).subscribe({
        next: (demande) => { this.gesteEnCours = false; this.geste = null; this.demandes = [demande, ...this.demandes];
          this.messageStock = `Demande envoyée à « ${demande.source_nom} » : rien ne part tant qu'il n'a pas accepté.`; },
        error: (e) => { this.gesteEnCours = false; this.erreurStock = e?.error?.detail || 'Cette demande n’a pas pu être envoyée.'; },
      });
      return;
    }
    this.envoyerGeste(g.type, corps, g.type === 'distribuer' ? 'Distribution enregistrée.' : 'Inventaire enregistré.');
  }

  ouvrirDotation(): void {
    this.erreurStock = this.messageStock = '';
    this.dotation = { article: '', depot: '', quantite: null };
    this.stockService.etat().subscribe({
      next: (etat) => {
        this.monStock = { ...etat, depots: etat.depots.filter(d => d.actif && !d.point) };
        if (this.monStock.depots.length === 1) { this.dotation!.depot = this.depotRetour = this.monStock.depots[0].id; }
      },
      error: (e) => this.erreurStock = e?.error?.detail || 'Votre stock n’a pas pu être lu.',
    });
  }

  /** Les articles que j'ai dans le dépôt choisi, avec ce qu'il en reste. */
  get articlesDotables(): { id: string; libelle: string }[] {
    const depot = this.dotation?.depot;
    return (this.monStock?.articles ?? []).filter(a => depot && +(a.par_depot[depot] ?? 0) > 0)
      .map(a => ({ id: a.id, libelle: `${a.designation} — ${(+a.par_depot[depot!]).toLocaleString('fr-FR')} ${a.unite} en stock` }));
  }

  doter(): void {
    const d = this.dotation;
    if (!d || !d.article || !d.depot || !d.quantite || d.quantite <= 0) return;
    this.envoyerGeste('doter', { article: d.article, depot: d.depot, quantite: d.quantite }, 'Point doté : le stock a quitté le dépôt.');
  }

  rapatrier(): void {
    if (!this.depotRetour) return;
    if (!confirm(`Ramener au dépôt tout ce que ${this.suivi?.institution_nom || 'votre institution'} a encore sur ce point ?`)) return;
    this.envoyerGeste('rapatrier', { depot: this.depotRetour }, 'Le stock restant est revenu au dépôt.');
  }

  private envoyerGeste(geste: GesteStockPoint, corps: Record<string, unknown>, succes: string): void {
    this.gesteEnCours = true;
    this.erreurStock = '';
    this.stockService.gestePoint(this.point.id, geste, corps).subscribe({
      next: (suivi) => {
        this.gesteEnCours = false;
        this.suivi = suivi;
        this.geste = null;
        this.dotation = null;
        this.messageStock = succes;
        this.load();
      },
      error: (e) => {
        this.gesteEnCours = false;
        const corpsErreur = e?.error;
        this.erreurStock = corpsErreur?.detail || (corpsErreur && Object.values(corpsErreur)[0] as string) || 'Ce mouvement n’a pas pu être enregistré.';
      },
    });
  }

  importerFichier(): void {
    this.router.navigate(['/admin/import-materiel-point'], { queryParams: { point: this.point.id } });
  }

  // ── Apports (ContributionMateriel) ────────────────────────────
  expandedItemId: string | null = null;
  contributionsByMaterielPoint: Record<string, ContributionMateriel[]> = {};
  loadingContributions = false;
  newContribution = { fournisseur_nom: '', quantite: 1, unite: 'unité' };

  toggleApports(entry: MaterielPoint): void {
    if (this.expandedItemId === entry.item) {
      this.expandedItemId = null;
      return;
    }
    this.expandedItemId = entry.item;
    this.newContribution = { fournisseur_nom: '', quantite: 1, unite: 'unité' };
    if (entry.id) this.loadContributions(entry.id);
  }

  private loadContributions(materielPointId: string): void {
    this.loadingContributions = true;
    this.contributionService.getByMaterielPoint(materielPointId).subscribe({
      next: (list) => { this.contributionsByMaterielPoint[materielPointId] = list; this.loadingContributions = false; },
      error: () => { this.loadingContributions = false; },
    });
  }

  contributionsFor(entry: MaterielPoint): ContributionMateriel[] {
    return entry.id ? (this.contributionsByMaterielPoint[entry.id] ?? []) : [];
  }

  /** Apport manuel ; crée d'abord la ligne MaterielPoint si besoin. */
  ajouterApportManuel(entry: MaterielPoint): void {
    if (!this.newContribution.fournisseur_nom.trim() || !this.newContribution.quantite) return;

    const enregistrer = (materielPointId: string) => {
      this.contributionService.create({
        materiel_point: materielPointId,
        fournisseur_nom: this.newContribution.fournisseur_nom.trim(),
        quantite: this.newContribution.quantite,
        unite: this.newContribution.unite || 'unité',
      }).subscribe({
        next: () => {
          this.loadContributions(materielPointId);
          this.newContribution = { fournisseur_nom: '', quantite: 1, unite: 'unité' };
          this.load();
        },
      });
    };

    if (entry.id) {
      enregistrer(entry.id);
    } else {
      this.materielService.create({ point: this.point.id, item: entry.item, niveau_stock: 'NUL' }).subscribe({
        next: (created) => {
          const idx = this.stocks.findIndex(s => s.item === entry.item);
          if (idx !== -1) this.stocks[idx] = created;
          enregistrer(created.id!);
        },
      });
    }
  }

  catalogueSearchFn = (q: string) => this.catalogueService.search(q);
  catalogueCreateFn = (nom: string) => this.catalogueService.create({ nom });
  fnCreateLabel = (value: string) => `Ajouter « ${value} » comme nouveau besoin`;

  ngOnInit(): void {
    this.load();
    this.chargerSuivi();
    this.chargerDemandes();
    this.pointTypeService.getAll().subscribe(types => {
      this.categoriesExclues = types.find(t => t.code === this.point.type_code)?.categories_materiel_exclues ?? [];
    });
  }

  /** Ajout groupé depuis app-materiel-categorie-picker. */
  onCatalogueItemsAdded(items: MaterielCatalogue[]): void {
    for (const item of items) this.onCatalogueItemSelected(item);
  }

  private load(): void {
    this.loading = true;
    this.materielService.getStocks(this.point.id).subscribe(data => {
      this.stocks = data;
      this.loading = false;
    });
  }

  get existingItemIds(): string[] {
    return this.stocks.map(s => s.item);
  }

  niveauLabel(niveau: NiveauStock): string {
    return this.niveaux.find(n => n.value === niveau)?.label ?? niveau;
  }

  /** Item ajouté localement à niveau nul ; la ligne serveur est créée au premier changement. */
  onCatalogueItemSelected(item: MaterielCatalogue): void {
    if (this.stocks.some(s => s.item === item.id)) return;
    this.stocks = [
      { id: null, point: this.point.id, item: item.id, item_nom: item.nom, niveau_stock: 'NUL',
        quantite: 1, unite: 'unité', statut: null, responsable: null, commentaire: null, date_maj: null },
      ...this.stocks,
    ];
  }

  /** Précision libre par item ; crée la ligne au premier enregistrement si besoin. */
  commentaireEnCours: Record<string, string> = {};
  savingCommentaireItemId: string | null = null;

  commentaireAffiche(entry: MaterielPoint): string {
    const id = entry.item;
    return id in this.commentaireEnCours ? this.commentaireEnCours[id] : (entry.commentaire ?? '');
  }

  modifierCommentaire(entry: MaterielPoint, valeur: string): void {
    this.commentaireEnCours[entry.item] = valeur;
  }

  enregistrerCommentaire(entry: MaterielPoint): void {
    const valeur = (this.commentaireEnCours[entry.item] ?? entry.commentaire ?? '').trim() || null;
    if (valeur === (entry.commentaire ?? null)) {
      delete this.commentaireEnCours[entry.item];
      return;
    }
    this.savingCommentaireItemId = entry.item;
    const request$ = entry.id
      ? this.materielService.update(entry.id, { commentaire: valeur ?? undefined })
      : this.materielService.create({ point: this.point.id, item: entry.item, niveau_stock: 'NUL', commentaire: valeur ?? undefined });

    request$.subscribe({
      next: (updated) => {
        const idx = this.stocks.findIndex(s => s.item === entry.item);
        if (idx !== -1) this.stocks[idx] = updated;
        delete this.commentaireEnCours[entry.item];
        this.savingCommentaireItemId = null;
      },
      error: () => { this.savingCommentaireItemId = null; },
    });
  }

  /** Retire le besoin du point ; une ligne jamais enregistrée est retirée localement. */
  supprimerEntree(entry: MaterielPoint): void {
    if (!confirm(`Retirer « ${entry.item_nom} » de la liste de ce centre ?`)) return;
    if (!entry.id) {
      this.stocks = this.stocks.filter(s => s.item !== entry.item);
      return;
    }
    this.materielService.delete(entry.id).subscribe(() => {
      this.stocks = this.stocks.filter(s => s.item !== entry.item);
    });
  }

  setNiveau(entry: MaterielPoint, niveau: NiveauStock): void {
    if (entry.niveau_stock === niveau) return;
    this.savingItemId = entry.item;

    const request$ = entry.id
      ? this.materielService.update(entry.id, { niveau_stock: niveau })
      : this.materielService.create({ point: this.point.id, item: entry.item, niveau_stock: niveau });

    request$.subscribe({
      next: (updated) => {
        const idx = this.stocks.findIndex(s => s.item === entry.item);
        if (idx !== -1) this.stocks[idx] = updated;
        this.savingItemId = null;
      },
      error: () => { this.savingItemId = null; },
    });
  }

  close(): void {
    this.closed.emit();
  }

  compare(): void {
    this.compareRequested.emit();
  }
}
