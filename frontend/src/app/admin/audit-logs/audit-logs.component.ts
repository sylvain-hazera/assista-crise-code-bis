import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, takeUntil } from 'rxjs';
import { AuditLogService, AuditLogAdminEntry, AuditLogFilters } from '../../services/audit-log.service';

interface ActionOption {
  code: string;
  libelle: string;
}

@Component({
  selector: 'app-audit-logs',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './audit-logs.component.html',
  styleUrls: ['./audit-logs.component.scss'],
})
export class AuditLogsComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  isLoading = false;
  isExporting = false;
  errorMessage = '';

  entries: AuditLogAdminEntry[] = [];
  totalCount = 0;
  page = 1;
  readonly pageSize = 50;

  filters: AuditLogFilters = {};

  // Options fixes (le référentiel AuditAction ne change quasiment jamais, pas d'endpoint dédié).
  readonly actionOptions: ActionOption[] = [
    { code: 'CONNEXION', libelle: 'Connexion' },
    { code: 'DECONNEXION', libelle: 'Déconnexion' },
    { code: 'LECTURE', libelle: 'Consultation' },
    { code: 'CREATION', libelle: 'Création' },
    { code: 'MODIFICATION', libelle: 'Modification' },
    { code: 'SUPPRESSION', libelle: 'Suppression' },
    { code: 'DESACTIVATION', libelle: 'Désactivation' },
    { code: 'REACTIVATION', libelle: 'Réactivation' },
    { code: 'AFFECTATION', libelle: 'Affectation' },
    { code: 'CLOTURE', libelle: 'Clôture de dossier' },
    { code: 'DELEGATION_COMPETENCE', libelle: 'Délégation de compétence' },
    { code: 'PRISE_PERMANENCE', libelle: 'Prise de permanence' },
    { code: 'FIN_PERMANENCE', libelle: 'Fin de permanence' },
    { code: 'ACQUITTEMENT', libelle: 'Acquittement' },
    { code: 'TELECHARGEMENT', libelle: 'Téléchargement de document' },
    { code: 'ENVOI_EMAIL', libelle: "Envoi d'email" },
    { code: 'EXPORT', libelle: 'Export de données' },
    { code: 'JOURNAL_BORD', libelle: 'Écriture au journal de bord' },
    { code: 'IMPORT_LISTE', libelle: "Import d'une liste (CSV/XLS)" },
  ];

  constructor(private auditLogService: AuditLogService) {}

  ngOnInit(): void { this.load(); }
  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalCount / this.pageSize));
  }

  load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.auditLogService.browse(this.filters, this.page, this.pageSize)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (result) => {
          this.entries = result.results;
          this.totalCount = result.count;
          this.isLoading = false;
        },
        error: () => {
          this.errorMessage = "Impossible de charger le registre — réservé aux administrateurs.";
          this.isLoading = false;
        },
      });
  }

  applyFilters(): void {
    this.page = 1;
    this.load();
  }

  resetFilters(): void {
    this.filters = {};
    this.page = 1;
    this.load();
  }

  goToPage(page: number): void {
    if (page < 1 || page > this.totalPages) return;
    this.page = page;
    this.load();
  }

  exportCsv(): void {
    this.isExporting = true;
    this.auditLogService.exportCsv(this.filters)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (blob) => {
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          const horodatage = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
          a.href = url;
          a.download = `main-courante-${horodatage}.csv`;
          a.click();
          window.URL.revokeObjectURL(url);
          this.isExporting = false;
        },
        error: () => {
          this.errorMessage = "Impossible d'exporter le registre.";
          this.isExporting = false;
        },
      });
  }

  actionLibelle(code: string | null): string {
    return this.actionOptions.find(o => o.code === code)?.libelle ?? (code ?? '—');
  }
}
