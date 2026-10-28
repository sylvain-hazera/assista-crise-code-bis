import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  CandidatHabilitation,
  HabilitationRegistreService,
} from '../../services/vulnerabilite.service';
import { AuthService } from '../../auth/services/auth.service';
import { messageErreurServeur } from '../../shared/utils/message-erreur';
import {
  EtatRegistreVulnerables,
  HabilitationRegistre,
  QualiteDesignataire,
} from '../../shared/models/habilitation-registre.model';

/**
 * Désignation nominative des personnes habilitées à tenir le registre communal des personnes
 * vulnérables — art. R. 121-7 du CASF, voir BASE-LEGALE-REGISTRE-VULNERABLES.md § 5.
 *
 * **Ce que cet écran fait porter à son utilisateur.** La plateforme ne peut pas vérifier qu'un
 * compte est bien celui du maire. L'attestation sur l'honneur est précisément le mécanisme qui
 * transfère la responsabilité de cette déclaration sur son auteur, nommément et horodatée dans
 * le journal. L'écran doit donc être explicite sur ce qui est attesté — un simple « OK » qui
 * enregistre une attestation sans la nommer serait une signature extorquée.
 *
 * Deux règles de l'écran viennent du droit et non du confort :
 *
 * - **Un agent ne peut pas se désigner lui-même** : l'habilitation émane du maire. Seuls le
 *   maire et ses adjoints peuvent s'auto-désigner, sans quoi une commune qui démarre n'aurait
 *   personne pour ouvrir le registre (le premier compte de la mairie est le leur).
 * - **Le retrait exige un motif et ne supprime rien.** C'est ce qui permet de répondre, un an
 *   plus tard, à « qui avait accès au registre le jour de la canicule ? ». Les habilitations
 *   retirées restent donc affichées, dans une section à part.
 *
 * La colonne « engagement » dit si le désigné a contresigné : une habilitation non contresignée
 * est prononcée mais n'ouvre aucune fiche, et le maire doit pouvoir le voir d'un coup d'œil
 * plutôt que de croire son équipe opérationnelle à tort.
 */
@Component({
  selector: 'app-habilitations-registre',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './habilitations-registre.component.html',
  styleUrl: './habilitations-registre.component.scss',
})
export class HabilitationsRegistreComponent implements OnInit {
  habilitations: HabilitationRegistre[] = [];
  candidats: CandidatHabilitation[] = [];
  etat: EtatRegistreVulnerables | null = null;

  isLoading = true;
  errorMessage = '';
  successMessage = '';

  formOuvert = false;
  enregistrement = false;

  /** Qualités qui autorisent l'auto-désignation — même liste que
   * HabilitationRegistreVulnerablesViewSet.QUALITES_AUTO_DESIGNATION côté serveur, qui reste
   * l'autorité : on la reprend ici seulement pour expliquer avant le refus. */
  readonly QUALITES_AUTO_DESIGNATION: QualiteDesignataire[] = ['MAIRE', 'ADJOINT'];

  readonly QUALITES: { valeur: QualiteDesignataire; libelle: string }[] = [
    { valeur: 'MAIRE', libelle: 'Maire' },
    { valeur: 'ADJOINT', libelle: 'Adjoint au maire' },
    { valeur: 'AGENT', libelle: 'Personnel de mairie habilité par le maire à désigner' },
  ];

  nouvelle: {
    utilisateur: string;
    qualite_accordant: QualiteDesignataire | '';
    fonction: string;
    date_fin: string;
    attestation: boolean;
  } = { utilisateur: '', qualite_accordant: '', fonction: '', date_fin: '', attestation: false };

  constructor(
    private service: HabilitationRegistreService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.charger();
  }

  private charger(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.service.monEtat().subscribe({
      next: (etat) => {
        this.etat = etat;
        if (!etat.peut_designer) {
          this.isLoading = false;
          return;
        }
        this.service.getAll().subscribe({
          next: (habilitations) => {
            this.habilitations = habilitations;
            this.isLoading = false;
          },
          error: () => {
            this.errorMessage = 'Impossible de charger la liste des habilitations.';
            this.isLoading = false;
          },
        });
        this.service.candidats().subscribe({
          next: (candidats) => this.candidats = candidats,
          error: () => this.candidats = [],
        });
      },
      error: () => {
        this.errorMessage = "Impossible de vérifier vos droits.";
        this.isLoading = false;
      },
    });
  }

  get peutDesigner(): boolean {
    return !!this.etat?.peut_designer;
  }

  get actives(): HabilitationRegistre[] {
    return this.habilitations.filter(h => h.actif);
  }

  get retirees(): HabilitationRegistre[] {
    return this.habilitations.filter(h => !h.actif);
  }

  /** Candidats encore désignables : ceux qui le sont déjà sont écartés du sélecteur plutôt que
   * de mener à un refus « déjà habilitée » après coup. */
  get candidatsDisponibles(): CandidatHabilitation[] {
    return this.candidats.filter(c => !c.deja_habilite);
  }

  get candidatChoisiEstMoiMeme(): boolean {
    const moi = this.authService.getCurrentUser()?.id;
    return !!moi && this.nouvelle.utilisateur === moi;
  }

  /** Mise en garde affichee AVANT le refus du serveur, qui reste l'autorite : mieux vaut
   * expliquer la regle au moment du choix que la decouvrir sur un 400. */
  get autoDesignationInterdite(): boolean {
    if (!this.candidatChoisiEstMoiMeme || !this.nouvelle.qualite_accordant) return false;
    return !this.QUALITES_AUTO_DESIGNATION.includes(this.nouvelle.qualite_accordant);
  }

  get formValide(): boolean {
    return !!this.nouvelle.utilisateur
      && !!this.nouvelle.qualite_accordant
      && this.nouvelle.attestation
      && !this.autoDesignationInterdite;
  }

  ouvrirForm(): void {
    this.formOuvert = true;
    this.successMessage = '';
    this.nouvelle = {
      utilisateur: '', qualite_accordant: '', fonction: '', date_fin: '', attestation: false,
    };
  }

  fermerForm(): void {
    this.formOuvert = false;
  }

  designer(): void {
    if (!this.formValide || this.enregistrement) return;
    this.enregistrement = true;
    this.errorMessage = '';
    this.service.designer({
      utilisateur: this.nouvelle.utilisateur,
      qualite_accordant: this.nouvelle.qualite_accordant as QualiteDesignataire,
      attestation_accordant: true,
      fonction: this.nouvelle.fonction.trim() || undefined,
      date_fin: this.nouvelle.date_fin || null,
    }).subscribe({
      next: () => {
        this.enregistrement = false;
        this.formOuvert = false;
        this.successMessage = "Habilitation prononcée. La personne devra signer son engagement "
          + "au secret professionnel à sa première ouverture du registre.";
        this.charger();
      },
      error: (err) => {
        this.enregistrement = false;
        this.errorMessage = messageErreurServeur(err, "La désignation n'a pas pu être enregistrée.");
      },
    });
  }

  retirer(habilitation: HabilitationRegistre): void {
    const motif = prompt(
      `Retirer l'habilitation de ${habilitation.utilisateur_nom} ?\n\n`
      + "Indiquez le motif (départ, changement de fonction, fin de mission...). "
      + "L'habilitation n'est pas supprimée : elle reste tracée, retirée à cette date."
    );
    if (motif === null) return;
    if (!motif.trim()) {
      this.errorMessage = 'Le retrait doit porter un motif.';
      return;
    }
    this.service.retirer(habilitation.id, motif.trim()).subscribe({
      next: () => {
        this.successMessage = 'Habilitation retirée.';
        this.charger();
      },
      error: (err) => this.errorMessage = messageErreurServeur(
        err, "Le retrait n'a pas pu être enregistré."),
    });
  }

}
