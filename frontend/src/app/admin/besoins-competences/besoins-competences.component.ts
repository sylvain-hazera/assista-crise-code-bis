import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { BesoinCompetenceService } from '../../services/besoin-competence.service';
import { BesoinMaterielService } from '../../services/besoin-materiel.service';
import { BesoinService } from '../../services/besoin.service';
import { CompetenceService } from '../../services/competence.service';
import { MaterielCatalogueService } from '../../services/materiel-catalogue.service';
import { BesoinCompetence } from '../../shared/models/besoin-competence.model';
import { BesoinMateriel } from '../../shared/models/besoin-materiel.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Competence } from '../../shared/models/competence.model';
import { MaterielCatalogue } from '../../shared/models/materiel-catalogue.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

@Component({
  selector: 'app-besoins-competences',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './besoins-competences.component.html'
})
export class BesoinsCompetencesComponent implements OnInit {

  correspondancesCompetence: BesoinCompetence[] = [];
  correspondancesMateriel: BesoinMateriel[] = [];
  besoins: Besoin[] = [];

  selectedBesoinIdCompetence: string | null = null;
  selectedCompetence: Competence | null = null;

  selectedBesoinIdMateriel: string | null = null;
  selectedMateriel: MaterielCatalogue | null = null;

  constructor(
    private service: BesoinCompetenceService,
    private materielService: BesoinMaterielService,
    private besoinService: BesoinService,
    private competenceService: CompetenceService,
    private materielCatalogueService: MaterielCatalogueService
  ) {}

  ngOnInit(): void {
    this.load();
    this.besoinService.getAll().subscribe(data => {
      this.besoins = data;
    });
  }

  load(): void {
    this.service.getAll().subscribe(data => {
      this.correspondancesCompetence = data;
    });
    this.materielService.getAll().subscribe(data => {
      this.correspondancesMateriel = data;
    });
  }

  /** Besoins pour lesquels une correspondance compétence a du sens — non qualifiés (nature
   * absente) inclus, pour ne pas bloquer avant qualification via la page Besoins. */
  besoinsPourCompetence(): Besoin[] {
    return this.besoins.filter(b => !b.nature || b.nature === 'COMPETENCE' || b.nature === 'MIXTE');
  }

  besoinsPourMateriel(): Besoin[] {
    return this.besoins.filter(b => !b.nature || b.nature === 'MATERIEL' || b.nature === 'MIXTE');
  }

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  materielSearchFn = (q: string) => this.materielCatalogueService.search(q);
  materielCreateFn = (nom: string) => this.materielCatalogueService.create({ nom });

  onCompetenceSelected(item: Competence): void {
    this.selectedCompetence = item;
  }

  onMaterielSelected(item: MaterielCatalogue): void {
    this.selectedMateriel = item;
  }

  submitCompetence(): void {
    if (!this.selectedBesoinIdCompetence || !this.selectedCompetence) {
      return;
    }
    this.service.create(this.selectedBesoinIdCompetence, this.selectedCompetence.id).subscribe(() => {
      this.selectedBesoinIdCompetence = null;
      this.selectedCompetence = null;
      this.load();
    });
  }

  submitMateriel(): void {
    if (!this.selectedBesoinIdMateriel || !this.selectedMateriel) {
      return;
    }
    this.materielService.create(this.selectedBesoinIdMateriel, this.selectedMateriel.id).subscribe(() => {
      this.selectedBesoinIdMateriel = null;
      this.selectedMateriel = null;
      this.load();
    });
  }

  deleteCompetence(id: string): void {
    if (!confirm('Supprimer cette correspondance ?')) {
      return;
    }
    this.service.delete(id).subscribe(() => this.load());
  }

  deleteMateriel(id: string): void {
    if (!confirm('Supprimer cette correspondance ?')) {
      return;
    }
    this.materielService.delete(id).subscribe(() => this.load());
  }
}
