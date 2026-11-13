import { Component, Input, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ConservationPiecesService } from '../../../../services/conservation-pieces.service';
import {
  PieceConservation, RegimeConservation, RegimeDescription, TableConservation,
} from '../../../models/conservation-piece.model';

/**
 * Ce que deviennent les pièces justificatives, affiché là où on les demande et là où on les
 * valide.
 *
 * Demande de Sylvain du 13/11/2026 : le tableau, le texte de loi applicable, et le pourquoi,
 * sur la page de dépôt **et** sur la page de validation.
 *
 * Deux décisions de conception méritent d'être écrites :
 *
 * 1. **La table vient du serveur**, jamais du navigateur. C'est elle qui décide, côté
 *    serveur, de détruire le fichier. Une copie ici finirait par diverger, et l'écran
 *    promettrait une destruction qui n'aurait pas lieu — pire que ne rien promettre.
 * 2. **Repliée par défaut, sauf la règle qui s'applique à vous.** Trente lignes de politique
 *    de conservation au-dessus d'un bouton « Déposer » ne se lisent pas. Ce qui se lit, c'est
 *    une phrase sur la pièce qu'on s'apprête à déposer ; le reste est à un clic pour qui veut
 *    tout voir — et le bureau, lui, veut tout voir.
 */
@Component({
  selector: 'app-conservation-pieces',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './conservation-pieces.component.html',
  styleUrl: './conservation-pieces.component.scss',
})
export class ConservationPiecesComponent implements OnInit {
  /** Limite l'affichage aux pièces qu'un bénévole dépose lui-même. La page de validation,
   * elle, montre tout : le bureau tient le registre des traitements de l'association. */
  @Input() seulementDeposables = false;

  /** Titre du bloc, adapté à qui le lit. */
  @Input() titre = 'Ce que deviennent vos pièces';

  ouvert = false;
  table: TableConservation | null = null;
  erreur = '';

  constructor(private service: ConservationPiecesService) {}

  ngOnInit(): void {
    this.service.table().subscribe({
      next: (table) => this.table = table,
      // Muet et non bloquant : l'absence de ce tableau ne doit pas empêcher de déposer une
      // pièce. On le signale sans transformer la page en page d'erreur.
      error: () => this.erreur = "La politique de conservation n'a pas pu être chargée.",
    });
  }

  basculer(): void {
    this.ouvert = !this.ouvert;
  }

  get familles(): { code: string; libelle: string; pieces: PieceConservation[] }[] {
    if (!this.table) { return []; }
    const retenues = this.seulementDeposables
      ? this.table.pieces.filter(p => p.deposable)
      : this.table.pieces;
    return this.table.familles
      .map(f => ({ ...f, pieces: retenues.filter(p => p.famille === f.code) }))
      .filter(f => f.pieces.length > 0);
  }

  get regimes(): RegimeDescription[] {
    return this.table?.regimes ?? [];
  }

  libelleRegime(code: RegimeConservation): string {
    return this.regimes.find(r => r.code === code)?.libelle ?? code;
  }

  classeRegime(code: RegimeConservation): string {
    return `regime-${code.toLowerCase().replace(/_/g, '-')}`;
  }
}
