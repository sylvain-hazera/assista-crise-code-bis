import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../auth/services/auth.service';
import { AppelDonsService } from '../../services/appel-dons.service';
import { AvisDons } from '../../shared/models/appel-dons.model';

/**
 * Les avis d'appels aux dons, lisibles sans compte : ce qu'il faut, pour combien de personnes,
 * et ce qui reste à couvrir. On n'y trouve ni contact ni lieu de livraison : organiser une
 * collecte passe par une institution (association, mairie…) qui rejoint le réseau, gratuitement,
 * et s'engage sur une quantité précise. C'est ce qui évite dix collectes pour un même besoin.
 */
@Component({
  selector: 'app-avis-dons',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './avis-dons.component.html',
  styleUrl: './avis-dons.component.scss',
})
export class AvisDonsComponent implements OnInit {
  avis: AvisDons[] = [];
  commentAider = '';
  chargement = true;
  erreur = false;

  constructor(private dons: AppelDonsService, public authService: AuthService) {}

  ngOnInit(): void {
    this.dons.avis().subscribe({
      next: (reponse) => { this.avis = reponse.avis; this.commentAider = reponse.comment_aider; this.chargement = false; },
      error: () => { this.erreur = true; this.chargement = false; },
    });
  }

  /** Les lignes d'un avis par rubrique, celles qui restent à couvrir d'abord. */
  parRubrique(avis: AvisDons): { libelle: string; lignes: AvisDons['lignes'] }[] {
    const groupes = new Map<string, AvisDons['lignes']>();
    for (const ligne of avis.lignes) groupes.set(ligne.famille_libelle, [...(groupes.get(ligne.famille_libelle) ?? []), ligne]);
    return [...groupes.entries()].map(([libelle, lignes]) => ({ libelle, lignes: [...lignes].sort((a, b) => +a.couvert - +b.couvert) }));
  }

  pourcent(avis: AvisDons): number {
    return avis.pieces_voulues ? Math.round(100 * (avis.pieces_voulues - avis.pieces_restantes) / avis.pieces_voulues) : 0;
  }
}
