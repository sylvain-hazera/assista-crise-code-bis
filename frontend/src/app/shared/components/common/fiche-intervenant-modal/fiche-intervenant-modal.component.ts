import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

import { FicheIntervenantService } from '../../../../services/fiche-intervenant.service';
import { FicheIntervenant } from '../../../models/fiche-intervenant.model';

/** Fiche détaillée d'une personne mobilisée (depuis Ressources mobilisées), avec deux
 * historiques distincts : compte (sécurité) et activité. Un seul appel (FicheIntervenantView). */
@Component({
  selector: 'app-fiche-intervenant-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './fiche-intervenant-modal.component.html',
  styleUrl: './fiche-intervenant-modal.component.scss',
})
export class FicheIntervenantModalComponent implements OnChanges {
  @Input({ required: true }) userId!: string;
  @Input() criseId: string | null = null;
  @Input() equipeId: string | null = null;
  @Input() equipeNom: string | null = null;

  @Output() closed = new EventEmitter<void>();

  fiche: FicheIntervenant | null = null;
  chargement = true;
  erreur = '';

  constructor(private ficheService: FicheIntervenantService) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['userId'] && this.userId) this.charger();
  }

  private charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.ficheService.get(this.userId, this.criseId, this.equipeId).subscribe({
      next: (fiche) => { this.fiche = fiche; this.chargement = false; },
      error: () => { this.erreur = "Impossible de charger la fiche de cette personne."; this.chargement = false; },
    });
  }
}
