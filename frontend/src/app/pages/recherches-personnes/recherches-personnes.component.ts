import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { RecherchePersonneService } from '../../services/recherche-personne.service';

@Component({
  selector: 'app-recherches-personnes',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    FormsModule
  ],
  templateUrl: './recherches-personnes.component.html',
  styleUrls: ['./recherches-personnes.component.scss']
})
export class RecherchesPersonnesComponent implements OnInit, OnDestroy {

  recherches: any[] = [];
  photoUrls: Record<string, string> = {};

  searchTerm = '';

  get filteredRecherches(): any[] {
    if (!this.searchTerm.trim()) {
      return this.recherches;
    }

    const term = this.searchTerm.toLowerCase();

    return this.recherches.filter(r =>
      `${r.prenom ?? ''} ${r.nom ?? ''}`.toLowerCase().includes(term) ||
      (r.ville ?? '').toLowerCase().includes(term)
    );
  }

  constructor(
    private service: RecherchePersonneService
  ) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.service
      .getAll()
      .subscribe(data => {
        this.recherches = data;
        data.filter(r => r.has_photo).forEach(r => this.loadPhoto(r.id));
      });
  }

  private loadPhoto(id: string): void {
    this.service.preview(id).subscribe({
      next: (blob) => { this.photoUrls[id] = URL.createObjectURL(blob); },
      error: () => {},
    });
  }

  ngOnDestroy(): void {
    Object.values(this.photoUrls).forEach(url => URL.revokeObjectURL(url));
  }
}
