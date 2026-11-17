import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { NatureRapport, RapportService } from '../../../../services/rapport.service';

/**
 * Le bouton « Rapport (PDF) » d'un dossier, d'une mission ou d'une crise.
 *
 * Il s'appelle « Rapport de clôture » une fois l'objet clos, et porte son propre état (édition
 * en cours, échec) : les trois écrans qui l'accueillent n'ont rien d'autre à faire que le poser.
 */
@Component({
  selector: 'app-bouton-rapport',
  standalone: true,
  imports: [CommonModule],
  template: `
    <button type="button" class="btn-secondary sm bouton-rapport" [disabled]="edition || !id" (click)="editer($event)" [title]="infobulle">
      <span class="material-icons">picture_as_pdf</span>
      {{ edition ? 'Édition…' : (clos ? 'Rapport de clôture (PDF)' : 'Rapport (PDF)') }}
    </button>
    <label class="toutes-les-photos" (click)="$event.stopPropagation()"
           title="Par défaut le rapport retient un nombre limité de photos pour rester facile à envoyer. Cochez pour les avoir toutes : le fichier peut être lourd.">
      <input type="checkbox" [checked]="toutesLesPhotos" (change)="toutesLesPhotos = $any($event.target).checked"> toutes les photos
    </label>
    @if (erreur) { <small class="erreur-rapport" role="alert">{{ erreur }}</small> }
  `,
  styles: [`
    :host { display: inline-flex; flex-direction: column; gap: .2rem; }
    .bouton-rapport { display: inline-flex; align-items: center; gap: .3rem; }
    .bouton-rapport .material-icons { font-size: 1.05rem; }
    .erreur-rapport { color: #b91c1c; max-width: 18rem; }
    .toutes-les-photos { display: inline-flex; align-items: center; gap: .25rem; font-size: .78rem; font-weight: 400; }
  `],
})
export class BoutonRapportComponent {
  @Input({ required: true }) nature!: NatureRapport;
  @Input() id: string | null | undefined;
  /** Vrai une fois le dossier clôturé, la mission terminée ou la crise close. */
  @Input() clos = false;
  /** Ce qui distingue ce rapport dans le nom du fichier (numéro de dossier, par exemple). */
  @Input() reference = '';

  /** Sans le plafond de photos par défaut (l'assureur les veut parfois toutes). */
  toutesLesPhotos = false;
  edition = false;
  erreur = '';

  private readonly infobulles: Record<NatureRapport, string> = {
    dossier: "La demande d'origine, le bien et les dégâts relevés, la chronologie, les photos en annexe : à joindre à une déclaration de sinistre.",
    mission: "L'objectif, les équipes, les dossiers traités ; en annexe le rapport de chaque dossier et les photos.",
    crise: "La crise pour votre collectivité : chiffres, dégâts relevés, moyens engagés, alertes, journal de bord ; missions, dossiers et photos en annexe. À éditer avant la clôture : les rapports gardés sur le serveur sont effacés à ce moment-là.",
    bien: "Le bien, sa position, la cause et l'état du dommage, les observations et les photos : à remettre au propriétaire pour son assurance.",
  };

  constructor(private rapports: RapportService) {}

  get infobulle(): string { return this.infobulles[this.nature]; }

  editer(evenement?: Event): void {
    evenement?.stopPropagation();      // posé dans une ligne de tableau cliquable : ne pas l'ouvrir
    if (!this.id || this.edition) return;
    this.edition = true;
    this.erreur = '';
    const nom = `rapport-${this.nature}${this.reference ? '-' + this.reference.replace(/[^A-Za-z0-9_-]+/g, '-') : ''}`;
    this.rapports.telecharger(this.nature, this.id, nom, this.toutesLesPhotos).subscribe({
      next: () => { this.edition = false; },
      error: (e) => {
        this.edition = false;
        this.erreur = e?.status === 403 ? "Vous n'avez pas accès à ce rapport." : "Le rapport n'a pas pu être édité.";
      },
    });
  }
}
