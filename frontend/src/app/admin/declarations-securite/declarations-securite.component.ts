import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { DeclarationSecuriteService } from '../../services/declaration-securite.service';
import { DeclarationSecurite } from '../../shared/models/declaration-securite.model';

@Component({
  selector: 'app-declarations-securite',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './declarations-securite.component.html',
  styleUrls: ['./declarations-securite.component.scss'],
})
export class DeclarationsSecuriteComponent implements OnInit {

  declarations: DeclarationSecurite[] = [];
  isLoading = true;
  errorMessage = '';

  searchQuery = '';
  filterCentre: 'ALL' | 'AVEC_CENTRE' | 'SANS_CENTRE' = 'ALL';

  constructor(private declarationSecuriteService: DeclarationSecuriteService) {}

  ngOnInit(): void {
    this.loadAll();
  }

  loadAll(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.declarationSecuriteService.getAll().subscribe({
      next: (declarations) => {
        this.declarations = declarations;
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMessage = err?.error?.error || "Impossible de charger les déclarations.";
        this.isLoading = false;
      },
    });
  }

  get filteredDeclarations(): DeclarationSecurite[] {
    let list = [...this.declarations];
    if (this.filterCentre === 'AVEC_CENTRE') list = list.filter(d => !!d.centre_accueil);
    if (this.filterCentre === 'SANS_CENTRE') list = list.filter(d => !d.centre_accueil);
    const q = this.searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(d =>
        `${d.prenom_referent} ${d.nom_referent}`.toLowerCase().includes(q)
        || d.contact_referent?.toLowerCase().includes(q)
      );
    }
    return list;
  }

  headcount(d: DeclarationSecurite): number {
    return d.nombre_adultes + d.nombre_enfants;
  }

  fmtDate(d: string | null | undefined): string {
    if (!d) return '—';
    return new Date(d).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
}
