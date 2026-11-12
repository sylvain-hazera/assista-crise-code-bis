import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TeamService } from '../../services/team.service';
import { PlanningEquipeService } from '../../services/planning-equipe.service';
import { Team } from '../../shared/models/team.model';
import {
  ConflitPlanning, EcartDisponibilite, LIBELLES_STATUT_CRENEAU, PersonnePlanning,
  PlanningEquipe, StatutCreneauEquipe,
} from '../../shared/models/planning-equipe.model';

/** Planning d'une équipe : qui tient quel créneau, quel jour.
 *
 * **Le tableau est la saisie.** On ne remplit pas un formulaire pour poser un créneau : on
 * clique la case, comme sur la grille de disponibilités — c'est le même geste, sur le même
 * découpage (quatre créneaux par jour), et en apprendre un second pour la même chose n'aurait
 * aucun sens.
 *
 * Deux écarts sont signalés et jamais bloqués (voir `core/planning_equipe.py`) :
 * le **double engagement** (la même personne attendue par deux équipes au même moment) et
 * l'affectation **hors disponibilité déclarée** (un chef d'équipe a le droit d'appeler). Les
 * deux sont nommés, parce qu'« il y a 3 conflits » n'a jamais permis à personne de décider.
 */
@Component({
  selector: 'app-planning-equipes',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './planning-equipes.component.html',
  styleUrl: './planning-equipes.component.scss',
})
export class PlanningEquipesComponent implements OnInit {
  equipes: Team[] = [];
  equipeChoisie: string | null = null;

  planning: PlanningEquipe | null = null;
  chargement = true;
  erreur = '';
  message = '';

  joursAffiches = 14;
  debut = '';
  effectifCible = 0;

  /** Statut posé par un clic. Modifiable : on compose souvent un planning en « prévu », puis
   * on confirme une fois les gens prévenus. */
  statutAPoser: StatutCreneauEquipe = 'PREVU';
  roleAPoser = '';

  conflits: ConflitPlanning[] = [];
  horsDisponibilite: EcartDisponibilite[] = [];
  enregistrement = false;

  readonly LIBELLES_STATUT = LIBELLES_STATUT_CRENEAU;
  readonly STATUTS = Object.keys(LIBELLES_STATUT_CRENEAU) as StatutCreneauEquipe[];

  constructor(
    private teamService: TeamService,
    private planningService: PlanningEquipeService,
  ) {}

  ngOnInit(): void {
    this.teamService.getAll().subscribe({
      next: (liste) => {
        this.equipes = (liste ?? []).filter(e => e.actif !== false);
        this.equipeChoisie = this.equipes[0]?.id ?? null;
        this.chargement = false;
        if (this.equipeChoisie) { this.charger(); }
      },
      error: () => {
        this.erreur = 'Impossible de charger vos équipes.';
        this.chargement = false;
      },
    });
  }

  charger(): void {
    if (!this.equipeChoisie) { return; }
    this.chargement = true;
    this.planningService.planning(
      this.equipeChoisie, this.joursAffiches, this.debut || undefined, this.effectifCible,
    ).subscribe({
      next: (p) => { this.planning = p; this.chargement = false; this.erreur = ''; },
      error: (err) => {
        this.chargement = false;
        this.erreur = err?.error?.error || err?.error?.detail
          || 'Impossible de charger ce planning.';
      },
    });
  }

  changerEquipe(): void {
    this.planning = null;
    this.conflits = [];
    this.horsDisponibilite = [];
    this.charger();
  }

  // ══ Lecture du tableau ════════════════════════════════════════════════════

  caseDe(personne: PersonnePlanning, index: number, creneau: string) {
    return personne.jours[index]?.creneaux?.[creneau] ?? null;
  }

  /** Effectif réellement tenu sur ce créneau. Annulés et absents exclus : compter une ligne
   * annulée ferait croire une garde armée. */
  effectif(jour: string, creneau: string): number {
    return this.planning?.effectifs?.[jour]?.[creneau] ?? 0;
  }

  sousArme(jour: string, creneau: string): boolean {
    return !!this.effectifCible && this.effectif(jour, creneau) < this.effectifCible;
  }

  estWeekEnd(iso: string): boolean {
    const jour = new Date(iso + 'T00:00:00').getDay();
    return jour === 0 || jour === 6;
  }

  enTeteJour(iso: string): string {
    const d = new Date(iso + 'T00:00:00');
    const jours = ['di', 'lu', 'ma', 'me', 'je', 've', 'sa'];
    return `${jours[d.getDay()]} ${d.getDate()}`;
  }

  initialeCreneau(creneau: string): string {
    const initiales: Record<string, string> = {
      MATIN: 'M', MIDI: 'Mi', SOIR: 'S', NUIT: 'N',
    };
    return initiales[creneau] ?? creneau.slice(0, 1);
  }

  libelleCreneau(creneau: string): string {
    const libelles: Record<string, string> = {
      MATIN: 'Matin', MIDI: 'Midi', SOIR: 'Soir', NUIT: 'Nuit',
    };
    return libelles[creneau] ?? creneau;
  }

  /** La classe d'une case : vide, ou le statut qu'elle porte. */
  classeCase(personne: PersonnePlanning, index: number, creneau: string): string {
    const occupe = this.caseDe(personne, index, creneau);
    return occupe ? `case ${occupe.statut.toLowerCase()}` : 'case libre';
  }

  // ══ Saisie ════════════════════════════════════════════════════════════════

  /** Clic sur une case : pose le créneau, ou le retire s'il portait déjà le statut choisi.
   *
   * Reprendre le même clic pour poser ET retirer évite un mode « gomme » : la case est son
   * propre interrupteur, et le statut à poser se choisit dans la barre du haut. */
  basculerCase(personne: PersonnePlanning, index: number, creneau: string): void {
    if (!this.planning || this.enregistrement) { return; }
    const jour = this.planning.jours[index];
    const occupe = this.caseDe(personne, index, creneau);

    if (occupe && occupe.statut === this.statutAPoser) {
      this.enregistrement = true;
      this.planningService.retirer(occupe.id).subscribe({
        next: () => { this.enregistrement = false; this.charger(); },
        error: (err) => {
          this.enregistrement = false;
          this.erreur = err?.error?.detail || 'Impossible de retirer ce créneau.';
        },
      });
      return;
    }

    this.poser([{ utilisateur: personne.utilisateur, date: jour, creneau }]);
  }

  /** Toute une journée pour une personne, ou tout un créneau pour toute l'équipe : composer
   * une garde case par case sur quatorze jours est impraticable. */
  poserJournee(personne: PersonnePlanning, index: number): void {
    if (!this.planning) { return; }
    const jour = this.planning.jours[index];
    this.poser(this.planning.creneaux.map(
      creneau => ({ utilisateur: personne.utilisateur, date: jour, creneau })));
  }

  poserColonne(index: number, creneau: string): void {
    if (!this.planning) { return; }
    const jour = this.planning.jours[index];
    this.poser(this.planning.personnes.map(
      p => ({ utilisateur: p.utilisateur, date: jour, creneau })));
  }

  private poser(creneaux: { utilisateur: string; date: string; creneau: string }[]): void {
    if (!this.equipeChoisie || !creneaux.length) { return; }
    this.enregistrement = true;
    this.planningService.pointer(this.equipeChoisie, creneaux, {
      statut: this.statutAPoser, role: this.roleAPoser.trim() || undefined,
    }).subscribe({
      next: (res) => {
        this.enregistrement = false;
        // Remplacés et non accumulés : ce sont les écarts du DERNIER geste, pas un journal.
        this.conflits = res.conflits ?? [];
        this.horsDisponibilite = res.hors_disponibilite ?? [];
        this.message = `${res.poses} créneau(x) posé(s)`
          + (res.mis_a_jour ? `, ${res.mis_a_jour} mis à jour` : '') + '.';
        this.erreur = '';
        this.charger();
      },
      error: (err) => {
        this.enregistrement = false;
        this.erreur = err?.error?.error || err?.error?.detail
          || 'Impossible de poser ces créneaux.';
      },
    });
  }

  changerStatut(id: string, statut: StatutCreneauEquipe): void {
    this.planningService.changerStatut(id, statut).subscribe({
      next: () => this.charger(),
      error: () => this.erreur = 'Impossible de changer ce statut.',
    });
  }

  /** Les créneaux sous-armés, rendus par le serveur : les chercher à l'œil dans quatorze
   * colonnes est exactement ce qu'un écran doit éviter de faire faire. */
  get manques() {
    return this.planning?.non_couverts ?? [];
  }

  get totalCreneauxTenus(): number {
    return (this.planning?.personnes ?? []).reduce((t, p) => t + p.creneaux_tenus, 0);
  }
}
