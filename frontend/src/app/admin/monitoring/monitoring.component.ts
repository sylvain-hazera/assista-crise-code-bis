import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { environment } from '../../../environments/environment';

/** Tableau de bord Grafana (demande utilisateur du 19/10), administrateurs uniquement.
 * Grafana est servi par le site lui-même sous /grafana/ : la page demande d'abord au backend
 * un cookie d'accès (voir core/grafana_acces.py) -- une iframe ne transmet pas le jeton JWT --
 * puis affiche le tableau de bord. */
@Component({
  selector: 'app-monitoring',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './monitoring.component.html',
  styleUrls: ['./monitoring.component.scss'],
})
export class MonitoringComponent implements OnInit {
  static readonly TABLEAU_DE_BORD = '/grafana/d/assista-overview/assista-crise-overview?orgId=1';

  urlIframe: SafeResourceUrl | null = null;
  errorMessage = '';
  readonly urlPleinEcran = MonitoringComponent.TABLEAU_DE_BORD;

  constructor(private http: HttpClient, private sanitizer: DomSanitizer) {}

  ngOnInit(): void {
    this.http.post(`${environment.apiUrl}/monitoring/grafana-session/`, {}, { withCredentials: true }).subscribe({
      // URL constante du même site, jamais issue d'une saisie : seul cas où contourner
      // l'assainissement d'Angular est sûr.
      next: () => this.urlIframe = this.sanitizer.bypassSecurityTrustResourceUrl(`${MonitoringComponent.TABLEAU_DE_BORD}&kiosk`),
      error: () => this.errorMessage = "Accès au monitoring refusé : réservé aux administrateurs de la plateforme.",
    });
  }
}
