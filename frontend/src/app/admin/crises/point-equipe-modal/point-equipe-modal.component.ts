import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { DisponibilitePointEquipeService } from '../../../services/disponibilite-point-equipe.service';
import { PointOperationnel, PointEquipeMembre, PointType } from '../../../shared/models/point-operationnel.model';
import { DisponibilitePointEquipe } from '../../../shared/models/disponibilite-point-equipe.model';
import { Creneau } from '../../../shared/models/disponibilite-offre.model';
import { AffectationPointBenevole, StatutAffectation } from '../../../shared/models/affectation-point-benevole.model';
import { RecrutementBenevolesModalComponent } from '../recrutement-benevoles-modal/recrutement-benevoles-modal.component';

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
  EN_VALIDATION: 'En attente de validation',
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
  imports: [CommonModule, FormsModule, RecrutementBenevolesModalComponent],
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

  recrutementModalOpen = false;

  constructor(
    private pointService: PointOperationnelService,
    private dispoService: DisponibilitePointEquipeService,
  ) {}

  ngOnInit(): void {
    this.load();
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

  private affectationFor(membreId: string): AffectationPointBenevole | undefined {
    return this.affectations.find(a => a.benevole === membreId);
  }

  // --- Validation régulateur d'un créneau accepté par le bénévole (statut EN_VALIDATION) ---

  validatingId: string | null = null;

  validerCreneau(membreId: string, decision: 'confirmer' | 'refuser'): void {
    const affectation = this.affectationFor(membreId);
    if (!affectation || this.validatingId) return;
    this.validatingId = affectation.id;
    this.pointService.validerBenevole(this.point.id, { affectation_id: affectation.id, decision }).subscribe({
      next: () => {
        this.validatingId = null;
        this.load();
      },
      error: () => {
        this.validatingId = null;
      },
    });
  }

  // --- Recrutement (mini-outil RH dédié, voir RecrutementBenevolesModalComponent) ---

  openRecrutementModal(): void {
    this.recrutementModalOpen = true;
  }

  closeRecrutementModal(): void {
    this.recrutementModalOpen = false;
  }

  onBenevolesAffected(): void {
    this.load();
  }

  close(): void {
    this.closed.emit();
  }
}
