import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, of } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, catchError } from 'rxjs/operators';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { CompetenceService } from '../../../services/competence.service';
import { PointOperationnel, PointType } from '../../../shared/models/point-operationnel.model';
import { Creneau } from '../../../shared/models/disponibilite-offre.model';
import { Competence } from '../../../shared/models/competence.model';
import { CandidatBenevole } from '../../../shared/models/candidat-benevole.model';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';

interface JourCreneaux {
  date: string;
  label: string;
  creneaux: { creneau: Creneau; label: string }[];
}

const CRENEAUX: { creneau: Creneau; label: string }[] = [
  { creneau: 'MATIN', label: 'M' },
  { creneau: 'MIDI', label: 'Md' },
  { creneau: 'SOIR', label: 'S' },
  { creneau: 'NUIT', label: 'N' },
];

function buildJours(): JourCreneaux[] {
  const jours: JourCreneaux[] = [];
  for (let i = 0; i < 8; i++) {
    const d = new Date();
    d.setDate(d.getDate() + i);
    jours.push({
      date: d.toISOString().slice(0, 10),
      label: d.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' }),
      creneaux: CRENEAUX,
    });
  }
  return jours;
}

/**
 * Mini-outil RH de recrutement de bénévoles sur un point : tableau paginé/filtrable/triable
 * (recherche, disponibilité, compétences, distance), sélection multiple, affectation groupée.
 * Remplace l'ancienne section "Recruter un bénévole" de PointEquipeModalComponent, devenue
 * inadaptée dès qu'il y a des centaines d'offres d'aide à parcourir.
 */
@Component({
  selector: 'app-recrutement-benevoles-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './recrutement-benevoles-modal.component.html',
  styleUrl: './recrutement-benevoles-modal.component.scss'
})
export class RecrutementBenevolesModalComponent implements OnInit {
  @Input({ required: true }) point!: PointOperationnel;
  @Input() crisisId: string | null = null;
  @Input() pointTypes: PointType[] = [];
  @Output() closed = new EventEmitter<void>();
  @Output() affected = new EventEmitter<void>();

  readonly jours = buildJours();

  // Liste / pagination
  candidats: CandidatBenevole[] = [];
  totalCount = 0;
  page = 1;
  pageSize = 25;
  loading = true;
  errorMessage = '';

  // Filtres
  searchQuery = '';
  ordering: 'distance' | 'nom' = this.hasPointLocation ? 'distance' : 'nom';
  filterCreneaux = new Set<string>();
  selectedCompetences: Competence[] = [];
  competenceSearchFn = (q: string) => this.competenceService.search(q);

  // Sélection multiple (persiste entre les pages)
  selectedIds = new Set<string>();

  // Affectation groupée
  transitPoints: PointOperationnel[] = [];
  batchDateAttendue = '';
  batchPointTransitId: string | null = null;
  batchCreneaux = new Set<string>();
  submitting = false;
  submitError = '';
  submitSummary = '';

  // Compteurs "déjà affecté" par créneau, déduits de la vue équipe existante
  private equipeDisponibilites: { date: string; creneau: Creneau }[] = [];

  private search$ = new Subject<string>();

  constructor(
    private pointService: PointOperationnelService,
    private competenceService: CompetenceService,
  ) {
    this.search$
      .pipe(debounceTime(300), distinctUntilChanged())
      .subscribe(() => { this.page = 1; this.load(); });
  }

  get hasPointLocation(): boolean {
    return this.point?.latitude != null && this.point?.longitude != null;
  }

  ngOnInit(): void {
    this.ordering = this.hasPointLocation ? 'distance' : 'nom';
    this.load();
    this.loadTransitPoints();
    this.loadEquipeCounts();
  }

  private loadTransitPoints(): void {
    if (!this.crisisId) return;
    const transitType = this.pointTypes.find(t => t.code === 'TRANSIT');
    if (!transitType) return;
    this.pointService.getByCrise(this.crisisId).subscribe(points => {
      this.transitPoints = points.filter(p => p.type === transitType.id);
    });
  }

  private loadEquipeCounts(): void {
    this.pointService.getEquipe(this.point.id).subscribe(res => {
      this.equipeDisponibilites = res.disponibilites
        .filter(d => !d.affectation_statut || d.affectation_statut !== 'DECLINE')
        .map(d => ({ date: d.date, creneau: d.creneau }));
    });
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.pointService.getCandidatsBenevoles(this.point.id, {
      search: this.searchQuery || undefined,
      ordering: this.ordering,
      creneaux: Array.from(this.filterCreneaux),
      competences: this.selectedCompetences.map(c => c.id),
      page: this.page,
      page_size: this.pageSize,
    }).pipe(catchError(() => {
      this.errorMessage = "Impossible de charger la liste des bénévoles.";
      return of(null);
    })).subscribe(res => {
      this.loading = false;
      if (!res) return;
      this.candidats = res.results;
      this.totalCount = res.count;
    });
  }

  onSearchChange(value: string): void {
    this.searchQuery = value;
    this.search$.next(value);
  }

  setOrdering(ordering: 'distance' | 'nom'): void {
    this.ordering = ordering;
    this.page = 1;
    this.load();
  }

  toggleFilterCreneau(date: string, creneau: Creneau): void {
    const key = `${date}|${creneau}`;
    if (this.filterCreneaux.has(key)) this.filterCreneaux.delete(key);
    else this.filterCreneaux.add(key);
    this.page = 1;
    this.load();
  }

  isFilterCreneauChecked(date: string, creneau: Creneau): boolean {
    return this.filterCreneaux.has(`${date}|${creneau}`);
  }

  onCompetenceFilterSelected(item: Competence): void {
    if (this.selectedCompetences.some(c => c.id === item.id)) return;
    this.selectedCompetences = [...this.selectedCompetences, item];
    this.page = 1;
    this.load();
  }

  removeCompetenceFilter(id: string): void {
    this.selectedCompetences = this.selectedCompetences.filter(c => c.id !== id);
    this.page = 1;
    this.load();
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalCount / this.pageSize));
  }

  goToPage(p: number): void {
    if (p < 1 || p > this.totalPages) return;
    this.page = p;
    this.load();
  }

  // --- Sélection ---

  isSelected(id: string): boolean {
    return this.selectedIds.has(id);
  }

  toggleSelect(id: string): void {
    if (this.selectedIds.has(id)) this.selectedIds.delete(id);
    else this.selectedIds.add(id);
  }

  get allOnPageSelected(): boolean {
    return this.candidats.length > 0 && this.candidats.every(c => this.selectedIds.has(c.id));
  }

  toggleSelectAllOnPage(): void {
    if (this.allOnPageSelected) {
      this.candidats.forEach(c => this.selectedIds.delete(c.id));
    } else {
      this.candidats.forEach(c => this.selectedIds.add(c.id));
    }
  }

  hasDispo(candidat: CandidatBenevole, date: string, creneau: Creneau): boolean {
    return candidat.disponibilites.some(d => d.date === date && d.creneau === creneau);
  }

  // --- Affectation groupée ---

  isBatchCreneauChecked(date: string, creneau: Creneau): boolean {
    return this.batchCreneaux.has(`${date}|${creneau}`);
  }

  toggleBatchCreneau(date: string, creneau: Creneau): void {
    const key = `${date}|${creneau}`;
    if (this.batchCreneaux.has(key)) this.batchCreneaux.delete(key);
    else this.batchCreneaux.add(key);
  }

  dejaAffectes(date: string, creneau: Creneau): number {
    return this.equipeDisponibilites.filter(d => d.date === date && d.creneau === creneau).length;
  }

  delta(date: string, creneau: Creneau): number {
    return this.isBatchCreneauChecked(date, creneau) ? this.selectedIds.size : 0;
  }

  submitBatch(): void {
    if (this.selectedIds.size === 0) {
      this.submitError = "Sélectionnez au moins un bénévole.";
      return;
    }
    if (!this.batchDateAttendue) {
      this.submitError = "Indiquez la date/heure attendue.";
      return;
    }

    const creneaux = Array.from(this.batchCreneaux).map(key => {
      const [date, creneau] = key.split('|');
      return { date, creneau: creneau as Creneau };
    });

    this.submitting = true;
    this.submitError = '';
    this.submitSummary = '';
    this.pointService.inviterBenevole(this.point.id, {
      offer_ids: Array.from(this.selectedIds),
      date_attendue: new Date(this.batchDateAttendue).toISOString(),
      point_transit_id: this.batchPointTransitId || undefined,
      creneaux,
    }).subscribe({
      next: (res) => {
        this.submitting = false;
        const nbCreated = res.created.length;
        const nbErrors = res.errors.length;
        this.submitSummary = nbErrors > 0
          ? `${nbCreated} bénévole(s) affecté(s), ${nbErrors} échec(s).`
          : `${nbCreated} bénévole(s) affecté(s) avec succès.`;
        this.selectedIds.clear();
        this.batchCreneaux.clear();
        this.batchDateAttendue = '';
        this.batchPointTransitId = null;
        this.loadEquipeCounts();
        this.affected.emit();
      },
      error: (err) => {
        this.submitting = false;
        this.submitError = err.error?.error || err.error?.detail || "Impossible d'affecter ces bénévoles.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }
}
