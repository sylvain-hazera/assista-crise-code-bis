import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { BesoinService } from '../../services/besoin.service';
import { Besoin } from '../../shared/models/besoin.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

@Component({
  selector: 'app-besoins',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './besoins.component.html'
})
export class BesoinsComponent implements OnInit {

  besoins: Besoin[] = [];

  constructor(private besoinService: BesoinService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.besoinService.getAll().subscribe(data => {
      this.besoins = data;
    });
  }

  searchFn = (q: string) => this.besoinService.search(q);
  createFn = (nom: string) => this.besoinService.create({ nom });

  onCreated(item: Besoin): void {
    if (!this.besoins.find(b => b.id === item.id)) {
      this.besoins = [item, ...this.besoins];
    }
  }

  toggleActif(besoin: Besoin): void {
    this.besoinService.patch(besoin.id, { actif: !besoin.actif }).subscribe(updated => {
      this.besoins = this.besoins.map(b => (b.id === updated.id ? updated : b));
    });
  }

  /** Besoins "de premier niveau" proposables comme parent — jamais plus d'un niveau (un
   * sous-besoin ne peut pas lui-même avoir des enfants), et jamais soi-même — même règle
   * que CompetencesComponent.parentOptions. */
  parentOptions(besoin: Besoin): Besoin[] {
    return this.besoins.filter(b => b.id !== besoin.id && !b.parent);
  }

  setParent(besoin: Besoin, parentId: string): void {
    this.besoinService.patch(besoin.id, { parent: parentId || null }).subscribe(updated => {
      this.besoins = this.besoins.map(b => (b.id === updated.id ? updated : b));
    });
  }
}
