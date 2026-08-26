import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { BesoinCompetenceService } from '../../services/besoin-competence.service';
import { BesoinService } from '../../services/besoin.service';
import { CompetenceService } from '../../services/competence.service';
import { BesoinCompetence } from '../../shared/models/besoin-competence.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Competence } from '../../shared/models/competence.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

@Component({
  selector: 'app-besoins-competences',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './besoins-competences.component.html'
})
export class BesoinsCompetencesComponent implements OnInit {

  correspondances: BesoinCompetence[] = [];
  besoins: Besoin[] = [];

  selectedBesoinId: string | null = null;
  selectedCompetence: Competence | null = null;

  constructor(
    private service: BesoinCompetenceService,
    private besoinService: BesoinService,
    private competenceService: CompetenceService
  ) {}

  ngOnInit(): void {
    this.load();
    this.besoinService.getAll().subscribe(data => {
      this.besoins = data;
    });
  }

  load(): void {
    this.service.getAll().subscribe(data => {
      this.correspondances = data;
    });
  }

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  onCompetenceSelected(item: Competence): void {
    this.selectedCompetence = item;
  }

  submit(): void {
    if (!this.selectedBesoinId || !this.selectedCompetence) {
      return;
    }
    this.service.create(this.selectedBesoinId, this.selectedCompetence.id).subscribe(() => {
      this.selectedBesoinId = null;
      this.selectedCompetence = null;
      this.load();
    });
  }

  delete(id: string): void {
    if (!confirm('Supprimer cette correspondance ?')) {
      return;
    }
    this.service.delete(id).subscribe(() => this.load());
  }
}
