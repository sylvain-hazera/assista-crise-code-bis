import { Component, OnInit, OnDestroy } from '@angular/core';
import { RouterLink } from '@angular/router';
import { CommonModule } from '@angular/common';
import { forkJoin, Subject, takeUntil } from 'rxjs';
import { CrisisService } from '../../services/crisis.service';
import { OfferService } from '../../services/offer.service';
import { RequestService } from '../../services/request.service';
import { Crisis } from '../../shared/models/crisis.model';
import { Offer } from '../../shared/models/offer.model';
import { Request } from '../../shared/models/request.model';

// ── Types internes ────────────────────────────────────────────────────────────

interface StatCard {
  title: string;
  value: string;
  change: string;
  changePositive: boolean;
  icon: string;
  color: 'crisis' | 'offer' | 'request';
  loading: boolean;
}

interface DayPoint {
  label: string;       // "01/02"
  crises: number;
  offres: number;
  demandes: number;
}

interface PieSlice {
  label: string;
  count: number;
  percent: number;
  color: string;
  // SVG arc path
  path: string;
}

interface RecentItem {
  id: string;
  title: string;
  type: 'Crise' | 'Ressource' | 'Besoin';
  date: string;
  status: string;
  statusClass: string;
}

enum FilterAction {
  All      = 'all',
  Week     = 'week',
  Month    = 'month',
  Quarter  = 'quarter',
  HalfYear = 'half_year',
  Year     = 'year',
}

// ── Composant ─────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [RouterLink, CommonModule],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss'],
})
export class DashboardComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();
  protected readonly Math = Math;

  // ── State ──────────────────────────────────────────────────
  isLoading        = true;
  errorMessage     = '';
  isDropdownOpen   = false;
  currentFilter    = FilterAction.All;
  lineFullscreen   = false;
  pieFullscreen    = false;

  // ── Raw data ───────────────────────────────────────────────
  rawCrises:   Crisis[]   = [];
  rawOffers:   Offer[]   = [];
  rawRequests: Request[] = [];

  // ── Processed data ─────────────────────────────────────────
  stats:              StatCard[]    = this.emptyStats();
  dayPoints:          DayPoint[]    = [];
  pieSlices:          PieSlice[]    = [];
  recentItems:        RecentItem[]  = [];
  lineMax             = 1;

  // ── Config ─────────────────────────────────────────────────
  readonly filterOptions = [
    { label: 'Tout',         action: FilterAction.All      },
    { label: 'Cette semaine',action: FilterAction.Week     },
    { label: 'Ce mois',      action: FilterAction.Month    },
    { label: 'Ce trimestre', action: FilterAction.Quarter  },
    { label: 'Ce semestre',  action: FilterAction.HalfYear },
    { label: 'Cette année',  action: FilterAction.Year     },
  ];

  readonly PIE_COLORS = ['#ef4444','#f97316','#eab308','#22c55e','#3b82f6','#8b5cf6'];

  // SVG chart dimensions
  readonly CHART_W  = 700;
  readonly CHART_H  = 160;
  readonly CHART_X0 = 40;
  readonly CHART_Y0 = 10;

  constructor(
    private crisisService:  CrisisService,
    private offerService:   OfferService,
    private requestService: RequestService,
  ) {}

  ngOnInit(): void  { this.loadAll(); }
  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  // ────────────────────────────────────────────────────────────────────────────
  // DATA LOADING
  // ────────────────────────────────────────────────────────────────────────────

  loadAll(): void {
    this.isLoading    = true;
    this.errorMessage = '';

    forkJoin({
      crises:   this.crisisService.getAll(),
      offres:   this.offerService.getAll(),
      demandes: this.requestService.getAll(),
    })
    .pipe(takeUntil(this.destroy$))
    .subscribe({
      next: ({ crises, offres, demandes }) => {
        this.rawCrises   = crises;
        this.rawOffers   = offres;
        this.rawRequests = demandes;
        this.process();
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les données du tableau de bord.';
        this.isLoading    = false;
        this.stats        = this.emptyStats(false);
      },
    });
  }

  // ────────────────────────────────────────────────────────────────────────────
  // PROCESSING  (called on load + filter change)
  // ────────────────────────────────────────────────────────────────────────────

  private process(): void {
    const { crises, offres, demandes } = this.filtered();
    this.buildStats(crises, offres, demandes);
    this.buildLineChart(crises, offres, demandes);
    this.buildPieChart(crises);
    this.buildRecentItems(crises, offres, demandes);
  }

  // ── Filter ────────────────────────────────────────────────

  private filtered(): { crises: Crisis[]; offres: Offer[]; demandes: Request[] } {
    if (this.currentFilter === FilterAction.All) {
      return { crises: this.rawCrises, offres: this.rawOffers, demandes: this.rawRequests };
    }
    const start = this.filterStart();
    const now   = new Date();
    return {
      crises:   this.byDate(this.rawCrises,   start, now, 'start_date'),
      offres:   this.byDate(this.rawOffers,   start, now, 'created_at'),
      demandes: this.byDate(this.rawRequests, start, now, 'created_at'),
    };
  }

  private filterStart(): Date {
    const now = new Date();
    switch (this.currentFilter) {
      case FilterAction.Week:     return new Date(now.getTime() - 7  * 86400000);
      case FilterAction.Month:    return new Date(now.getFullYear(), now.getMonth() - 1,  now.getDate());
      case FilterAction.Quarter:  return new Date(now.getFullYear(), now.getMonth() - 3,  now.getDate());
      case FilterAction.HalfYear: return new Date(now.getFullYear(), now.getMonth() - 6,  now.getDate());
      case FilterAction.Year:     return new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
      default:                    return new Date(0);
    }
  }

  private byDate<T>(items: T[], start: Date, end: Date, field: keyof T): T[] {
    return items.filter(item => {
      const d = new Date((item[field] as unknown) as string);
      return !isNaN(d.getTime()) && d >= start && d <= end;
    });
  }

  // ── Stats cards ───────────────────────────────────────────

  private buildStats(crises: Crisis[], offres: Offer[], demandes: Request[]): void {
    const prev  = this.previousPeriod();
    const delta = (cur: number, old: number): string => {
      if (old === 0) return cur > 0 ? '+100%' : '0%';
      const p = ((cur - old) / old) * 100;
      return `${p >= 0 ? '+' : ''}${p.toFixed(0)}%`;
    };

    this.stats = [
      {
        title: 'Crises',           value: this.fmt(crises.length),
        change: delta(crises.length,   prev.crises),
        changePositive: crises.length   <= prev.crises,   // fewer crises = good
        icon: 'local_fire_department', color: 'crisis',   loading: false,
      },
      {
        title: 'Ressources',       value: this.fmt(offres.length),
        change: delta(offres.length,   prev.offres),
        changePositive: offres.length   >= prev.offres,
        icon: 'volunteer_activism',    color: 'offer',    loading: false,
      },
      {
        title: 'Besoins',          value: this.fmt(demandes.length),
        change: delta(demandes.length, prev.demandes),
        changePositive: demandes.length >= prev.demandes,
        icon: 'emergency',             color: 'request',  loading: false,
      },
    ];
  }

  private previousPeriod(): { crises: number; offres: number; demandes: number } {
    if (this.currentFilter === FilterAction.All) return { crises: 0, offres: 0, demandes: 0 };
    const now     = new Date();
    const curStart = this.filterStart();
    const dur     = now.getTime() - curStart.getTime();
    const prevEnd  = new Date(curStart.getTime() - 1);
    const prevStart= new Date(prevEnd.getTime() - dur);
    return {
      crises:   this.byDate(this.rawCrises,   prevStart, prevEnd, 'start_date').length,
      offres:   this.byDate(this.rawOffers,   prevStart, prevEnd, 'created_at').length,
      demandes: this.byDate(this.rawRequests, prevStart, prevEnd, 'created_at').length,
    };
  }

  // ── Line chart ────────────────────────────────────────────

  private buildLineChart(crises: Crisis[], offres: Offer[], demandes: Request[]): void {
    const days: DayPoint[] = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      days.push({
        label:    d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }),
        crises:   this.countOnDay(crises,   d, 'start_date'),
        offres:   this.countOnDay(offres,   d, 'created_at'),
        demandes: this.countOnDay(demandes, d, 'created_at'),
      });
    }
    this.dayPoints = days;
    this.lineMax   = Math.max(1, ...days.map(d => Math.max(d.crises, d.offres, d.demandes)));
  }

  private countOnDay<T>(items: T[], day: Date, field: keyof T): number {
    const key = day.toDateString();
    return items.filter(i => new Date((i[field] as unknown) as string).toDateString() === key).length;
  }

  /** Returns SVG polyline points string for a given series */
  linePoints(series: 'crises' | 'offres' | 'demandes'): string {
    if (!this.dayPoints.length) return '';
    const n  = this.dayPoints.length;
    const W  = this.CHART_W;
    const H  = this.CHART_H;
    const x0 = this.CHART_X0;
    const y0 = this.CHART_Y0;
    return this.dayPoints.map((d, i) => {
      const x = x0 + (i / (n - 1)) * W;
      const y = y0 + H - (d[series] / this.lineMax) * H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
  }

  /** X-axis label positions (show every 5 days) */
  get xLabels(): { x: number; label: string }[] {
    return this.dayPoints
      .map((d, i) => ({
        x: this.CHART_X0 + (i / (this.dayPoints.length - 1)) * this.CHART_W,
        label: d.label,
        show: i % 5 === 0 || i === this.dayPoints.length - 1,
      }))
      .filter(l => l.show);
  }

  /** Y-axis gridlines */
  get yLines(): { y: number; label: number }[] {
    const steps = 4;
    return Array.from({ length: steps + 1 }, (_, i) => {
      const frac = i / steps;
      return {
        y:     this.CHART_Y0 + this.CHART_H - frac * this.CHART_H,
        label: Math.round(frac * this.lineMax),
      };
    });
  }

  // ── Pie chart ─────────────────────────────────────────────

  private buildPieChart(crises: Crisis[]): void {
    const counts = new Map<string, number>();
    crises.forEach(c => {
      const t = c.type?.trim() || 'Non spécifié';
      counts.set(t, (counts.get(t) ?? 0) + 1);
    });

    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
    const total  = sorted.reduce((s, [, n]) => s + n, 0) || 1;

    // Build SVG arc paths (cx=100, cy=100, r=80)
    let angle = -90; // start at top
    this.pieSlices = sorted.map(([label, count], i) => {
      const pct      = count / total;
      const sweep    = pct * 360;
      const endAngle = angle + sweep;
      const path     = this.arcPath(100, 100, 75, angle, endAngle, pct > 0.999);
      angle = endAngle;
      return {
        label,
        count,
        percent: Math.round(pct * 100),
        color:   this.PIE_COLORS[i % this.PIE_COLORS.length],
        path,
      };
    });
  }

  private arcPath(cx: number, cy: number, r: number, startDeg: number, endDeg: number, full: boolean): string {
    if (full) {
      // Full circle: two half arcs
      return `M ${cx},${cy - r} A ${r},${r} 0 1,1 ${cx - 0.001},${cy - r} Z`;
    }
    const s  = (startDeg * Math.PI) / 180;
    const e  = (endDeg   * Math.PI) / 180;
    const x1 = cx + r * Math.cos(s);
    const y1 = cy + r * Math.sin(s);
    const x2 = cx + r * Math.cos(e);
    const y2 = cy + r * Math.sin(e);
    const la = endDeg - startDeg > 180 ? 1 : 0;
    return `M ${cx},${cy} L ${x1.toFixed(2)},${y1.toFixed(2)} A ${r},${r} 0 ${la},1 ${x2.toFixed(2)},${y2.toFixed(2)} Z`;
  }

  // ── Recent items ──────────────────────────────────────────

  private buildRecentItems(crises: Crisis[], offres: Offer[], demandes: Request[]): void {
    const all: RecentItem[] = [
      ...crises.map(c => this.toItem(c.id, c.name, 'Crise', c.start_date, c.status ?? 'NON_TRAITEE')),
      ...offres.map(o => this.toItem(o.id, o.title, 'Ressource', o.created_at, o.status)),
      ...demandes.map(d => this.toItem(d.id, d.title, 'Besoin', d.created_at, d.status)),
    ];
    this.recentItems = all
      .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
      .slice(0, 8);
  }

  private toItem(id: string, title: string, type: RecentItem['type'], date: string, status: string): RecentItem {
    const statusMap: Record<string, { label: string; cls: string }> = {
      NON_TRAITEE:  { label: 'Urgent',      cls: 'status-urgent'   },
      EN_COURS:     { label: 'En cours',    cls: 'status-encours'  },
      TRAITEE:      { label: 'Traitée',     cls: 'status-traitee'  },
      DISPONIBLE:   { label: 'Disponible',  cls: 'status-dispo'    },
      INDISPONIBLE: { label: 'Indisponible',cls: 'status-indispo'  },
    };
    const s = statusMap[status] ?? { label: status, cls: '' };
    return {
      id, title, type, status: s.label, statusClass: s.cls,
      date: new Date(date).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }),
    };
  }

  // ────────────────────────────────────────────────────────────────────────────
  // TEMPLATE HELPERS
  // ────────────────────────────────────────────────────────────────────────────

  selectFilter(action: FilterAction): void {
    this.currentFilter  = action;
    this.isDropdownOpen = false;
    this.process();
  }

  currentFilterLabel(): string {
    return this.filterOptions.find(o => o.action === this.currentFilter)?.label ?? 'Tout';
  }

  typeIcon(type: RecentItem['type']): string {
    return { Crise: 'local_fire_department', Ressource: 'volunteer_activism', Besoin: 'emergency' }[type];
  }

  typeClass(type: RecentItem['type']): string {
    return { Crise: 'tag-crisis', Ressource: 'tag-offer', Besoin: 'tag-request' }[type];
  }

  /** Route vers la fiche détail de l'item (crise : gestion dédiée ; ressource/besoin : signalements). */
  detailRoute(type: RecentItem['type']): string[] {
    return type === 'Crise' ? ['/admin/crises'] : ['/admin/signalements'];
  }

  // ── CSV export ────────────────────────────────────────────

  downloadLine(): void {
    const rows = ['Date,Crises,Ressources,Besoins',
      ...this.dayPoints.map(d => `${d.label},${d.crises},${d.offres},${d.demandes}`)];
    this.dl(rows.join('\n'), 'evolution.csv');
  }

  downloadPie(): void {
    const rows = ['Type,Nombre,Pourcentage',
      ...this.pieSlices.map(s => `${s.label},${s.count},${s.percent}%`)];
    this.dl(rows.join('\n'), 'types_crises.csv');
  }

  private dl(content: string, name: string): void {
    const a  = document.createElement('a');
    a.href   = URL.createObjectURL(new Blob([content], { type: 'text/csv' }));
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ── Utils ─────────────────────────────────────────────────

  private fmt(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
    return n.toString();
  }

  private emptyStats(loading = true): StatCard[] {
    return [
      { title: 'Crises',     value: '—', change: '', changePositive: false, icon: 'local_fire_department', color: 'crisis',   loading },
      { title: 'Ressources', value: '—', change: '', changePositive: true,  icon: 'volunteer_activism',    color: 'offer',    loading },
      { title: 'Besoins',    value: '—', change: '', changePositive: true,  icon: 'emergency',             color: 'request',  loading },
    ];
  }

  get totalItems(): number {
    return this.rawCrises.length + this.rawOffers.length + this.rawRequests.length;
  }
}