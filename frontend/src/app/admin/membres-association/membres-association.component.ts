import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AssociationService } from '../../services/association.service';
import { AuthService } from '../../auth/services/auth.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { InstitutionService } from '../../services/institution.service';
import {
  CandidatureAssociation, ETAPES_CIRCUIT, EtapeCandidature, GrilleDisponibilites,
  InvitationAssociation, Qualification, QualificationMembre, StatutMembre,
} from '../../shared/models/association.model';
import { ContactInstitution, Institution } from '../../shared/models/institution.model';

type Onglet = 'membres' | 'candidatures' | 'disponibilites' | 'liens';

/**
 * Gestion des membres d'une association agréée de sécurité civile : annuaire, recrutement,
 * qualifications et disponibilités.
 *
 * Quatre onglets plutôt que quatre pages : ce sont quatre vues du même effectif, et un
 * président qui instruit une candidature a besoin de voir dans la foulée ce que la personne
 * apporte et quand elle est libre. Les séparer obligerait à naviguer entre des écrans qui
 * parlent des mêmes gens.
 *
 * Deux partis pris que l'écran rend visibles, parce qu'ils décident de vraies mobilisations :
 *
 * - **une disponibilité a trois valeurs**, pas deux. Un blanc n'est pas un refus : c'est un
 *   silence, et la grille le montre comme tel pour qu'on sache qui relancer. Confondre les deux
 *   fait partir une mobilisation avec un effectif imaginaire ;
 * - **une qualification périmée vaut une qualification absente**, donc elle s'affiche à côté du
 *   nom et pas dans un sous-menu. On ne découvre pas un PSE1 expiré le jour du départ.
 *
 * L'écriture est réservée au bureau (ContactInstitution.membre_bureau) ; le serveur l'impose de
 * son côté, cette page ne fait que ne pas proposer ce qui sera refusé.
 */
@Component({
  selector: 'app-membres-association',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './membres-association.component.html',
  styleUrl: './membres-association.component.scss',
})
export class MembresAssociationComponent implements OnInit {
  onglet: Onglet = 'membres';
  chargement = true;
  erreur = '';
  message = '';

  /** Les institutions dont je suis au bureau. Plusieurs sont possibles — on est au bureau
   * d'une association précise, pas « du bureau » en général. */
  mesInstitutions: Institution[] = [];
  institutionChoisie: string | null = null;

  membres: ContactInstitution[] = [];
  candidatures: CandidatureAssociation[] = [];
  invitations: InvitationAssociation[] = [];
  catalogue: Qualification[] = [];
  qualifications: QualificationMembre[] = [];
  grille: GrilleDisponibilites | null = null;
  joursGrille = 15;

  readonly ETAPES = ETAPES_CIRCUIT;
  readonly LIBELLES_STATUT: Record<StatutMembre, string> = {
    ACTIF: 'Actif', CONGE: 'En congé', SORTI: 'Sorti',
  };

  /** Fenêtre d'alerte sur les échéances. Trente jours : assez tôt pour reprogrammer une
   * formation, assez tard pour ne pas noyer l'écran d'avertissements sans objet. */
  readonly JOURS_ALERTE = 30;

  // Saisie d'une nouvelle qualification.
  membreSelectionne: string | null = null;
  nouvelleQualification = { qualification: '', date_obtention: '', date_expiration: '',
                            organisme: '' };

  // Saisie d'un lien d'invitation.
  nouveauLien = { libelle: '', date_expiration: '' };
  refusEnCours: { id: string; motif: string } | null = null;

  constructor(
    private associationService: AssociationService,
    private contactService: ContactInstitutionService,
    private institutionService: InstitutionService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.charger();
  }

  private charger(): void {
    this.chargement = true;
    const moi = this.authService.getCurrentUser();
    forkJoin({
      contacts: this.contactService.getAll(),
      institutions: this.institutionService.getAll(),
      catalogue: this.associationService.getCatalogueQualifications(),
    }).subscribe({
      next: ({ contacts, institutions, catalogue }) => {
        this.catalogue = catalogue.filter(q => q.actif);
        const auBureau = contacts.filter(
          c => c.utilisateur === moi?.id && c.actif && c.membre_bureau);
        const ids = new Set(auBureau.map(c => c.institution));
        const liste = Array.isArray(institutions) ? institutions
          : (institutions as { results?: Institution[] }).results ?? [];
        this.mesInstitutions = liste.filter(i => i.id && ids.has(i.id));
        this.institutionChoisie = this.mesInstitutions[0]?.id ?? null;
        this.chargement = false;
        if (this.institutionChoisie) { this.chargerInstitution(); }
      },
      error: () => {
        this.erreur = 'Impossible de charger vos associations.';
        this.chargement = false;
      },
    });
  }

  changerInstitution(id: string): void {
    this.institutionChoisie = id || null;
    this.grille = null;
    this.membreSelectionne = null;
    if (this.institutionChoisie) { this.chargerInstitution(); }
  }

  private chargerInstitution(): void {
    const id = this.institutionChoisie;
    if (!id) { return; }
    this.contactService.getForInstitution(id).subscribe({
      next: (membres) => this.membres = membres,
      error: () => this.erreur = "Impossible de charger l'annuaire des membres.",
    });
    this.associationService.getCandidatures(id).subscribe({
      next: (c) => this.candidatures = c,
      error: () => undefined,
    });
    this.associationService.getInvitations().subscribe({
      next: (liens) => this.invitations = liens.filter(l => l.institution === id),
      error: () => undefined,
    });
    this.associationService.getQualificationsMembres().subscribe({
      next: (q) => this.qualifications = q,
      error: () => undefined,
    });
  }

  // ══ Annuaire ══════════════════════════════════════════════════════════════

  /** Les sortis en dernier, puis par nom : un ancien membre reste consultable mais ne doit pas
   * occuper le haut de l'annuaire. */
  get membresTries(): ContactInstitution[] {
    const rang = (c: ContactInstitution) => c.statut === 'SORTI' ? 2
      : c.statut === 'CONGE' ? 1 : 0;
    return [...this.membres].sort((a, b) =>
      rang(a) - rang(b)
      || (a.utilisateur_nom ?? '').localeCompare(b.utilisateur_nom ?? '', 'fr'));
  }

  get compteActifs(): number {
    return this.membres.filter(m => m.statut !== 'SORTI' && m.statut !== 'CONGE').length;
  }

  get compteBureau(): number {
    return this.membres.filter(m => m.membre_bureau).length;
  }

  libelleStatut(statut?: StatutMembre): string {
    return statut ? this.LIBELLES_STATUT[statut] : '—';
  }

  /** Jours restants avant une échéance, négatif si dépassée, null si aucune date.
   *
   * Calculé sur la date du navigateur, et c'est assumé ici : ce n'est qu'un affichage. Les
   * décisions (titre périmé ou non) viennent du serveur, qui ne dépend pas de l'horloge du
   * poste — voir QualificationMembre.expiree. */
  joursRestants(date?: string | null): number | null {
    if (!date) { return null; }
    const cible = new Date(date + 'T00:00:00');
    const aujourdhui = new Date();
    aujourdhui.setHours(0, 0, 0, 0);
    return Math.round((cible.getTime() - aujourdhui.getTime()) / 86400000);
  }

  /** '' (rien à signaler), 'bientot' ou 'depasse' — sert les classes CSS et le tri visuel. */
  etatEcheance(date?: string | null): '' | 'bientot' | 'depasse' {
    const jours = this.joursRestants(date);
    if (jours === null) { return ''; }
    if (jours < 0) { return 'depasse'; }
    return jours <= this.JOURS_ALERTE ? 'bientot' : '';
  }

  changerStatut(membre: ContactInstitution, statut: StatutMembre): void {
    if (!membre.id || membre.statut === statut) { return; }
    this.enregistrerMembre(membre, { statut });
  }

  basculerBureau(membre: ContactInstitution): void {
    this.enregistrerMembre(membre, { membre_bureau: !membre.membre_bureau });
  }

  enregistrerChamp(membre: ContactInstitution, champ: keyof ContactInstitution,
                   valeur: unknown): void {
    if (membre[champ] === valeur) { return; }
    this.enregistrerMembre(membre, { [champ]: valeur } as Partial<ContactInstitution>);
  }

  private enregistrerMembre(membre: ContactInstitution,
                            modif: Partial<ContactInstitution>): void {
    if (!membre.id) { return; }
    this.contactService.update(membre.id, { ...membre, ...modif }).subscribe({
      next: (maj) => {
        this.membres = this.membres.map(m => (m.id === maj.id ? maj : m));
        // Un membre sorti perd ses accès (règle tenue au modèle) : le dire, sinon le bureau
        // croit n'avoir changé qu'une étiquette.
        this.message = modif.statut === 'SORTI'
          ? 'Membre sorti : son rattachement est désactivé et ses accès retirés.'
          : 'Enregistré.';
        this.erreur = '';
      },
      error: () => this.erreur = "Impossible d'enregistrer cette modification.",
    });
  }

  // ══ Qualifications ════════════════════════════════════════════════════════

  qualificationsDe(utilisateurId: string): QualificationMembre[] {
    return this.qualifications.filter(q => q.utilisateur === utilisateurId);
  }

  nomQualification(id: string): string {
    return this.catalogue.find(q => q.id === id)?.nom ?? id;
  }

  ouvrirSaisie(membre: ContactInstitution): void {
    this.membreSelectionne = this.membreSelectionne === membre.utilisateur
      ? null : membre.utilisateur;
    this.nouvelleQualification = { qualification: '', date_obtention: '',
                                   date_expiration: '', organisme: '' };
  }

  /** Préremplit l'échéance depuis la durée habituelle du titre — une proposition, pas une
   * contrainte : c'est la date portée par l'attestation réelle qui fait foi. */
  onQualificationChoisie(): void {
    const titre = this.catalogue.find(q => q.id === this.nouvelleQualification.qualification);
    const base = this.nouvelleQualification.date_obtention;
    if (!titre?.validite_mois || !base) { return; }
    const echeance = new Date(base + 'T00:00:00');
    echeance.setMonth(echeance.getMonth() + titre.validite_mois);
    this.nouvelleQualification.date_expiration = echeance.toISOString().slice(0, 10);
  }

  enregistrerQualification(): void {
    if (!this.membreSelectionne || !this.nouvelleQualification.qualification) { return; }
    const { qualification, date_obtention, date_expiration, organisme } =
      this.nouvelleQualification;
    this.associationService.enregistrerQualification({
      utilisateur: this.membreSelectionne,
      qualification,
      date_obtention: date_obtention || null,
      date_expiration: date_expiration || null,
      organisme: organisme || null,
    }).subscribe({
      next: (q) => {
        this.qualifications = [...this.qualifications, q];
        this.membreSelectionne = null;
        this.message = 'Qualification enregistrée.';
      },
      error: (err) => this.erreur = err?.error?.detail
        || "Impossible d'enregistrer cette qualification (déjà présente ?).",
    });
  }

  supprimerQualification(q: QualificationMembre): void {
    this.associationService.supprimerQualification(q.id).subscribe({
      next: () => this.qualifications = this.qualifications.filter(x => x.id !== q.id),
      error: () => this.erreur = 'Impossible de supprimer cette qualification.',
    });
  }

  // ══ Candidatures ══════════════════════════════════════════════════════════

  get candidaturesEnCours(): CandidatureAssociation[] {
    return this.candidatures.filter(c => c.etape !== 'ACCEPTE' && c.etape !== 'REFUSE');
  }

  get candidaturesCloturees(): CandidatureAssociation[] {
    return this.candidatures.filter(c => c.etape === 'ACCEPTE' || c.etape === 'REFUSE');
  }

  rangEtape(etape: EtapeCandidature): number {
    const i = this.ETAPES.indexOf(etape);
    return i < 0 ? -1 : i;
  }

  etapeFranchie(candidature: CandidatureAssociation, etape: EtapeCandidature): boolean {
    return this.rangEtape(candidature.etape) >= this.rangEtape(etape);
  }

  prendreEnCharge(c: CandidatureAssociation): void {
    this.agir(this.associationService.prendreEnCharge(c.id), 'Dossier pris en charge.');
  }

  marquerVerifiee(c: CandidatureAssociation): void {
    this.agir(this.associationService.marquerVerifiee(c.id),
              'Pièces et qualifications vérifiées.');
  }

  accepter(c: CandidatureAssociation): void {
    this.agir(this.associationService.accepter(c.id),
              'Candidature acceptée : le compte est activé et la personne rattachée.');
  }

  ouvrirRefus(c: CandidatureAssociation): void {
    this.refusEnCours = { id: c.id, motif: '' };
  }

  confirmerRefus(): void {
    if (!this.refusEnCours?.motif.trim()) { return; }
    const { id, motif } = this.refusEnCours;
    this.refusEnCours = null;
    this.agir(this.associationService.refuser(id, motif.trim()), 'Candidature refusée.');
  }

  private agir(appel: ReturnType<AssociationService['accepter']>, succes: string): void {
    appel.subscribe({
      next: (maj) => {
        this.candidatures = this.candidatures.map(c => (c.id === maj.id ? maj : c));
        this.message = succes;
        this.erreur = '';
        // Une acceptation change l'annuaire : la personne y entre comme membre.
        if (maj.etape === 'ACCEPTE') { this.chargerInstitution(); }
      },
      // Le serveur renvoie un message écrit pour être lu par un agent (sens du circuit,
      // droits) : on l'affiche tel quel plutôt que de le remplacer par une phrase générique.
      error: (err) => this.erreur = err?.error?.error || "L'action a échoué.",
    });
  }

  // ══ Liens d'invitation ════════════════════════════════════════════════════

  lienComplet(invitation: InvitationAssociation): string {
    return `${window.location.origin}/inscription?invitation=${invitation.jeton}`;
  }

  copierLien(invitation: InvitationAssociation): void {
    navigator.clipboard?.writeText(this.lienComplet(invitation)).then(
      () => this.message = 'Lien copié.',
      () => this.erreur = 'Copie impossible : sélectionnez le lien à la main.',
    );
  }

  creerLien(): void {
    if (!this.institutionChoisie) { return; }
    this.associationService.creerInvitation(
      this.institutionChoisie, this.nouveauLien.libelle.trim(),
      this.nouveauLien.date_expiration || null,
    ).subscribe({
      next: (lien) => {
        this.invitations = [lien, ...this.invitations];
        this.nouveauLien = { libelle: '', date_expiration: '' };
        this.message = 'Lien créé. Il pose une candidature, il n\'accorde aucun accès.';
      },
      error: () => this.erreur = 'Impossible de créer ce lien.',
    });
  }

  desactiverLien(lien: InvitationAssociation): void {
    this.associationService.desactiverInvitation(lien.id).subscribe({
      next: (maj) => this.invitations = this.invitations.map(
        l => (l.id === maj.id ? maj : l)),
      error: () => this.erreur = 'Impossible de désactiver ce lien.',
    });
  }

  // ══ Disponibilités ════════════════════════════════════════════════════════

  chargerGrille(): void {
    if (!this.institutionChoisie) { return; }
    this.associationService.getGrille(this.institutionChoisie, this.joursGrille).subscribe({
      next: (g) => { this.grille = g; this.erreur = ''; },
      error: (err) => this.erreur = err?.error?.error
        || 'Impossible de charger les disponibilités.',
    });
  }

  ouvrirOnglet(onglet: Onglet): void {
    this.onglet = onglet;
    this.message = '';
    this.erreur = '';
    if (onglet === 'disponibilites' && !this.grille) { this.chargerGrille(); }
  }

  /** 'oui' | 'non' | 'silence'. Trois valeurs et non deux : un blanc n'est pas un refus, et la
   * grille doit permettre de voir qui n'a pas répondu. */
  etatJour(disponible: boolean | null): 'oui' | 'non' | 'silence' {
    if (disponible === true) { return 'oui'; }
    if (disponible === false) { return 'non'; }
    return 'silence';
  }

  /** Jour de la semaine sur deux lettres + numéro : une grille de quinze colonnes n'a pas la
   * place d'une date complète, et « sa 7 » se lit mieux que « 2026-11-07 ». */
  enTeteJour(iso: string): string {
    const d = new Date(iso + 'T00:00:00');
    const jours = ['di', 'lu', 'ma', 'me', 'je', 've', 'sa'];
    return `${jours[d.getDay()]} ${d.getDate()}`;
  }

  estWeekEnd(iso: string): boolean {
    const jour = new Date(iso + 'T00:00:00').getDay();
    return jour === 0 || jour === 6;
  }

  comptePourJour(index: number, etat: 'oui' | 'non' | 'silence'): number {
    if (!this.grille) { return 0; }
    return this.grille.membres.filter(
      m => this.etatJour(m.jours[index]?.disponible ?? null) === etat).length;
  }
}
