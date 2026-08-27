import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { DisponibilitePointEquipeService } from '../../../services/disponibilite-point-equipe.service';
import { PointOperationnel, PointEquipeMembre } from '../../../shared/models/point-operationnel.model';
import { DisponibilitePointEquipe } from '../../../shared/models/disponibilite-point-equipe.model';
import { Creneau } from '../../../shared/models/disponibilite-offre.model';

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

/**
 * "Sous-menu équipe" d'un point : liste des bénévoles de l'équipe responsable, et pour le
 * membre sélectionné, un planning de disponibilité jour×créneau sur les 8 prochains jours —
 * même grille que celle déjà utilisée côté bénévole pour une offre d'aide
 * (propose-help-form), rejouée ici pour DisponibilitePointEquipe.
 */
@Component({
  selector: 'app-point-equipe-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './point-equipe-modal.component.html',
  styleUrl: './point-equipe-modal.component.scss'
})
export class PointEquipeModalComponent implements OnInit {
  @Input({ required: true }) point!: PointOperationnel;
  @Output() closed = new EventEmitter<void>();

  membres: PointEquipeMembre[] = [];
  selectedMembreId: string | null = null;
  jours: JourDispo[] = [];
  loading = true;
  private allDisponibilites: DisponibilitePointEquipe[] = [];

  constructor(
    private pointService: PointOperationnelService,
    private dispoService: DisponibilitePointEquipeService,
  ) {}

  ngOnInit(): void {
    this.pointService.getEquipe(this.point.id).subscribe(res => {
      this.membres = res.membres;
      this.selectedMembreId = this.membres[0]?.id ?? null;
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

  close(): void {
    this.closed.emit();
  }
}
