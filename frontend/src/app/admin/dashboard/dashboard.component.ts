import { Component, OnInit, OnDestroy } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { forkJoin, Subject, takeUntil } from 'rxjs';
import { CrisisService } from '../../services/crisis.service';
import { OfferService } from '../../services/offer.service';
import { RequestService } from '../../services/request.service';

interface StatCard {
  title: string;
  value: string;
  change: string;
  icon: string;
  color: 'primary' | 'secondary' | 'danger';
  loading?: boolean;
}

interface ChartData {
  series: { name: string; data: number[] }[];
  categories: string[];
}

enum FilterAction {
  All = 'all',
  Around = 'around',
  Week = 'week',
  Month = 'month',
  Quarter = 'quarter',
  HalfYear = 'half_year',
  Year = 'year'
}

interface FilterOptions {
  label: string;
  action: FilterAction;
}

interface DashboardStats {
  totalCrises: number;
  totalResources: number;
  totalNeeds: number;
  crisisChange: number;
  resourceChange: number;
  needChange: number;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
// export class DashboardComponent implements OnInit, OnDestroy {
//   private destroy$ = new Subject<void>();
  
//   currentFilter: FilterAction = FilterAction.Around;
//   isDropdownOpen = false;
//   isLineChartFullScreen = false;
//   isPieChartFullScreen = false;
//   isLoading = true;
//   errorMessage = '';

//   filterOptions: FilterOptions[] = [
//     { label: 'Tout', action: FilterAction.All },
//     { label: 'À proximité', action: FilterAction.Around },
//     { label: 'Cette semaine', action: FilterAction.Week },
//     { label: 'Ce mois', action: FilterAction.Month },
//     { label: 'Ce trimestre', action: FilterAction.Quarter },
//     { label: 'Ce semestre', action: FilterAction.HalfYear },
//     { label: 'Cette année', action: FilterAction.Year }
//   ];

//   stats: StatCard[] = [
//     {
//       title: 'Total crises',
//       value: '0',
//       change: '+0',
//       icon: 'local_fire_department',
//       color: 'primary',
//       loading: true
//     },
//     {
//       title: 'Total ressources',
//       value: '0',
//       change: '+0',
//       icon: 'groups',
//       color: 'secondary',
//       loading: true
//     },
//     {
//       title: 'Total besoins',
//       value: '0',
//       change: '+0',
//       icon: 'error',
//       color: 'danger',
//       loading: true
//     }
//   ];

//   lineChartData: ChartData = {
//     series: [],
//     categories: []
//   };

//   pieChartData: any = {
//     series: [],
//     labels: []
//   };

//   recentAnnouncements: any[] = [];

//   constructor(
//     private helpRequestService: RequestService,
//     private helpProposeService: OfferService,
//     private crisisService: CrisisService,
//     private router: Router
//   ) {}

//   ngOnInit(): void {
//     this.loadDashboardData();
//   }

//   ngOnDestroy(): void {
//     this.destroy$.next();
//     this.destroy$.complete();
//   }

//   loadDashboardData(): void {
//     this.isLoading = true;
//     this.errorMessage = '';

//     const filterParams = this.getFilterParams();

//     // Charger toutes les données en parallèle
//     forkJoin({
//       crisisStats: this.crisisService.getStats(filterParams),
//       // proposeStats: this.helpProposeService.getProposeStats(filterParams),
//       requestStats: this.helpRequestService.getStats(filterParams),
//       recentCrises: this.crisisService.getRecent(5)
//     })
//       .pipe(takeUntil(this.destroy$))
//       .subscribe({
//         next: (data) => {
//           this.updateStats(data);
//           this.updateCharts(data);
//           this.updateRecentAnnouncements(data.recentCrises);
//           this.isLoading = false;
//         },
//         error: (error) => {
//           console.error('Erreur lors du chargement des données:', error);
//           this.errorMessage = 'Impossible de charger les données du tableau de bord';
//           this.isLoading = false;
          
//           // Utiliser des données de secours
//           this.useFallbackData();
//         }
//       });
//   }

//   private getFilterParams(): any {
//     const now = new Date();
//     let startDate: Date;

//     switch (this.currentFilter) {
//       case FilterAction.Week:
//         startDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
//         break;
//       case FilterAction.Month:
//         startDate = new Date(now.getFullYear(), now.getMonth() - 1, now.getDate());
//         break;
//       case FilterAction.Quarter:
//         startDate = new Date(now.getFullYear(), now.getMonth() - 3, now.getDate());
//         break;
//       case FilterAction.HalfYear:
//         startDate = new Date(now.getFullYear(), now.getMonth() - 6, now.getDate());
//         break;
//       case FilterAction.Year:
//         startDate = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
//         break;
//       case FilterAction.Around:
//         return { radius: 50 }; // 50km de rayon
//       case FilterAction.All:
//       default:
//         return {};
//     }

//     return {
//       start_date: startDate.toISOString(),
//       end_date: now.toISOString()
//     };
//   }

//   private updateStats(data: any): void {
//     // Mise à jour des statistiques de crises
//     this.stats[0] = {
//       title: 'Total crises',
//       value: this.formatNumber(data.crisisStats.total || 0),
//       change: this.formatChange(data.crisisStats.change || 0),
//       icon: 'local_fire_department',
//       color: 'primary',
//       loading: false
//     };

//     // Mise à jour des statistiques de ressources
//     this.stats[1] = {
//       title: 'Total ressources',
//       value: this.formatNumber(data.proposeStats.total || 0),
//       change: this.formatChange(data.proposeStats.change || 0),
//       icon: 'groups',
//       color: 'secondary',
//       loading: false
//     };

//     // Mise à jour des statistiques de besoins
//     this.stats[2] = {
//       title: 'Total besoins',
//       value: this.formatNumber(data.requestStats.total || 0),
//       change: this.formatChange(data.requestStats.change || 0),
//       icon: 'error',
//       color: 'danger',
//       loading: false
//     };
//   }

//   private updateCharts(data: any): void {
//     // Graphique linéaire - évolution dans le temps
//     if (data.crisisStats.timeline) {
//       this.lineChartData = {
//         series: [
//           {
//             name: 'Crises',
//             data: data.crisisStats.timeline.map((item: any) => item.count)
//           },
//           {
//             name: 'Ressources',
//             data: data.proposeStats.timeline.map((item: any) => item.count)
//           },
//           {
//             name: 'Besoins',
//             data: data.requestStats.timeline.map((item: any) => item.count)
//           }
//         ],
//         categories: data.crisisStats.timeline.map((item: any) => item.date)
//       };
//     }

//     // Graphique circulaire - répartition par type
//     if (data.crisisStats.byType) {
//       this.pieChartData = {
//         series: data.crisisStats.byType.map((item: any) => item.count),
//         labels: data.crisisStats.byType.map((item: any) => item.type)
//       };
//     }
//   }

//   private updateRecentAnnouncements(crises: any[]): void {
//     this.recentAnnouncements = crises.map(crisis => ({
//       id: crisis.id,
//       title: crisis.type || 'Crise sans titre',
//       date: this.formatDate(crisis.createdAt),
//       status: this.mapCrisisStatus(crisis.status)
//     }));
//   }

//   private useFallbackData(): void {
//     // Données par défaut en cas d'erreur
//     this.stats = [
//       {
//         title: 'Total crises',
//         value: '0',
//         change: '+0',
//         icon: 'local_fire_department',
//         color: 'primary',
//         loading: false
//       },
//       {
//         title: 'Total ressources',
//         value: '0',
//         change: '+0',
//         icon: 'groups',
//         color: 'secondary',
//         loading: false
//       },
//       {
//         title: 'Total besoins',
//         value: '0',
//         change: '+0',
//         icon: 'error',
//         color: 'danger',
//         loading: false
//       }
//     ];

//     this.recentAnnouncements = [];
//   }

//   private formatNumber(num: number): string {
//     if (num >= 1000000) {
//       return (num / 1000000).toFixed(1) + 'M';
//     } else if (num >= 1000) {
//       return (num / 1000).toFixed(1) + 'K';
//     }
//     return num.toString();
//   }

//   private formatChange(change: number): string {
//     const sign = change >= 0 ? '+' : '';
//     return `${sign}${this.formatNumber(Math.abs(change))}`;
//   }

//   private formatDate(date: any): string {
//     if (!date) return 'Date inconnue';
//     const d = new Date(date);
//     return d.toLocaleDateString('fr-FR');
//   }

//   private mapCrisisStatus(status: string): string {
//     const statusMap: { [key: string]: string } = {
//       'new': 'urgent',
//       'in_progress': 'en cours',
//       'resolved': 'résolu',
//       'closed': 'résolu'
//     };
//     return statusMap[status] || status;
//   }

//   getCardClass(color: string): string {
//     return `stat-card stat-card-${color}`;
//   }

//   toggleDropdown(): void {
//     this.isDropdownOpen = !this.isDropdownOpen;
//   }

//   toggleLineChartScreen(): void {
//     this.isLineChartFullScreen = !this.isLineChartFullScreen;
//     this.isPieChartFullScreen = false;
//   }

//   togglePieChartScreen(): void {
//     this.isPieChartFullScreen = !this.isPieChartFullScreen;
//     this.isLineChartFullScreen = false;
//   }

//   selectFilter(option: FilterOptions): void {
//     this.currentFilter = option.action;
//     this.isDropdownOpen = false;
//     this.loadDashboardData();
//   }

//   downloadLineChart(): void {
//     // TODO: Implémenter le téléchargement du graphique
//     console.log('Téléchargement du graphique linéaire');
//   }

//   downloadPieChart(): void {
//     // TODO: Implémenter le téléchargement du graphique
//     console.log('Téléchargement du graphique circulaire');
//   }

//   refreshData(): void {
//     this.loadDashboardData();
//   }
// }

export class DashboardComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  currentFilter: FilterAction = FilterAction.Around;
  isDropdownOpen = false;
  isLineChartFullScreen = false;
  isPieChartFullScreen = false;

  isLoading = true;
  errorMessage = '';
  stats: any[] = [];
  recentAnnouncements: any[] = [];

  filterOptions: FilterOptions[] = [
    { label: 'Tout', action: FilterAction.All },
    { label: 'À proximité', action: FilterAction.Around },
    { label: 'Cette semaine', action: FilterAction.Week },
    { label: 'Ce mois', action: FilterAction.Month },
    { label: 'Ce trimestre', action: FilterAction.Quarter },
    { label: 'Ce semestre', action: FilterAction.HalfYear },
    { label: 'Cette année', action: FilterAction.Year }
  ];

  // stats: StatCard[] = [
  //   {
  //     title: 'Total crises',
  //     value: '0',
  //     change: '+0',
  //     icon: 'local_fire_department',
  //     color: 'primary',
  //     loading: true
  //   },
  //   {
  //     title: 'Total ressources',
  //     value: '0',
  //     change: '+0',
  //     icon: 'groups',
  //     color: 'secondary',
  //     loading: true
  //   },
  //   {
  //     title: 'Total besoins',
  //     value: '0',
  //     change: '+0',
  //     icon: 'error',
  //     color: 'danger',
  //     loading: true
  //   }
  // ];

  lineChartData: ChartData = {
    series: [],
    categories: []
  };

  pieChartData: any = {
    series: [],
    labels: []
  };

  constructor(
    private criseService:   CrisisService,
    private offreService:   OfferService,
    private demandeService: RequestService
  ) {}

  ngOnInit(): void { this.loadDashboardData(); }
  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  loadDashboardData(): void {
    this.isLoading = true;
    this.errorMessage = '';

    forkJoin({
      crisisStats:   this.criseService.getStats(),     // GET /api/crises/stats/
      demandeStats:  this.demandeService.getStats(),   // GET /api/demandes/stats/
      ressourceStats:this.offreService.getStats(),     // GET /api/ressources/stats/
      recentCrises:  this.criseService.getRecent(5)    // GET /api/crises/?ordering=-date_debut&limit=5
    })
    .pipe(takeUntil(this.destroy$))
    .subscribe({
      next: data => {
        this.stats = [
          {
            title:  'Total crises',
            value:  this.fmt(data.crisisStats.total),
            change: this.fmtChange(data.crisisStats.change),
            icon:   'local_fire_department',
            color:  'primary'
          },
          {
            title:  'Total besoins',
            value:  this.fmt(data.demandeStats.total),
            change: this.fmtChange(data.demandeStats.change),
            icon:   'help',
            color:  'danger'
          }
        ];
        this.recentAnnouncements = data.recentCrises.map(c => ({
          id:     c.id,
          title:  c.nom,                                   // ← "nom" Django, pas "name"
          date:   c.date_debut ? new Date(c.date_debut).toLocaleDateString('fr-FR') : '—',
          status: c.date_fin ? 'Terminée' : 'En cours'
        }));
        this.isLoading = false;
      },
      error: err => {
        this.errorMessage = 'Impossible de charger les données';
        this.isLoading = false;
        console.error(err);
      }
    });
  }

  private fmt(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  }

  private fmtChange(n: number): string {
    return (n >= 0 ? '+' : '') + this.fmt(Math.abs(n));
  }

   private mapCrisisStatus(status: string): string {
    const statusMap: { [key: string]: string } = {
      'new': 'urgent',
      'in_progress': 'en cours',
      'resolved': 'résolu',
      'closed': 'résolu'
    };
    return statusMap[status] || status;
  }

  getCardClass(color: string): string {
    return `stat-card stat-card-${color}`;
  }

  toggleDropdown(): void {
    this.isDropdownOpen = !this.isDropdownOpen;
  }

  toggleLineChartScreen(): void {
    this.isLineChartFullScreen = !this.isLineChartFullScreen;
    this.isPieChartFullScreen = false;
  }

  togglePieChartScreen(): void {
    this.isPieChartFullScreen = !this.isPieChartFullScreen;
    this.isLineChartFullScreen = false;
  }

  selectFilter(option: FilterOptions): void {
    this.currentFilter = option.action;
    this.isDropdownOpen = false;
    this.loadDashboardData();
  }

  downloadLineChart(): void {
    // TODO: Implémenter le téléchargement du graphique
    console.log('Téléchargement du graphique linéaire');
  }

  downloadPieChart(): void {
    // TODO: Implémenter le téléchargement du graphique
    console.log('Téléchargement du graphique circulaire');
  }

  refreshData(): void { this.loadDashboardData(); }
}

