import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { CrisisService } from '../../services/crisis.service';
import { Crisis } from '../../shared/models/crisis.model';
import { CelluleCriseService } from '../../services/cellule-crise.service';
import { CelluleCrise } from '../../shared/models/cellule-crise.model';
import { TeamService } from '../../services/team.service';
import { Team, MatrixMessage, teamDisplayName } from '../../shared/models/team.model';
import { Apprentissage, DossierService } from '../../services/dossier.service';
import { AffectationCompetenceService } from '../../services/affectation-competence.service';
import { AffectationCompetence } from '../../shared/models/affectation-competence.model';
import { Dossier } from '../../shared/models/dossier.model';
import { RessourceMobilisee } from '../../shared/models/ressource-mobilisee.model';
import { OfferService } from '../../services/offer.service';
import { Offer } from '../../shared/models/offer.model';
import { DisponibiliteOffreService } from '../../services/disponibilite-offre.service';
import { DisponibiliteOffre } from '../../shared/models/disponibilite-offre.model';
import { ImplicationService } from '../../services/implication.service';
import { ImplicationInstitution } from '../../shared/models/implication.model';
import { JournalCollectiviteService } from '../../services/journal-collectivite.service';
import { JournalCollectivite } from '../../shared/models/journal-collectivite.model';
import { AuthService } from '../../auth/services/auth.service';
import { MinimapComponent } from '../../shared/components/common/minimap/minimap.component';
import { MatrixSalonChatComponent } from '../teams/matrix-salon-chat/matrix-salon-chat.component';
import { dureeDepuis } from '../../shared/utils/duree.util';
import { AVEC_COORDONNEES } from '../../services/coordonnees';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';

/** Code couleur et libellés de la page Signalements (reporting.component.scss). */
export type GenreFiche = 'demande' | 'signalement' | 'offre';

type OngletRessource = 'demandes' | 'offres' | 'disponibilites' | 'signalements' | 'retours';

interface EquipeAvecResume {
  team: Team;
  nbPersonnes: number;
  materielParType: { label: string; total: number }[];
}

/** Page "Cellule de crise" : 3 panneaux repliables (ressource/moyen/coordination) sur un même
 * écran -- conçue sur ~15 échanges de réflexion (voir le plan archivé). Principe transversal :
 * repliable partout, jamais de route séparée, pour rester utilisable aussi bien par une
 * cellule à 1 seule personne (tout ouvert par défaut) qu'à plusieurs (chacun replie ce qui
 * n'est pas le sien, état mémorisé par utilisateur en localStorage). */
@Component({
  selector: 'app-cellule-crise',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, MinimapComponent, MatrixSalonChatComponent],
  templateUrl: './cellule-crise.component.html',
  styleUrl: './cellule-crise.component.scss',
})
export class CelluleCriseComponent implements OnInit, OnDestroy {
  dureeDepuis = dureeDepuis;
  teamDisplayName = teamDisplayName;

  crises: Crisis[] = [];
  criseId = '';
  cellule: CelluleCrise | null = null;
  chargementCellule = false;

  // --- Barres "Messages" / "Urgences" (repliables + badge, en tête de page) ---
  messagesOuvert = false;
  urgencesOuvert = false;
  messagesUrgents: { equipeNom: string; message: MatrixMessage }[] = [];

  // --- 3 panneaux repliables (état par utilisateur, localStorage) ---
  panneaux: { ressource: boolean; moyen: boolean; coordination: boolean } = {
    ressource: true, moyen: true, coordination: true,
  };

  // --- Panneau Moyen : équipes repliables ---
  equipes: EquipeAvecResume[] = [];
  equipesDepliees = new Set<string>();
  dossiersParEquipe: Record<string, Dossier[]> = {};

  // --- Panneau Ressource : 5 onglets ---
  ongletRessource: OngletRessource = 'demandes';
  dossiersNonAffectes: Dossier[] = [];
  signalementsNonAffectes: Dossier[] = [];
  offresDisponibles: Offer[] = [];
  disponibilites: DisponibiliteOffre[] = [];
  retoursExternes: Offer[] = [];
  chargementRessource = false;
  categoriesExclues = new Set<string>();

  // --- Affectation depuis la cellule, qui « apprend » (22/10/2026, voir apprendre_affectation
  // côté backend) : le choix de Fred pour un dossier devient la suggestion des suivants. ---
  dossiersMateriel: Dossier[] = [];
  affectationsCrise: AffectationCompetence[] = [];
  equipeChoisie: Record<string, string> = {};
  selection = new Set<string>();
  equipeLot = '';
  filtreCategorie = '';
  affectationEnCours = false;
  toast: { texte: string; annuler?: () => void } | null = null;

  // --- Aperçu dépliable d'une ligne (photo, description, mini-carte), comme la fiche de la
  // page Signalements, pour affecter à la bonne équipe sans changer de page. ---
  apercus = new Set<string>();
  photos: Record<string, string> = {};
  equipeOffre: Record<string, string> = {};
  private toastTimer?: ReturnType<typeof setTimeout>;

  // --- Panneau Coordination ---
  dossiersAValider: Dossier[] = [];
  implicationsEnAttente: ImplicationInstitution[] = [];
  journal: JournalCollectivite[] = [];
  nouvelleEntreeJournal = '';

  private cleStorage = '';
  private sub?: Subscription;

  constructor(
    private crisisService: CrisisService,
    private celluleCriseService: CelluleCriseService,
    private teamService: TeamService,
    private dossierService: DossierService,
    private offerService: OfferService,
    private disponibiliteOffreService: DisponibiliteOffreService,
    private implicationService: ImplicationService,
    private journalService: JournalCollectiviteService,
    private affectationCompetenceService: AffectationCompetenceService,
    private requestService: RequestService,
    private informationService: InformationService,
    public authService: AuthService,
  ) {}

  ngOnInit(): void {
    const userId = this.authService.getCurrentUser()?.id || 'anonyme';
    this.cleStorage = `cellule-crise-panneaux-${userId}`;
    this.chargerEtatPanneaux();

    this.crisisService.getAll().subscribe({
      next: (crises) => {
        this.crises = crises.filter(c => c.is_open !== false);
        if (this.crises.length > 0 && !this.criseId) {
          this.criseId = this.crises[0].id;
          this.onCriseChange();
        }
      },
      error: () => {},
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
    if (this.toastTimer) clearTimeout(this.toastTimer);
    Object.values(this.photos).forEach(url => URL.revokeObjectURL(url));
  }

  // ── Panneaux repliables (persistance) ──────────────────────────────
  private chargerEtatPanneaux(): void {
    try {
      const brut = localStorage.getItem(this.cleStorage);
      if (brut) this.panneaux = { ...this.panneaux, ...JSON.parse(brut) };
    } catch { /* ignore -- comportement par défaut (tout ouvert) */ }
  }

  basculerPanneau(nom: keyof typeof this.panneaux): void {
    this.panneaux[nom] = !this.panneaux[nom];
    try { localStorage.setItem(this.cleStorage, JSON.stringify(this.panneaux)); } catch { /* ignore */ }
  }

  // ── Chargement au changement de crise ──────────────────────────────
  onCriseChange(): void {
    if (!this.criseId) return;
    this.chargerCellule();
    this.chargerEquipes();
    this.chargerRessource();
    this.chargerCoordination();
  }

  private chargerCellule(): void {
    this.chargementCellule = true;
    this.celluleCriseService.get(this.criseId).subscribe({
      next: (c) => { this.cellule = c; this.chargementCellule = false; this.chargerUrgences(); },
      error: () => { this.chargementCellule = false; },
    });
  }

  // ── Barre "Urgences" : agrège les messages urgents de tous les salons d'équipe de la crise ──
  private chargerUrgences(): void {
    this.messagesUrgents = [];
    // Filtrées AVANT l'indexation : resultats[i] doit correspondre à equipesDeLaCrise[i].
    const equipesDeLaCrise = this.equipes.map(e => e.team).filter(t => !!t.salon_matrix_room_id);
    const appels = equipesDeLaCrise
      .map(t => this.teamService.getSalonMatrixMessages(t.id!).pipe(
        catchError(() => of({ messages: [] as MatrixMessage[] })),
      ));
    if (appels.length === 0) return;
    forkJoin(appels).subscribe(resultats => {
      resultats.forEach((res, i) => {
        res.messages.filter(m => m.urgent).forEach(m => {
          this.messagesUrgents.push({ equipeNom: teamDisplayName(equipesDeLaCrise[i]), message: m });
        });
      });
    });
  }

  get nombreUrgences(): number { return this.messagesUrgents.length; }

  // ── Panneau Moyen ──────────────────────────────────────────────────
  private chargerEquipes(): void {
    forkJoin({
      teams: this.teamService.getAll(),
      ressources: this.teamService.ressourcesMobilisees().pipe(catchError(() => of([] as RessourceMobilisee[]))),
    }).subscribe(({ teams, ressources }) => {
      const equipesDeLaCrise = teams.filter(t => t.assigned_crisis_ids?.includes(this.criseId));
      this.equipes = equipesDeLaCrise.map(team => this.construireResume(team, ressources));
      this.chargerUrgences();
    });
  }

  private construireResume(team: Team, ressources: RessourceMobilisee[]): EquipeAvecResume {
    const lignes = ressources.filter(r => r.equipe_id === team.id);
    const nbPersonnes = lignes.filter(r => r.type === 'personne').length;
    const parType = new Map<string, number>();
    lignes.filter(r => r.type === 'materiel').forEach(r => {
      const cle = r.detail || r.nom;
      parType.set(cle, (parType.get(cle) || 0) + 1);
    });
    const materielParType = Array.from(parType.entries()).map(([label, total]) => ({ label, total }));
    return { team, nbPersonnes, materielParType };
  }

  /** Troncature au-delà de 4 types (sinon la carte repliée explose en hauteur, voir plan). */
  materielAffiche(equipe: EquipeAvecResume): { texte: string; reste: number } {
    const items = equipe.materielParType;
    const visibles = items.slice(0, 4);
    const texte = visibles.map(i => i.total > 1 ? `${i.total} ${i.label}` : i.label).join(', ');
    return { texte, reste: Math.max(0, items.length - 4) };
  }

  estDepliee(equipeId: string): boolean { return this.equipesDepliees.has(equipeId); }

  basculerEquipe(equipeId: string): void {
    if (this.equipesDepliees.has(equipeId)) {
      this.equipesDepliees.delete(equipeId);
    } else {
      this.equipesDepliees.add(equipeId);
      if (!this.dossiersParEquipe[equipeId]) this.chargerDossiersEquipe(equipeId);
    }
  }

  private chargerDossiersEquipe(equipeId: string): void {
    this.dossierService.getAll().subscribe(dossiers => {
      this.dossiersParEquipe[equipeId] = dossiers.filter(d => d.equipe === equipeId);
    });
  }

  estCadreEquipe(team: Team): boolean {
    return this.authService.isInstitutionalEffective() || team.leader === this.authService.getCurrentUser()?.id;
  }

  // Messagerie unifiée (TeamViewSet.messagerie_unifiee) : Matrix + MeshCore + Meshtastic.
  chargerMessagesEquipe = (equipeId: string) => () => this.teamService.getMessagerieUnifiee(equipeId);
  envoyerMessageEquipe = (equipeId: string) => (texte: string, urgent = false) => this.teamService.envoyerMessageUnifie(equipeId, texte, urgent);
  reagirMessageEquipe = (equipeId: string) => (eventId: string) => this.teamService.reagirSalonMatrix(equipeId, eventId);

  demarrerEngagement(team: Team): void {
    this.teamService.demarrerEngagement(team.id!).subscribe({
      next: t => { team.engagement_debut = t.engagement_debut; },
      error: err => alert(this.messageErreur(err, "Impossible de démarrer l'engagement.")),
    });
  }

  mettreAuRepos(team: Team): void {
    this.teamService.mettreAuRepos(team.id!).subscribe({
      next: t => { team.engagement_debut = t.engagement_debut; },
      error: err => alert(this.messageErreur(err, 'Impossible de mettre cette équipe au repos.')),
    });
  }

  // ── Panneau Ressource ───────────────────────────────────────────────
  changerOngletRessource(o: OngletRessource): void {
    this.ongletRessource = o;
    this.filtreCategorie = '';
    this.selection.clear();
  }

  private chargerRessource(): void {
    this.chargementRessource = true;
    this.dossierService.getAll().subscribe({
      next: (dossiers) => {
        const enAttente = dossiers.filter(d =>
          d.crise === this.criseId &&
          ['EN_ATTENTE_AFFECTATION', 'EN_ATTENTE_DISTRIBUTION'].includes(d.statut),
        );
        this.dossiersNonAffectes = enAttente.filter(d => !d.information && (d.besoin_nature === 'COMPETENCE' || d.besoin_nature === 'MIXTE' || !d.besoin_nature));
        this.signalementsNonAffectes = enAttente.filter(d => !!d.information && (d.besoin_nature === 'COMPETENCE' || d.besoin_nature === 'MIXTE' || !d.besoin_nature));
        this.dossiersMateriel = enAttente.filter(d => d.besoin_nature === 'MATERIEL');
        // Sélection et choix en cours : seulement ce qui est encore en attente.
        const ids = new Set(enAttente.map(d => d.id));
        this.selection = new Set([...this.selection].filter(id => ids.has(id)));
        this.chargementRessource = false;
      },
      error: () => { this.chargementRessource = false; },
    });
    this.offerService.getAll({ crisis: this.criseId, status: 'DISPONIBLE', ...AVEC_COORDONNEES }).subscribe({
      next: (offres) => {
        this.offresDisponibles = offres;
        this.disponibiliteOffreService.getByOffers(offres.map(o => o.id)).subscribe({
          next: (dispos) => { this.disponibilites = dispos; },
          error: () => {},
        });
      },
      error: () => {},
    });
    this.offerService.retoursExternes(this.criseId).subscribe({
      next: (offres) => { this.retoursExternes = offres; },
      error: () => {},
    });
    this.affectationCompetenceService.getAll().subscribe({
      next: (affectations) => { this.affectationsCrise = affectations.filter(a => a.crise === this.criseId && a.active); },
      error: () => {},
    });
  }

  /** Masque une catégorie de l'affichage (non destructif, mémorisé par utilisateur). */
  basculerExclusion(categorie: string): void {
    if (this.categoriesExclues.has(categorie)) {
      this.categoriesExclues.delete(categorie);
    } else {
      this.categoriesExclues.add(categorie);
    }
    try { localStorage.setItem(`${this.cleStorage}-exclusions`, JSON.stringify([...this.categoriesExclues])); } catch { /* ignore */ }
  }

  estExclue(categorie: string | undefined | null): boolean {
    return !!categorie && this.categoriesExclues.has(categorie);
  }

  get dossiersNonAffectesFiltres(): Dossier[] {
    return this.dossiersNonAffectes.filter(d => !this.estExclue(d.competence_nom));
  }

  get signalementsNonAffectesFiltres(): Dossier[] {
    return this.signalementsNonAffectes.filter(d => !this.estExclue(d.competence_nom));
  }

  // ── Affecter depuis la cellule (1 clic si une équipe est suggérée, 2 sinon) ─────────

  /** Équipes de la crise pour ce dossier : la suggérée, puis celles qui prennent déjà sa
   * compétence, puis les autres. */
  equipesPour(d: Dossier): { id: string; libelle: string }[] {
    const prennent = new Set(this.affectationsCrise.filter(a => a.competence === d.competence).map(a => a.equipe));
    const rang = (t: Team) => t.id === d.equipe ? 0 : prennent.has(t.id!) ? 1 : 2;
    return this.equipes.map(e => e.team)
      .sort((a, b) => rang(a) - rang(b) || teamDisplayName(a).localeCompare(teamDisplayName(b)))
      .map(t => ({
        id: t.id!,
        libelle: teamDisplayName(t) + (t.id === d.equipe ? ' (suggérée)' : prennent.has(t.id!) ? ` (prend ${d.competence_nom})` : ''),
      }));
  }

  choixPour(d: Dossier): string {
    return this.equipeChoisie[d.id] ?? d.equipe ?? '';
  }

  affecterDossier(dossier: Dossier, equipeId: string): void {
    if (!equipeId || this.affectationEnCours) return;
    this.affectationEnCours = true;
    this.dossierService.affecterEquipe(dossier.id, equipeId, true).subscribe({
      next: (res) => {
        this.affectationEnCours = false;
        delete this.equipeChoisie[dossier.id];
        this.apresAffectation(1, this.nomEquipe(equipeId), res.apprentissages || [], !dossier.competence);
      },
      error: (err) => { this.affectationEnCours = false; alert(this.messageErreur(err, "Impossible d'affecter ce dossier.")); },
    });
  }

  basculerSelection(d: Dossier): void {
    if (this.selection.has(d.id)) this.selection.delete(d.id); else this.selection.add(d.id);
  }

  toutEstCoche(liste: Dossier[]): boolean {
    return liste.length > 0 && liste.every(d => this.selection.has(d.id));
  }

  basculerTout(liste: Dossier[]): void {
    if (this.toutEstCoche(liste)) liste.forEach(d => this.selection.delete(d.id));
    else liste.forEach(d => this.selection.add(d.id));
  }

  affecterSelection(): void {
    const ids = [...this.selection];
    if (!ids.length || !this.equipeLot || this.affectationEnCours) return;
    this.affectationEnCours = true;
    this.dossierService.affecterEquipeBulk(ids, this.equipeLot, true).subscribe({
      next: (res) => {
        this.affectationEnCours = false;
        this.selection.clear();
        this.apresAffectation(res.affectes, this.nomEquipe(this.equipeLot), res.apprentissages || [], false);
      },
      error: (err) => { this.affectationEnCours = false; alert(this.messageErreur(err, "Impossible d'affecter la sélection.")); },
    });
  }

  /** Catégories (compétences) présentes dans une liste, pour le filtre « Catégorie ». */
  categoriesDe(liste: Dossier[]): { nom: string; total: number }[] {
    const parNom = new Map<string, number>();
    liste.forEach(d => parNom.set(d.competence_nom || 'Sans compétence', (parNom.get(d.competence_nom || 'Sans compétence') || 0) + 1));
    return [...parNom.entries()].map(([nom, total]) => ({ nom, total })).sort((a, b) => b.total - a.total);
  }

  filtrerCategorie(liste: Dossier[]): Dossier[] {
    if (!this.filtreCategorie) return liste;
    return liste.filter(d => (d.competence_nom || 'Sans compétence') === this.filtreCategorie);
  }

  private nomEquipe(id: string): string {
    const e = this.equipes.find(x => x.team.id === id);
    return e ? teamDisplayName(e.team) : '';
  }

  private apresAffectation(nombre: number, equipe: string, appris: Apprentissage[], sansCompetence: boolean): void {
    this.chargerRessource();
    this.chargerCoordination();
    this.chargerCellule();
    const base = nombre > 1 ? `${nombre} dossiers affectés à ${equipe}.` : `Affecté à ${equipe}.`;
    if (appris.length) {
      const a = appris[0];
      const autres = a.dossiers_resuggeres ? ` ${a.dossiers_resuggeres} dossier(s) en attente lui sont maintenant suggérés.` : '';
      this.afficherToast(`${base} Désormais, les demandes « ${a.competence_nom} » lui seront suggérées.${autres}`,
        () => this.annulerApprentissages(appris));
    } else if (sansCompetence) {
      this.afficherToast(`${base} Ce type de demande n'a pas de compétence : pas de suggestion automatique pour les suivantes.`);
    } else {
      this.afficherToast(base);
    }
  }

  private annulerApprentissages(appris: Apprentissage[]): void {
    const appels = appris.map(a => a.cree
      ? this.affectationCompetenceService.delete(a.id)
      : this.affectationCompetenceService.patch(a.id, { active: false }));
    forkJoin(appels).subscribe({
      next: () => { this.afficherToast('Apprentissage annulé : les affectations faites sont conservées.'); this.chargerRessource(); },
      error: (err) => alert(this.messageErreur(err, "Impossible d'annuler.")),
    });
  }

  private afficherToast(texte: string, annuler?: () => void): void {
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toast = { texte, annuler };
    this.toastTimer = setTimeout(() => { this.toast = null; }, annuler ? 12000 : 5000);
  }

  annulerDepuisToast(): void {
    const annuler = this.toast?.annuler;
    this.toast = null;
    annuler?.();
  }

  // ── Panneau Coordination ────────────────────────────────────────────
  private chargerCoordination(): void {
    this.dossierService.getAll().subscribe(dossiers => {
      this.dossiersAValider = dossiers.filter(d =>
        d.crise === this.criseId && d.statut === 'EN_ATTENTE_AFFECTATION' && !!d.equipe,
      );
    });
    this.implicationService.getByCrise(this.criseId).subscribe(implications => {
      this.implicationsEnAttente = implications.filter(i => i.statut === 'EN_ATTENTE' && i.type_implication === 'ACTEUR');
    });
    this.journalService.getAll(this.criseId).subscribe(entries => { this.journal = entries; });
  }

  confirmerAffectation(dossier: Dossier): void {
    if (!dossier.equipe) return;
    this.dossierService.affecterEquipe(dossier.id, dossier.equipe).subscribe(() => this.chargerCoordination());
  }

  validerImplication(implication: ImplicationInstitution): void {
    this.implicationService.valider(implication.id).subscribe({
      next: () => this.chargerCoordination(),
      error: err => alert(this.messageErreur(err, 'Impossible de valider cette institution.')),
    });
  }

  refuserImplication(implication: ImplicationInstitution): void {
    this.implicationService.refuser(implication.id).subscribe({
      next: () => this.chargerCoordination(),
      error: err => alert(this.messageErreur(err, 'Impossible de refuser cette institution.')),
    });
  }

  // ── Aperçu dépliable ────────────────────────────────────────────────

  genreDossier(d: Dossier): GenreFiche {
    return d.information ? 'signalement' : 'demande';
  }

  libelleGenre(g: GenreFiche): string {
    return { demande: 'Demande', signalement: 'Signalement', offre: 'Offre' }[g];
  }

  iconeGenre(g: GenreFiche): string {
    return { demande: 'help_outline', signalement: 'info', offre: 'volunteer_activism' }[g];
  }

  estOuvert(cle: string): boolean { return this.apercus.has(cle); }

  /** Déplie / replie l'aperçu ; la photo n'est chargée qu'à la première ouverture (une requête
   * par fiche consultée, pas par ligne affichée). */
  basculerApercu(cle: string, genre: GenreFiche, objetId: string | null | undefined, aPhoto: boolean | undefined): void {
    if (this.apercus.has(cle)) { this.apercus.delete(cle); return; }
    this.apercus.add(cle);
    if (!objetId || !aPhoto || this.photos[objetId]) return;
    const service = genre === 'offre' ? this.offerService : genre === 'signalement' ? this.informationService : this.requestService;
    service.preview(objetId).subscribe({
      next: (blob) => { this.photos[objetId] = URL.createObjectURL(blob); },
      error: () => {},
    });
  }

  idSource(d: Dossier): string | null {
    return (d.information || d.demande) ?? null;
  }

  // ── Offres : affecter à une équipe (même effet que la page Signalements) ──

  equipeDeLOffre(o: Offer): string {
    const e = this.equipes.find(x => (x.team.assigned_offer_ids || []).includes(o.id));
    return e ? teamDisplayName(e.team) : '';
  }

  affecterOffre(o: Offer): void {
    const equipe = this.equipes.find(e => e.team.id === this.equipeOffre[o.id])?.team;
    if (!equipe || this.affectationEnCours) return;
    const offres = (equipe.assigned_offer_ids || []).includes(o.id) ? equipe.assigned_offer_ids : [...(equipe.assigned_offer_ids || []), o.id];
    // Comme la page Signalements : affecter l'offre ajoute aussi son auteur à l'équipe.
    let membres = equipe.member_ids ?? [];
    if (o.author && !membres.includes(o.author)) membres = [...membres, o.author];
    this.affectationEnCours = true;
    this.teamService.patch(equipe.id!, { assigned_offer_ids: offres, member_ids: membres }).subscribe({
      next: (maj) => {
        this.affectationEnCours = false;
        const e = this.equipes.find(x => x.team.id === maj.id);
        if (e) e.team = maj;
        delete this.equipeOffre[o.id];
        this.afficherToast(`Offre « ${o.title} » affectée à ${teamDisplayName(maj)}.`);
      },
      error: (err) => { this.affectationEnCours = false; alert(this.messageErreur(err, "Impossible d'affecter cette offre.")); },
    });
  }

  /** Message renvoyé par l'API (`error` de nos actions, `detail` d'un 403 DRF) ou repli. */
  private messageErreur(err: any, repli: string): string {
    return err?.error?.error || err?.error?.detail || repli;
  }

  envoyerEntreeJournal(): void {
    const contenu = this.nouvelleEntreeJournal.trim();
    if (!contenu) return;
    this.journalService.create(contenu, this.criseId).subscribe(() => {
      this.nouvelleEntreeJournal = '';
      this.chargerCoordination();
    });
  }
}
