import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { MaterielCatalogueService } from '../../services/materiel-catalogue.service';
import { MaterielCatalogue } from '../../shared/models/materiel-catalogue.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

/** Administration du catalogue matériel du formulaire public "Proposer mon aide" — même
 * patron que CompetencesComponent/BesoinsComponent (créer, regrouper en catégorie/sous-
 * catégorie via `parent`, activer/désactiver). Distinct de MaterielCategoriePickerComponent/
 * PointType.categories_materiel_exclues (`categorie`, une énumération fixe dédiée au stock des
 * centres) : cette page organise `parent`, une hiérarchie libre, jamais l'inverse. */
@Component({
  selector: 'app-materiel',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './materiel.component.html'
})
export class MaterielComponent implements OnInit {

  materiels: MaterielCatalogue[] = [];

  constructor(private materielCatalogueService: MaterielCatalogueService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.materielCatalogueService.getAll().subscribe(data => {
      this.materiels = data;
    });
  }

  searchFn = (q: string) => this.materielCatalogueService.search(q);
  createFn = (nom: string) => this.materielCatalogueService.create({ nom });

  onCreated(item: MaterielCatalogue): void {
    if (!this.materiels.find(m => m.id === item.id)) {
      this.materiels = [item, ...this.materiels];
    }
  }

  toggleActif(materiel: MaterielCatalogue): void {
    this.materielCatalogueService.patch(materiel.id, { actif: !materiel.actif }).subscribe(updated => {
      this.materiels = this.materiels.map(m => (m.id === updated.id ? updated : m));
    });
  }

  /** Matériels "de premier niveau" proposables comme parent — jamais plus d'un niveau (un
   * sous-matériel ne peut pas lui-même avoir des enfants), et jamais soi-même — même règle
   * que CompetencesComponent.parentOptions/BesoinsComponent.parentOptions. */
  parentOptions(materiel: MaterielCatalogue): MaterielCatalogue[] {
    return this.materiels.filter(m => m.id !== materiel.id && !m.parent);
  }

  setParent(materiel: MaterielCatalogue, parentId: string): void {
    this.materielCatalogueService.patch(materiel.id, { parent: parentId || null }).subscribe(updated => {
      this.materiels = this.materiels.map(m => (m.id === updated.id ? updated : m));
    });
  }
}
