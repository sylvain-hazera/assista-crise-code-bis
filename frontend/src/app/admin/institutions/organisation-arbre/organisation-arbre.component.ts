import { Component, EventEmitter, OnInit, Output } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { NoeudOrganisation, OrganisationService } from '../../../services/organisation.service';

/**
 * L'organisation : chaque institution de tête, ses filles (réserve communale, CCAS, comités…)
 * et les équipes de chacune, en arbre dépliable (23/11/2026). Un arbre plutôt qu'un
 * organigramme dessiné : il reste lisible avec des centaines d'institutions, et sur téléphone.
 * Le périmètre est celui du serveur (backend/core/organisation.py).
 */
@Component({
  selector: 'app-organisation-arbre',
  standalone: true,
  imports: [NgTemplateOutlet, FormsModule],
  templateUrl: './organisation-arbre.component.html',
  styleUrl: './organisation-arbre.component.scss',
})
export class OrganisationArbreComponent implements OnInit {
  /** Clic sur une institution : la page ouvre sa fiche. */
  @Output() ouvrir = new EventEmitter<string>();

  arbres: NoeudOrganisation[] = [];
  chargement = true;
  erreur = '';
  recherche = '';
  /** Les nœuds repliés (tout est déplié au départ, sauf au-delà de deux niveaux). */
  replies = new Set<string>();

  constructor(private organisation: OrganisationService) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.organisation.arbres(this.recherche).subscribe({
      next: ({ arbres }) => {
        this.arbres = arbres;
        this.replies = new Set();
        // Plus de dix têtes (vue plateforme) : on replie pour garder la page lisible.
        if (arbres.length > 10) arbres.forEach(a => this.replies.add(a.id));
        this.chargement = false;
      },
      error: () => { this.erreur = "Impossible de charger l'organisation."; this.chargement = false; },
    });
  }

  basculer(id: string): void {
    if (this.replies.has(id)) this.replies.delete(id); else this.replies.add(id);
  }

  aDesEnfants(n: NoeudOrganisation): boolean { return n.filles.length > 0 || n.equipes.length > 0; }

  icone(n: NoeudOrganisation): string {
    if (n.rcsc) return 'shield';
    switch (n.type_code) {
      case 'mairie': return 'account_balance';
      case 'epci': return 'holiday_village';
      case 'aasc': case 'association': return 'diversity_3';
      case 'prefecture': case 'sous_pref': return 'gavel';
      case 'sdis': return 'local_fire_department';
      default: return 'apartment';
    }
  }

  totalFilles(n: NoeudOrganisation): number {
    return n.filles.reduce((s, f) => s + 1 + this.totalFilles(f), 0);
  }

}
