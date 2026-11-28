import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BandeauOuvertComponent } from '../bandeau-ouvert.component';

/**
 * `/ouvert/rejoindre` (28/11/2026) : de quoi rejoindre le réseau radio du territoire. Rien que
 * des faits déjà établis dans le projet (bande et plafonds lus dans le firmware, fréquence du
 * réseau français, avertissement de l'ANFR) — et aucune clé de canal de crise ou d'équipe.
 */
@Component({
  selector: 'app-ouvert-rejoindre',
  standalone: true,
  imports: [RouterLink, BandeauOuvertComponent],
  templateUrl: './ouvert-rejoindre.component.html',
  styleUrl: './ouvert-rejoindre.component.scss',
})
export class OuvertRejoindreComponent {}
