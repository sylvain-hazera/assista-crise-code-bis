import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';

interface Report {
  id: string;
  type: 'crise' | 'besoin' | 'offre' | 'information';
  title: string;
  description: string;
  location: string;
  status: 'nouveau' | 'en_cours' | 'traité' | 'rejeté';
  priority: 'basse' | 'moyenne' | 'haute' | 'urgente';
  createdAt: Date;
  reporter: string;
  assignedTo?: string;
}

@Component({
  selector: 'app-reporting',
  standalone: true,
  imports: [CommonModule, RouterLink, FormsModule],
  templateUrl: './reporting.component.html',
  styleUrls: ['./reporting.component.scss']
})
export class ReportingComponent implements OnInit {
  reports: Report[] = [];
  filteredReports: Report[] = [];
  
  filterType: string = 'tous';
  filterStatus: string = 'tous';
  filterPriority: string = 'tous';
  searchTerm: string = '';
  
  isLoading = false;
  selectedReport: Report | null = null;
  showDetailModal = false;

  // Stats
  stats = {
    total: 0,
    nouveau: 0,
    en_cours: 0,
    traité: 0
  };

  ngOnInit(): void {
    this.loadReports();
  }

  loadReports(): void {
    this.isLoading = true;
    
    // Mock data - à remplacer par un service
    setTimeout(() => {
      this.reports = [
        {
          id: 'RPT-001',
          type: 'crise',
          title: 'Inondation majeure',
          description: 'Inondation dans le quartier nord suite aux fortes pluies',
          location: 'Quartier Nord, Paris',
          status: 'nouveau',
          priority: 'urgente',
          createdAt: new Date('2025-02-10T08:30:00'),
          reporter: 'Jean Dupont'
        },
        {
          id: 'RPT-002',
          type: 'besoin',
          title: 'Besoin de vivres',
          description: 'Famille de 5 personnes sans nourriture',
          location: '15 Rue de la Paix',
          status: 'en_cours',
          priority: 'haute',
          createdAt: new Date('2025-02-10T09:15:00'),
          reporter: 'Marie Martin',
          assignedTo: 'Équipe A'
        },
        {
          id: 'RPT-003',
          type: 'offre',
          title: 'Hébergement disponible',
          description: '3 chambres disponibles pour familles',
          location: '42 Avenue Victor Hugo',
          status: 'traité',
          priority: 'moyenne',
          createdAt: new Date('2025-02-09T14:20:00'),
          reporter: 'Pierre Dubois'
        }
      ];
      
      this.filteredReports = [...this.reports];
      this.updateStats();
      this.isLoading = false;
    }, 500);
  }

  updateStats(): void {
    this.stats.total = this.reports.length;
    this.stats.nouveau = this.reports.filter(r => r.status === 'nouveau').length;
    this.stats.en_cours = this.reports.filter(r => r.status === 'en_cours').length;
    this.stats.traité = this.reports.filter(r => r.status === 'traité').length;
  }

  applyFilters(): void {
    this.filteredReports = this.reports.filter(report => {
      const matchType = this.filterType === 'tous' || report.type === this.filterType;
      const matchStatus = this.filterStatus === 'tous' || report.status === this.filterStatus;
      const matchPriority = this.filterPriority === 'tous' || report.priority === this.filterPriority;
      const matchSearch = !this.searchTerm || 
        report.title.toLowerCase().includes(this.searchTerm.toLowerCase()) ||
        report.description.toLowerCase().includes(this.searchTerm.toLowerCase()) ||
        report.location.toLowerCase().includes(this.searchTerm.toLowerCase());
      
      return matchType && matchStatus && matchPriority && matchSearch;
    });
  }

  viewDetails(report: Report): void {
    this.selectedReport = report;
    this.showDetailModal = true;
  }

  updateStatus(report: Report, newStatus: string): void {
    report.status = newStatus as any;
    this.updateStats();
    // TODO: Appeler le service pour mettre à jour le backend
  }

  deleteReport(report: Report): void {
    if (confirm(`Êtes-vous sûr de vouloir supprimer le signalement ${report.id} ?`)) {
      this.reports = this.reports.filter(r => r.id !== report.id);
      this.applyFilters();
      this.updateStats();
      // TODO: Appeler le service pour supprimer du backend
    }
  }

  getPriorityClass(priority: string): string {
    const classes: { [key: string]: string } = {
      'basse': 'priority-low',
      'moyenne': 'priority-medium',
      'haute': 'priority-high',
      'urgente': 'priority-urgent'
    };
    return classes[priority] || '';
  }

  getStatusClass(status: string): string {
    const classes: { [key: string]: string } = {
      'nouveau': 'status-new',
      'en_cours': 'status-progress',
      'traité': 'status-done',
      'rejeté': 'status-rejected'
    };
    return classes[status] || '';
  }

  getTypeIcon(type: string): string {
    const icons: { [key: string]: string } = {
      'crise': 'local_fire_department',
      'besoin': 'help',
      'offre': 'volunteer_activism',
      'information': 'info'
    };
    return icons[type] || 'report';
  }

  exportReports(): void {
    // TODO: Implémenter l'export CSV
    console.log('Export des signalements');
  }
}