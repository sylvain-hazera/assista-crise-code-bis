import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CompetenceService } from '../../services/competence.service';
import { Competence } from '../../shared/models/competence.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

@Component({
  selector: 'app-competences',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './competences.component.html'
})
export class CompetencesComponent implements OnInit {

  competences: Competence[] = [];

  constructor(
    private competenceService: CompetenceService
  ) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.competenceService.getAll()
      .subscribe(data => {
        this.competences = data;
      });
  }

  searchFn = (q: string) => this.competenceService.search(q);
  createFn = (nom: string) => this.competenceService.create({ nom });

  onCreated(item: Competence): void {
    if (!this.competences.find(c => c.id === item.id)) {
      this.competences = [item, ...this.competences];
    }
  }

  toggleActive(competence: Competence): void {
    this.competenceService.patch(competence.id, { active: !competence.active }).subscribe(updated => {
      this.competences = this.competences.map(c => (c.id === updated.id ? updated : c));
    });
  }

  /** Compétences "de premier niveau" proposables comme parent — jamais plus d'un niveau
   * (une sous-compétence ne peut pas elle-même avoir des enfants), et jamais soi-même. */
  parentOptions(competence: Competence): Competence[] {
    return this.competences.filter(c => c.id !== competence.id && !c.parent);
  }

  setParent(competence: Competence, parentId: string): void {
    this.competenceService.patch(competence.id, { parent: parentId || null }).subscribe(updated => {
      this.competences = this.competences.map(c => (c.id === updated.id ? updated : c));
    });
  }
}
