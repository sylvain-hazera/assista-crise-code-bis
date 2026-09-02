import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CrisisService } from '../../../services/crisis.service';
import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { StocksComparaison } from '../../../shared/models/materiel-point.model';

interface SelectedItem {
  materielPointId: string;
  itemNom: string;
  quantiteDisponible: number | null;
  quantiteDemandee: number | null;
}

/** Tableau comparatif des stocks (lignes = besoins du catalogue, colonnes = centres de la
 * crise) — pour repérer d'un coup d'œil où organiser une navette (ex: un centre "en trop" sur
 * l'eau pendant qu'un autre est "nul"). Sélection multiple sur UNE colonne (le centre source)
 * pour demander un transfert vers un autre centre — voir demanderTransfert(). */
@Component({
  selector: 'app-stocks-comparaison-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './stocks-comparaison-modal.component.html',
  styleUrl: './stocks-comparaison-modal.component.scss'
})
export class StocksComparaisonModalComponent implements OnInit {
  @Input({ required: true }) crisisId!: string;
  @Output() closed = new EventEmitter<void>();

  data: StocksComparaison | null = null;
  loading = true;

  // Point source en cours de sélection pour une demande de transfert (une seule colonne à la
  // fois, pour ne jamais mélanger des articles de deux centres différents dans une même demande).
  sourcePointId: string | null = null;
  selectedItems: SelectedItem[] = [];

  showTransferForm = false;
  destinationPointId = '';
  transferMessage = '';
  sendingTransfer = false;
  transferError = '';
  transferSuccess = '';

  constructor(
    private crisisService: CrisisService,
    private pointOperationnelService: PointOperationnelService,
  ) {}

  ngOnInit(): void {
    this.crisisService.getStocksComparaison(this.crisisId).subscribe(data => {
      this.data = data;
      this.loading = false;
    });
  }

  close(): void {
    this.closed.emit();
  }

  otherPoints(): { id: string; nom: string }[] {
    if (!this.data || !this.sourcePointId) return [];
    return this.data.points.filter(p => p.id !== this.sourcePointId);
  }

  isSelectable(pointId: string, materielPointId: string | null): boolean {
    if (!materielPointId) return false;
    return this.sourcePointId === null || this.sourcePointId === pointId;
  }

  isSelected(materielPointId: string | null): boolean {
    return !!materielPointId && this.selectedItems.some(s => s.materielPointId === materielPointId);
  }

  toggleSelection(pointId: string, itemNom: string, cell: { materiel_point_id: string | null; quantite: number | null }): void {
    if (!cell.materiel_point_id) return;
    if (this.sourcePointId !== null && this.sourcePointId !== pointId) return;
    this.sourcePointId = pointId;

    const idx = this.selectedItems.findIndex(s => s.materielPointId === cell.materiel_point_id);
    if (idx >= 0) {
      this.selectedItems.splice(idx, 1);
      if (this.selectedItems.length === 0) this.sourcePointId = null;
    } else {
      this.selectedItems.push({
        materielPointId: cell.materiel_point_id,
        itemNom,
        quantiteDisponible: cell.quantite,
        quantiteDemandee: cell.quantite,
      });
    }
  }

  sourcePointNom(): string {
    return this.data?.points.find(p => p.id === this.sourcePointId)?.nom ?? '';
  }

  openTransferForm(): void {
    if (this.selectedItems.length === 0) return;
    this.showTransferForm = true;
    this.transferError = '';
    this.transferSuccess = '';
  }

  cancelTransferForm(): void {
    this.showTransferForm = false;
  }

  confirmTransfer(): void {
    if (!this.sourcePointId || !this.destinationPointId) {
      this.transferError = 'Choisissez un centre de destination.';
      return;
    }
    this.sendingTransfer = true;
    this.transferError = '';
    this.pointOperationnelService.demanderTransfert(
      this.sourcePointId,
      this.destinationPointId,
      this.selectedItems.map(s => ({ materiel_point_id: s.materielPointId, quantite_demandee: s.quantiteDemandee })),
      this.transferMessage.trim() || undefined,
    ).subscribe({
      next: (res) => {
        this.transferSuccess = `Demande envoyée à ${res.notifies} responsable(s) du centre « ${this.sourcePointNom()} ».`;
        this.sendingTransfer = false;
        this.showTransferForm = false;
        this.selectedItems = [];
        this.sourcePointId = null;
        this.destinationPointId = '';
        this.transferMessage = '';
      },
      error: () => {
        this.transferError = "Erreur lors de l'envoi de la demande de transfert.";
        this.sendingTransfer = false;
      },
    });
  }
}
