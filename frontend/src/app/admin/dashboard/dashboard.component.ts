import { Component, OnInit } from '@angular/core';

interface StatCard {
  title: string;
  value: string;
  change: string;
  icon: string;
  color: 'primary' | 'secondary' | 'danger';
}

interface ChartData {
  series: { name: string; data: number[] }[];
  categories: string[];
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class DashboardComponent implements OnInit {
  stats: StatCard[] = [
    {
      title: 'Total crises',
      value: '21 324',
      change: '+2 031',
      icon: 'local_fire_department',
      color: 'primary'
    },
    {
      title: 'Total ressources',
      value: '21 324',
      change: '+2 031',
      icon: 'groups',
      color: 'secondary'
    },
    {
      title: 'Total besoins',
      value: '21 324',
      change: '+2 031',
      icon: 'error',
      color: 'danger'
    }
  ];

  recentAnnouncements: any[] = [
    { id: 1, title: 'Inondation à Paris', date: '2024-01-15', status: 'urgent' },
    { id: 2, title: 'Incendie Lyon', date: '2024-01-14', status: 'en cours' },
    { id: 3, title: 'Accident A7', date: '2024-01-13', status: 'résolu' }
  ];

  ngOnInit(): void {
    // Initialisation des données
  }

  getCardClass(color: string): string {
    return `stat-card stat-card-${color}`;
  }
}