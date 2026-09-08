import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { CrisisService } from '../../services/crisis.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { StocksComparaison } from '../../shared/models/materiel-point.model';

interface SelectedItem {
  materielPointId: string;
  itemNom: string;
  quantiteDisponible: number | null;
  quantiteDemandee: number | null;
}

/** Tableau comparatif des stocks (lignes = besoins du catalogue, colonnes = centres de la
 * crise) — pour repérer d'un coup d'œil où organiser une navette (ex: un centre "en trop" sur
 * l'eau pendant qu'un autre est "nul"). Sélection multiple sur UNE colonne (le centre source)
 * pour demander un transfert vers un autre centre — voir demanderTransfert().
 *
 * Page dédiée (route `/admin/crises/:crisisId/stocks`) plutôt qu'une modale imbriquée dans le
 * détail du point (point-modal > point-inventaire-modal > cette modale) : le tableau, large par
 * nature (une colonne par centre), était trop à l'étroit dans une modale contrainte. */
@Component({
  selector: 'app-stocks-comparaison',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './stocks-comparaison.component.html',
  styleUrl: './stocks-comparaison.component.scss'
})
export class StocksComparaisonComponent implements OnInit {
  crisisId!: string;
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
    private route: ActivatedRoute,
    private router: Router,
    private crisisService: CrisisService,
    private pointOperationnelService: PointOperationnelService,
  ) {}

  ngOnInit(): void {
    this.crisisId = this.route.snapshot.paramMap.get('crisisId')!;
    this.crisisService.getStocksComparaison(this.crisisId).subscribe(data => {
      this.data = data;
      this.loading = false;
    });
  }

  goBack(): void {
    this.router.navigate(['/admin/crises'], { queryParams: { id: this.crisisId } });
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
