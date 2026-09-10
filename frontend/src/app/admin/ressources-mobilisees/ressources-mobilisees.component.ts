import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TeamService } from '../../services/team.service';
import { RessourceMobilisee } from '../../shared/models/ressource-mobilisee.model';

type SortField = 'type' | 'nom' | 'equipe_nom' | 'institution' | 'detail' | 'statut';
type TypeFilter = 'ALL' | 'personne' | 'materiel';

/** Récap des ressources mobilisées (personnes ET matériel), où (institution/centre/crise) et
 * avec quoi (compétence ou matériel précis) — voir TeamViewSet.ressources_mobilisees. Une
 * page dédiée plutôt qu'un ajout à ReportingComponent (déjà volumineux, et cette vue porte sur
 * ce qui est RETENU par une équipe, pas sur les demandes/offres/signalements bruts). */
@Component({
  selector: 'app-ressources-mobilisees',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './ressources-mobilisees.component.html',
  styleUrl: './ressources-mobilisees.component.scss',
})
export class RessourcesMobiliseesComponent implements OnInit {
  rows: RessourceMobilisee[] = [];
  loading = true;
  errorMessage = '';

  typeFilter: TypeFilter = 'ALL';
  searchQuery = '';

  sortField: SortField = 'equipe_nom';
  sortAsc = true;

  constructor(private teamService: TeamService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.teamService.ressourcesMobilisees().subscribe({
      next: (rows) => { this.rows = rows; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les ressources mobilisées.'; this.loading = false; },
    });
  }

  get filteredRows(): RessourceMobilisee[] {
    const q = this.searchQuery.trim().toLowerCase();
    let list = this.rows;
    if (this.typeFilter !== 'ALL') list = list.filter(r => r.type === this.typeFilter);
    if (q) {
      list = list.filter(r =>
        r.nom.toLowerCase().includes(q) ||
        r.equipe_nom.toLowerCase().includes(q) ||
        (r.institution ?? '').toLowerCase().includes(q) ||
        (r.detail ?? '').toLowerCase().includes(q) ||
        r.centres.some(c => c.toLowerCase().includes(q)) ||
        r.crises.some(c => c.toLowerCase().includes(q))
      );
    }
    const dir = this.sortAsc ? 1 : -1;
    return [...list].sort((a, b) => {
      const av = (a[this.sortField] ?? '') as string;
      const bv = (b[this.sortField] ?? '') as string;
      return av.localeCompare(bv) * dir;
    });
  }

  sortBy(field: SortField): void {
    if (this.sortField === field) this.sortAsc = !this.sortAsc;
    else { this.sortField = field; this.sortAsc = true; }
  }

  sortIcon(field: SortField): string {
    if (this.sortField !== field) return 'unfold_more';
    return this.sortAsc ? 'arrow_upward' : 'arrow_downward';
  }

  get countPersonnes(): number {
    return this.rows.filter(r => r.type === 'personne').length;
  }

  get countMateriel(): number {
    return this.rows.filter(r => r.type === 'materiel').length;
  }

  exportCSV(): void {
    const rows = this.filteredRows;
    const headers = ['Type', 'Nom', 'Équipe', 'Institution', 'Crise(s)', 'Centre(s)', 'Compétence / Matériel', 'Statut'];
    const lines = rows.map(r => [
      r.type === 'personne' ? 'Personne' : 'Matériel',
      r.nom, r.equipe_nom, r.institution ?? '',
      r.crises.join(' / '), r.centres.join(' / '),
      r.detail ?? '', r.statut ?? '',
    ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));

    const csv = [headers.join(','), ...lines].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' }));
    a.download = `ressources_mobilisees_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
}
