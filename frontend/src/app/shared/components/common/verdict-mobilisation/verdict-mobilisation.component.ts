import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { VerdictMobilisation } from '../../../../services/verification-mobilisation.service';

/**
 * Affichage d'un verdict de vérification d'attestation.
 *
 * Purement présentationnel, et partagé par les deux chemins qui mènent au même fait :
 *
 * - le **scanner intégré** (`ScannerMobilisationComponent`), quand le navigateur sait décoder
 *   un QR ;
 * - la **page ouverte par le QR** (`VerificationMobilisationComponent`), qui est le chemin de
 *   l'iPhone : l'appareil photo natif ouvre l'URL, l'application retrouve la session.
 *
 * Mutualisé parce que c'est le même verdict : deux rendus écrits séparément finiraient par ne
 * plus dire la même chose, et on ne saurait plus lequel croire.
 *
 * **Trois verdicts et non deux** : valide, révoquée, et « code inconnu ». Le troisième n'est
 * pas une révocation — c'est un QR qui n'est pas des nôtres, ce qui n'appelle pas la même
 * réaction sur le terrain.
 */
@Component({
  selector: 'app-verdict-mobilisation',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './verdict-mobilisation.component.html',
  styleUrl: './verdict-mobilisation.component.scss',
})
export class VerdictMobilisationComponent {

  @Input({ required: true }) verdict!: VerdictMobilisation;

  get icone(): string {
    if (this.verdict.valide) { return 'verified'; }
    return this.verdict.connue ? 'block' : 'help_outline';
  }

  get titre(): string {
    if (this.verdict.valide) { return 'ATTESTATION VALIDE'; }
    return this.verdict.connue ? 'ATTESTATION RÉVOQUÉE' : 'CODE INCONNU';
  }

  /** Vrai quand le serveur a retenu le nom et le lieu faute d'authentification. */
  get reduit(): boolean {
    return this.verdict.connue && this.verdict.complet === false;
  }
}
