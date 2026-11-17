import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CrisisService } from '../../../../services/crisis.service';
import { ImplicationService } from '../../../../services/implication.service';
import { AideRenfort, CriseACandidater } from '../../../models/crisis.model';

/** Ce que la fenêtre annonce quand la candidature est partie. */
export interface CandidatureEnvoyee {
  crise: CriseACandidater;
  /** La commune a choisi de dessiner sa zone : l'appelant l'emmène sur la fiche de la crise. */
  zoneADessiner: boolean;
}

/**
 * Candidater sur une crise, depuis n'importe où en France (17/11/2026).
 *
 * Deux situations que l'ancien formulaire confondait :
 *
 * - **la crise touche mon territoire** — l'institution devient « impliquée », et sa commune
 *   entre dans la zone : en entier, ou par une zone qu'elle dessine ;
 * - **mon institution peut aider** — elle n'est pas sinistrée, elle vient en renfort, et dit
 *   avec quoi : ouvrir un centre d'accueil, tenir un point de regroupement des moyens, mettre
 *   du personnel à disposition… La zone de la crise ne bouge pas, et chaque commune d'accueil
 *   donne son accord.
 *
 * Le catalogue des aides vient du serveur : c'est lui qui les valide.
 */
@Component({
  selector: 'app-candidature-crise-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './candidature-crise-modal.component.html',
  styleUrl: './candidature-crise-modal.component.scss',
})
export class CandidatureCriseModalComponent {
  @Input({ required: true }) crise!: CriseACandidater;
  @Input({ required: true }) institution!: { id: string; nom: string };
  @Input() aides: AideRenfort[] = [];

  @Output() envoyee = new EventEmitter<CandidatureEnvoyee>();
  @Output() fermee = new EventEmitter<void>();

  situation: 'touchee' | 'aide' | null = null;
  territoire: 'entier' | 'dessine' = 'entier';
  aidesCochees = new Set<string>();
  message = '';
  enregistrement = false;
  errorMessage = '';

  constructor(private crisisService: CrisisService, private implicationService: ImplicationService) {}

  /** On ne se redéclare pas : chaque situation n'est proposée que si elle n'est pas acquise. */
  get peutSeDireTouchee(): boolean { return !this.crise.situation.impliquee; }
  get peutProposerSonAide(): boolean { return !this.crise.situation.acteur; }

  basculerAide(code: string): void {
    if (this.aidesCochees.has(code)) this.aidesCochees.delete(code);
    else this.aidesCochees.add(code);
  }

  get peutEnvoyer(): boolean {
    if (this.enregistrement || !this.situation) return false;
    // Proposer son aide sans dire laquelle n'aide personne à décider.
    return this.situation === 'touchee' || this.aidesCochees.size > 0;
  }

  envoyer(): void {
    if (!this.peutEnvoyer) return;
    this.enregistrement = true;
    this.errorMessage = '';
    const message = this.message.trim() || undefined;

    const envoi = this.situation === 'touchee'
      ? this.implicationService.create({
          crise: this.crise.id, institution: this.institution.id, type_implication: 'IMPLIQUE',
          commentaire: message, territoire_partiel: this.territoire === 'dessine',
        })
      : this.crisisService.proposerAide(this.crise.id, [], message, Array.from(this.aidesCochees));

    envoi.subscribe({
      next: () => {
        this.enregistrement = false;
        this.envoyee.emit({
          crise: this.crise,
          zoneADessiner: this.situation === 'touchee' && this.territoire === 'dessine',
        });
      },
      error: (err) => {
        this.enregistrement = false;
        this.errorMessage = err?.error?.error || err?.error?.detail
          || "La candidature n'a pas pu être enregistrée.";
      },
    });
  }
}
