import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ActivatedRoute } from '@angular/router';
import { environment } from '../../../environments/environment';

/** Tableaux de bord Grafana, administrateurs uniquement : Monitoring (demande utilisateur du
 * 19/10), Supervision WAF et Fail2ban (20/10) -- un composant, le tableau de bord vient de la
 * route (data.grafana).
 * Grafana est servi par le site lui-même sous /grafana/ : la page demande d'abord au backend
 * un cookie d'accès (voir core/grafana_acces.py) -- une iframe ne transmet pas le jeton JWT --
 * puis affiche le tableau de bord. */
export interface TableauGrafana {
  titre: string;
  icone: string;
  chemin: string;   // sous /grafana/, sans paramètres
}

export const TABLEAUX_GRAFANA = {
  monitoring: { titre: 'Monitoring', icone: 'monitor_heart', chemin: '/grafana/d/assista-overview/assista-crise-overview' },
  waf: { titre: 'Supervision WAF', icone: 'shield', chemin: '/grafana/d/assista-waf/supervision-waf' },
  fail2ban: { titre: 'Fail2ban', icone: 'block', chemin: '/grafana/d/assista-fail2ban/fail2ban' },
} satisfies Record<string, TableauGrafana>;

@Component({
  selector: 'app-monitoring',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './monitoring.component.html',
  styleUrls: ['./monitoring.component.scss'],
})
export class MonitoringComponent implements OnInit {
  tableau: TableauGrafana = TABLEAUX_GRAFANA.monitoring;
  urlIframe: SafeResourceUrl | null = null;
  errorMessage = '';

  constructor(private http: HttpClient, private sanitizer: DomSanitizer, private route: ActivatedRoute) {}

  get urlPleinEcran(): string {
    return `${this.tableau.chemin}?orgId=1`;
  }

  ngOnInit(): void {
    this.tableau = this.route.snapshot.data['grafana'] ?? TABLEAUX_GRAFANA.monitoring;
    this.http.post(`${environment.apiUrl}/monitoring/grafana-session/`, {}, { withCredentials: true }).subscribe({
      // URL constante du même site (TABLEAUX_GRAFANA), jamais issue d'une saisie : seul cas où
      // contourner l'assainissement d'Angular est sûr.
      next: () => this.urlIframe = this.sanitizer.bypassSecurityTrustResourceUrl(`${this.urlPleinEcran}&kiosk`),
      error: () => this.errorMessage = "Accès au monitoring refusé : réservé aux administrateurs de la plateforme.",
    });
  }
}
