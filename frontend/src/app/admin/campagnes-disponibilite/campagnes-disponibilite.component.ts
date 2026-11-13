import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AuthService } from '../../auth/services/auth.service';
import { AssociationService } from '../../services/association.service';
import { CampagneDisponibiliteService } from '../../services/campagne-disponibilite.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { CompetenceService } from '../../services/competence.service';
import { CrisisService } from '../../services/crisis.service';
import { InstitutionService } from '../../services/institution.service';
import { TeamService } from '../../services/team.service';
import {
  BilanRotations, CampagneDisponibilite, CanalEnvoi, CibleCampagne, CouvertureCampagne,
  ECHELONS, MOTIFS, RotationCampagne,
} from '../../shared/models/campagne-disponibilite.model';
import { Competence } from '../../shared/models/competence.model';
import { Crisis } from '../../shared/models/crisis.model';
import { Institution } from '../../shared/models/institution.model';
import { Qualification } from '../../shared/models/association.model';
import { Team } from '../../shared/models/team.model';
import { CRENEAUX } from '../../shared/models/fiche-benevole.model';

type Onglet = 'liste' | 'composer' | 'suivi';

/** Code de l'InstitutionType des AASC — comparé sans casse, comme côté serveur. */
const CODE_TYPE_AASC = 'aasc';

/**
 * Campagnes de disponibilité : solliciter en masse ses bénévoles pour une période à venir.
 *
 * Demande de Sylvain du 11/11/2026. L'écran suit délibérément **trois temps** et non un
 * formulaire unique avec un bouton « envoyer » :
 *
 * 1. **composer** — le motif typé, la période en dates, le texte du pourquoi ;
 * 2. **vérifier la cible** — les critères, et surtout le NOMBRE de personnes retenues avant
 *    d'écrire à qui que ce soit. C'est le garde-fou : un critère qui ne filtre pas ce qu'on
 *    croyait se voit là, pas à l'arrivée du premier mail ;
 * 3. **envoyer**, puis suivre qui a répondu et armer les tours de garde.
 *
 * Écrire à quatre cents personnes au nom d'une association ne se fait pas d'un clic depuis un
 * formulaire qu'on vient de remplir — et ça ne se défait pas.
 */
@Component({
  selector: 'app-campagnes-disponibilite',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './campagnes-disponibilite.component.html',
  styleUrl: './campagnes-disponibilite.component.scss',
})
export class CampagnesDisponibiliteComponent implements OnInit {
  onglet: Onglet = 'liste';
  chargement = true;
  enCours = false;
  erreur = '';
  message = '';

  mesInstitutions: Institution[] = [];
  institutionChoisie: string | null = null;

  campagnes: CampagneDisponibilite[] = [];
  campagne: CampagneDisponibilite | null = null;

  competences: Competence[] = [];
  qualifications: Qualification[] = [];
  equipes: Team[] = [];
  crises: Crisis[] = [];

  readonly MOTIFS = MOTIFS;
  readonly ECHELONS = ECHELONS;
  readonly CRENEAUX = CRENEAUX;

  /** Brouillon en cours de composition. Les dates sont des chaînes `YYYY-MM-DD` : c'est ce
   * qu'un `<input type="date">` produit, et les convertir ici ne servirait qu'à les
   * reconvertir avant l'envoi. */
  saisie: Partial<CampagneDisponibilite> = this.saisieVide();

  // ── Suivi ────────────────────────────────────────────────────────────────
  cibles: CibleCampagne[] = [];
  couverture: CouvertureCampagne | null = null;
  rotations: RotationCampagne[] = [];
  bilanRotations: BilanRotations | null = null;
  apercu: { total: number; noms: string[]; tronque: boolean } | null = null;
  /** Les canaux chiffrés pour la cible qu'on vient de compter. */
  canaux: CanalEnvoi[] = [];

  constructor(
    private service: CampagneDisponibiliteService,
    private associationService: AssociationService,
    private contactService: ContactInstitutionService,
    private institutionService: InstitutionService,
    private competenceService: CompetenceService,
    private teamService: TeamService,
    private crisisService: CrisisService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.charger();
  }

  private saisieVide(): Partial<CampagneDisponibilite> {
    const dans = (jours: number) => {
      const d = new Date();
      d.setDate(d.getDate() + jours);
      return d.toISOString().slice(0, 10);
    };
    return {
      intitule: '', motif: 'CRISE_A_VENIR', texte: '', crise: null,
      // Une semaine à partir de dans deux jours : une campagne pour « demain » laisse trop
      // peu de temps pour répondre, et personne ne prépare un dispositif à six mois.
      periode_debut: dans(2), periode_fin: dans(9),
      creneaux: [], echelon: 'NATIONAL', territoire_code: '', rayon_km: null,
      competences: [], qualifications: [], titres_a_jour: true, equipe: null,
      // Désactivés par défaut : le défaut va vers le moins d'effet, ce qui est le bon sens
      // pour une option qui propose d'affecter des gens.
      // Email seul : le canal le moins cher est le défaut, et cocher un SMS reste un geste
      // délibéré. Un défaut qui engage des dizaines d'euros n'est pas un défaut.
      canaux: ['BREVO_EMAIL'],
      tours_de_garde: false,
      duree_rotation_jours: 3, repos_min_jours: 2, effectif_cible: 0,
    };
  }

  private charger(): void {
    const moi = this.authService.getCurrentUser();
    forkJoin({
      contacts: this.contactService.getAll(),
      institutions: this.institutionService.getAll(),
      competences: this.competenceService.getAll(),
      qualifications: this.associationService.getCatalogueQualifications(),
    }).subscribe({
      next: ({ contacts, institutions, competences, qualifications }) => {
        const liste = Array.isArray(institutions) ? institutions
          : (institutions as { results?: Institution[] }).results ?? [];
        const associations = liste.filter(
          i => i.id && i.actif !== false
            && (i.type_code || '').toLowerCase() === CODE_TYPE_AASC);
        if (moi?.type === 'ADMIN') {
          this.mesInstitutions = associations;
        } else {
          // Toutes celles dont on est membre actif : le serveur tranchera qui peut LANCER
          // (bureau, ou encadrement sur sa branche). La page ne fait que ne pas proposer ce
          // qui serait refusé de toute façon.
          const ids = new Set(contacts.filter(c => c.utilisateur === moi?.id && c.actif)
            .map(c => c.institution));
          this.mesInstitutions = associations.filter(i => ids.has(i.id!));
        }
        this.competences = competences.filter(c => c.active !== false);
        this.qualifications = qualifications.filter(q => q.actif);
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
    this.campagne = null;
    this.onglet = 'liste';
    if (this.institutionChoisie) { this.chargerInstitution(); }
  }

  chargerInstitution(): void {
    const id = this.institutionChoisie;
    if (!id) { return; }
    this.service.getAll().subscribe({
      next: (liste) => this.campagnes = liste.filter(c => c.institution === id),
      error: () => this.erreur = 'Impossible de charger les campagnes.',
    });
    this.teamService.getAll().subscribe({
      next: (equipes) => this.equipes = equipes.filter(
        e => e.institution === id && e.actif !== false),
      error: () => undefined,
    });
    // Les crises servent au ciblage par rayon : sans crise localisée, ce critère est refusé
    // par le serveur, donc autant ne pas le proposer à vide.
    this.crisisService.getAll().subscribe({
      next: (crises) => this.crises = crises,
      error: () => undefined,
    });
  }

  // ══ Composition ═══════════════════════════════════════════════════════════

  nouvelle(): void {
    this.saisie = this.saisieVide();
    this.campagne = null;
    this.apercu = null;
    this.canaux = [];
    this.onglet = 'composer';
    this.message = '';
    this.erreur = '';
  }

  reprendre(campagne: CampagneDisponibilite): void {
    this.campagne = campagne;
    this.saisie = { ...campagne };
    this.apercu = null;
    this.canaux = [];
    this.onglet = campagne.statut === 'BROUILLON' ? 'composer' : 'suivi';
    if (this.onglet === 'suivi') { this.chargerSuivi(); }
  }

  get aideMotif(): string {
    return this.MOTIFS.find(m => m.valeur === this.saisie.motif)?.aide ?? '';
  }

  get demandeUnTerritoire(): boolean {
    return ['ZONE_DEFENSE', 'REGION', 'DEPARTEMENT', 'COMMUNE']
      .includes(this.saisie.echelon ?? '');
  }

  get demandeUneCrise(): boolean {
    return this.saisie.echelon === 'RAYON_CRISE';
  }

  /** Nombre de jours de la période, calculé à la saisie : « du 12 au 26 » ne dit pas d'un coup
   * d'œil que ça fait quinze jours à couvrir. */
  get nombreDeJours(): number {
    const debut = this.saisie.periode_debut;
    const fin = this.saisie.periode_fin;
    if (!debut || !fin) { return 0; }
    const d = new Date(debut + 'T00:00:00');
    const f = new Date(fin + 'T00:00:00');
    return Math.max(0, Math.round((f.getTime() - d.getTime()) / 86400000) + 1);
  }

  get periodeIncoherente(): boolean {
    return this.nombreDeJours === 0 && !!this.saisie.periode_debut;
  }

  /** Combien de tours de garde la période donnera. Affiché pendant la saisie : c'est ce qui
   * rend concret le paramètre de rotation. */
  get nombreDeTours(): number {
    const duree = this.saisie.duree_rotation_jours || 1;
    return this.nombreDeJours ? Math.ceil(this.nombreDeJours / duree) : 0;
  }

  basculerCreneau(creneau: string): void {
    const actuels = this.saisie.creneaux ?? [];
    this.saisie.creneaux = actuels.includes(creneau)
      ? actuels.filter(c => c !== creneau)
      : [...actuels, creneau];
  }

  creneauCoche(creneau: string): boolean {
    const actuels = this.saisie.creneaux ?? [];
    // Vide = les quatre : la case est donc cochée quand rien n'est sélectionné.
    return actuels.length === 0 || actuels.includes(creneau);
  }

  basculerDansLaListe(champ: 'competences' | 'qualifications', id: string): void {
    const actuels = (this.saisie[champ] as string[] | undefined) ?? [];
    this.saisie[champ] = actuels.includes(id)
      ? actuels.filter(x => x !== id)
      : [...actuels, id];
  }

  estSelectionne(champ: 'competences' | 'qualifications', id: string): boolean {
    return ((this.saisie[champ] as string[] | undefined) ?? []).includes(id);
  }

  get peutEnregistrer(): boolean {
    return !!this.saisie.intitule?.trim()
      && !!this.saisie.periode_debut && !!this.saisie.periode_fin
      && !this.periodeIncoherente
      && (!this.demandeUnTerritoire || !!this.saisie.territoire_code?.trim())
      && (!this.demandeUneCrise || (!!this.saisie.crise && !!this.saisie.rayon_km))
      // Tours de garde activés sans effectif : refusé ici comme côté serveur. On ne peut pas
      // armer une garde avec zéro personne par créneau, et laisser passer promettrait dans le
      // message une organisation qui ne serait jamais produite.
      && (!this.saisie.tours_de_garde || !!this.saisie.effectif_cible);
  }

  /** Activer les tours propose un effectif plutôt que de laisser un zéro bloquant : on vient
   * de cocher une option, pas de remplir un formulaire administratif. */
  basculerToursDeGarde(): void {
    this.saisie.tours_de_garde = !this.saisie.tours_de_garde;
    if (this.saisie.tours_de_garde && !this.saisie.effectif_cible) {
      this.saisie.effectif_cible = 2;
    }
  }

  enregistrer(): void {
    if (!this.peutEnregistrer || !this.institutionChoisie) { return; }
    this.enCours = true;
    this.erreur = '';
    const corps = { ...this.saisie, institution: this.institutionChoisie };
    const appel = this.campagne
      ? this.service.modifier(this.campagne.id, corps)
      : this.service.creer(corps);
    appel.subscribe({
      next: (campagne) => {
        this.enCours = false;
        this.campagne = campagne;
        this.saisie = { ...campagne };
        this.campagnes = [campagne, ...this.campagnes.filter(c => c.id !== campagne.id)];
        this.message = 'Campagne enregistrée. Vérifiez la cible avant d\'envoyer.';
      },
      error: (err) => {
        this.enCours = false;
        this.erreur = this.premierMessage(err) || "Impossible d'enregistrer cette campagne.";
      },
    });
  }

  /** Fige la cible et rend le nombre, SANS écrire à personne. */
  verifierLaCible(): void {
    if (!this.campagne) { return; }
    this.enCours = true;
    this.erreur = '';
    this.service.apercu(this.campagne.id).subscribe({
      next: (res) => {
        this.enCours = false;
        this.apercu = {
          total: res.total,
          noms: res.cibles.map(c => c.nom),
          tronque: res.tronque,
        };
        this.canaux = res.canaux ?? [];
        this.message = '';
      },
      error: (err) => {
        this.enCours = false;
        this.apercu = null;
        this.canaux = [];
        // Le serveur nomme le critère inapplicable : on l'affiche tel quel, c'est la seule
        // information utile.
        this.erreur = this.premierMessage(err) || 'Ciblage impossible.';
      },
    });
  }

  // ── Canaux d'envoi ───────────────────────────────────────────────────────

  /** Les canaux retenus, ou email seul si rien n'est coché : c'est la règle du serveur, et
   * l'écran doit montrer la même chose que ce qui partira. */
  get canauxChoisis(): string[] {
    const choisis = this.saisie.canaux ?? [];
    return choisis.length ? choisis : ['BREVO_EMAIL'];
  }

  canalCoche(code: string): boolean {
    return this.canauxChoisis.includes(code);
  }

  basculerCanal(canal: CanalEnvoi): void {
    if (!canal.disponible) { return; }
    const actuels = this.canauxChoisis;
    this.saisie.canaux = actuels.includes(canal.code)
      ? actuels.filter(c => c !== canal.code)
      : [...actuels, canal.code];
  }

  /** Ce que l'envoi coûtera en tout, canaux cochés confondus. `null` dès qu'un tarif manque :
   * un total partiel sous-estimerait la dépense, ce qui est la pire des erreurs ici. */
  get coutTotalCentimes(): number | null {
    const retenus = this.canaux.filter(c => this.canalCoche(c.code) && c.disponible);
    if (!retenus.length) { return 0; }
    // Matrix est gratuit pour de vrai ; ailleurs, un total nul veut dire tarif non
    // renseigné, et on ne l'additionne pas comme s'il valait zéro.
    if (retenus.some(c => c.code !== 'MATRIX' && c.destinataires > 0
                          && c.cout_total_centimes === null)) {
      return null;
    }
    return retenus.reduce((somme, c) => somme + (c.cout_total_centimes ?? 0), 0);
  }

  /** Combien de personnes aucun canal coché ne touche. Le chiffre qui décide d'en cocher un
   * de plus. */
  get nonJoignablesParAucunCanal(): number {
    if (!this.apercu) { return 0; }
    const retenus = this.canaux.filter(c => this.canalCoche(c.code) && c.disponible);
    if (!retenus.length) { return this.apercu.total; }
    return Math.max(0, this.apercu.total - Math.max(...retenus.map(c => c.destinataires)));
  }

  /** Vrai si un canal coché n'a pas assez de crédits. Prévient, ne bloque pas : partir quand
   * même sur les cent premiers est une décision de l'association. */
  get creditsInsuffisants(): boolean {
    return this.canaux.some(c => this.canalCoche(c.code) && c.credits_suffisants === false);
  }

  euros(centimes: number | null): string {
    if (centimes === null) { return 'coût inconnu'; }
    if (centimes === 0) { return 'aucun coût'; }
    return (centimes / 100).toLocaleString('fr-FR',
      { style: 'currency', currency: 'EUR' });
  }

  envoyer(): void {
    if (!this.campagne || !this.apercu) { return; }
    // Les canaux cochés ne sont pas encore enregistrés : on les écrit AVANT de partir, sinon
    // la campagne s'enverrait par le canal d'hier.
    const choisis = this.canauxChoisis;
    const memes = JSON.stringify([...(this.campagne.canaux ?? [])].sort())
      === JSON.stringify([...choisis].sort());
    if (!memes) {
      this.enCours = true;
      this.service.modifier(this.campagne.id, { canaux: choisis }).subscribe({
        next: (maj) => { this.campagne = maj; this.enCours = false; this.envoyerVraiment(); },
        error: (err) => {
          this.enCours = false;
          this.erreur = this.premierMessage(err) || "Le choix des canaux n'a pas pu être enregistré.";
        },
      });
      return;
    }
    this.envoyerVraiment();
  }

  private envoyerVraiment(): void {
    if (!this.campagne || !this.apercu) { return; }
    this.enCours = true;
    this.erreur = '';
    this.service.envoyer(this.campagne.id).subscribe({
      next: (res) => {
        this.enCours = false;
        this.campagne = res.campagne;
        this.campagnes = this.campagnes.map(c => (c.id === res.campagne.id ? res.campagne : c));
        this.message = res.echecs
          ? `${res.envoyes} message(s) envoyé(s), ${res.echecs} échec(s) — voir le suivi.`
          : `${res.envoyes} message(s) envoyé(s).`;
        this.onglet = 'suivi';
        this.chargerSuivi();
      },
      error: (err) => {
        this.enCours = false;
        this.erreur = this.premierMessage(err) || "L'envoi a échoué.";
      },
    });
  }

  // ══ Suivi ═════════════════════════════════════════════════════════════════

  chargerSuivi(): void {
    const campagne = this.campagne;
    if (!campagne) { return; }
    this.service.cibles(campagne.id).subscribe({
      next: (cibles) => this.cibles = cibles,
      error: () => undefined,
    });
    this.service.couverture(campagne.id).subscribe({
      next: (c) => this.couverture = c,
      error: () => undefined,
    });
    this.service.rotations(campagne.id).subscribe({
      next: (res) => { this.rotations = res.rotations; this.bilanRotations = res.bilan; },
      error: () => undefined,
    });
  }

  relancer(): void {
    if (!this.campagne) { return; }
    this.enCours = true;
    this.service.relancer(this.campagne.id).subscribe({
      next: (res) => {
        this.enCours = false;
        this.message = `${res.relances} silencieux relancé(s), ${res.envoyes} envoyé(s).`;
        this.chargerSuivi();
      },
      error: (err) => {
        this.enCours = false;
        this.erreur = this.premierMessage(err) || 'La relance a échoué.';
      },
    });
  }

  genererRotations(): void {
    if (!this.campagne) { return; }
    this.enCours = true;
    this.service.genererRotations(this.campagne.id).subscribe({
      next: (res) => {
        this.enCours = false;
        this.rotations = res.rotations;
        this.bilanRotations = res.bilan;
        this.message = `${res.bilan.rotations} tour(s), ${res.bilan.proposees} proposition(s)`
          + (res.bilan.conservees ? `, ${res.bilan.conservees} confirmation(s) conservée(s)`
                                  : '');
      },
      error: (err) => {
        this.enCours = false;
        this.erreur = this.premierMessage(err) || 'Génération impossible.';
      },
    });
  }

  decider(affectationId: string, decision: 'CONFIRMEE' | 'RETIREE'): void {
    if (!this.campagne) { return; }
    this.service.decider(this.campagne.id, affectationId, decision).subscribe({
      next: (maj) => {
        this.rotations = this.rotations.map(r => ({
          ...r,
          affectations: r.affectations.map(a => (a.id === maj.id ? maj : a)),
        }));
      },
      error: (err) => this.erreur = this.premierMessage(err) || 'Décision impossible.',
    });
  }

  cloturer(): void {
    if (!this.campagne) { return; }
    this.service.cloturer(this.campagne.id).subscribe({
      next: (maj) => {
        this.campagne = maj;
        this.campagnes = this.campagnes.map(c => (c.id === maj.id ? maj : c));
        this.message = 'Campagne clôturée.';
      },
      error: () => this.erreur = 'Clôture impossible.',
    });
  }

  /** Les cibles en sous-effectif, nommées : une grille qui paraît complète parce qu'on a caché
   * les trous est pire que pas de grille. */
  get manques(): BilanRotations['manques'] {
    return this.bilanRotations?.manques ?? [];
  }

  libelleCreneau(creneau: string): string {
    return this.CRENEAUX.find(c => c.creneau === creneau)?.libelle ?? creneau;
  }

  nomEquipe(id: string | null | undefined): string {
    if (!id) { return ''; }
    return this.equipes.find(e => e.id === id)?.name ?? '';
  }

  enTeteJour(iso: string): string {
    const d = new Date(iso + 'T00:00:00');
    const jours = ['di', 'lu', 'ma', 'me', 'je', 've', 'sa'];
    return `${jours[d.getDay()]} ${d.getDate()}`;
  }

  /** Premier message lisible d'une réponse d'erreur DRF. Sans ça, une erreur de validation
   * s'affiche « [object Object] ». */
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
