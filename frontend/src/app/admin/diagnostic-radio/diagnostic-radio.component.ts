import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { AdministrationMeshtasticService } from '../../services/administration-meshtastic.service';
import {
  DiagnosticLiaisons, RelaisSourd,
} from '../../shared/models/administration-meshtastic.model';

/** Diagnostic des liaisons radio : ce que les mesures disent de l'état du réseau.
 *
 * Quatre conclusions, de la plus actionnable à la plus indicative : relais sourds, liaisons à
 * sens unique, liaisons déséquilibrées, nœuds inaudibles.
 *
 * Cette page a une responsabilité particulière : **une conclusion fausse envoie quelqu'un sur un
 * point haut**. Elle affiche donc systématiquement ce qui permet de la juger — l'origine de la
 * preuve, le nombre d'observations, et si la puissance d'émission était connue. Une conclusion
 * non corrigée en puissance est affichée comme telle, jamais comme un fait établi.
 *
 * Le calcul est lourd (il relit une semaine d'observations) : il se déclenche au chargement et
 * sur demande explicite, jamais en boucle. */
@Component({
  selector: 'app-diagnostic-radio',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './diagnostic-radio.component.html',
  styleUrl: './diagnostic-radio.component.scss',
})
export class DiagnosticRadioComponent implements OnInit {

  diagnostic: DiagnosticLiaisons | null = null;
  chargement = true;
  erreur: string | null = null;

  /** Relais sourd dont on déplie les mesures. */
  sourdDeplie: number | null = null;

  constructor(private service: AdministrationMeshtasticService) {}

  ngOnInit(): void {
    this.calculer();
  }

  calculer(): void {
    this.chargement = true;
    this.erreur = null;
    this.service.diagnostic().subscribe({
      next: (diagnostic) => { this.diagnostic = diagnostic; this.chargement = false; },
      error: (e: HttpErrorResponse) => {
        this.erreur = e.status === 403
          ? 'Le diagnostic radio est réservé aux acteurs institutionnels.'
          : 'Impossible de calculer le diagnostic.';
        this.chargement = false;
      },
    });
  }

  basculerSourd(nodeNum: number): void {
    this.sourdDeplie = this.sourdDeplie === nodeNum ? null : nodeNum;
  }

  hexa(nodeNum: number): string {
    return `!${nodeNum.toString(16).padStart(8, '0')}`;
  }

  /** Vrai quand le réseau ne porte aucune conclusion : évite d'afficher quatre tableaux vides
   * sans dire pourquoi. */
  get aucuneConclusion(): boolean {
    const d = this.diagnostic;
    return !!d && !d.sourds.length && !d.sens_unique.length
      && !d.desequilibrees.length && !d.inaudibles.length;
  }

  /** Mesure réciproque ou simple borne basse. La distinction compte : une borne basse dit
   * seulement « il l'a reçu sous son seuil de démodulation », pas de combien. */
  libelleMesure(mesure: RelaisSourd['mesures'][number]): string {
    return mesure.borne
      ? `au moins ${mesure.ecart_db} dB (il ne l'a jamais rapporté)`
      : `${mesure.ecart_db} dB`;
  }
}
