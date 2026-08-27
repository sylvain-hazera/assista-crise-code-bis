import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

import { CrisisService } from '../../../services/crisis.service';
import { StocksComparaison } from '../../../shared/models/materiel-point.model';

/** Tableau comparatif des stocks (lignes = besoins du catalogue, colonnes = centres de la
 * crise) — pour repérer d'un coup d'œil où organiser une navette (ex: un centre "en trop" sur
 * l'eau pendant qu'un autre est "nul"). */
@Component({
  selector: 'app-stocks-comparaison-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './stocks-comparaison-modal.component.html',
  styleUrl: './stocks-comparaison-modal.component.scss'
})
export class StocksComparaisonModalComponent implements OnInit {
  @Input({ required: true }) crisisId!: string;
  @Output() closed = new EventEmitter<void>();

  data: StocksComparaison | null = null;
  loading = true;

  constructor(private crisisService: CrisisService) {}

  ngOnInit(): void {
    this.crisisService.getStocksComparaison(this.crisisId).subscribe(data => {
      this.data = data;
      this.loading = false;
    });
  }

  close(): void {
    this.closed.emit();
  }
}
