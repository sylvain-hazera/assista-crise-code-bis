import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AssociationService } from '../../services/association.service';
import { AuthService } from '../../auth/services/auth.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { InstitutionService } from '../../services/institution.service';
import {
  AnnuaireAssociation, CandidatureAssociation, ETAPES_CIRCUIT, EtapeCandidature,
  GrilleDisponibilites, InvitationAssociation, LIBELLES_ROLE_EQUIPE, MembreAnnuaire,
  Qualification, QualificationMembre, QualificationsAVerifier, RoleDansEquipe,
  StatutMembre,
} from '../../shared/models/association.model';
import { Team, rangEchelon } from '../../shared/models/team.model';
import { TeamService } from '../../services/team.service';
import { CrisisService } from '../../services/crisis.service';
import { Crisis } from '../../shared/models/crisis.model';
import { ContactInstitution, Institution } from '../../shared/models/institution.model';
import { BlocAjoutComponent, ChampInvitation } from '../../shared/components/common/bloc-ajout/bloc-ajout.component';
import { environment } from '../../../environments/environment';

type Onglet = 'membres' | 'arborescence' | 'candidatures' | 'disponibilites' | 'liens';

/** Un nœud de l'arborescence des équipes. Construit côté client à partir de `equipe_parente` :
 * le serveur sert une liste plate, et la hiérarchie est déjà dans les données. */
export interface NoeudEquipe {
  equipe: Team;
  enfants: NoeudEquipe[];
  /** Pièces en attente de vérification pour les membres de CETTE équipe seulement. */
  aVerifier: number;
  /** Idem, en comptant toutes les équipes en dessous : c'est ce nombre que porte la pastille
   * d'une branche repliée, sinon replier une branche masquerait ce qui attend dedans. */
  aVerifierTotal: number;
  /** Les deux cadres dépliables de l'équipe, calculés une fois par `recalculerLesVues()` et
   * non à chaque appel du gabarit : avec 125 équipes, trier et filtrer dans une expression de
   * template se refait à chaque cycle de détection de changements. */
  cadres: MembreAnnuaire[];
  groupes: GroupePersonnes[];
  /** Combien de personnes de CETTE équipe passent le filtre courant. */
  correspondants: number;
  /** Idem, branche entière : c'est lui qui permet d'ouvrir ce qui correspond à une recherche
   * sans déplier les 125 équipes. */
  correspondantsTotal: number;
}

/** Un bloc de personnes à l'intérieur du second cadre d'une équipe : les cadres d'une
 * sous-équipe, ou les intervenants de l'équipe elle-même. */
export interface GroupePersonnes {
  cle: string;
  libelle: string;
  /** Équipe d'où viennent ces personnes — sert à afficher leur rôle dans LA BONNE équipe. */
  equipeId: string;
  membres: MembreAnnuaire[];
}

export type TriAnnuaire = 'nom' | 'fonction' | 'commune' | 'perimes' | 'silencieux';

/** Code de l'InstitutionType des AASC -- compare en insensible a la casse, comme cote serveur
 * (institution_attachment.CODE_TYPE_AASC) : les lignes de catalogue existent en « AASC »
 * comme en « aasc » selon la facon dont elles ont ete creees. */
const CODE_TYPE_AASC = 'aasc';

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
  imports: [CommonModule, FormsModule, BlocAjoutComponent],
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

  // ── Les trois gestes d'ajout (BlocAjoutComponent) ──────────────────────────
  // L'import de « personnel communal » sert ici tel quel : il cree des comptes rattaches a
  // l'institution DE L'APPELANT, qui pour un membre du bureau est l'association. Pas besoin
  // d'un second importeur au vocabulaire identique.
  readonly urlExemplePersonnel = `${environment.apiUrl}/imports/personnel-communal/exemple/`;
  readonly urlImportPersonnel = `${environment.apiUrl}/imports/personnel-communal/`;
  readonly urlInvitationContact = `${environment.apiUrl}/contacts-institutions/inviter/`;

  readonly champsInvitationMembre: ChampInvitation[] = [
    { cle: 'email', label: 'Adresse email', type: 'email', requis: true,
      placeholder: 'prenom.nom@exemple.fr' },
    { cle: 'fonction', label: 'Fonction dans l\'association',
      placeholder: 'Equipier, chef d\'equipe, tresorier...' },
    { cle: 'first_name', label: 'Prenom' },
    { cle: 'last_name', label: 'Nom' },
  ];
  /** Un administrateur voit toutes les institutions, pas seulement celles dont il est au
   * bureau — c'est ce que le serveur lui accorde déjà. */
  estAdministrateur = false;

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

  // ── Arborescence des équipes et vérification des justificatifs ──────────────
  equipes: Team[] = [];
  arborescence: NoeudEquipe[] = [];
  /** Ids des équipes DÉPLIÉES. Un ensemble des dépliées et non des repliées : une
   * arborescence de 125 équipes doit s'ouvrir refermée, sinon la page s'ouvre sur un mur. */
  depliees = new Set<string>();
  aVerifier: QualificationsAVerifier = { total: 0, par_membre: {} };
  refusPieceEnCours: { id: string; motif: string } | null = null;

  // ── Annuaire enrichi, recherche, sélection ─────────────────────────────────
  /** L'effectif indexé par utilisateur. Sert les fiches, la recherche et les filtres. */
  annuaire = new Map<string, MembreAnnuaire>();
  /** Faux = le lecteur n'est pas au bureau. L'écran doit alors DIRE qu'il ne voit pas les
   * coordonnées, pas les afficher vides : « — » affirmerait qu'il n'y a pas de téléphone. */
  coordonneesVisibles = false;
  rolesParEquipe: Record<string, Record<string, RoleDansEquipe>> = {};
  readonly LIBELLES_ROLE = LIBELLES_ROLE_EQUIPE;

  recherche = '';
  tri: TriAnnuaire = 'nom';
  filtreRole: '' | RoleDansEquipe = '';
  filtreCompetence = '';
  filtreBureau = false;
  filtreSansDeclaration = false;
  filtreTitresPerimes = false;
  filtreSansRessource = false;

  /** Clés `equipeId:cadres` et `equipeId:niveau` : les deux cadres se replient séparément. */
  cadresDeplies = new Set<string>();
  detailsEquipe = new Set<string>();
  detailsMembre = new Set<string>();

  /** Sélection multiple, par identifiant d'utilisateur. Volontairement transverse à l'arbre :
   * on compose une équipe terrain en piochant dans plusieurs branches. */
  selection = new Set<string>();
  equipeCible: string | null = null;
  missionTitre = '';
  criseCible: string | null = null;
  crises: Crisis[] = [];
  affectationEnCours = false;
  refusAffectation: { nom: string; motif: string }[] = [];

  // Saisie d'un lien d'invitation.
  nouveauLien = { libelle: '', date_expiration: '' };
  refusEnCours: { id: string; motif: string } | null = null;

  constructor(
    private associationService: AssociationService,
    private contactService: ContactInstitutionService,
    private institutionService: InstitutionService,
    private authService: AuthService,
    private teamService: TeamService,
    private crisisService: CrisisService,
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
        const liste = Array.isArray(institutions) ? institutions
          : (institutions as { results?: Institution[] }).results ?? [];
        // Un administrateur accède à toutes : le serveur l'y autorise (voir
        // recrutement_association.peut_instruire) parce qu'il doit pouvoir débloquer une
        // association dont le bureau a perdu ses accès. Ne rien lui proposer ici fermait la
        // page à celui-là même qui en a le droit — constaté en essayant la page le 28/10/2026.
        this.estAdministrateur = moi?.type === 'ADMIN';
        // Deux filtres qui s'appliquent a TOUT LE MONDE, administrateur compris :
        //
        // - `actif` : une institution fusionnee est conservee comme pierre tombale
        //   (actif=False, nom suffixe « [fusionnee dans ...] », voir la commande
        //   fusionner_institutions). La proposer revenait a offrir de gerer les membres d'une
        //   association qui n'existe plus -- constate le 28/10/2026 sur Chateauneuf-du-Faou.
        // - `type_code === aasc` : cette page ne parle que d'associations agreees de securite
        //   civile. Une mairie n'a rien a y faire, et un administrateur n'a pas davantage de
        //   raison de voir des mairies dans un selecteur d'associations.
        const associations = liste.filter(
          i => i.id && i.actif !== false
            && (i.type_code || '').toLowerCase() === CODE_TYPE_AASC);

        if (this.estAdministrateur) {
          this.mesInstitutions = associations;
        } else {
          const auBureau = contacts.filter(
            c => c.utilisateur === moi?.id && c.actif && c.membre_bureau);
          const ids = new Set(auBureau.map(c => c.institution));
          this.mesInstitutions = associations.filter(i => ids.has(i.id!));
        }
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
    // Une sélection faite dans une association n'a aucun sens dans une autre : la garder
    // ferait proposer d'affecter des gens que l'équipe cible ne peut pas accueillir.
    this.selection.clear();
    this.equipeCible = null;
    this.annuaire.clear();
    if (this.institutionChoisie) { this.chargerInstitution(); }
  }

  // Public : appelee depuis le template par le bloc d'ajout (AOT refuse un membre prive).
  chargerInstitution(): void {
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
      next: (q) => { this.qualifications = q; this.construireArborescence(); },
      error: () => undefined,
    });
    this.teamService.getAll().subscribe({
      next: (equipes) => {
        this.equipes = equipes.filter(e => e.institution === id && e.actif !== false);
        this.construireArborescence();
      },
      error: () => undefined,
    });
    this.associationService.getAnnuaire(id).subscribe({
      next: (a) => this.appliquerAnnuaire(a),
      // Silencieux : l'arbre reste lisible sans l'annuaire (noms et justificatifs viennent
      // d'ailleurs). Afficher une erreur ferait croire la page cassée alors que l'essentiel
      // est là — mais les fiches, elles, diront qu'elles n'ont rien à montrer.
      error: () => this.appliquerAnnuaire(
        { institution: id, institution_nom: '', membres: [], coordonnees_visibles: false,
          roles_par_equipe: {} }),
    });
    this.chargerAVerifier();
  }

  private appliquerAnnuaire(a: AnnuaireAssociation): void {
    this.annuaire = new Map(a.membres.map(m => [m.utilisateur, m]));
    this.coordonneesVisibles = a.coordonnees_visibles;
    this.rolesParEquipe = a.roles_par_equipe ?? {};
    this.construireArborescence();
  }

  // ══ Arborescence et justificatifs ═════════════════════════════════════════

  /** Le compteur de la pastille. Rechargé après chaque décision : c'est le serveur qui sait ce
   * qui reste à instruire, et un décompte tenu localement finirait par mentir. */
  chargerAVerifier(): void {
    this.associationService.qualificationsAVerifier().subscribe({
      next: (res) => { this.aVerifier = res; this.construireArborescence(); },
      // Silencieux : un compte sans encadrement n'a rien à vérifier, et le serveur peut
      // légitimement refuser. Afficher une erreur ferait croire la page cassée.
      error: () => this.aVerifier = { total: 0, par_membre: {} },
    });
  }

  /** Reconstruit l'arbre depuis la liste plate. Rappelée à chaque arrivée de données plutôt
   * que mémorisée : les trois sources (équipes, qualifications, compteurs) arrivent dans un
   * ordre non garanti. */
  private construireArborescence(): void {
    const noeuds = new Map<string, NoeudEquipe>();
    for (const equipe of this.equipes) {
      if (!equipe.id) { continue; }
      noeuds.set(equipe.id, {
        equipe, enfants: [], aVerifier: 0, aVerifierTotal: 0,
        cadres: [], groupes: [], correspondants: 0, correspondantsTotal: 0,
      });
    }

    const racines: NoeudEquipe[] = [];
    for (const noeud of noeuds.values()) {
      const parent = noeud.equipe.equipe_parente
        ? noeuds.get(noeud.equipe.equipe_parente) : undefined;
      // Une équipe dont le parent n'est pas dans la liste (parent d'une autre institution,
      // ou désactivé) devient racine : sinon elle disparaîtrait de l'écran sans que rien ne
      // le dise.
      if (parent && parent !== noeud) { parent.enfants.push(noeud); } else { racines.push(noeud); }
    }

    const compter = (noeud: NoeudEquipe, vus: Set<string>): number => {
      // Garde-fou : un cycle dans `equipe_parente` ferait tourner la page indéfiniment.
      if (noeud.equipe.id && vus.has(noeud.equipe.id)) { return 0; }
      if (noeud.equipe.id) { vus.add(noeud.equipe.id); }
      noeud.enfants.sort((a, b) =>
        rangEchelon(a.equipe.echelon) - rangEchelon(b.equipe.echelon)
        || a.equipe.name.localeCompare(b.equipe.name, 'fr'));
      noeud.aVerifier = (noeud.equipe.member_ids ?? []).reduce(
        (total, id) => total + (this.aVerifier.par_membre[id]?.length ?? 0), 0);
      noeud.aVerifierTotal = noeud.aVerifier
        + noeud.enfants.reduce((total, enfant) => total + compter(enfant, vus), 0);
      return noeud.aVerifierTotal;
    };
    const vus = new Set<string>();
    racines.forEach(r => compter(r, vus));
    racines.sort((a, b) =>
      rangEchelon(a.equipe.echelon) - rangEchelon(b.equipe.echelon)
      || a.equipe.name.localeCompare(b.equipe.name, 'fr'));
    this.arborescence = racines;
    this.recalculerLesVues();
  }

  // ══ Les deux cadres, la recherche et les filtres ═══════════════════════════

  /** Reconstruit, pour chaque équipe, ses deux cadres et son décompte de correspondances.
   *
   * Fait ici et non dans le gabarit : trier et filtrer dans une expression de template se
   * refait à chaque cycle de détection de changements, et l'arborescence réelle compte 125
   * équipes. Rappelée à chaque changement de filtre, pas davantage. */
  recalculerLesVues(): void {
    const parcourir = (noeud: NoeudEquipe, vus: Set<string>): number => {
      if (noeud.equipe.id && vus.has(noeud.equipe.id)) { return 0; }
      if (noeud.equipe.id) { vus.add(noeud.equipe.id); }
      const equipeId = noeud.equipe.id ?? '';
      const tous = this.personnesDe(noeud);
      const cadres = tous.filter(m => this.roleDans(equipeId, m.utilisateur) !== 'INTERVENANT');
      const intervenants = tous.filter(
        m => this.roleDans(equipeId, m.utilisateur) === 'INTERVENANT');

      noeud.cadres = this.trier(cadres.filter(m => this.retenu(m, equipeId)));

      // Second cadre : « le niveau N-1 ». Pour une équipe de coordination, ce sont les CADRES
      // des équipes rattachées — c'est ainsi qu'on lit une chaîne de commandement. Pour une
      // équipe départementale, qui n'a rien en dessous, ce sont ses propres intervenants. Les
      // deux coexistent quand une équipe a des sous-équipes ET des équipiers en propre : les
      // taire en ferait disparaître de l'écran.
      const groupes: GroupePersonnes[] = [];
      for (const enfant of noeud.enfants) {
        const id = enfant.equipe.id ?? '';
        const membres = this.trier(
          this.personnesDe(enfant)
            .filter(m => this.roleDans(id, m.utilisateur) !== 'INTERVENANT')
            .filter(m => this.retenu(m, id)));
        if (membres.length) {
          groupes.push({ cle: `${equipeId}:${id}`, libelle: enfant.equipe.name,
                         equipeId: id, membres });
        }
      }
      const propres = this.trier(intervenants.filter(m => this.retenu(m, equipeId)));
      if (propres.length) {
        groupes.push({ cle: `${equipeId}:propres`, libelle: 'Intervenants de cette équipe',
                       equipeId, membres: propres });
      }
      noeud.groupes = groupes;

      noeud.correspondants = noeud.cadres.length + propres.length;
      noeud.correspondantsTotal = noeud.correspondants
        + noeud.enfants.reduce((total, enfant) => total + parcourir(enfant, vus), 0);
      return noeud.correspondantsTotal;
    };
    const vus = new Set<string>();
    this.arborescence.forEach(r => parcourir(r, vus));
  }

  /** L'effectif d'une équipe, enrichi par l'annuaire.
   *
   * Une personne absente de l'annuaire reste affichée avec son seul nom : elle est membre de
   * l'équipe sans rattachement actif à l'association (rattachée ailleurs, ou sortie). La
   * masquer ferait mentir l'effectif affiché juste au-dessus. */
  private personnesDe(noeud: NoeudEquipe): MembreAnnuaire[] {
    return (noeud.equipe.members_info ?? []).map(
      info => this.annuaire.get(info.id) ?? this.inconnu(info.id, info.nom));
  }

  private inconnu(id: string, nom: string): MembreAnnuaire {
    return {
      utilisateur: id, contact: '', nom, fonction: '', membre_bureau: false,
      statut: 'ACTIF', competences: [], a_declare: false, a_ressource: false,
      a_fiche: false, fiche_complete: false, titres: 0, titres_verifies: 0,
      titres_perimes: 0,
    };
  }

  /** Combien de personnes dans le second cadre, tous groupes confondus. */
  comptePersonnes(groupes: GroupePersonnes[]): number {
    return groupes.reduce((total, g) => total + g.membres.length, 0);
  }

  roleDans(equipeId: string, utilisateurId: string): RoleDansEquipe {
    return this.rolesParEquipe[equipeId]?.[utilisateurId] ?? 'INTERVENANT';
  }

  libelleRole(role: RoleDansEquipe): string {
    return this.LIBELLES_ROLE[role];
  }

  /** Le filtre, appliqué aux critères ET au texte libre.
   *
   * Le texte cherche dans tout ce que la fiche montre — nom, fonction, rôle, commune, métier,
   * compétences, coordonnées quand on y a droit. Chercher « plongeur » ou « 35 » ou « Rennes »
   * doit trouver, sans avoir à savoir dans quelle colonne l'information se range. */
  private retenu(membre: MembreAnnuaire, equipeId: string): boolean {
    if (this.filtreBureau && !membre.membre_bureau) { return false; }
    if (this.filtreSansDeclaration && membre.a_declare) { return false; }
    if (this.filtreTitresPerimes && !membre.titres_perimes) { return false; }
    if (this.filtreSansRessource && membre.a_ressource) { return false; }
    if (this.filtreRole && this.roleDans(equipeId, membre.utilisateur) !== this.filtreRole) {
      return false;
    }
    if (this.filtreCompetence
        && !membre.competences.some(c => c.id === this.filtreCompetence)) {
      return false;
    }
    const q = this.recherche.trim().toLowerCase();
    if (!q) { return true; }
    const champs = [
      membre.nom, membre.fonction, membre.ville ?? '', membre.metier ?? '',
      membre.email ?? '', membre.telephone ?? '', membre.departement_code ?? '',
      this.libelleRole(this.roleDans(equipeId, membre.utilisateur)),
      ...membre.competences.map(c => c.nom),
    ];
    return champs.some(valeur => (valeur || '').toLowerCase().includes(q));
  }

  private trier(membres: MembreAnnuaire[]): MembreAnnuaire[] {
    const parNom = (a: MembreAnnuaire, b: MembreAnnuaire) =>
      (a.nom || '').localeCompare(b.nom || '', 'fr');
    return [...membres].sort((a, b) => {
      switch (this.tri) {
        case 'fonction':
          return (a.fonction || '').localeCompare(b.fonction || '', 'fr') || parNom(a, b);
        case 'commune':
          return (a.ville || '').localeCompare(b.ville || '', 'fr') || parNom(a, b);
        // Les deux tris « ce qui cloche d'abord » : ce sont eux qu'on ouvre avant une
        // mobilisation, pour savoir qui relancer et qui ne peut pas partir.
        case 'perimes':
          return b.titres_perimes - a.titres_perimes || parNom(a, b);
        case 'silencieux':
          return Number(a.a_declare) - Number(b.a_declare) || parNom(a, b);
        default:
          return parNom(a, b);
      }
    });
  }

  /** Rappelée par tous les contrôles de la barre de recherche. */
  filtresChanges(): void {
    this.recalculerLesVues();
  }

  reinitialiserFiltres(): void {
    this.recherche = '';
    this.tri = 'nom';
    this.filtreRole = '';
    this.filtreCompetence = '';
    this.filtreBureau = false;
    this.filtreSansDeclaration = false;
    this.filtreTitresPerimes = false;
    this.filtreSansRessource = false;
    this.recalculerLesVues();
  }

  get filtreActif(): boolean {
    return !!(this.recherche.trim() || this.filtreRole || this.filtreCompetence
      || this.filtreBureau || this.filtreSansDeclaration || this.filtreTitresPerimes
      || this.filtreSansRessource);
  }

  get nombreCorrespondants(): number {
    return this.arborescence.reduce((t, n) => t + n.correspondantsTotal, 0);
  }

  /** Le catalogue des compétences réellement portées par l'effectif, pour la liste
   * déroulante. Pris sur les membres et non sur le catalogue général : proposer un filtre
   * « Plongée » dans une association qui n'a aucun plongeur ne rend que du vide. */
  get competencesDeLEffectif(): { id: string; nom: string }[] {
    const vues = new Map<string, string>();
    this.annuaire.forEach(m => m.competences.forEach(c => vues.set(c.id, c.nom)));
    return [...vues.entries()].map(([id, nom]) => ({ id, nom }))
      .sort((a, b) => a.nom.localeCompare(b.nom, 'fr'));
  }

  /** Déplie tout ce qui mène à une personne retenue par le filtre, et rien d'autre. */
  ouvrirCeQuiCorrespond(): void {
    const ouvrir = (noeud: NoeudEquipe): void => {
      if (noeud.correspondantsTotal > 0 && noeud.equipe.id) {
        this.depliees.add(noeud.equipe.id);
        this.cadresDeplies.add(`${noeud.equipe.id}:cadres`);
        this.cadresDeplies.add(`${noeud.equipe.id}:niveau`);
      }
      noeud.enfants.forEach(ouvrir);
    };
    this.arborescence.forEach(ouvrir);
  }

  // ══ Dépliage des cadres et des fiches ══════════════════════════════════════

  basculerCadre(cle: string): void {
    if (this.cadresDeplies.has(cle)) { this.cadresDeplies.delete(cle); }
    else { this.cadresDeplies.add(cle); }
  }

  cadreOuvert(cle: string): boolean {
    return this.cadresDeplies.has(cle);
  }

  basculerDetailEquipe(noeud: NoeudEquipe): void {
    const id = noeud.equipe.id;
    if (!id) { return; }
    if (this.detailsEquipe.has(id)) { this.detailsEquipe.delete(id); }
    else { this.detailsEquipe.add(id); }
  }

  detailEquipeOuvert(noeud: NoeudEquipe): boolean {
    return !!noeud.equipe.id && this.detailsEquipe.has(noeud.equipe.id);
  }

  /** La fiche d'une personne s'ouvre PAR ÉQUIPE : la même personne peut figurer dans deux
   * cadres (cadre ici, intervenant là), et une clé par personne ouvrirait les deux. */
  basculerDetailMembre(equipeId: string, utilisateurId: string): void {
    const cle = `${equipeId}:${utilisateurId}`;
    if (this.detailsMembre.has(cle)) { this.detailsMembre.delete(cle); }
    else { this.detailsMembre.add(cle); }
  }

  detailMembreOuvert(equipeId: string, utilisateurId: string): boolean {
    return this.detailsMembre.has(`${equipeId}:${utilisateurId}`);
  }

  // ══ Sélection multiple et affectation terrain ══════════════════════════════

  basculerSelection(utilisateurId: string): void {
    if (this.selection.has(utilisateurId)) { this.selection.delete(utilisateurId); }
    else { this.selection.add(utilisateurId); }
    if (this.selection.size && !this.crises.length) { this.chargerCrises(); }
  }

  estSelectionne(utilisateurId: string): boolean {
    return this.selection.has(utilisateurId);
  }

  /** Coche (ou décoche) tout un cadre d'un geste : c'est l'intérêt d'une sélection en masse. */
  basculerGroupe(membres: MembreAnnuaire[]): void {
    const tous = membres.every(m => this.selection.has(m.utilisateur));
    membres.forEach(m => tous ? this.selection.delete(m.utilisateur)
                              : this.selection.add(m.utilisateur));
    if (this.selection.size && !this.crises.length) { this.chargerCrises(); }
  }

  groupeEntierSelectionne(membres: MembreAnnuaire[]): boolean {
    return membres.length > 0 && membres.every(m => this.selection.has(m.utilisateur));
  }

  viderSelection(): void {
    this.selection.clear();
    this.refusAffectation = [];
  }

  get nomsSelectionnes(): string[] {
    return [...this.selection]
      .map(id => this.annuaire.get(id)?.nom ?? id)
      .sort((a, b) => a.localeCompare(b, 'fr'));
  }

  /** Les équipes où l'on peut affecter : celles de l'association. Les opérationnelles (sans
   * échelon) d'abord — ce sont les équipes d'intervention terrain, et c'est ce qu'on cherche
   * ici ; les équipes de coordination restent proposées, parce qu'on y nomme aussi des gens. */
  get equipesAffectables(): Team[] {
    return [...this.equipes]
      .filter(e => e.peut_gerer !== false)
      .sort((a, b) =>
        Number(!!a.echelon) - Number(!!b.echelon)
        || a.name.localeCompare(b.name, 'fr'));
  }

  private chargerCrises(): void {
    this.crisisService.getAll().subscribe({
      next: (liste) => this.crises = (liste ?? []).filter(c => c.is_open !== false),
      error: () => this.crises = [],
    });
  }

  affecter(): void {
    if (!this.equipeCible || !this.selection.size || this.affectationEnCours) { return; }
    this.affectationEnCours = true;
    this.refusAffectation = [];
    const equipeId = this.equipeCible;
    this.teamService.ajouterMembres(
      equipeId, [...this.selection], this.missionTitre.trim() || undefined,
      this.criseCible || undefined,
    ).subscribe({
      next: (res) => {
        this.affectationEnCours = false;
        const nom = this.equipes.find(e => e.id === equipeId)?.name ?? "l'équipe";
        // Les refus sont NOMMÉS, jamais fondus dans un « c'est fait » : une affectation
        // partielle présentée comme un succès fait partir une équipe incomplète.
        this.refusAffectation = (res.refuses ?? []).map(r => ({
          nom: this.annuaire.get(r.utilisateur)?.nom ?? r.utilisateur, motif: r.motif,
        }));
        this.message = `${res.ajoutes} personne(s) affectée(s) à « ${nom} »`
          + (res.deja_presents ? `, ${res.deja_presents} y étaient déjà` : '')
          + (this.missionTitre.trim() ? `, mission « ${this.missionTitre.trim()} »` : '')
          + '.';
        this.erreur = '';
        this.selection.clear();
        this.missionTitre = '';
        this.criseCible = null;
        // L'équipe a changé : recharger pour que l'arbre montre les nouveaux arrivants.
        this.chargerInstitution();
      },
      error: (err) => {
        this.affectationEnCours = false;
        this.erreur = err?.error?.error || "L'affectation a échoué.";
      },
    });
  }

  basculer(noeud: NoeudEquipe): void {
    const id = noeud.equipe.id;
    if (!id) { return; }
    if (this.depliees.has(id)) { this.depliees.delete(id); } else { this.depliees.add(id); }
  }

  estDepliee(noeud: NoeudEquipe): boolean {
    return !!noeud.equipe.id && this.depliees.has(noeud.equipe.id);
  }

  /** Déplie tout ce qui mène à une pièce en attente, et rien d'autre : c'est le geste que
   * cherche le manager en arrivant sur l'onglet avec une pastille.
   *
   * Ouvre aussi les deux cadres et la fiche des personnes concernées : depuis que les
   * justificatifs vivent dans la fiche d'une personne, déplier la seule branche laissait
   * encore trois clics entre la pastille et la pièce. */
  deplierCeQuiAttend(): void {
    const ouvrir = (noeud: NoeudEquipe): void => {
      const id = noeud.equipe.id;
      if (noeud.aVerifierTotal > 0 && id) {
        this.depliees.add(id);
        this.cadresDeplies.add(`${id}:cadres`);
        this.cadresDeplies.add(`${id}:niveau`);
        for (const membre of noeud.equipe.members_info ?? []) {
          if (this.nombreAVerifierPour(membre.id)) {
            this.detailsMembre.add(`${id}:${membre.id}`);
          }
        }
      }
      noeud.enfants.forEach(ouvrir);
    };
    this.arborescence.forEach(ouvrir);
  }

  toutReplier(): void {
    this.depliees.clear();
    this.cadresDeplies.clear();
    this.detailsEquipe.clear();
    this.detailsMembre.clear();
  }

  /** La ligne d'annuaire d'une personne, ou `undefined` si elle n'y est pas (membre d'équipe
   * sans rattachement actif à l'association). La fiche le dit alors plutôt que d'afficher des
   * champs vides. */
  ficheDe(utilisateurId: string): MembreAnnuaire | undefined {
    return this.annuaire.get(utilisateurId);
  }

  nombreAVerifierPour(utilisateurId: string): number {
    return this.aVerifier.par_membre[utilisateurId]?.length ?? 0;
  }

  /** Les pièces d'un membre que l'appelant a le droit de voir. La liste vient du serveur, déjà
   * filtrée par la visibilité (core/visibilite_membres.py) : ce filtre-ci n'est qu'un
   * regroupement d'affichage. */
  piecesDe(utilisateurId: string): QualificationMembre[] {
    return this.qualifications.filter(q => q.utilisateur === utilisateurId);
  }

  /** Ouvre le justificatif dans un onglet. Passe par un blob : la route exige l'en-tête
   * d'authentification posé par l'intercepteur, qu'un `<a href>` n'enverrait pas. Chaque
   * consultation est journalisée côté serveur — savoir qui a regardé le diplôme de quelqu'un
   * fait partie de la protection. */
  voirPiece(q: QualificationMembre): void {
    this.associationService.telechargerJustificatif(q.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      },
      error: (err) => this.erreur = err?.error?.error
        || "Impossible d'ouvrir cette pièce.",
    });
  }

  verifierPiece(q: QualificationMembre): void {
    this.associationService.verifierQualification(q.id).subscribe({
      next: (maj) => {
        this.qualifications = this.qualifications.map(x => (x.id === maj.id ? maj : x));
        this.message = 'Pièce vérifiée.';
        this.erreur = '';
        this.chargerAVerifier();
      },
      error: (err) => this.erreur = err?.error?.error || 'Impossible de vérifier cette pièce.',
    });
  }

  ouvrirRefusPiece(q: QualificationMembre): void {
    this.refusPieceEnCours = { id: q.id, motif: '' };
  }

  confirmerRefusPiece(): void {
    if (!this.refusPieceEnCours?.motif.trim()) { return; }
    const { id, motif } = this.refusPieceEnCours;
    this.refusPieceEnCours = null;
    this.associationService.refuserQualification(id, motif.trim()).subscribe({
      next: (maj) => {
        this.qualifications = this.qualifications.map(x => (x.id === maj.id ? maj : x));
        this.message = 'Pièce refusée : le membre voit le motif et peut en redéposer une.';
        this.erreur = '';
        this.chargerAVerifier();
      },
      error: (err) => this.erreur = err?.error?.error || 'Impossible de refuser cette pièce.',
    });
  }

  classeStatutPiece(q: QualificationMembre): string {
    return q.statut.toLowerCase();
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

  /** Libellé d'un créneau pour l'infobulle. La grille n'a pas la place d'écrire « Matin »
   * quinze fois sur soixante colonnes. */
  libelleCreneau(creneau: string): string {
    const libelles: Record<string, string> = {
      MATIN: 'Matin', MIDI: 'Midi', SOIR: 'Soir', NUIT: 'Nuit',
    };
    return libelles[creneau] ?? creneau;
  }

  /** Une lettre par créneau : M / Mi / S / N. « Mi » sur deux lettres parce que « M »
   * désignerait aussi bien matin que midi. */
  initialeCreneau(creneau: string): string {
    const initiales: Record<string, string> = {
      MATIN: 'M', MIDI: 'Mi', SOIR: 'S', NUIT: 'N',
    };
    return initiales[creneau] ?? creneau.slice(0, 1);
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

  /** Combien de membres sont disponibles sur ce créneau de ce jour. C'est le chiffre qu'on
   * lit pour savoir si une garde est armée. */
  compteDisponibles(index: number, creneau: string): number {
    if (!this.grille) { return 0; }
    return this.grille.membres.filter(
      m => !!m.jours[index]?.creneaux?.[creneau]).length;
  }

  /** Combien n'ont RIEN déclaré. Compté par membre et non par case : ce moteur ne stocke pas
   * de « non renseigné », donc une grille vierge et une grille tout décochée sont identiques
   * en base — seul `a_declare` les distingue, et c'est lui qui dit qui relancer. */
  compteSansDeclaration(): number {
    if (!this.grille) { return 0; }
    return this.grille.membres.filter(m => !m.a_declare).length;
  }
}
