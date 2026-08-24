import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { forkJoin, Observable, Subject, takeUntil } from 'rxjs';

import { CrisisService }  from '../../services/crisis.service';
import { OfferService }   from '../../services/offer.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';

import { Crisis }       from '../../shared/models/crisis.model';
import { Offer }       from '../../shared/models/offer.model';
import { Request }     from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { Status }      from '../../shared/models/status.model';

// ── Unified row displayed in the table ───────────────────────────────────────

export type ReportKind = 'Crisis' | 'Offer' | 'Request' | 'Information';

export interface ReportRow {
  id:           string;
  kind:         ReportKind;
  title:        string;
  contact:      string;        // first_name + last_name
  email:        string;
  telephone:    string | null;
  status:       Status;
  date:         string;        // created_at / start_date
  dateExp:      string | null;
  crisis:        string | null; // UUID
  author:       string | null;
  latitude:     number | null;
  longitude:    number | null;
  photo:        string | null;
  // raw originals for detail modal
  _raw:         Crisis | Offer | Request | Information;
}

// ─────────────────────────────────────────────────────────────────────────────

type FilterKind   = ReportKind | 'ALL';
type FilterStatus = Status     | 'ALL';
type SortField    = 'title' | 'kind' | 'status' | 'date' | 'contact';

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
  rawCrises:       Crisis[]       = [];
  rawOffers:       Offer[]       = [];
  rawRequests:     Request[]     = [];
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
  filterStatus: FilterStatus = 'ALL';
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
  newStatus:   Status | ''      = '';

  // ── Exposed enums ──────────────────────────────────────────
  readonly Status = Status;

  readonly kindOptions: { label: string; value: FilterKind; icon: string }[] = [
    { label: 'Tout',         value: 'ALL',         icon: 'dashboard'           },
    { label: 'Crises',       value: 'Crisis',        icon: 'local_fire_department'},
    { label: 'Offres',       value: 'Offer',        icon: 'volunteer_activism'  },
    { label: 'Demandes',     value: 'Request',      icon: 'emergency'           },
    { label: 'Informations', value: 'Information',  icon: 'info'                },
  ];

  readonly statusOptions: { label: string; value: FilterStatus }[] = [
    { label: 'Tous statuts',  value: 'ALL'             },
    { label: 'Non traitée',   value: Status.UNPROCESSED},
    { label: 'En cours',      value: Status.IN_PROGRESS   },
    { label: 'Traitée',       value: Status.PROCESSED    },
    { label: 'Disponible',    value: Status.AVAILABLE },
    { label: 'Indisponible',  value: Status.UNAVAILABLE},
  ];

  readonly editableStatuses: { label: string; value: Status }[] = [
    { label: 'Non traitée',  value: Status.UNPROCESSED  },
    { label: 'En cours',     value: Status.IN_PROGRESS     },
    { label: 'Traitée',      value: Status.PROCESSED      },
    { label: 'Disponible',   value: Status.AVAILABLE   },
    { label: 'Indisponible', value: Status.UNAVAILABLE },
  ];

  constructor(
    private route: ActivatedRoute,
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
        this.rawOffers       = offres;
        this.rawRequests     = demandes;
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
    const crisisRows: ReportRow[] = this.rawCrises.map(c => ({
      id:        c.id,
      kind:      'Crisis',
      title:     c.name,
      contact:   '—',
      email:     '—',
      telephone: null,
      status:    (c.status ?? Status.UNPROCESSED) as Status,
      date:      c.start_date,
      dateExp:   c.end_date,
      crisis:     c.id,
      author:    c.author,
      latitude:  c.latitude ?? null,
      longitude: c.longitude ?? null,
      photo:     c.photo ?? null,
      _raw:      c,
    }));

    const offerRows: ReportRow[] = this.rawOffers.map(o => ({
      id:        o.id,
      kind:      'Offer',
      title:     o.title,
      contact:   `${o.first_name_offer} ${o.last_name_offer}`,
      email:     o.email_offer,
      telephone: null,
      status:    o.status,
      date:      o.created_at,
      dateExp:   o.expires_at,
      crisis:     o.crisis,
      author:    o.author,
      latitude:  o.latitude ?? null,
      longitude: o.longitude ?? null,
      photo:     o.photo,
      _raw:      o,
    }));

    const requestRows: ReportRow[] = this.rawRequests.map(d => ({
      id:        d.id,
      kind:      'Request',
      title:     d.title,
      contact:   `${d.first_name_request} ${d.last_name_request}`,
      email:     d.email_request,
      telephone: d.phone_request,
      status:    d.status,
      date:      d.created_at,
      dateExp:   d.expires_at,
      crisis:     d.crisis,
      author:    d.author,
      latitude:  d.latitude ?? null,
      longitude: d.longitude ?? null,
      photo:     d.photo,
      _raw:      d,
    }));

    const infoRows: ReportRow[] = this.rawInformations.map(i => ({
      id:        i.id,
      kind:      'Information',
      title:     i.title,
      contact:   `${i.first_name_information} ${i.last_name_information}`,
      email:     i.email_information,
      telephone: i.phone_information,
      status:    i.status,
      date:      i.created_at,
      dateExp:   i.expires_at,
      crisis:     i.crisis,
      author:    i.author,
      latitude:  i.latitude ?? null,
      longitude: i.longitude ?? null,
      photo:     i.photo,
      _raw:      i,
    }));

    this.allRows = [...crisisRows, ...offerRows, ...requestRows, ...infoRows];
    this.applyFilters();

    const targetId = this.route.snapshot.queryParamMap.get('id');
    const target = targetId ? this.allRows.find(r => r.id === targetId) : null;
    if (target) this.openDetail(target);
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
    if (this.filterStatus !== 'ALL') {
      list = list.filter(r => r.status === this.filterStatus);
    }

    // Search
    const q = this.searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(r =>
        r.title?.toLowerCase().includes(q)     ||
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
    this.filterStatus  = 'ALL';
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
    this.newStatus      = row.status;
    this.showStatusModal = true;
  }

  submitStatus(): void {
    if (!this.selectedRow || !this.newStatus) return;
    this.isSaving = true;
    const id  = this.selectedRow.id;
    const obs = this.getUpdateObservable(this.selectedRow.kind, id, { status: this.newStatus } as any);
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
      case 'Crisis':       return this.crisisService.update(id, data);
      case 'Offer':       return this.offerService.update(id, data);
      case 'Request':     return this.requestService.update(id, data);
      case 'Information': return this.informationService.update(id, data);
    }
  }

  private getDeleteObservable(kind: ReportKind, id: string): Observable<any> {
    switch (kind) {
      case 'Crisis':       return this.crisisService.delete(id);
      case 'Offer':       return this.offerService.delete(id);
      case 'Request':     return this.requestService.delete(id);
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
      r.id, r.kind, r.title, r.contact, r.email,
      r.telephone ?? '', r.status,
      this.fmtDate(r.date), r.dateExp ? this.fmtDate(r.dateExp) : '',
      r.latitude ?? '', r.longitude ?? '',
      r.crisis ?? '', r.author ?? '',
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
    const values  = [row.id, row.kind, row.title, row.contact, row.email,
                     row.telephone ?? '', row.status, this.fmtDate(row.date),
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
    this.newStatus   = '';
  }

  kindIcon(kind: ReportKind): string {
    return ({ Crisis: 'local_fire_department', Offer: 'volunteer_activism',
              Request: 'emergency', Information: 'info' })[kind];
  }

  kindClass(kind: ReportKind): string {
    return ({ Crisis: 'kind-crisis', Offer: 'kind-offer',
              Request: 'kind-request', Information: 'kind-info' })[kind];
  }

  statusClass(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'stat-urgent',
      [Status.IN_PROGRESS]:     'stat-encours',
      [Status.PROCESSED]:      'stat-traitee',
      [Status.AVAILABLE]:   'stat-dispo',
      [Status.UNAVAILABLE]: 'stat-indispo',
    })[s] ?? '';
  }

  statusLabel(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'Non traitée',
      [Status.IN_PROGRESS]:     'En cours',
      [Status.PROCESSED]:      'Traitée',
      [Status.AVAILABLE]:   'Disponible',
      [Status.UNAVAILABLE]: 'Indisponible',
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
      Crisis:       this.rawCrises.length,
      Offer:       this.rawOffers.length,
      Request:     this.rawRequests.length,
      Information: this.rawInformations.length,
    };
  }

  isCrisis(r: ReportRow['_raw']): r is Crisis         { return 'name'              in r; }
  isOffer(r: ReportRow['_raw']): r is Offer          { return 'first_name_offer'     in r; }
  isDemande(r: ReportRow['_raw']): r is Request      { return 'first_name_request'   in r; }
  isInfo(r: ReportRow['_raw']): r is Information     { return 'first_name_information' in r; }

  private showSuccess(msg: string): void {
    this.successMessage = msg;
    setTimeout(() => (this.successMessage = ''), 3500);
  }
  private showError(msg: string): void {
    this.errorMessage = msg;
    setTimeout(() => (this.errorMessage = ''), 5000);
  }
}