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
import { DossierService } from '../../services/dossier.service';
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
    const equipesDeLaCrise = this.equipes.map(e => e.team);
    const appels = equipesDeLaCrise
      .filter(t => !!t.salon_matrix_room_id)
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

  chargerMessagesEquipe = (equipeId: string) => () => this.teamService.getSalonMatrixMessages(equipeId);
  envoyerMessageEquipe = (equipeId: string) => (texte: string, urgent = false) => this.teamService.envoyerMessageSalonMatrix(equipeId, texte, urgent);
  reagirMessageEquipe = (equipeId: string) => (eventId: string) => this.teamService.reagirSalonMatrix(equipeId, eventId);

  demarrerEngagement(team: Team): void {
    this.teamService.demarrerEngagement(team.id!).subscribe(t => { team.engagement_debut = t.engagement_debut; });
  }

  mettreAuRepos(team: Team): void {
    this.teamService.mettreAuRepos(team.id!).subscribe(t => { team.engagement_debut = t.engagement_debut; });
  }

  // ── Panneau Ressource ───────────────────────────────────────────────
  changerOngletRessource(o: OngletRessource): void { this.ongletRessource = o; }

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

  affecterDossier(dossier: Dossier, equipeId: string): void {
    if (!equipeId) return;
    this.dossierService.affecterEquipe(dossier.id, equipeId).subscribe(() => this.chargerRessource());
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
    this.implicationService.valider(implication.id).subscribe(() => this.chargerCoordination());
  }

  refuserImplication(implication: ImplicationInstitution): void {
    this.implicationService.refuser(implication.id).subscribe(() => this.chargerCoordination());
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
