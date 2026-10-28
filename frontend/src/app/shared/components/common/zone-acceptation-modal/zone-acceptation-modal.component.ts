import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ImplicationService, ZoneDelegable } from '../../../../services/implication.service';
import { ImplicationInstitution } from '../../../models/implication.model';

/**
 * Accepter une institution comme acteur d'une crise, **en choisissant la zone**.
 *
 * Demandé le 28/10/2026 : « quand on ajoute une AASC à une crise, pouvoir cocher quels droits
 * sur quelle zone ». La zone est le premier volet, et c'est celui qui est réellement appliqué
 * : les communes cochées deviennent `ImplicationInstitution.communes`, que la couche d'accès
 * honore partout (voir `zone_scoping.viewer_perimetre`).
 *
 * **La liste des communes vient du serveur et n'est jamais déduite ici.** Elle EST la règle
 * d'accès : « je ne donne pas les droits sur une commune sur laquelle je n'ai pas les droits ».
 * Un conseil départemental, dont le périmètre couvre la crise entière, voit donc toutes ses
 * communes et le raccourci « toute la crise » ; une commune ne voit qu'elle-même. Recalculer
 * cela dans le navigateur reviendrait à proposer de donner ce qu'on ne détient pas, et le
 * serveur refuserait — après avoir laissé croire le contraire.
 *
 * Cas limite assumé : quand une seule commune est accordable, on la coche d'emblée. Demander
 * de cocher l'unique case possible est une formalité vide, et en pleine crise chaque geste
 * compte.
 */
@Component({
  selector: 'app-zone-acceptation-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './zone-acceptation-modal.component.html',
  styleUrl: './zone-acceptation-modal.component.scss',
})
export class ZoneAcceptationModalComponent implements OnInit {
  @Input({ required: true }) implication!: ImplicationInstitution;

  @Output() acceptee = new EventEmitter<void>();
  @Output() fermee = new EventEmitter<void>();

  zone: ZoneDelegable | null = null;
  chargement = true;
  enregistrement = false;
  errorMessage = '';

  /** Codes cochés. */
  selection = new Set<string>();
  /** « Toute la zone de la crise » : n'envoie aucune commune, ce que le serveur interprète
   * comme l'acceptation la plus large — et qui reste donc juste si la zone de la crise
   * s'étend après coup. */
  touteLaCrise = false;

  constructor(private implicationService: ImplicationService) {}

  ngOnInit(): void {
    this.implicationService.zoneDelegable(this.implication.id).subscribe({
      next: (zone) => {
        this.zone = zone;
        zone.deja_accordees.forEach(c => this.selection.add(c));
        if (!zone.deja_accordees.length && zone.communes.length === 1) {
          this.selection.add(zone.communes[0].code);
        }
        this.chargement = false;
      },
      error: () => {
        this.errorMessage = "Impossible de déterminer ce que vous pouvez accorder.";
        this.chargement = false;
      },
    });
  }

  estCochee(code: string): boolean {
    return this.selection.has(code);
  }

  basculer(code: string): void {
    if (this.selection.has(code)) {
      this.selection.delete(code);
    } else {
      this.selection.add(code);
    }
    // Cocher une commune à la main sort du mode « toute la crise » : les deux diraient la
    // même chose aujourd'hui, mais pas demain si la crise s'étend.
    this.touteLaCrise = false;
  }

  basculerToutLeCrise(): void {
    this.touteLaCrise = !this.touteLaCrise;
    if (this.touteLaCrise) {
      this.selection.clear();
    }
  }

  get peutValider(): boolean {
    return !this.enregistrement && (this.touteLaCrise || this.selection.size > 0);
  }

  get resume(): string {
    if (this.touteLaCrise) return 'toute la zone de la crise';
    const n = this.selection.size;
    if (n === 0) return 'aucune commune';
    return n === 1 ? '1 commune' : `${n} communes`;
  }

  accepter(): void {
    if (!this.peutValider) return;
    this.enregistrement = true;
    this.errorMessage = '';
    const communes = this.touteLaCrise ? undefined : Array.from(this.selection);
    this.implicationService.valider(this.implication.id, communes).subscribe({
      next: () => {
        this.enregistrement = false;
        this.acceptee.emit();
      },
      error: (err) => {
        this.enregistrement = false;
        this.errorMessage = err?.error?.detail || err?.error?.error
          || "L'acceptation n'a pas pu être enregistrée.";
      },
    });
  }
}
