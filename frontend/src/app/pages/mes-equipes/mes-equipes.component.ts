import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

import { TeamService } from '../../services/team.service';
import { Team, teamDisplayName } from '../../shared/models/team.model';

/**
 * Mes équipes, en deux temps : celles qui sont engagées maintenant, et celles auxquelles
 * j'appartiens de façon permanente.
 *
 * Demande de Sylvain du 13/11/2026 : *« dans la vue Mon / Mes équipe(s), j'aimerais que tu
 * regroupes en bas "mes équipes permanentes", en haut "Mes équipes d'intervention" »*.
 *
 * Le lien du menu ne menait qu'à **une** équipe (`/mon-equipe/<premier id trouvé>`), alors
 * qu'on appartient souvent à plusieurs : sa section départementale, l'équipe de sa commune,
 * et l'équipe d'intervention constituée pour la crise en cours. Celle qui compte un jour de
 * crise est la dernière — elle doit donc être en haut, et pas noyée dans l'ordre
 * alphabétique.
 *
 * **Ce qui fait une équipe « d'intervention » ici** : elle est engagée. Concrètement, elle a
 * une mission en cours, ou un engagement démarré, ou une crise assignée. Ce n'est pas une
 * nature différente d'équipe en base — une section départementale engagée sur une crise
 * apparaît donc en haut le temps de l'engagement, ce qui est exactement ce qu'on veut : on
 * cherche « où suis-je attendu aujourd'hui », pas « comment l'association est-elle
 * organisée ».
 */
@Component({
  selector: 'app-mes-equipes',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './mes-equipes.component.html',
  styleUrl: './mes-equipes.component.scss',
})
export class MesEquipesComponent implements OnInit {
  chargement = true;
  erreur = '';
  equipes: Team[] = [];

  constructor(private teamService: TeamService) {}

  ngOnInit(): void {
    this.teamService.mesEquipes().subscribe({
      next: (equipes) => {
        this.equipes = equipes.filter(e => e.actif !== false);
        this.chargement = false;
      },
      error: () => {
        this.erreur = 'Impossible de charger vos équipes.';
        this.chargement = false;
      },
    });
  }

  /** Engagée = attendue aujourd'hui. Voir la note de classe : c'est un état, pas une nature. */
  private estEngagee(equipe: Team): boolean {
    const missionEnCours = !!equipe.mission_active
      && equipe.mission_active_statut !== 'TERMINEE';
    return missionEnCours || !!equipe.engagement_debut
      || (equipe.assigned_crisis_ids?.length ?? 0) > 0;
  }

  get equipesIntervention(): Team[] {
    return this.equipes.filter(e => this.estEngagee(e));
  }

  /** Tout le reste, par ordre alphabétique : on y cherche une équipe précise, pas la plus
   * urgente. */
  get equipesPermanentes(): Team[] {
    return this.equipes.filter(e => !this.estEngagee(e))
      .sort((a, b) => this.nom(a).localeCompare(this.nom(b), 'fr'));
  }

  nom(equipe: Team): string {
    return teamDisplayName(equipe);
  }

  /** Pourquoi cette équipe est en haut, dit en clair. Un classement qu'on ne peut pas
   * expliquer ne se relit pas, il se subit. */
  motifEngagement(equipe: Team): string {
    if (equipe.mission_active_titre) {
      return `Mission « ${equipe.mission_active_titre} »`
        + (equipe.mission_active_crise_nom ? ` — ${equipe.mission_active_crise_nom}` : '');
    }
    if (equipe.engagement_debut) { return 'Engagement en cours'; }
    const crises = equipe.assigned_crisis_ids?.length ?? 0;
    return crises > 1 ? `${crises} crises en cours` : 'Engagée sur une crise';
  }
}
