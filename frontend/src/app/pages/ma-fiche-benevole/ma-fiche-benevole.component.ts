import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { FicheBenevoleService } from '../../services/fiche-benevole.service';
import { AssociationService } from '../../services/association.service';
import { AuthService } from '../../auth/services/auth.service';
import {
  CRENEAUX, Creneau, FREQUENCES_ENGAGEMENT, FicheBenevole, JourCreneaux, MesDisponibilites,
  SITUATIONS,
} from '../../shared/models/fiche-benevole.model';
import { Qualification, QualificationMembre } from '../../shared/models/association.model';

type Onglet = 'fiche' | 'disponibilites' | 'justificatifs' | 'acces';

/**
 * « Ma fiche de bénévole » : ce que le membre d'une association voit de lui-même.
 *
 * C'est la page d'arrivée du lien d'activation reçu après un import (déroulé d'enrôlement du
 * 11/11/2026, points 3 à 5) : il relit ce que l'import a saisi à sa place, le corrige, dépose
 * ses justificatifs, et peut se donner un mot de passe.
 *
 * Trois partis pris que l'écran rend visibles :
 *
 * - **le mot de passe est facultatif.** Le lien magique continue de marcher. En imposer un
 *   juste après le premier clic ajoute une friction au pire moment ; l'onglet le propose, il
 *   ne le réclame pas.
 * - **le secteur ne se saisit pas.** Il vient du géocodage de l'adresse, et c'est lui qui place
 *   dans l'équipe départementale. Le laisser taper permettrait de se déclarer dans un
 *   département où l'on n'habite pas.
 * - **une qualification déposée n'est pas une qualification acquise.** L'écran affiche l'état
 *   d'instruction (déclarée / vérifiée / refusée) et le motif d'un refus, sans quoi le membre
 *   redépose la même pièce sans savoir ce qui n'allait pas.
 */
import {
  ConservationPiecesComponent,
} from '../../shared/components/common/conservation-pieces/conservation-pieces.component';
import { PieceConservation } from '../../shared/models/conservation-piece.model';

@Component({
  selector: 'app-ma-fiche-benevole',
  standalone: true,
  imports: [CommonModule, FormsModule, ConservationPiecesComponent],
  templateUrl: './ma-fiche-benevole.component.html',
  styleUrl: './ma-fiche-benevole.component.scss',
})
export class MaFicheBenevoleComponent implements OnInit {
  onglet: Onglet = 'fiche';
  chargement = true;
  enregistrement = false;
  erreur = '';
  message = '';
  avertissement = '';

  fiche: FicheBenevole | null = null;
  /** Copie de travail : la fiche servie reste la référence, pour pouvoir n'envoyer que ce qui
   * a changé — et surtout ne pas déclencher un regéocodage quand l'adresse n'a pas bougé. */
  saisie: Partial<FicheBenevole> = {};

  readonly SITUATIONS = SITUATIONS;
  readonly FREQUENCES_ENGAGEMENT = FREQUENCES_ENGAGEMENT;

  /** Grille personnelle : quinze jours × quatre créneaux, servie par le moteur unique. */
  disponibilites: MesDisponibilites | null = null;
  readonly CRENEAUX = CRENEAUX;
  /** Clé `date|creneau` en cours d'enregistrement, pour désactiver la seule case touchée
   * plutôt que toute la grille. */
  enregistrementEnCours = '';

  // ── Mot de passe ──────────────────────────────────────────────────────────
  motDePasse = '';
  motDePasseConfirme = '';

  // ── Justificatifs ─────────────────────────────────────────────────────────
  catalogue: Qualification[] = [];
  mesQualifications: QualificationMembre[] = [];
  depot = { qualification: '', date_obtention: '', date_expiration: '', organisme: '' };
  fichierChoisi: File | null = null;

  constructor(
    private ficheService: FicheBenevoleService,
    private associationService: AssociationService,
    private authService: AuthService,
    private route: ActivatedRoute,
  ) {}

  ngOnInit(): void {
    this.charger();
    // `?onglet=justificatifs` : permet d'arriver directement sur ses pièces depuis « Mon
    // espace ». Sans cela, le lien déposait les gens sur le formulaire d'identité, à charge
    // pour eux de retrouver l'onglet — c'est exactement ce qu'un lien doit éviter.
    this.route.queryParamMap.subscribe(params => {
      const demande = params.get('onglet');
      if (demande && (['fiche', 'disponibilites', 'justificatifs', 'acces'] as string[])
          .includes(demande)) {
        this.ouvrirOnglet(demande as Onglet);
      }
    });
  }

  private charger(): void {
    this.chargement = true;
    forkJoin({
      fiche: this.ficheService.maFiche(),
      catalogue: this.associationService.getCatalogueQualifications(),
      miennes: this.associationService.getQualificationsMembres(this.monId ?? undefined),
    }).subscribe({
      next: ({ fiche, catalogue, miennes }) => {
        this.appliquer(fiche);
        this.catalogue = catalogue.filter(q => q.actif);
        this.mesQualifications = miennes;
        this.chargement = false;
      },
      error: () => {
        this.erreur = 'Impossible de charger votre fiche.';
        this.chargement = false;
      },
    });
  }

  get monId(): string | null {
    return this.authService.getCurrentUser()?.id ?? null;
  }

  get monNom(): string {
    const moi = this.authService.getCurrentUser();
    if (!moi) { return ''; }
    return `${moi.first_name ?? ''} ${moi.last_name ?? ''}`.trim();
  }

  private appliquer(fiche: FicheBenevole): void {
    this.fiche = fiche;
    this.avertissement = fiche.avertissement ?? '';
    this.saisie = {
      adresse: fiche.adresse ?? '',
      code_postal: fiche.code_postal ?? '',
      ville: fiche.ville ?? '',
      date_naissance: fiche.date_naissance ?? null,
      metier: fiche.metier ?? '',
      situation: fiche.situation ?? '',
      frequence_engagement: fiche.frequence_engagement ?? '',
      message: fiche.message ?? '',
      diplome_premier_secours: !!fiche.diplome_premier_secours,
    };
  }

  /** Vrai quand l'adresse saisie diffère de celle enregistrée : l'écran annonce alors le
   * regéocodage, qui peut changer d'équipe départementale. Une personne doit savoir qu'en
   * corrigeant son adresse elle change d'équipe, pas le découvrir. */
  get adresseModifiee(): boolean {
    if (!this.fiche) { return false; }
    return (this.saisie.adresse ?? '') !== (this.fiche.adresse ?? '')
      || (this.saisie.code_postal ?? '') !== (this.fiche.code_postal ?? '')
      || (this.saisie.ville ?? '') !== (this.fiche.ville ?? '');
  }

  get secteurConnu(): boolean {
    return !!this.fiche?.departement_code;
  }

  enregistrer(): void {
    this.enregistrement = true;
    this.erreur = '';
    this.message = '';
    // `date_naissance` vide doit partir en null : l'API attend une date ou rien, jamais une
    // chaîne vide.
    const corps: Partial<FicheBenevole> = {
      ...this.saisie,
      date_naissance: this.saisie.date_naissance || null,
    };
    this.ficheService.enregistrer(corps).subscribe({
      next: (fiche) => {
        this.appliquer(fiche);
        this.enregistrement = false;
        this.message = this.avertissement
          ? 'Fiche enregistrée.'
          : 'Fiche enregistrée. Merci.';
      },
      error: (err) => {
        this.enregistrement = false;
        this.erreur = this.premierMessage(err) || "Impossible d'enregistrer votre fiche.";
      },
    });
  }

  // ══ Disponibilités (moteur unique) ════════════════════════════════════════

  ouvrirOnglet(onglet: Onglet): void {
    this.onglet = onglet;
    this.message = '';
    this.erreur = '';
    // Chargée à la première ouverture seulement : la grille n'intéresse pas qui vient
    // corriger son adresse, et c'est une requête de plus à l'arrivée.
    if (onglet === 'disponibilites' && !this.disponibilites) { this.chargerDisponibilites(); }
  }

  chargerDisponibilites(): void {
    this.ficheService.mesDisponibilites().subscribe({
      next: (grille) => this.disponibilites = grille,
      error: () => this.erreur = 'Impossible de charger vos disponibilités.',
    });
  }

  /** Vrai quand la personne n'a pas encore de ressource : elle n'a alors rien à déclarer, et
   * il faut le dire plutôt que de montrer une grille vide. */
  get sansRessource(): boolean {
    return !!this.disponibilites && this.disponibilites.ressources.length === 0;
  }

  estCoche(jour: JourCreneaux, creneau: Creneau): boolean {
    return !!jour.creneaux[creneau];
  }

  enCours(date: string, creneau?: Creneau): boolean {
    return this.enregistrementEnCours === `${date}|${creneau ?? ''}`;
  }

  /** Coche ou décoche un créneau. Deux états : ce moteur ne stocke pas de « non renseigné »,
   * « pas de ligne = indisponible » est sa règle depuis l'origine. */
  basculerCreneau(jour: JourCreneaux, creneau: Creneau): void {
    const vise = !jour.creneaux[creneau];
    this.enregistrementEnCours = `${jour.date}|${creneau}`;
    this.ficheService.declarerCreneau(jour.date, vise, creneau).subscribe({
      next: () => {
        jour.creneaux[creneau] = vise;
        this.enregistrementEnCours = '';
        this.erreur = '';
      },
      error: (err) => this.echecDeclaration(err),
    });
  }

  /** Toute la journée d'un coup. Soixante cases sur quinze jours, personne ne les coche une
   * par une — et une grille que personne ne remplit ne sert pas à armer une garde. */
  basculerJournee(jour: JourCreneaux): void {
    // Si tout n'est pas déjà coché, on coche tout : c'est le geste attendu quand on clique
    // « toute la journée » sur une journée à moitié remplie.
    const vise = !this.journeeComplete(jour);
    this.enregistrementEnCours = `${jour.date}|`;
    this.ficheService.declarerCreneau(jour.date, vise).subscribe({
      next: () => {
        for (const { creneau } of this.CRENEAUX) { jour.creneaux[creneau] = vise; }
        this.enregistrementEnCours = '';
        this.erreur = '';
      },
      error: (err) => this.echecDeclaration(err),
    });
  }

  journeeComplete(jour: JourCreneaux): boolean {
    return this.CRENEAUX.every(({ creneau }) => jour.creneaux[creneau]);
  }

  journeeVide(jour: JourCreneaux): boolean {
    return this.CRENEAUX.every(({ creneau }) => !jour.creneaux[creneau]);
  }

  /** La semaine entière, pour que remplir quinze jours ne demande pas quinze clics. */
  basculerToutesLesJournees(vise: boolean): void {
    const grille = this.disponibilites;
    if (!grille) { return; }
    // Séquentiel et non en parallèle : quinze requêtes simultanées sur le même jeu de lignes,
    // c'est quinze fois l'occasion d'un conflit pour un gain invisible à l'œil.
    const suivant = (index: number): void => {
      if (index >= grille.jours.length) {
        this.enregistrementEnCours = '';
        return;
      }
      const jour = grille.jours[index];
      this.enregistrementEnCours = `${jour.date}|`;
      this.ficheService.declarerCreneau(jour.date, vise).subscribe({
        next: () => {
          for (const { creneau } of this.CRENEAUX) { jour.creneaux[creneau] = vise; }
          suivant(index + 1);
        },
        error: (err) => this.echecDeclaration(err),
      });
    };
    suivant(0);
  }

  /** La case n'est PAS modifiée : une case qui change d'apparence sans que le serveur l'ait
   * enregistrée est pire qu'un refus visible — on partirait sur une disponibilité
   * imaginaire. */
  private echecDeclaration(err: unknown): void {
    this.enregistrementEnCours = '';
    this.erreur = this.premierMessage(err)
      || "Impossible d'enregistrer cette disponibilité.";
  }

  /** Jour de la semaine abrégé + numéro : « sa 14 » se lit mieux que « 2026-11-14 ». */
  enTeteJour(iso: string): string {
    const d = new Date(iso + 'T00:00:00');
    const jours = ['di', 'lu', 'ma', 'me', 'je', 've', 'sa'];
    return `${jours[d.getDay()]} ${d.getDate()}`;
  }

  estWeekEnd(iso: string): boolean {
    const jour = new Date(iso + 'T00:00:00').getDay();
    return jour === 0 || jour === 6;
  }

  // ══ Mot de passe ══════════════════════════════════════════════════════════

  get motsDePasseConcordent(): boolean {
    return !!this.motDePasse && this.motDePasse === this.motDePasseConfirme;
  }

  definirMotDePasse(): void {
    if (!this.motsDePasseConcordent) {
      this.erreur = 'Les deux mots de passe saisis ne sont pas identiques.';
      return;
    }
    this.enregistrement = true;
    this.erreur = '';
    this.message = '';
    this.ficheService.definirMotDePasse(this.motDePasse).subscribe({
      next: (res) => {
        this.enregistrement = false;
        this.motDePasse = '';
        this.motDePasseConfirme = '';
        if (this.fiche) { this.fiche = { ...this.fiche, mot_de_passe_defini: true }; }
        this.message = res.message
          || 'Mot de passe enregistré. Votre lien par email continue de fonctionner.';
      },
      error: (err) => {
        this.enregistrement = false;
        // Le serveur renvoie les règles de robustesse non respectées, écrites pour être lues :
        // les remplacer par « mot de passe invalide » laisserait chercher laquelle.
        this.erreur = this.premierMessage(err) || "Ce mot de passe n'a pas été accepté.";
      },
    });
  }

  // ══ Justificatifs ═════════════════════════════════════════════════════════

  /** Préremplit l'échéance depuis la durée habituelle du titre — une proposition, pas une
   * contrainte : c'est la date portée par l'attestation qui fait foi. */
  /** Ce qui arrivera à la pièce qu'on s'apprête à déposer. Annoncé AVANT l'envoi : apprendre
   * après coup que sa photo de permis a été détruite, ou au contraire conservée cinq ans,
   * n'est pas un consentement. */
  get regleDuTitreChoisi(): PieceConservation | null {
    const titre = this.catalogue.find(q => q.id === this.depot.qualification);
    return titre?.conservation ?? null;
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
    const entree = evenement.target as HTMLInputElement;
    this.fichierChoisi = entree.files?.[0] ?? null;
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

  /** Les titres encore sans pièce : ce qui reste à faire, mis en avant plutôt que caché dans
   * la liste déroulante. */
  get titresSansPiece(): QualificationMembre[] {
    return this.mesQualifications.filter(q => !q.a_justificatif);
  }

  get aUnRefus(): boolean {
    return this.mesQualifications.some(q => q.statut === 'REFUSEE');
  }

  classeStatut(q: QualificationMembre): string {
    return q.statut.toLowerCase();
  }

  /** Ouvre la pièce dans un onglet. Passe par un blob et non par un lien direct : la route
   * exige l'en-tête d'authentification que pose l'intercepteur, qu'un `<a href>` n'enverrait
   * pas. L'URL temporaire est révoquée au bout d'une minute — assez pour que l'onglet ait
   * chargé, assez tôt pour ne pas laisser le fichier en mémoire. */
  voirPiece(q: QualificationMembre): void {
    this.associationService.telechargerJustificatif(q.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      },
      error: () => this.erreur = 'Impossible d\'ouvrir cette pièce.',
    });
  }

  /** Premier message lisible d'une réponse d'erreur DRF, qu'elle porte `detail`, `error` ou
   * une liste par champ. Sans ça, une erreur de validation s'affiche « [object Object] ». */
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
