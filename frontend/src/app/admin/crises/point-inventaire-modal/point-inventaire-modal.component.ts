import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { MaterielPointService } from '../../../services/materiel-point.service';
import { MaterielCatalogueService } from '../../../services/materiel-catalogue.service';
import { ContributionMaterielService } from '../../../services/contribution-materiel.service';
import { PointOperationnel } from '../../../shared/models/point-operationnel.model';
import { MaterielPoint, NiveauStock } from '../../../shared/models/materiel-point.model';
import { MaterielCatalogue } from '../../../shared/models/materiel-catalogue.model';
import { ContributionMateriel } from '../../../shared/models/contribution-materiel.model';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';

const NIVEAUX: { value: NiveauStock; label: string }[] = [
  { value: 'NUL', label: 'Nul' },
  { value: 'FAIBLE', label: 'Faible' },
  { value: 'OK', label: 'OK' },
  { value: 'EN_TROP', label: 'En trop' },
];

/** "Sous-menu - fenêtre" besoins/stocks d'un point : le catalogue matériel est partagé entre
 * tous les centres (voir MaterielCatalogueService — recherche ou création façon hashtag) — un
 * item ajouté ici apparaît, à niveau nul, dans la liste de tous les autres centres, sans action
 * de leur part (backend : PointOperationnelViewSet.stocks). */
@Component({
  selector: 'app-point-inventaire-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
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

  constructor(
    private materielService: MaterielPointService,
    private catalogueService: MaterielCatalogueService,
    private contributionService: ContributionMaterielService,
  ) {}

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

  /** Ajoute un apport manuel (stock non issu d'une offre publique) — crée d'abord la ligne
   * MaterielPoint si elle n'existe pas encore, même logique que setNiveau. */
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
  }

  private load(): void {
    this.loading = true;
    this.materielService.getStocks(this.point.id).subscribe(data => {
      this.stocks = data;
      this.loading = false;
    });
  }

  niveauLabel(niveau: NiveauStock): string {
    return this.niveaux.find(n => n.value === niveau)?.label ?? niveau;
  }

  /** Un item du catalogue pas encore dans la liste locale (nouvellement créé par CE centre ou
   * découvert via un autre) : on l'ajoute côté client à niveau nul, sans appel serveur — la
   * ligne réelle n'est créée qu'au premier changement de niveau (cf. setNiveau). */
  onCatalogueItemSelected(item: MaterielCatalogue): void {
    if (this.stocks.some(s => s.item === item.id)) return;
    this.stocks = [
      { id: null, point: this.point.id, item: item.id, item_nom: item.nom, niveau_stock: 'NUL',
        quantite: 1, unite: 'unité', statut: null, responsable: null, commentaire: null, date_maj: null },
      ...this.stocks,
    ];
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
