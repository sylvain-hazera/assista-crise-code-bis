import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, catchError } from 'rxjs/operators';
import { of } from 'rxjs';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { DisponibilitePointEquipeService } from '../../../services/disponibilite-point-equipe.service';
import { OfferService } from '../../../services/offer.service';
import { PointOperationnel, PointEquipeMembre, PointType } from '../../../shared/models/point-operationnel.model';
import { DisponibilitePointEquipe } from '../../../shared/models/disponibilite-point-equipe.model';
import { Creneau } from '../../../shared/models/disponibilite-offre.model';
import { Offer } from '../../../shared/models/offer.model';
import { AffectationPointBenevole, StatutAffectation } from '../../../shared/models/affectation-point-benevole.model';

interface JourDispo {
  date: string;
  label: string;
  creneaux: { creneau: Creneau; label: string; checked: boolean; dispoId: string | null }[];
}

const CRENEAUX: { creneau: Creneau; label: string }[] = [
  { creneau: 'MATIN', label: 'Matin' },
  { creneau: 'MIDI', label: 'Midi' },
  { creneau: 'SOIR', label: 'Soir' },
  { creneau: 'NUIT', label: 'Nuit' },
];

const STATUT_LABELS: Record<StatutAffectation, string> = {
  EN_ATTENTE: 'En attente de confirmation',
  CONFIRME: 'Confirmé',
  DECLINE: 'Décliné',
};

/**
 * "Sous-menu équipe" d'un point : liste des bénévoles de l'équipe responsable, leurs
 * disponibilités et leur temps cumulé sur ce point (affichage seul, pas de blocage — l'équipe
 * du point reste juge de son propre repos), plus une section de recrutement de bénévoles
 * individuels depuis les offres d'aide (pas seulement les membres déjà affectés au point).
 */
@Component({
  selector: 'app-point-equipe-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './point-equipe-modal.component.html',
  styleUrl: './point-equipe-modal.component.scss'
})
export class PointEquipeModalComponent implements OnInit {
  @Input({ required: true }) point!: PointOperationnel;
  @Input() crisisId: string | null = null;
  @Input() pointTypes: PointType[] = [];
  @Output() closed = new EventEmitter<void>();

  membres: PointEquipeMembre[] = [];
  affectations: AffectationPointBenevole[] = [];
  selectedMembreId: string | null = null;
  jours: JourDispo[] = [];
  loading = true;
  private allDisponibilites: DisponibilitePointEquipe[] = [];

  // Recrutement d'un bénévole individuel
  recruiting = false;
  searchQuery = '';
  searchResults: Offer[] = [];
  searchLoading = false;
  selectedOffer: Offer | null = null;
  transitPoints: PointOperationnel[] = [];
  inviteDateAttendue = '';
  invitePointTransitId: string | null = null;
  inviteCreneaux = new Set<string>();
  inviteError = '';
  inviting = false;

  private search$ = new Subject<string>();

  constructor(
    private pointService: PointOperationnelService,
    private dispoService: DisponibilitePointEquipeService,
    private offerService: OfferService,
  ) {
    this.search$
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        switchMap(q => {
          if (!q.trim()) return of([]);
          this.searchLoading = true;
          return this.offerService.getAll({ search: q }).pipe(catchError(() => of([])));
        })
      )
      .subscribe(results => {
        this.searchResults = results;
        this.searchLoading = false;
      });
  }

  ngOnInit(): void {
    this.load();
    this.loadTransitPoints();
  }

  private load(): void {
    this.pointService.getEquipe(this.point.id).subscribe(res => {
      this.membres = res.membres;
      this.affectations = res.affectations ?? [];
      this.selectedMembreId = this.selectedMembreId ?? this.membres[0]?.id ?? null;
      this.buildJours(res.disponibilites);
      this.loading = false;
    });
  }

  private loadTransitPoints(): void {
    if (!this.crisisId) return;
    const transitType = this.pointTypes.find(t => t.code === 'TRANSIT');
    if (!transitType) return;
    this.pointService.getByCrise(this.crisisId).subscribe(points => {
      this.transitPoints = points.filter(p => p.type === transitType.id);
    });
  }

  private buildJours(disponibilites: DisponibilitePointEquipe[]): void {
    const jours: JourDispo[] = [];
    for (let i = 0; i < 8; i++) {
      const d = new Date();
      d.setDate(d.getDate() + i);
      const dateStr = d.toISOString().slice(0, 10);
      jours.push({
        date: dateStr,
        label: d.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' }),
        creneaux: CRENEAUX.map(c => {
          const existing = disponibilites.find(
            dp => dp.membre === this.selectedMembreId && dp.date === dateStr && dp.creneau === c.creneau
          );
          return { ...c, checked: !!existing, dispoId: existing?.id ?? null };
        }),
      });
    }
    this.jours = jours;
    this.allDisponibilites = disponibilites;
  }

  selectMembre(membreId: string): void {
    this.selectedMembreId = membreId;
    this.buildJours(this.allDisponibilites);
  }

  toggleSlot(jour: JourDispo, slot: JourDispo['creneaux'][number]): void {
    if (!this.selectedMembreId) return;

    if (slot.checked && slot.dispoId) {
      this.dispoService.delete(slot.dispoId).subscribe(() => {
        this.allDisponibilites = this.allDisponibilites.filter(d => d.id !== slot.dispoId);
        slot.checked = false;
        slot.dispoId = null;
      });
    } else {
      this.dispoService.create({
        point: this.point.id, membre: this.selectedMembreId, date: jour.date, creneau: slot.creneau,
      }).subscribe(created => {
        this.allDisponibilites = [...this.allDisponibilites, created];
        slot.checked = true;
        slot.dispoId = created.id;
      });
    }
  }

  statutFor(membreId: string): { statut: StatutAffectation; libelle: string } | null {
    const affectation = this.affectations.find(a => a.benevole === membreId);
    if (!affectation) return null;
    return { statut: affectation.statut, libelle: STATUT_LABELS[affectation.statut] };
  }

  // --- Recrutement ---

  toggleRecruiting(): void {
    this.recruiting = !this.recruiting;
    if (!this.recruiting) this.resetRecruitForm();
  }

  onSearchChange(value: string): void {
    this.searchQuery = value;
    this.search$.next(value);
  }

  selectOffer(offer: Offer): void {
    this.selectedOffer = offer;
    this.searchResults = [];
    this.searchQuery = '';
  }

  offerLabel(offer: Offer): string {
    const nom = `${offer.first_name_offer} ${offer.last_name_offer}`.trim();
    return nom ? `${nom} — ${offer.title}` : offer.title;
  }

  toggleCreneau(date: string, creneau: Creneau): void {
    const key = `${date}|${creneau}`;
    if (this.inviteCreneaux.has(key)) {
      this.inviteCreneaux.delete(key);
    } else {
      this.inviteCreneaux.add(key);
    }
  }

  isCreneauChecked(date: string, creneau: Creneau): boolean {
    return this.inviteCreneaux.has(`${date}|${creneau}`);
  }

  get inviteJours(): { date: string; label: string; creneaux: { creneau: Creneau; label: string }[] }[] {
    const jours = [];
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

  submitInvite(): void {
    if (!this.selectedOffer || !this.inviteDateAttendue) {
      this.inviteError = "Sélectionnez une offre et une date/heure attendue.";
      return;
    }

    const creneaux = Array.from(this.inviteCreneaux).map(key => {
      const [date, creneau] = key.split('|');
      return { date, creneau: creneau as Creneau };
    });

    this.inviting = true;
    this.inviteError = '';
    this.pointService.inviterBenevole(this.point.id, {
      offer_id: this.selectedOffer.id,
      date_attendue: new Date(this.inviteDateAttendue).toISOString(),
      point_transit_id: this.invitePointTransitId || undefined,
      creneaux,
    }).subscribe({
      next: () => {
        this.inviting = false;
        this.resetRecruitForm();
        this.recruiting = false;
        this.load();
      },
      error: (err) => {
        this.inviting = false;
        this.inviteError = err.error?.error || err.error?.detail || "Impossible d'inviter ce bénévole.";
      },
    });
  }

  private resetRecruitForm(): void {
    this.searchQuery = '';
    this.searchResults = [];
    this.selectedOffer = null;
    this.inviteDateAttendue = '';
    this.invitePointTransitId = null;
    this.inviteCreneaux.clear();
    this.inviteError = '';
  }

  close(): void {
    this.closed.emit();
  }
}
