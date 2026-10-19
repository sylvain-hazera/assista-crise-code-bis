import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MaterielPointService } from '../../../services/materiel-point.service';
import { MaterielCatalogueService } from '../../../services/materiel-catalogue.service';
import { ContributionMaterielService } from '../../../services/contribution-materiel.service';
import { PointTypeService } from '../../../services/point-type.service';
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
