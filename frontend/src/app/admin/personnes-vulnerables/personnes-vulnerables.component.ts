import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { HabilitationRegistreService, PersonneVulnerableService } from '../../services/vulnerabilite.service';
import { PersonneVulnerable } from '../../shared/models/vulnerabilite.model';
import { EtatRegistreVulnerables } from '../../shared/models/habilitation-registre.model';
import { PersonneVulnerableModalComponent } from './personne-vulnerable-modal/personne-vulnerable-modal.component';
import { EngagementSecretModalComponent } from './engagement-secret-modal/engagement-secret-modal.component';

/**
 * Registre communal des personnes vulnérables (recensement PCS, voir PersonneVulnerable côté
 * backend).
 *
 * **L'état des droits est chargé avant les fiches, et conditionne tout le reste.** C'est ce que
 * demande l'art. R. 121-7 du CASF : l'accès suppose une désignation nominative par le maire, et
 * l'engagement au secret professionnel de la personne désignée. Trois situations, donc, avant
 * d'afficher quoi que ce soit :
 *
 * - **aucun titre** : on explique quoi faire (demander son habilitation) et on ne charge rien ;
 * - **désigné mais pas encore engagé** : le disclaimer bloquant, à la première connexion après
 *   l'attribution des droits. Le serveur ne renverrait de toute façon aucune fiche ;
 * - **en règle** : les fiches, sous un bandeau de rappel du secret affiché en permanence.
 *
 * Cette page ne décide d'aucune permission — elle montre ce que le serveur accepte de renvoyer
 * (voir core/vulnerabilites.py) et dit *pourquoi* quand il refuse. Les deux textes juridiques
 * viennent du serveur, jamais du bundle : ce qu'on fait signer doit avoir une version unique.
 *
 * Catégories de vulnérabilité volontairement fonctionnelles/opérationnelles uniquement (voir
 * TypeVulnerabilite) — jamais un diagnostic médical, c'est ce qui tient le registre hors du
 * champ de l'art. 9 du RGPD.
 */
@Component({
  selector: 'app-personnes-vulnerables',
  standalone: true,
  imports: [CommonModule, FormsModule, PersonneVulnerableModalComponent, EngagementSecretModalComponent],
  templateUrl: './personnes-vulnerables.component.html',
  styleUrl: './personnes-vulnerables.component.scss',
})
export class PersonnesVulnerablesComponent implements OnInit {
  personnes: PersonneVulnerable[] = [];
  searchQuery = '';
  isLoading = true;
  errorMessage = '';

  etat: EtatRegistreVulnerables | null = null;

  modalOpen = false;
  editingPersonne: PersonneVulnerable | null = null;

  constructor(
    private personneVulnerableService: PersonneVulnerableService,
    private habilitationService: HabilitationRegistreService,
  ) {}

  ngOnInit(): void {
    this.chargerEtat();
  }

  /** Une habilitation non contresignée n'ouvre aucune fiche : on ne demande donc même pas la
   * liste tant que l'engagement n'est pas pris, pour ne pas afficher un tableau vide qui
   * ressemblerait à un registre vide. */
  private chargerEtat(): void {
    this.isLoading = true;
    this.habilitationService.monEtat().subscribe({
      next: (etat) => {
        this.etat = etat;
        if (etat.a_un_titre && etat.engagement_signe) {
          this.load();
        } else {
          this.isLoading = false;
        }
      },
      error: () => {
        this.errorMessage = "Impossible de vérifier vos droits d'accès au registre.";
        this.isLoading = false;
      },
    });
  }

  onEngagementSigne(): void {
    // Relire l'état plutôt que de basculer un drapeau local : c'est le serveur qui décide si
    // l'engagement compte (bonne version, titre toujours valide).
    this.chargerEtat();
  }

  private load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.personneVulnerableService.getAll().subscribe({
      next: (personnes) => {
        this.personnes = personnes;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = 'Impossible de charger le registre des personnes vulnérables.';
        this.isLoading = false;
      },
    });
  }

  /** Le disclaimer de première connexion : un titre d'accès, mais pas encore d'engagement. */
  get engagementARemplir(): boolean {
    return !!this.etat?.engagement_a_signer;
  }

  get sansTitre(): boolean {
    return !!this.etat && !this.etat.a_un_titre;
  }

  /** Un administrateur de la plateforme lit pour l'exploitation mais n'inscrit personne : le
   * registre est tenu par la collectivité (R. 121-7). Masquer le bouton plutôt que de le
   * laisser mener à un 403. */
  get peutEcrire(): boolean {
    return !!this.etat?.a_un_titre
      && this.etat.engagement_signe
      && !this.etat.lecture_seule_administrateur;
  }

  get filteredPersonnes(): PersonneVulnerable[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.personnes;
    return this.personnes.filter(p =>
      `${p.nom} ${p.prenom} ${p.adresse}`.toLowerCase().includes(q)
    );
  }

  openCreateModal(): void {
    this.editingPersonne = null;
    this.modalOpen = true;
  }

  openEditModal(personne: PersonneVulnerable): void {
    this.editingPersonne = personne;
    this.modalOpen = true;
  }

  closeModal(): void {
    this.modalOpen = false;
    this.editingPersonne = null;
  }

  onSaved(): void {
    this.closeModal();
    this.load();
  }

  radierPersonne(personne: PersonneVulnerable, event: Event): void {
    event.stopPropagation();
    if (!confirm(`Radier la fiche de « ${personne.prenom} ${personne.nom} » du registre ?`)) return;
    this.personneVulnerableService.radier(personne.id).subscribe({
      next: () => this.load(),
      error: () => this.errorMessage = 'Impossible de radier cette fiche.',
    });
  }
}
