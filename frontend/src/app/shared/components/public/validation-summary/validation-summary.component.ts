import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Encadré rouge récapitulant, en un seul endroit, tous les champs obligatoires manquants ou
 * invalides lors d'une tentative de soumission — remplace les `alert()` génériques
 * ("Veuillez remplir tous les champs obligatoires") qui ne disaient jamais LESQUELS. Purement
 * présentationnel : chaque formulaire public reste responsable de calculer sa propre liste de
 * messages (leurs validations sont trop hétérogènes — FormArray, contrôles hors FormGroup...
 * — pour un calcul générique fiable), ce composant se contente de l'afficher.
 */
@Component({
  selector: 'app-validation-summary',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './validation-summary.component.html',
  styleUrl: './validation-summary.component.scss',
})
export class ValidationSummaryComponent {
  @Input() errors: string[] = [];
}
