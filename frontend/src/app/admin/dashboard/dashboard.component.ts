import { Component, OnInit, OnDestroy } from '@angular/core';
import { RouterLink } from '@angular/router';
import { CommonModule } from '@angular/common';
import { Subject, takeUntil } from 'rxjs';
import { DashboardStatsService, DashboardStats, DashboardFilter } from '../../services/dashboard-stats.service';

// ── Types internes ────────────────────────────────────────────────────────────

interface StatCard {
  title: string;
  value: string;
  change: string;
  changePositive: boolean;
  icon: string;
  color: 'crisis' | 'offer' | 'request' | 'information' | 'benevole';
  loading: boolean;
}

/** Chiffre brut (pas de delta) pour la 6ᵉ fenêtre miniature nationale. */
interface NationalFigure {
  title: string;
  value: string;
  icon: string;
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

  // ── Processed data (dérivée directement de la réponse du backend) ──────
  stats:              StatCard[]    = this.emptyStats();
  dayPoints:          DayPoint[]    = [];
  pieSlices:          PieSlice[]    = [];
  recentItems:        RecentItem[]  = [];
  lineMax             = 1;
  totalItems          = 0;
  crisesTotal         = 0;
  nationalFigures:    NationalFigure[] = [];
  isZoneScoped        = false;

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

  constructor(private dashboardStatsService: DashboardStatsService) {}

  ngOnInit(): void  { this.loadAll(); }
  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  // ────────────────────────────────────────────────────────────────────────────
  // DATA LOADING
  // ────────────────────────────────────────────────────────────────────────────

  loadAll(): void {
    this.isLoading    = true;
    this.errorMessage = '';

    this.dashboardStatsService.getStats(this.currentFilter as DashboardFilter)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.process(data);
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
  // PROCESSING
  // ────────────────────────────────────────────────────────────────────────────

  private process(data: DashboardStats): void {
    this.totalItems  = data.total_items;
    this.crisesTotal = data.totals.crises;
    this.isZoneScoped = data.is_zone_scoped;
    this.buildStats(data);
    this.buildNational(data);
    this.buildLineChart(data.day_points);
    this.buildPieChart(data.pie);
    this.buildRecentItems(data.recent_items);
  }

  // ── Stat cards ────────────────────────────────────────────

  private buildStats(data: DashboardStats): void {
    const delta = (cur: number, old: number): string => {
      if (old === 0) return cur > 0 ? '+100%' : '0%';
      const p = ((cur - old) / old) * 100;
      return `${p >= 0 ? '+' : ''}${p.toFixed(0)}%`;
    };

    this.stats = [
      {
        title: 'Crises',           value: this.fmt(data.stats.crises),
        change: delta(data.stats.crises,   data.previous.crises),
        changePositive: data.stats.crises   <= data.previous.crises,   // fewer crises = good
        icon: 'local_fire_department', color: 'crisis',   loading: false,
      },
      {
        title: 'Ressources',       value: this.fmt(data.stats.offres),
        change: delta(data.stats.offres,   data.previous.offres),
        changePositive: data.stats.offres   >= data.previous.offres,
        icon: 'volunteer_activism',    color: 'offer',    loading: false,
      },
      {
        title: 'Besoins',          value: this.fmt(data.stats.demandes),
        change: delta(data.stats.demandes, data.previous.demandes),
        changePositive: data.stats.demandes >= data.previous.demandes,
        icon: 'emergency',             color: 'request',  loading: false,
      },
      {
        title: 'Signalements',     value: this.fmt(data.stats.signalements),
        change: delta(data.stats.signalements, data.previous.signalements),
        changePositive: data.stats.signalements <= data.previous.signalements,   // moins de signalements = mieux
        icon: 'campaign',              color: 'information', loading: false,
      },
      {
        title: 'Bénévoles',        value: this.fmt(data.stats.benevoles),
        change: delta(data.stats.benevoles, data.previous.benevoles),
        changePositive: data.stats.benevoles >= data.previous.benevoles,
        icon: 'groups',                 color: 'benevole', loading: false,
      },
    ];
  }

  // ── National (6ᵉ fenêtre miniature) ─────────────────────────

  private buildNational(data: DashboardStats): void {
    const n = data.national.stats;
    this.nationalFigures = [
      { title: 'Crises',       value: this.fmt(n.crises),       icon: 'local_fire_department' },
      { title: 'Ressources',   value: this.fmt(n.offres),       icon: 'volunteer_activism' },
      { title: 'Besoins',      value: this.fmt(n.demandes),     icon: 'emergency' },
      { title: 'Signalements', value: this.fmt(n.signalements), icon: 'campaign' },
      { title: 'Bénévoles',    value: this.fmt(n.benevoles),    icon: 'groups' },
    ];
  }

  // ── Line chart ────────────────────────────────────────────

  private buildLineChart(points: DashboardStats['day_points']): void {
    const days: DayPoint[] = points.map(p => ({
      label:    new Date(p.date).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }),
      crises:   p.crises,
      offres:   p.offres,
      demandes: p.demandes,
    }));
    this.dayPoints = days;
    this.lineMax   = Math.max(1, ...days.map(d => Math.max(d.crises, d.offres, d.demandes)));
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

  private buildPieChart(slices: DashboardStats['pie']): void {
    const total = slices.reduce((s, sl) => s + sl.count, 0) || 1;

    // Build SVG arc paths (cx=100, cy=100, r=80)
    let angle = -90; // start at top
    this.pieSlices = slices.map((sl, i) => {
      const pct      = sl.count / total;
      const sweep    = pct * 360;
      const endAngle = angle + sweep;
      const path     = this.arcPath(100, 100, 75, angle, endAngle, pct > 0.999);
      angle = endAngle;
      return {
        label:   sl.type_display,
        count:   sl.count,
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

  private buildRecentItems(items: DashboardStats['recent_items']): void {
    this.recentItems = items.map(item => this.toItem(item));
  }

  private toItem(item: DashboardStats['recent_items'][number]): RecentItem {
    const statusMap: Record<string, { label: string; cls: string }> = {
      NON_TRAITEE:  { label: 'Urgent',      cls: 'status-urgent'   },
      EN_COURS:     { label: 'En cours',    cls: 'status-encours'  },
      TRAITEE:      { label: 'Traitée',     cls: 'status-traitee'  },
      DISPONIBLE:   { label: 'Disponible',  cls: 'status-dispo'    },
      INDISPONIBLE: { label: 'Indisponible',cls: 'status-indispo'  },
    };
    const s = statusMap[item.status] ?? { label: item.status, cls: '' };
    return {
      id: item.id, title: item.title, type: item.type, status: s.label, statusClass: s.cls,
      date: new Date(item.date).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }),
    };
  }

  // ────────────────────────────────────────────────────────────────────────────
  // TEMPLATE HELPERS
  // ────────────────────────────────────────────────────────────────────────────

  selectFilter(action: FilterAction): void {
    this.currentFilter  = action;
    this.isDropdownOpen = false;
    this.loadAll();
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
      { title: 'Signalements', value: '—', change: '', changePositive: true, icon: 'campaign',             color: 'information', loading },
      { title: 'Bénévoles',  value: '—', change: '', changePositive: true,  icon: 'groups',                color: 'benevole', loading },
    ];
  }
}
