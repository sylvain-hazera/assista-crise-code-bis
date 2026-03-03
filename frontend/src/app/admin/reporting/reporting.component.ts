import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin, Observable, Subject, takeUntil } from 'rxjs';

import { CrisisService }  from '../../services/crisis.service';
import { OfferService }   from '../../services/offer.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';

import { Crise }       from '../../shared/models/crisis.model';
import { Offre }       from '../../shared/models/offer.model';
import { Demande }     from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { Statut }      from '../../shared/models/status.model';

// ── Unified row displayed in the table ───────────────────────────────────────

export type ReportKind = 'Crise' | 'Offre' | 'Demande' | 'Information';

export interface ReportRow {
  id:           string;
  kind:         ReportKind;
  titre:        string;
  contact:      string;        // prenom + nom
  email:        string;
  telephone:    string | null;
  statut:       Statut;
  date:         string;        // date_creation / date_debut
  dateExp:      string | null;
  crise:        string | null; // UUID
  auteur:       string | null;
  latitude:     number | null;
  longitude:    number | null;
  photo:        string | null;
  // raw originals for detail modal
  _raw:         Crise | Offre | Demande | Information;
}

// ─────────────────────────────────────────────────────────────────────────────

type FilterKind   = ReportKind | 'ALL';
type FilterStatut = Statut     | 'ALL';
type SortField    = 'titre' | 'kind' | 'statut' | 'date' | 'contact';

@Component({
  selector: 'app-reporting',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './reporting.component.html',
  styleUrls: ['./reporting.component.scss'],
})
export class ReportingComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  // ── Raw data ───────────────────────────────────────────────
  rawCrises:       Crise[]       = [];
  rawOffres:       Offre[]       = [];
  rawDemandes:     Demande[]     = [];
  rawInformations: Information[] = [];

  // ── Processed rows ─────────────────────────────────────────
  allRows:      ReportRow[] = [];
  filteredRows: ReportRow[] = [];
  pagedRows:    ReportRow[] = [];

  // ── UI state ───────────────────────────────────────────────
  isLoading      = true;
  isSaving       = false;
  errorMessage   = '';
  successMessage = '';

  // ── Filters / sort ─────────────────────────────────────────
  searchQuery   = '';
  filterKind:   FilterKind   = 'ALL';
  filterStatut: FilterStatut = 'ALL';
  sortField:    SortField    = 'date';
  sortAsc                    = false;

  // ── Pagination ─────────────────────────────────────────────
  pageSize    = 15;
  currentPage = 1;
  totalPages  = 1;

  // ── Modals ─────────────────────────────────────────────────
  showDetailModal = false;
  showDeleteModal = false;
  showStatusModal = false;
  selectedRow: ReportRow | null = null;
  newStatut:   Statut | ''      = '';

  // ── Exposed enums ──────────────────────────────────────────
  readonly Statut = Statut;

  readonly kindOptions: { label: string; value: FilterKind; icon: string }[] = [
    { label: 'Tout',         value: 'ALL',         icon: 'dashboard'           },
    { label: 'Crises',       value: 'Crise',        icon: 'local_fire_department'},
    { label: 'Offres',       value: 'Offre',        icon: 'volunteer_activism'  },
    { label: 'Demandes',     value: 'Demande',      icon: 'emergency'           },
    { label: 'Informations', value: 'Information',  icon: 'info'                },
  ];

  readonly statutOptions: { label: string; value: FilterStatut }[] = [
    { label: 'Tous statuts',  value: 'ALL'             },
    { label: 'Non traitée',   value: Statut.NON_TRAITEE},
    { label: 'En cours',      value: Statut.EN_COURS   },
    { label: 'Traitée',       value: Statut.TRAITEE    },
    { label: 'Disponible',    value: Statut.DISPONIBLE },
    { label: 'Indisponible',  value: Statut.INDISPONIBLE},
  ];

  readonly editableStatuts: { label: string; value: Statut }[] = [
    { label: 'Non traitée',  value: Statut.NON_TRAITEE  },
    { label: 'En cours',     value: Statut.EN_COURS     },
    { label: 'Traitée',      value: Statut.TRAITEE      },
    { label: 'Disponible',   value: Statut.DISPONIBLE   },
    { label: 'Indisponible', value: Statut.INDISPONIBLE },
  ];

  constructor(
    private crisisService:      CrisisService,
    private offerService:       OfferService,
    private requestService:     RequestService,
    private informationService: InformationService,
  ) {}

  ngOnInit():    void { this.loadAll(); }
  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  // ────────────────────────────────────────────────────────────────────────────
  // LOAD
  // ────────────────────────────────────────────────────────────────────────────

  loadAll(): void {
    this.isLoading = true;
    forkJoin({
      crises:       this.crisisService.getAll(),
      offres:       this.offerService.getAll(),
      demandes:     this.requestService.getAll(),
      informations: this.informationService.getAll(),
    })
    .pipe(takeUntil(this.destroy$))
    .subscribe({
      next: ({ crises, offres, demandes, informations }) => {
        this.rawCrises       = crises;
        this.rawOffres       = offres;
        this.rawDemandes     = demandes;
        this.rawInformations = informations;
        this.buildRows();
        this.isLoading = false;
      },
      error: () => {
        this.showError('Impossible de charger les signalements.');
        this.isLoading = false;
      },
    });
  }

  // ────────────────────────────────────────────────────────────────────────────
  // BUILD UNIFIED ROWS
  // ────────────────────────────────────────────────────────────────────────────

  private buildRows(): void {
    const criseRows: ReportRow[] = this.rawCrises.map(c => ({
      id:        c.id,
      kind:      'Crise',
      titre:     c.nom,
      contact:   '—',
      email:     '—',
      telephone: null,
      statut:    (c.statut ?? Statut.NON_TRAITEE) as Statut,
      date:      c.date_debut,
      dateExp:   c.date_fin,
      crise:     c.id,
      auteur:    c.auteur,
      latitude:  c.latitude ?? null,
      longitude: c.longitude ?? null,
      photo:     c.photo ?? null,
      _raw:      c,
    }));

    const offreRows: ReportRow[] = this.rawOffres.map(o => ({
      id:        o.id,
      kind:      'Offre',
      titre:     o.titre,
      contact:   `${o.prenom_offre} ${o.nom_offre}`,
      email:     o.email_offre,
      telephone: null,
      statut:    o.statut,
      date:      o.date_creation,
      dateExp:   o.date_expiration,
      crise:     o.crise,
      auteur:    o.auteur,
      latitude:  o.latitude ?? null,
      longitude: o.longitude ?? null,
      photo:     o.photo,
      _raw:      o,
    }));

    const demandeRows: ReportRow[] = this.rawDemandes.map(d => ({
      id:        d.id,
      kind:      'Demande',
      titre:     d.titre,
      contact:   `${d.prenom_demande} ${d.nom_demande}`,
      email:     d.email_demande,
      telephone: d.telephone_demande,
      statut:    d.statut,
      date:      d.date_creation,
      dateExp:   d.date_expiration,
      crise:     d.crise,
      auteur:    d.auteur,
      latitude:  d.latitude ?? null,
      longitude: d.longitude ?? null,
      photo:     d.photo,
      _raw:      d,
    }));

    const infoRows: ReportRow[] = this.rawInformations.map(i => ({
      id:        i.id,
      kind:      'Information',
      titre:     i.titre,
      contact:   `${i.prenom_information} ${i.nom_information}`,
      email:     i.email_information,
      telephone: i.telephone_information,
      statut:    i.statut,
      date:      i.date_creation,
      dateExp:   i.date_expiration,
      crise:     i.crise,
      auteur:    i.auteur,
      latitude:  i.latitude ?? null,
      longitude: i.longitude ?? null,
      photo:     i.photo,
      _raw:      i,
    }));

    this.allRows = [...criseRows, ...offreRows, ...demandeRows, ...infoRows];
    this.applyFilters();
  }

  // ────────────────────────────────────────────────────────────────────────────
  // FILTER / SORT / PAGINATE
  // ────────────────────────────────────────────────────────────────────────────

  applyFilters(): void {
    let list = [...this.allRows];

    // Kind filter
    if (this.filterKind !== 'ALL') {
      list = list.filter(r => r.kind === this.filterKind);
    }

    // Statut filter
    if (this.filterStatut !== 'ALL') {
      list = list.filter(r => r.statut === this.filterStatut);
    }

    // Search
    const q = this.searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(r =>
        r.titre?.toLowerCase().includes(q)     ||
        r.contact?.toLowerCase().includes(q)   ||
        r.email?.toLowerCase().includes(q)     ||
        r.telephone?.toLowerCase().includes(q) ||
        r.kind?.toLowerCase().includes(q)
      );
    }

    // Sort
    list.sort((a, b) => {
      let va: any = a[this.sortField] ?? '';
      let vb: any = b[this.sortField] ?? '';
      if (typeof va === 'string') va = va.toLowerCase();
      if (typeof vb === 'string') vb = vb.toLowerCase();
      if (va < vb) return this.sortAsc ? -1 :  1;
      if (va > vb) return this.sortAsc ?  1 : -1;
      return 0;
    });

    this.filteredRows = list;
    this.totalPages   = Math.max(1, Math.ceil(list.length / this.pageSize));
    this.currentPage  = Math.min(this.currentPage, this.totalPages);
    this.paginate();
  }

  private paginate(): void {
    const start   = (this.currentPage - 1) * this.pageSize;
    this.pagedRows = this.filteredRows.slice(start, start + this.pageSize);
  }

  setSort(field: SortField): void {
    if (this.sortField === field) this.sortAsc = !this.sortAsc;
    else { this.sortField = field; this.sortAsc = true; }
    this.applyFilters();
  }

  changePage(p: number): void {
    if (p < 1 || p > this.totalPages) return;
    this.currentPage = p;
    this.paginate();
  }

  resetFilters(): void {
    this.searchQuery   = '';
    this.filterKind    = 'ALL';
    this.filterStatut  = 'ALL';
    this.currentPage   = 1;
    this.applyFilters();
  }

  // ────────────────────────────────────────────────────────────────────────────
  // ACTIONS
  // ────────────────────────────────────────────────────────────────────────────

  openDetail(row: ReportRow): void {
    this.selectedRow    = row;
    this.showDetailModal = true;
  }

  openStatusEdit(row: ReportRow, event: Event): void {
    event.stopPropagation();
    this.selectedRow    = row;
    this.newStatut      = row.statut;
    this.showStatusModal = true;
  }

  submitStatus(): void {
    if (!this.selectedRow || !this.newStatut) return;
    this.isSaving = true;
    const id  = this.selectedRow.id;
    const obs = this.getUpdateObservable(this.selectedRow.kind, id, { statut: this.newStatut } as any);
    if (!obs) { this.isSaving = false; return; }
    obs.subscribe({
      next: () => {
        this.showSuccess('Statut mis à jour.');
        this.showStatusModal = false;
        this.isSaving        = false;
        this.loadAll();
      },
      error: () => { this.showError('Erreur lors de la mise à jour.'); this.isSaving = false; },
    });
  }

  openDelete(row: ReportRow, event: Event): void {
    event.stopPropagation();
    this.selectedRow    = row;
    this.showDeleteModal = true;
  }

  confirmDelete(): void {
    if (!this.selectedRow) return;
    const obs = this.getDeleteObservable(this.selectedRow.kind, this.selectedRow.id);
    if (!obs) return;
    obs.subscribe({
      next: () => {
        this.showSuccess('Signalement supprimé.');
        this.showDeleteModal = false;
        this.selectedRow     = null;
        this.loadAll();
      },
      error: () => this.showError('Erreur lors de la suppression.'),
    });
  }

  private getUpdateObservable(kind: ReportKind, id: string, data: any): Observable<any> {
    switch (kind) {
      case 'Crise':       return this.crisisService.update(id, data);
      case 'Offre':       return this.offerService.update(id, data);
      case 'Demande':     return this.requestService.update(id, data);
      case 'Information': return this.informationService.update(id, data);
    }
  }

  private getDeleteObservable(kind: ReportKind, id: string): Observable<any> {
    switch (kind) {
      case 'Crise':       return this.crisisService.delete(id);
      case 'Offre':       return this.offerService.delete(id);
      case 'Demande':     return this.requestService.delete(id);
      case 'Information': return this.informationService.delete(id);
    }
  }

  // ────────────────────────────────────────────────────────────────────────────
  // EXPORT CSV
  // ────────────────────────────────────────────────────────────────────────────

  exportCSV(): void {
    const rows = this.filteredRows;
    const headers = ['ID','Type','Titre','Contact','Email','Téléphone','Statut','Date','Date expiration','Latitude','Longitude','Crise','Auteur'];
    const lines = rows.map(r => [
      r.id, r.kind, r.titre, r.contact, r.email,
      r.telephone ?? '', r.statut,
      this.fmtDate(r.date), r.dateExp ? this.fmtDate(r.dateExp) : '',
      r.latitude ?? '', r.longitude ?? '',
      r.crise ?? '', r.auteur ?? '',
    ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));

    const csv = [headers.join(','), ...lines].join('\n');
    const a   = document.createElement('a');
    a.href    = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' }));
    a.download= `signalements_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  exportRow(row: ReportRow, event: Event): void {
    event.stopPropagation();
    const headers = ['ID','Type','Titre','Contact','Email','Téléphone','Statut','Date','Latitude','Longitude'];
    const values  = [row.id, row.kind, row.titre, row.contact, row.email,
                     row.telephone ?? '', row.statut, this.fmtDate(row.date),
                     row.latitude ?? '', row.longitude ?? ''];
    const csv = [headers.join(','), values.map(v => `"${v}"`).join(',')].join('\n');
    const a   = document.createElement('a');
    a.href    = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' }));
    a.download= `${row.kind}_${row.id.slice(0,8)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ────────────────────────────────────────────────────────────────────────────
  // HELPERS (template)
  // ────────────────────────────────────────────────────────────────────────────

  closeAll(): void {
    this.showDetailModal = this.showDeleteModal = this.showStatusModal = false;
    this.selectedRow = null;
    this.newStatut   = '';
  }

  kindIcon(kind: ReportKind): string {
    return ({ Crise: 'local_fire_department', Offre: 'volunteer_activism',
              Demande: 'emergency', Information: 'info' })[kind];
  }

  kindClass(kind: ReportKind): string {
    return ({ Crise: 'kind-crisis', Offre: 'kind-offer',
              Demande: 'kind-request', Information: 'kind-info' })[kind];
  }

  statutClass(s: Statut): string {
    return ({
      [Statut.NON_TRAITEE]:  'stat-urgent',
      [Statut.EN_COURS]:     'stat-encours',
      [Statut.TRAITEE]:      'stat-traitee',
      [Statut.DISPONIBLE]:   'stat-dispo',
      [Statut.INDISPONIBLE]: 'stat-indispo',
    })[s] ?? '';
  }

  statutLabel(s: Statut): string {
    return ({
      [Statut.NON_TRAITEE]:  'Non traitée',
      [Statut.EN_COURS]:     'En cours',
      [Statut.TRAITEE]:      'Traitée',
      [Statut.DISPONIBLE]:   'Disponible',
      [Statut.INDISPONIBLE]: 'Indisponible',
    })[s] ?? s;
  }

  sortIcon(f: SortField): string {
    if (this.sortField !== f) return 'unfold_more';
    return this.sortAsc ? 'expand_less' : 'expand_more';
  }

  minOf(a: number, b: number): number { return Math.min(a, b); }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day:'2-digit', month:'2-digit', year:'numeric' });
  }

  get pageNumbers(): number[] {
    const pages: number[] = [];
    const start = Math.max(1, this.currentPage - 2);
    const end   = Math.min(this.totalPages, this.currentPage + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }

  get countByKind(): Record<string, number> {
    return {
      ALL:         this.allRows.length,
      Crise:       this.rawCrises.length,
      Offre:       this.rawOffres.length,
      Demande:     this.rawDemandes.length,
      Information: this.rawInformations.length,
    };
  }

  isCrise(r: ReportRow['_raw']): r is Crise         { return 'nom'              in r; }
  isOffre(r: ReportRow['_raw']): r is Offre          { return 'prenom_offre'     in r; }
  isDemande(r: ReportRow['_raw']): r is Demande      { return 'prenom_demande'   in r; }
  isInfo(r: ReportRow['_raw']): r is Information     { return 'prenom_information' in r; }

  private showSuccess(msg: string): void {
    this.successMessage = msg;
    setTimeout(() => (this.successMessage = ''), 3500);
  }
  private showError(msg: string): void {
    this.errorMessage = msg;
    setTimeout(() => (this.errorMessage = ''), 5000);
  }
}