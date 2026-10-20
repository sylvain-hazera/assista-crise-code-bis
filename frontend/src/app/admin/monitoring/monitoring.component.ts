import { Component, OnDestroy, OnInit } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ActivatedRoute, Router } from '@angular/router';
import { environment } from '../../../environments/environment';

export interface OngletSupervision {
  id: string;
  label: string;
  icon: string;
  /** uid fixe du tableau, dans monitoring/grafana/dashboards/. */
  uid: string;
  /** Le tableau a la variable Grafana `monitoring` (conteneurs du profil monitoring). */
  conteneurs?: boolean;
}

export const ONGLETS_SUPERVISION: OngletSupervision[] = [
  { id: 'complet', label: 'Vue complète', icon: 'dashboard', uid: 'assista-overview', conteneurs: true },
  { id: 'sante', label: 'Santé du site', icon: 'monitor_heart', uid: 'assista-sante' },
  { id: 'metier', label: 'Métriques métier', icon: 'insights', uid: 'assista-metier' },
  { id: 'infra', label: 'Infrastructure', icon: 'dns', uid: 'assista-infra', conteneurs: true },
];

/** Renouvelle le jeton avant son expiration : Grafana le renvoie à chaque requête. */
const MARGE_RENOUVELLEMENT_S = 300;

type ErreurSupervision = 'refus' | 'non-configuree' | 'indisponible';

/** Tableaux Grafana en iframe, un onglet par tableau. Connexion par un jeton signé par le
 * backend (DOCUMENTATION.md, « Monitoring ») ; accès de secours par tunnel SSH si le site
 * est en panne. */
@Component({
  selector: 'app-monitoring',
  standalone: true,
  imports: [],
  templateUrl: './monitoring.component.html',
  styleUrl: './monitoring.component.scss'
})
export class MonitoringComponent implements OnInit, OnDestroy {
  readonly onglets = ONGLETS_SUPERVISION;
  onglet = ONGLETS_SUPERVISION[0];
  jeton: string | null = null;
  erreur: ErreurSupervision | null = null;
  /** Valeur de la variable Grafana `monitoring` : le frontend choisit une option, jamais la requête. */
  afficherMonitoring = false;
  url: SafeResourceUrl | null = null;
  urlBrute = '';
  private renouvellement?: ReturnType<typeof setTimeout>;

  constructor(
    private http: HttpClient,
    private sanitizer: DomSanitizer,
    private route: ActivatedRoute,
    private router: Router,
  ) {}

  ngOnInit(): void {
    const id = this.route.snapshot.queryParamMap.get('onglet');
    this.onglet = this.onglets.find(o => o.id === id) ?? this.onglets[0];
    this.chargerJeton();
  }

  ngOnDestroy(): void {
    clearTimeout(this.renouvellement);
  }

  choisir(onglet: OngletSupervision): void {
    this.onglet = onglet;
    // l'onglet dans l'URL : lien direct et favori possibles
    this.router.navigate([], { relativeTo: this.route, queryParams: { onglet: onglet.id }, replaceUrl: true });
    this.majUrl();
  }

  basculerMonitoring(afficher: boolean): void {
    this.afficherMonitoring = afficher;
    this.majUrl();
  }

  chargerJeton(): void {
    clearTimeout(this.renouvellement);
    this.http.post<{ token: string; expires_in: number }>(`${environment.apiUrl}/monitoring/grafana-token/`, {})
      .subscribe({
        next: ({ token, expires_in }) => {
          this.jeton = token;
          this.erreur = null;
          this.majUrl();
          const delai = Math.max(expires_in - MARGE_RENOUVELLEMENT_S, 30);
          this.renouvellement = setTimeout(() => this.chargerJeton(), delai * 1000);
        },
        error: (e: HttpErrorResponse) => {
          this.jeton = null;
          this.url = null;
          this.erreur = e.status === 403 ? 'refus' : e.status === 503 ? 'non-configuree' : 'indisponible';
        },
      });
  }

  private majUrl(): void {
    if (!this.jeton) return;
    const variable = this.onglet.conteneurs
      ? `&var-monitoring=${this.afficherMonitoring ? 'aucun' : 'monitoring'}`
      : '';
    this.urlBrute = `${environment.grafanaUrl}/d/${this.onglet.uid}/?orgId=1&theme=light${variable}&auth_token=${this.jeton}`;
    // URL construite ici à partir de constantes et du jeton du backend, jamais d'une saisie
    this.url = this.sanitizer.bypassSecurityTrustResourceUrl(`${this.urlBrute}&kiosk`);
  }
}
