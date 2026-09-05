import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';
import { DeclarationSecuriteService } from '../../services/declaration-securite.service';
import { OfferService } from '../../services/offer.service';
import { TeamService } from '../../services/team.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { DossierService } from '../../services/dossier.service';
import { JournalCollectiviteService } from '../../services/journal-collectivite.service';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../auth/services/auth.service';

import { Request } from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { DeclarationSecurite } from '../../shared/models/declaration-securite.model';
import { Offer } from '../../shared/models/offer.model';
import { Team } from '../../shared/models/team.model';
import { PointOperationnel } from '../../shared/models/point-operationnel.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Status } from '../../shared/models/status.model';
import { JournalCollectivite } from '../../shared/models/journal-collectivite.model';

const NIVEAU_LABEL: Record<string, string> = {
  commune: 'Communal',
  epci: 'Intercommunal',
  departement: 'Départemental',
  region: 'Régional',
  national: 'National',
};

type FiltreDemande = 'total' | 'non_affectee' | 'affectee' | 'en_cours' | 'traitee';

type CategorieLimite = 'demandes' | 'offres' | 'benevoles' | 'signalements';

// null = "Tout" (pas de plafond). 25 par défaut pour les 4 catégories — un secteur large
// (région, national) peut charger des centaines de fiches d'un coup, en particulier l'annuaire
// de bénévoles (voir generate_benevoles_pompiers_national), inutile à charger en entier par
// défaut sur cette page.
const LIMITES_PAR_DEFAUT: Record<CategorieLimite, number | null> = {
  demandes: 25,
  offres: 25,
  benevoles: 25,
  signalements: 25,
};
const LIMITES_STORAGE_KEY = 'vueCollectivite.limites';
const OPTIONS_LIMITE: (number | null)[] = [25, 50, 100, 250, 500, null];

@Component({
  selector: 'app-vue-mairie',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './vue-mairie.component.html',
  styleUrls: ['./vue-mairie.component.scss'],
})
export class VueMairieComponent implements OnInit {

  demandes: Request[] = [];
  filtreDemande: FiltreDemande = 'total';
  informations: Information[] = [];
  declarationsSecurite: DeclarationSecurite[] = [];
  offres: Offer[] = [];
  benevoles: Offer[] = [];
  equipes: Team[] = [];
  points: PointOperationnel[] = [];
  dossiers: Dossier[] = [];

  journalEntries: JournalCollectivite[] = [];
  nouvelleEntree = '';
  journalEnCours = false;
  journalErreur = '';

  maZoneNom: string | null = null;
  maZoneNiveau: string | null = null;
  risquesTerritoire: { num_risque: string; libelle_risque_long: string }[] = [];
  risquesDateMaj: string | null = null;
  risquesEnCours = false;

  isLoading = true;
  errorMessage = '';

  limites: Record<CategorieLimite, number | null> = this.chargerLimites();
  readonly optionsLimite = OPTIONS_LIMITE;

  readonly Status = Status;

  constructor(
    private requestService: RequestService,
    private informationService: InformationService,
    private declarationSecuriteService: DeclarationSecuriteService,
    private offerService: OfferService,
    private teamService: TeamService,
    private pointOperationnelService: PointOperationnelService,
    private dossierService: DossierService,
    private journalCollectiviteService: JournalCollectiviteService,
    private userService: UserService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.loadAll();
    this.loadMaZone();
    this.loadJournal();
  }

  loadMaZone(): void {
    // Rafraîchi depuis le serveur (pas juste localStorage) : la zone peut avoir changé
    // (rattachement d'institution, secteur_override) depuis la dernière connexion.
    this.authService.fetchMe().subscribe({
      next: (user) => {
        this.maZoneNom = user.ma_zone?.nom ?? null;
        this.maZoneNiveau = user.ma_zone?.niveau ?? null;
        this.risquesTerritoire = user.ma_zone?.risques ?? [];
        this.risquesDateMaj = user.ma_zone?.risques_date_maj ?? null;
      },
      error: () => {},
    });
  }

  actualiserRisques(): void {
    this.risquesEnCours = true;
    this.userService.actualiserRisques().subscribe({
      next: ({ risques, risques_date_maj }) => {
        this.risquesTerritoire = risques;
        this.risquesDateMaj = risques_date_maj;
        this.risquesEnCours = false;
      },
      error: () => { this.risquesEnCours = false; },
    });
  }

  niveauLabel(niveau: string | null): string {
    return niveau ? (NIVEAU_LABEL[niveau] ?? niveau) : '';
  }

  labelLimite(v: number | null): string {
    return v === null ? 'Tout' : String(v);
  }

  // Le récapitulatif des demandes (voir recapDemandes) est calculé sur les seules demandes
  // chargées : si un plafond est actif et pile atteint, il ne reflète alors qu'un sous-ensemble
  // du secteur, pas le total réel — averti dans le template plutôt que silencieusement inexact.
  get recapDemandesTronque(): boolean {
    return this.limites.demandes !== null && this.demandes.length === this.limites.demandes;
  }

  loadJournal(): void {
    this.journalCollectiviteService.getAll().subscribe({
      next: (entries) => { this.journalEntries = entries; },
      error: () => {},
    });
  }

  ajouterEntreeJournal(): void {
    const contenu = this.nouvelleEntree.trim();
    if (!contenu) return;
    this.journalEnCours = true;
    this.journalErreur = '';
    this.journalCollectiviteService.create(contenu).subscribe({
      next: (entry) => {
        this.journalEntries = [entry, ...this.journalEntries];
        this.nouvelleEntree = '';
        this.journalEnCours = false;
      },
      error: (err) => {
        this.journalErreur = err?.error?.error || "Impossible d'ajouter cette entrée au journal.";
        this.journalEnCours = false;
      },
    });
  }

  loadAll(): void {
    this.isLoading = true;
    this.errorMessage = '';
    forkJoin({
      demandes: this.requestService.vueSecteur({ limite: this.limites.demandes ?? undefined }),
      informations: this.informationService.vueMairie({ limite: this.limites.signalements ?? undefined }),
      declarationsSecurite: this.declarationSecuriteService.vueMairie(),
      offres: this.offerService.vueSecteur({ limite: this.limites.offres ?? undefined, excludeType: 'Bénévolat' }),
      benevoles: this.offerService.vueSecteur({ limite: this.limites.benevoles ?? undefined, type: 'Bénévolat' }),
      equipes: this.teamService.vueMairie(),
      points: this.pointOperationnelService.vueMairie(),
      dossiers: this.dossierService.vueMairie(),
    }).subscribe({
      next: ({ demandes, informations, declarationsSecurite, offres, benevoles, equipes, points, dossiers }) => {
        this.demandes = demandes;
        this.informations = informations;
        this.declarationsSecurite = declarationsSecurite;
        this.offres = offres;
        this.benevoles = benevoles;
        this.equipes = equipes;
        this.points = points;
        this.dossiers = dossiers;
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMessage = err?.error?.error || "Impossible de charger la vue de votre collectivité.";
        this.isLoading = false;
      },
    });
  }

  private chargerLimites(): Record<CategorieLimite, number | null> {
    try {
      const brut = localStorage.getItem(LIMITES_STORAGE_KEY);
      if (brut) return { ...LIMITES_PAR_DEFAUT, ...JSON.parse(brut) };
    } catch {}
    return { ...LIMITES_PAR_DEFAUT };
  }

  changerLimite(categorie: CategorieLimite, valeur: number | null): void {
    this.limites = { ...this.limites, [categorie]: valeur };
    try {
      localStorage.setItem(LIMITES_STORAGE_KEY, JSON.stringify(this.limites));
    } catch {}
    this.loadAll();
  }

  get recapDemandes(): Record<FiltreDemande, number> {
    return {
      total: this.demandes.length,
      non_affectee: this.demandes.filter(d => !d.est_affectee).length,
      affectee: this.demandes.filter(d => !!d.est_affectee).length,
      en_cours: this.demandes.filter(d => d.status === Status.IN_PROGRESS).length,
      traitee: this.demandes.filter(d => d.status === Status.PROCESSED).length,
    };
  }

  get demandesAffichees(): Request[] {
    switch (this.filtreDemande) {
      case 'non_affectee': return this.demandes.filter(d => !d.est_affectee);
      case 'affectee':     return this.demandes.filter(d => !!d.est_affectee);
      case 'en_cours':     return this.demandes.filter(d => d.status === Status.IN_PROGRESS);
      case 'traitee':      return this.demandes.filter(d => d.status === Status.PROCESSED);
      default:             return this.demandes;
    }
  }

  setFiltreDemande(filtre: FiltreDemande): void {
    this.filtreDemande = filtre;
  }

  headcount(d: DeclarationSecurite): number {
    return d.nombre_adultes + d.nombre_enfants;
  }

  statusLabel(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'Non traitée',
      [Status.IN_PROGRESS]:  'En cours',
      [Status.PROCESSED]:    'Traitée',
      [Status.AVAILABLE]:    'Disponible',
      [Status.UNAVAILABLE]:  'Indisponible',
    } as Record<string, string>)[s] ?? s;
  }

  statusClass(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'stat-urgent',
      [Status.IN_PROGRESS]:  'stat-encours',
      [Status.PROCESSED]:    'stat-traitee',
      [Status.AVAILABLE]:    'stat-dispo',
      [Status.UNAVAILABLE]:  'stat-indispo',
    } as Record<string, string>)[s] ?? '';
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  fmtDateHeure(d: string): string {
    return new Date(d).toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }
}
