import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, of } from 'rxjs';
import { debounceTime, distinctUntilChanged, catchError } from 'rxjs/operators';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { CompetenceService } from '../../../services/competence.service';
import { PointOperationnel, PointType } from '../../../shared/models/point-operationnel.model';
import { InviterBenevoleAffectation } from '../../../shared/models/affectation-point-benevole.model';
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

// Heure conventionnelle de chaque créneau, pour déduire la date/heure attendue du premier
// créneau coché — l'utilisateur n'a plus à la saisir séparément, ça n'avait pas de sens
// puisqu'elle correspond justement à ce premier créneau.
const HEURE_CRENEAU: Record<Creneau, string> = {
  MATIN: '08:00',
  MIDI: '12:00',
  SOIR: '18:00',
  NUIT: '22:00',
};
const ORDRE_CRENEAU: Creneau[] = ['MATIN', 'MIDI', 'SOIR', 'NUIT'];

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
 * Sélectionner un bénévole coche d'office tous ses créneaux déclarés disponibles dans la
 * grille "créneaux à couvrir" (décochables ensuite un par un) — le régulateur garde la main
 * pour ajuster, mais n'a pas à tout cocher à la main. La ligne d'en-tête du tableau affiche en
 * direct, pour chaque créneau, le nombre de bénévoles déjà présents dans l'équipe.
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

  // Sélection multiple (persiste entre les pages) — on garde l'objet complet, pas seulement
  // l'id, pour pouvoir recalculer les créneaux à couvrir même pour un candidat d'une autre page.
  selectedIds = new Set<string>();
  private selectedCandidats = new Map<string, CandidatBenevole>();

  // Créneaux à couvrir PAR bénévole sélectionné (clé "date|creneau") — pré-cochés sur ses
  // propres disponibilités déclarées à la sélection, ajustables ensuite individuellement.
  // Avant ce correctif, une seule grille de créneaux était partagée par tout le lot sélectionné,
  // sans tenir compte des disponibilités propres à chacun.
  private benevoleCreneaux = new Map<string, Set<string>>();

  // Affectation groupée
  transitPoints: PointOperationnel[] = [];
  batchPointTransitId: string | null = null;
  submitting = false;
  submitError = '';
  submitSummary = '';

  // Compteurs "déjà affecté" par créneau, déduits de la vue équipe existante — affichés en
  // haut du tableau, sur la même grille que les disponibilités de chaque bénévole.
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

  toggleSelect(candidat: CandidatBenevole): void {
    if (this.selectedIds.has(candidat.id)) {
      this.selectedIds.delete(candidat.id);
      this.selectedCandidats.delete(candidat.id);
      this.benevoleCreneaux.delete(candidat.id);
    } else {
      this.selectedIds.add(candidat.id);
      this.selectedCandidats.set(candidat.id, candidat);
      this.benevoleCreneaux.set(candidat.id, this.disponibilitesEnSet(candidat));
    }
  }

  get allOnPageSelected(): boolean {
    return this.candidats.length > 0 && this.candidats.every(c => this.selectedIds.has(c.id));
  }

  toggleSelectAllOnPage(): void {
    if (this.allOnPageSelected) {
      this.candidats.forEach(c => {
        this.selectedIds.delete(c.id);
        this.selectedCandidats.delete(c.id);
        this.benevoleCreneaux.delete(c.id);
      });
    } else {
      this.candidats.forEach(c => {
        this.selectedIds.add(c.id);
        this.selectedCandidats.set(c.id, c);
        this.benevoleCreneaux.set(c.id, this.disponibilitesEnSet(c));
      });
    }
  }

  hasDispo(candidat: CandidatBenevole, date: string, creneau: Creneau): boolean {
    return candidat.disponibilites.some(d => d.date === date && d.creneau === creneau);
  }

  private disponibilitesEnSet(candidat: CandidatBenevole): Set<string> {
    return new Set(candidat.disponibilites.map(d => `${d.date}|${d.creneau}`));
  }

  /** Bénévoles sélectionnés, dans l'ordre — pour l'affichage individuel des créneaux à couvrir
   * dans la barre d'action groupée. */
  get selectedCandidatsList(): CandidatBenevole[] {
    return Array.from(this.selectedCandidats.values());
  }

  // --- Affectation groupée : créneaux propres à chaque bénévole sélectionné ---

  isBenevoleCreneauChecked(candidatId: string, date: string, creneau: Creneau): boolean {
    return this.benevoleCreneaux.get(candidatId)?.has(`${date}|${creneau}`) ?? false;
  }

  toggleBenevoleCreneau(candidatId: string, date: string, creneau: Creneau): void {
    const set = this.benevoleCreneaux.get(candidatId);
    if (!set) return;
    const key = `${date}|${creneau}`;
    if (set.has(key)) set.delete(key);
    else set.add(key);
  }

  dejaAffectes(date: string, creneau: Creneau): number {
    return this.equipeDisponibilites.filter(d => d.date === date && d.creneau === creneau).length;
  }

  /** Nombre de bénévoles sélectionnés couvrant ce créneau, tous confondus — affiché à titre
   * indicatif à côté du décompte "déjà présents dans l'équipe". */
  delta(date: string, creneau: Creneau): number {
    let count = 0;
    for (const id of this.selectedIds) {
      if (this.isBenevoleCreneauChecked(id, date, creneau)) count++;
    }
    return count;
  }

  /** Date/heure attendue déduite du premier créneau coché (le plus tôt) pour CE bénévole —
   * plus de champ à saisir séparément, ça correspond exactement à ce créneau. */
  premierCreneauFor(candidatId: string): { date: string; creneau: Creneau; label: string } | null {
    const set = this.benevoleCreneaux.get(candidatId);
    if (!set || set.size === 0) return null;
    const entries = Array.from(set).map(key => {
      const [date, creneau] = key.split('|') as [string, Creneau];
      return { date, creneau };
    });
    entries.sort((a, b) => {
      if (a.date !== b.date) return a.date < b.date ? -1 : 1;
      return ORDRE_CRENEAU.indexOf(a.creneau) - ORDRE_CRENEAU.indexOf(b.creneau);
    });
    const first = entries[0];
    const jour = this.jours.find(j => j.date === first.date);
    const creneauLabel = CRENEAUX.find(c => c.creneau === first.creneau)?.label ?? first.creneau;
    return { ...first, label: `${jour?.label ?? first.date} ${creneauLabel}` };
  }

  submitBatch(): void {
    if (this.selectedIds.size === 0) {
      this.submitError = "Sélectionnez au moins un bénévole.";
      return;
    }

    const affectations: InviterBenevoleAffectation[] = [];
    for (const candidat of this.selectedCandidats.values()) {
      const premier = this.premierCreneauFor(candidat.id);
      if (!premier) continue;
      const heure = HEURE_CRENEAU[premier.creneau];
      const dateAttendue = new Date(`${premier.date}T${heure}:00`).toISOString();
      const creneaux = Array.from(this.benevoleCreneaux.get(candidat.id) ?? []).map(key => {
        const [date, creneau] = key.split('|');
        return { date, creneau: creneau as Creneau };
      });
      affectations.push({ offer_id: candidat.id, date_attendue: dateAttendue, creneaux });
    }

    if (affectations.length === 0) {
      this.submitError = "Sélectionnez au moins un créneau à couvrir pour au moins un bénévole.";
      return;
    }

    this.submitting = true;
    this.submitError = '';
    this.submitSummary = '';
    this.pointService.inviterBenevole(this.point.id, {
      affectations,
      point_transit_id: this.batchPointTransitId || undefined,
    }).subscribe({
      next: (res) => {
        this.submitting = false;
        const nbCreated = res.created.length;
        const nbErrors = res.errors.length;
        this.submitSummary = nbErrors > 0
          ? `${nbCreated} bénévole(s) affecté(s), ${nbErrors} échec(s).`
          : `${nbCreated} bénévole(s) affecté(s) avec succès.`;
        this.selectedIds.clear();
        this.selectedCandidats.clear();
        this.benevoleCreneaux.clear();
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
