import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AssociationService } from '../../../../services/association.service';
import { ConservationPiecesService } from '../../../../services/conservation-pieces.service';
import { Qualification, QualificationMembre } from '../../../models/association.model';
import { PieceConservation } from '../../../models/conservation-piece.model';
import { ConservationPiecesComponent } from '../conservation-pieces/conservation-pieces.component';

/**
 * Déposer ses pièces justificatives, et suivre ce qu'elles deviennent.
 *
 * Demande de Sylvain du 13/11/2026 : *« dans mon compte, je mettrais ici la zone de dépôt des
 * documents et de consultation de leur acceptation / suivi »*.
 *
 * **Composant partagé, et non recopié.** Le dépôt existait dans « Ma fiche de bénévole » ; il
 * est maintenant attendu dans « Mon espace » également. Deux copies auraient divergé au
 * premier correctif — et ce formulaire-ci décide de la destruction d'un fichier, ce n'est pas
 * un endroit où se permettre deux vérités. Les deux pages affichent donc le même composant,
 * qui charge ses propres données.
 *
 * Ce qu'il montre, et dans cet ordre : d'abord **ce qui attend quelque chose de vous** (une
 * pièce refusée, un titre sans pièce), ensuite l'état de chaque titre, enfin le formulaire de
 * dépôt. Mettre le formulaire en premier obligerait à faire défiler pour savoir s'il y a
 * quelque chose à faire.
 */
@Component({
  selector: 'app-mes-justificatifs',
  standalone: true,
  imports: [CommonModule, FormsModule, ConservationPiecesComponent],
  templateUrl: './mes-justificatifs.component.html',
  styleUrl: './mes-justificatifs.component.scss',
})
export class MesJustificatifsComponent implements OnInit {
  chargement = true;
  enregistrement = false;
  message = '';
  erreur = '';

  catalogue: Qualification[] = [];
  mesQualifications: QualificationMembre[] = [];

  depot = { qualification: '', date_obtention: '', date_expiration: '', organisme: '' };
  fichierChoisi: File | null = null;

  /** Vrai sur un satellite : les fichiers déposés y restent, le central ne les verra pas. */
  surUnSatellite = false;

  constructor(
    private associationService: AssociationService,
    private conservationService: ConservationPiecesService,
  ) {}

  ngOnInit(): void {
    // Lu à part du reste : l'avertissement doit s'afficher même si le catalogue échoue, et
    // la table est déjà partagée entre les deux pages qui l'affichent.
    this.conservationService.table().subscribe({
      next: (table) => this.surUnSatellite = !!table.instance_satellite,
      error: () => this.surUnSatellite = false,
    });
    forkJoin({
      catalogue: this.associationService.getCatalogueQualifications(),
      miennes: this.associationService.getQualificationsMembres(),
    }).subscribe({
      next: ({ catalogue, miennes }) => {
        this.catalogue = catalogue.filter(q => q.actif);
        this.mesQualifications = miennes;
        this.chargement = false;
      },
      error: () => {
        this.erreur = 'Impossible de charger vos pièces.';
        this.chargement = false;
      },
    });
  }

  /** Ce qui arrivera à la pièce qu'on s'apprête à déposer. Annoncé AVANT l'envoi : apprendre
   * après coup que sa photo de permis a été détruite, ou au contraire conservée cinq ans,
   * n'est pas un consentement. */
  get regleDuTitreChoisi(): PieceConservation | null {
    return this.catalogue.find(q => q.id === this.depot.qualification)?.conservation ?? null;
  }

  onTitreChoisi(): void {
    const titre = this.catalogue.find(q => q.id === this.depot.qualification);
    const base = this.depot.date_obtention;
    if (!titre?.validite_mois || !base) { return; }
    const echeance = new Date(base + 'T00:00:00');
    echeance.setMonth(echeance.getMonth() + titre.validite_mois);
    this.depot.date_expiration = echeance.toISOString().slice(0, 10);
  }

  onFichier(evenement: Event): void {
    this.fichierChoisi = (evenement.target as HTMLInputElement).files?.[0] ?? null;
  }

  get depotPret(): boolean {
    return !!this.depot.qualification && !!this.fichierChoisi;
  }

  deposer(): void {
    if (!this.depotPret || !this.fichierChoisi) { return; }
    this.enregistrement = true;
    this.erreur = '';
    this.message = '';
    this.associationService.deposerJustificatif(this.depot.qualification, this.fichierChoisi, {
      date_obtention: this.depot.date_obtention,
      date_expiration: this.depot.date_expiration,
      organisme: this.depot.organisme,
    }).subscribe({
      next: (q) => {
        this.mesQualifications = [...this.mesQualifications.filter(x => x.id !== q.id), q];
        this.depot = { qualification: '', date_obtention: '', date_expiration: '',
                       organisme: '' };
        this.fichierChoisi = null;
        this.enregistrement = false;
        this.message = 'Pièce déposée. Votre encadrement en est informé et la vérifiera.';
      },
      error: (err) => {
        this.enregistrement = false;
        this.erreur = this.premierMessage(err)
          || "Impossible de déposer cette pièce (déjà présente pour ce titre ?).";
      },
    });
  }

  /** Remplacer une pièce refusée remet le titre à instruire : c'est la seule façon de
   * répondre à un refus. */
  remplacer(q: QualificationMembre, evenement: Event): void {
    const entree = evenement.target as HTMLInputElement;
    const fichier = entree.files?.[0];
    if (!fichier) { return; }
    this.enregistrement = true;
    this.associationService.remplacerJustificatif(q.id, fichier).subscribe({
      next: (maj) => {
        this.mesQualifications = this.mesQualifications.map(x => (x.id === maj.id ? maj : x));
        this.enregistrement = false;
        entree.value = '';
        this.message = 'Nouvelle pièce déposée. Elle repart en vérification.';
      },
      error: () => {
        this.enregistrement = false;
        entree.value = '';
        this.erreur = 'Impossible de remplacer cette pièce.';
      },
    });
  }

  /** Ce qui attend quelque chose de VOUS : un refus à corriger, un titre sans pièce. Mis en
   * tête, parce que c'est la seule raison d'ouvrir cette page quand tout va bien. */
  get aCorriger(): QualificationMembre[] {
    return this.mesQualifications.filter(q => q.statut === 'REFUSEE' || !q.a_justificatif);
  }

  get aUnRefus(): boolean {
    return this.mesQualifications.some(q => q.statut === 'REFUSEE');
  }

  get enAttenteDeVerification(): QualificationMembre[] {
    return this.mesQualifications.filter(q => q.statut === 'DECLAREE' && q.a_justificatif);
  }

  classeStatut(q: QualificationMembre): string {
    return q.statut.toLowerCase();
  }

  // ══ Le statut, dit en clair ═══════════════════════════════════════════════════════════
  //
  // Demande de Sylvain du 13/11/2026 : « permis : validé => photo détruite pour raisons de
  // confidentialité / attestation x : validée, vous pouvez la reconsulter en cliquant sur
  // l'œil ».
  //
  // « VERIFIEE » ne dit rien de ce qui est arrivé au FICHIER, et c'est pourtant la question
  // qu'on se pose en revenant sur cette page : est-ce que mon permis est encore quelque part ?
  // Deux titres au même statut peuvent avoir connu deux sorts opposés selon leur régime de
  // conservation. L'écran doit donc dire lequel, sans quoi une pièce disparue passe pour un
  // bug.

  etatLisible(q: QualificationMembre): string {
    if (q.statut === 'REFUSEE') {
      return q.motif_refus ? `Refusé — ${q.motif_refus}` : 'Refusé';
    }
    if (q.statut === 'VERIFIEE') {
      if (q.piece_detruite_le) {
        return 'Validé — la copie a été détruite, comme prévu pour ce type de document';
      }
      return q.a_justificatif
        ? 'Validé — vous pouvez le reconsulter'
        : 'Validé';
    }
    if (!q.a_justificatif) { return 'Aucun document déposé pour ce titre'; }
    return 'Déposé, en attente de vérification par votre encadrement';
  }

  /** Vrai quand la pièce est encore consultable : conditionne l'œil. Une icône qui ouvrirait
   * une erreur 404 serait pire que pas d'icône. */
  peutConsulter(q: QualificationMembre): boolean {
    return q.a_justificatif;
  }

  /** Ouvre la pièce dans un onglet. Passe par un blob et non par un lien direct : la route
   * exige l'en-tête d'authentification que pose l'intercepteur, qu'un `<a href>` n'enverrait
   * pas. L'URL temporaire est révoquée au bout d'une minute. */
  voirPiece(q: QualificationMembre): void {
    this.associationService.telechargerJustificatif(q.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      },
      error: () => this.erreur = "Impossible d'ouvrir cette pièce.",
    });
  }

  private premierMessage(err: unknown): string {
    const corps = (err as { error?: Record<string, unknown> })?.error;
    if (!corps) { return ''; }
    if (typeof corps === 'string') { return corps; }
    const direct = corps['detail'] ?? corps['error'];
    if (typeof direct === 'string') { return direct; }
    for (const valeur of Object.values(corps)) {
      if (typeof valeur === 'string') { return valeur; }
      if (Array.isArray(valeur) && typeof valeur[0] === 'string') { return valeur[0]; }
    }
    return '';
  }
}
