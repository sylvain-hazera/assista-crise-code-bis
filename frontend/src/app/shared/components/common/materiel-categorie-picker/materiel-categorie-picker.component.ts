import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

import { MaterielCatalogueService } from '../../../../services/materiel-catalogue.service';
import {
  CATEGORIES_MATERIEL_STOCK,
  CATEGORIE_MATERIEL_NON_CLASSE,
  MaterielCatalogue,
} from '../../../models/materiel-catalogue.model';

interface CategorieGroupe {
  code: string | null;
  libelle: string;
  items: MaterielCatalogue[];
}

/** Sélecteur groupé par catégorie du catalogue matériel : dépliable catégorie par catégorie,
 * une case à cocher par catégorie sélectionne/désélectionne tous ses items en un clic (voir
 * toggleCategorie), en plus des cases individuelles. `allowedCategories` (codes
 * MaterielCatalogueCategorie à MASQUER, voir PointType.categories_materiel_exclues) permet de
 * ne pas proposer, pour un centre donné, des catégories hors-sujet (ex: pas d'engins de
 * déblaiement dans un centre d'accueil des personnes) — les items non classés (categorie=null,
 * catalogue historique) restent toujours visibles, jamais filtrés par cette exclusion : ils
 * n'ont jamais été rattachés à une des 9 catégories, les masquer romprait des usages existants.
 * ENGIN (rubrique dédiée au formulaire public) n'apparaît jamais ici. */
@Component({
  selector: 'app-materiel-categorie-picker',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './materiel-categorie-picker.component.html',
  styleUrl: './materiel-categorie-picker.component.scss',
})
export class MaterielCategoriePickerComponent implements OnInit, OnChanges {
  /** Codes de catégorie à masquer (PointType.categories_materiel_exclues) — vide/absent =
   * aucune restriction. */
  @Input() excludedCategories: string[] = [];
  /** Ids déjà présents dans le stock du centre — ne sont pas reproposés ici. */
  @Input() existingItemIds: string[] = [];

  @Output() itemsAdded = new EventEmitter<MaterielCatalogue[]>();

  open = false;
  loading = true;
  groupes: CategorieGroupe[] = [];
  expanded = new Set<string | null>();
  selectedIds = new Set<string>();

  private allItems: MaterielCatalogue[] = [];

  constructor(private catalogueService: MaterielCatalogueService) {}

  ngOnInit(): void {
    this.catalogueService.getAll().subscribe(items => {
      this.allItems = items;
      this.buildGroupes();
      this.loading = false;
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if ((changes['excludedCategories'] || changes['existingItemIds']) && !this.loading) {
      this.buildGroupes();
    }
  }

  private buildGroupes(): void {
    const exclues = new Set(this.excludedCategories ?? []);
    const dejaPresents = new Set(this.existingItemIds ?? []);
    const disponibles = this.allItems.filter(i => i.categorie !== 'ENGIN' && !dejaPresents.has(i.id));

    const groupes: CategorieGroupe[] = [];
    for (const cat of CATEGORIES_MATERIEL_STOCK) {
      if (exclues.has(cat.code)) continue;
      const items = disponibles.filter(i => i.categorie === cat.code);
      if (items.length > 0) groupes.push({ code: cat.code, libelle: cat.libelle, items });
    }
    // Non classés : jamais filtrés par excludedCategories (voir docstring de classe).
    const nonClasses = disponibles.filter(i => !i.categorie);
    if (nonClasses.length > 0) {
      groupes.push({ code: CATEGORIE_MATERIEL_NON_CLASSE.code, libelle: CATEGORIE_MATERIEL_NON_CLASSE.libelle, items: nonClasses });
    }
    this.groupes = groupes;

    // Nettoie une éventuelle sélection sur un item qui vient de disparaître (déjà ajouté
    // entre-temps par ailleurs, ou catégorie désormais exclue).
    const idsVisibles = new Set(groupes.flatMap(g => g.items.map(i => i.id)));
    for (const id of Array.from(this.selectedIds)) {
      if (!idsVisibles.has(id)) this.selectedIds.delete(id);
    }
  }

  toggleOpen(): void {
    this.open = !this.open;
  }

  isExpanded(code: string | null): boolean {
    return this.expanded.has(code);
  }

  toggleExpand(code: string | null): void {
    if (this.expanded.has(code)) this.expanded.delete(code);
    else this.expanded.add(code);
  }

  isItemSelected(id: string): boolean {
    return this.selectedIds.has(id);
  }

  toggleItem(item: MaterielCatalogue): void {
    if (this.selectedIds.has(item.id)) this.selectedIds.delete(item.id);
    else this.selectedIds.add(item.id);
  }

  /** 'all' | 'some' | 'none' — pilote l'état (coché / indéterminé / décoché) de la case
   * "catégorie entière". */
  categorieState(groupe: CategorieGroupe): 'all' | 'some' | 'none' {
    const total = groupe.items.length;
    const selected = groupe.items.filter(i => this.selectedIds.has(i.id)).length;
    if (selected === 0) return 'none';
    return selected === total ? 'all' : 'some';
  }

  toggleCategorie(groupe: CategorieGroupe): void {
    const tout = this.categorieState(groupe) === 'all';
    for (const item of groupe.items) {
      if (tout) this.selectedIds.delete(item.id);
      else this.selectedIds.add(item.id);
    }
  }

  get selectedCount(): number {
    return this.selectedIds.size;
  }

  confirmAdd(): void {
    const chosen = this.groupes.flatMap(g => g.items).filter(i => this.selectedIds.has(i.id));
    if (chosen.length === 0) return;
    this.itemsAdded.emit(chosen);
    this.selectedIds.clear();
    this.open = false;
  }
}
