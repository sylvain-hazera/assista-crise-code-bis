import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { catchError, forkJoin, Observable, of, Subject, takeUntil } from 'rxjs';

import { CrisisService }  from '../../services/crisis.service';
import { OfferService }   from '../../services/offer.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';
import { GeolocationService } from '../../services/geolocation.service';
import { DisponibiliteOffreService } from '../../services/disponibilite-offre.service';
import { TeamService } from '../../services/team.service';
import { DossierService } from '../../services/dossier.service';
import { MissionService } from '../../services/mission.service';
import { UserService } from '../../services/user.service';
import { CompetenceService } from '../../services/competence.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { MinimapComponent } from '../../shared/components/common/minimap/minimap.component';
import { Competence } from '../../shared/models/competence.model';

import { DisponibiliteOffre } from '../../shared/models/disponibilite-offre.model';
import { Team, teamDisplayName } from '../../shared/models/team.model';
import { PointOperationnel } from '../../shared/models/point-operationnel.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Mission } from '../../shared/models/mission.model';
import { User, UserRole } from '../../shared/models/user.model';

import { Crisis }       from '../../shared/models/crisis.model';
import { Offer }       from '../../shared/models/offer.model';
import { Request }     from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { Status }      from '../../shared/models/status.model';
import { PageResponse } from '../../shared/models/api.model';

// ── Unified row displayed in the table ───────────────────────────────────────

export type ReportKind = 'Crisis' | 'Offer' | 'Request' | 'Information';

export interface ReportRow {
  id:           string;
  kind:         ReportKind;
  title:        string;
  contact:      string;        // first_name + last_name
  email:        string;
  telephone:    string | null;
  status:       Status;
  date:         string;        // created_at / start_date
  dateExp:      string | null;
  crisis:        string | null; // UUID
  crisis_nom:   string | null;
  author:       string | null;
  author_nom:   string | null;
  latitude:     number | null;
  longitude:    number | null;
  has_photo:    boolean;
  commune:      string | null;
  distanceFromCrisisKm: number | null;
  authorType:   string | null;
  isSecoursAccount: boolean;
  competencesLibelles: string[];
  description: string | null;
  // Offres uniquement (voir propose-help-form).
  materielLivraison?: string | null;
  diplomeSecourisme?: boolean;
  ancienSapeurPompier?: boolean;
  confirmationReglementaire?: boolean;
  presencePhysique?: boolean | null;
  organisationNom?: string | null;   // dépôt groupé : nom de l'entreprise/association déposante
  groupeId?: string | null;
  // Offer/Request/Information ; toujours true pour Crisis (supprimée réellement).
  actif:        boolean;
  // raw originals for detail modal
  _raw:         Crisis | Offer | Request | Information;
}

// ─────────────────────────────────────────────────────────────────────────────

type FilterKind   = ReportKind | 'ALL';
type FilterStatus = Status     | 'ALL';
type SortField    = 'title' | 'kind' | 'status' | 'date' | 'contact' | 'commune' | 'distanceFromCrisisKm';
type EchelleFilter = 'zone' | 'rayon' | 'departement' | 'region' | 'national';

// SortField (UI) -> `ordering` serveur. 'contact' est absent : champ chiffré, trié côté client
// sur la page affichée. Un ordering non supporté est ignoré par DRF, d'où une table unique.
const ORDERING_FIELD_MAP: Partial<Record<SortField, string>> = {
  title: 'title',
  status: 'status',
  date: 'created_at',
  commune: 'commune_code',
  distanceFromCrisisKm: 'distance_from_crisis',
};

@Component({
  selector: 'app-reporting',
  standalone: true,
  imports: [CommonModule, FormsModule, MinimapComponent],
  templateUrl: './reporting.component.html',
  styleUrls: ['./reporting.component.scss'],
})
export class ReportingComponent implements OnInit, OnDestroy {
  teamDisplayName = teamDisplayName;

  private destroy$ = new Subject<void>();

  // ── Support data (chargées une fois, non paginées) ────
  teams:           Team[]        = [];
  dossiers:        Dossier[]     = [];
  missions:        Mission[]     = [];
  regulateurs:     User[]        = [];
  /** Annuaire permanent de bénévoles (mode pickForTeamId), chargé une fois. Voir OfferService.vueSecteur. */
  benevoleRows:    ReportRow[]   = [];

  // ── Détail offre : disponibilités + affectation ─────────────
  selectedOfferDispos: DisponibiliteOffre[] = [];
  assignTeamId:    string | null = null;
  assignDossierId: string | null = null;

  // ── Lignes affichées : page courante du type actif, ou aperçu borné pour « Tout » ──
  pagedRows:    ReportRow[] = [];
  /** Total pour le type actif (`count` paginé) ; sans objet pour « Tout ». */
  totalCount = 0;

  // ── UI state ───────────────────────────────────────────────
  isLoading      = true;
  isSaving       = false;
  errorMessage   = '';
  successMessage = '';

  // ── Filters / sort ─────────────────────────────────────────
  searchQuery   = '';
  filterKind:   FilterKind   = 'ALL';
  filterStatus: FilterStatus = 'ALL';
  // Filtre client sur la page affichée (le nom de commune n'est pas une colonne commune aux 4 types).
  filterCommune   = '';
  filterCompetence = 'ALL';
  filterMaterielLivraison: 'ALL' | 'A_RECUPERER' | 'LIVRAISON_POSSIBLE' = 'ALL';
  sortField:    SortField    = 'date';
  sortAsc                    = false;
  // Les éléments désactivés sont masqués par le backend ; ?actif=all les fait réapparaître.
  showDesactives = false;

  // ── Échelle géographique (par défaut : ma zone) ─────────────
  // 'zone' = ?scope=zone ; 'rayon' = ?scope=zone&rayon_km= (offres seulement) ; autres = ?echelle=.
  echelleOptions: { value: EchelleFilter; label: string }[] = [
    { value: 'zone',        label: 'Ma zone' },
    { value: 'rayon',       label: 'Rayon (km)' },
    { value: 'departement', label: 'Mon département' },
    { value: 'region',      label: 'Ma région' },
    { value: 'national',    label: 'Toute la France' },
  ];
  echelle: EchelleFilter = 'zone';
  rayonKm = 25;

  competences: Competence[] = [];

  // ── Pagination (serveur) ────────────────────────────────────
  pageSize    = 15;
  currentPage = 1;
  totalPages  = 1;

  // ── Modals ─────────────────────────────────────────────────
  showDetailModal = false;
  showDeleteModal = false;
  showStatusModal = false;
  selectedRow: ReportRow | null = null;
  selectedRowAddress: string | null = null;
  isLoadingAddress = false;
  newStatus:   Status | ''      = '';

  // ── Sélection multiple + actions groupées ─────────────────────
  // Persiste entre les pages : Set d'ids + Map des lignes complètes (même patron que
  // RecrutementBenevolesModalComponent).
  selectedOfferIds   = new Set<string>();
  selectedRequestIds = new Set<string>();
  selectedInformationIds = new Set<string>();
  private selectedOfferRowsMap   = new Map<string, ReportRow>();
  private selectedRequestRowsMap = new Map<string, ReportRow>();
  private selectedInformationRowsMap = new Map<string, ReportRow>();

  showBulkInformationModal = false;
  bulkInformationTeamId: string | null = null;
  bulkInformationTeamQuery = '';
  showBulkInformationTeamResults = false;

  showBulkOfferModal   = false;
  bulkTeamName          = '';
  bulkRegulateurId: string | null = null;
  bulkRegulateurQuery    = '';
  showBulkRegulateurResults = false;

  showBulkRequestModal = false;
  bulkMissionMode: 'existing' | 'new' = 'new';
  bulkMissionId: string | null = null;
  bulkNewMissionTitre   = '';
  bulkTeamIdForRequests: string | null = null;
  bulkTeamQuery          = '';
  showBulkTeamResults    = false;

  // ── Photos (récupérées en blob via l'action access-contrôlée) ──────────
  photoUrls: Record<string, string> = {};

  // ── Exposed enums ──────────────────────────────────────────
  readonly Status = Status;

  readonly kindOptions: { label: string; value: FilterKind; icon: string }[] = [
    { label: 'Tout',         value: 'ALL',         icon: 'dashboard'           },
    { label: 'Crises',       value: 'Crisis',        icon: 'local_fire_department'},
    { label: 'Offres',       value: 'Offer',        icon: 'volunteer_activism'  },
    { label: 'Demandes',     value: 'Request',      icon: 'emergency'           },
    { label: 'Informations', value: 'Information',  icon: 'info'                },
  ];

  /** Compteurs par onglet, issus du `count` de chaque réponse paginée. */
  countByKind: Record<string, number> = { ALL: 0, Crisis: 0, Offer: 0, Request: 0, Information: 0 };

  readonly statusOptions: { label: string; value: FilterStatus }[] = [
    { label: 'Tous statuts',  value: 'ALL'             },
    { label: 'Non traitée',   value: Status.UNPROCESSED},
    { label: 'En cours',      value: Status.IN_PROGRESS   },
    { label: 'Traitée',       value: Status.PROCESSED    },
    { label: 'Disponible',    value: Status.AVAILABLE },
    { label: 'Indisponible',  value: Status.UNAVAILABLE},
  ];

  readonly editableStatuses: { label: string; value: Status }[] = [
    { label: 'Non traitée',  value: Status.UNPROCESSED  },
    { label: 'En cours',     value: Status.IN_PROGRESS     },
    { label: 'Traitée',      value: Status.PROCESSED      },
    { label: 'Disponible',   value: Status.AVAILABLE   },
    { label: 'Indisponible', value: Status.UNAVAILABLE },
  ];

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private crisisService:      CrisisService,
    private offerService:       OfferService,
    private requestService:     RequestService,
    private informationService: InformationService,
    private geolocationService: GeolocationService,
    private disponibiliteOffreService: DisponibiliteOffreService,
    private teamService:        TeamService,
    private dossierService:     DossierService,
    private missionService:     MissionService,
    private userService:        UserService,
    private competenceService:  CompetenceService,
    private pointOperationnelService: PointOperationnelService,
  ) {}

  /** Arrivée depuis le détail d'une équipe : bouton « Ajouter à l'équipe » par offre. */
  pickForTeamId: string | null = null;
  /** Arrivée depuis le détail d'un point : bouton « Ajouter au stock » par offre de matériel.
   * Exclusif avec pickForTeamId. */
  pickForPointId: string | null = null;
  points: PointOperationnel[] = [];

  /** Mode picker (équipe ou point) : la sélection groupée est masquée, les actions de ligne restent. */
  get pickerModeActive(): boolean {
    return !!(this.pickForTeamId || this.pickForPointId);
  }

  /** Onglet « Tout » : 1re page de chaque type, sans pagination ni tri. */
  get isOverview(): boolean {
    return this.filterKind === 'ALL';
  }

  ngOnInit():    void {
    this.pickForTeamId = this.route.snapshot.queryParamMap.get('pickForTeam');
    this.pickForPointId = this.route.snapshot.queryParamMap.get('pickForPoint');

    // Données de support chargées une fois, non rechargées à chaque filtre ou page.
    forkJoin({
      teams:    this.teamService.getAll(),
      dossiers: this.dossierService.getAll(),
      missions: this.missionService.getAll(),
      users:    this.userService.getAll(),
    }).pipe(takeUntil(this.destroy$)).subscribe({
      next: ({ teams, dossiers, missions, users }) => {
        this.teams = teams;
        this.dossiers = dossiers;
        this.missions = missions;
        this.regulateurs = users.filter(u => u.type === UserRole.REGULATEUR);
      },
      error: () => {},
    });

    if (this.pickForTeamId) {
      this.offerService.vueSecteur().pipe(catchError(() => of([]))).subscribe(offres => {
        this.benevoleRows = offres.map(o => this.toRow('Offer', o));
        if (this.filterKind === 'Offer' || this.filterKind === 'ALL') this.load();
      });
    }

    this.competenceService.getAll().subscribe({
      next: (competences) => { this.competences = competences; },
      error: () => {},
    });
    if (this.pickForPointId) {
      this.pointOperationnelService.getAll().subscribe({
        next: (points) => this.points = points,
        error: () => {},
      });
    }

    this.load();
    this.openByIdFromUrl();
  }

  get pickForTeam(): Team | undefined {
    return this.teams.find(t => t.id === this.pickForTeamId);
  }

  get pickForPoint(): PointOperationnel | undefined {
    return this.points.find(p => p.id === this.pickForPointId);
  }

  /** Ajoute l'offre comme ressource de l'équipe (TeamViewSet.assigner_ressource) ; reste sur le
   * tableau pour en ajouter plusieurs. */
  ajouterCommeRessource(offerId: string, e?: Event): void {
    e?.stopPropagation();
    if (!this.pickForTeamId) return;
    this.teamService.assignerRessource(this.pickForTeamId, offerId).subscribe({
      next: () => this.showSuccess('Ressource ajoutée à l\'équipe.'),
      error: (err) => this.showError(err?.error?.error || "Impossible d'ajouter cette ressource."),
    });
  }

  /** Ajoute l'offre au stock du point (OfferViewSet.affecter_stock). */
  ajouterAuStock(offerId: string, e?: Event): void {
    e?.stopPropagation();
    if (!this.pickForPointId) return;
    this.offerService.affecterStock(offerId, this.pickForPointId).subscribe({
      next: () => this.showSuccess('Matériel ajouté au stock du point.'),
      error: (err) => this.showError(err?.error?.error || "Impossible d'ajouter ce matériel au stock."),
    });
  }

  retourEquipe(): void {
    this.router.navigate(['/admin/equipes'], { queryParams: { openTeam: this.pickForTeamId } });
  }

  retourPoint(): void {
    this.router.navigate(['/admin/centres']);
  }

  isOffreMateriel(row: ReportRow): boolean {
    return row.kind === 'Offer' && (row._raw as Offer).materiel_type != null;
  }
  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    Object.values(this.photoUrls).forEach(url => URL.revokeObjectURL(url));
  }

  // ────────────────────────────────────────────────────────────────────────────
  // LOAD (serveur : pagination + recherche + tri + filtres, voir DOCUMENTATION.md, § 6.2)
  // ────────────────────────────────────────────────────────────────────────────

  /** Échelle commune aux 4 types : ?scope=zone + ?echelle= éventuel. ?rayon_km= ne concerne que les offres. */
  private buildEchelleParams(forOffer = false): Record<string, string> {
    const params: Record<string, string> = { scope: 'zone' };
    if (this.echelle === 'rayon') {
      if (forOffer) params['rayon_km'] = String(this.rayonKm);
    } else if (this.echelle !== 'zone') {
      params['echelle'] = this.echelle;
    }
    return params;
  }

  /** Query params serveur d'un type : échelle, actif, search/status/ordering, et
   * competence/materiel_livraison pour les offres. */
  private buildParams(kind: ReportKind): Record<string, string> {
    const params: Record<string, string> = { ...this.buildEchelleParams(kind === 'Offer') };
    if (this.showDesactives && kind !== 'Crisis') params['actif'] = 'all';
    if (kind === 'Offer') params['exclude_type'] = 'Bénévolat';
    const q = this.searchQuery.trim();
    if (q) params['search'] = q;
    if (this.filterStatus !== 'ALL' && kind !== 'Crisis') params['status'] = this.filterStatus;
    if (kind === 'Offer') {
      if (this.filterCompetence !== 'ALL') params['competence'] = this.filterCompetence;
      if (this.filterMaterielLivraison !== 'ALL') params['materiel_livraison'] = this.filterMaterielLivraison;
    }
    if (this.sortField !== 'contact' && this.sortField !== 'kind') {
      const field = kind === 'Crisis'
        ? ({ date: 'start_date', title: 'name' } as Partial<Record<SortField, string>>)[this.sortField]
        : ORDERING_FIELD_MAP[this.sortField];
      if (field) params['ordering'] = this.sortAsc ? field : `-${field}`;
    }
    return params;
  }

  private searchPageFor(kind: ReportKind, page: number, pageSize: number): Observable<PageResponse<Crisis | Offer | Request | Information>> {
    const params = this.buildParams(kind);
    switch (kind) {
      case 'Crisis':      return this.crisisService.searchPage(params, page, pageSize);
      case 'Offer':       return this.offerService.searchPage(params, page, pageSize);
      case 'Request':     return this.requestService.searchPage(params, page, pageSize);
      case 'Information': return this.informationService.searchPage(params, page, pageSize);
    }
  }

  /** Point d'entrée unique, appelé après tout changement de filtre/tri/page/onglet. */
  load(): void {
    this.isLoading = true;
    this.selectedOfferIds.clear();
    this.selectedRequestIds.clear();
    this.selectedInformationIds.clear();
    this.selectedOfferRowsMap.clear();
    this.selectedRequestRowsMap.clear();
    this.selectedInformationRowsMap.clear();

    if (this.isOverview) {
      this.loadOverview();
    } else {
      this.loadKindPage(this.filterKind as ReportKind);
    }
  }

  /** Recharge en conservant la sélection et la page (load() revient à la page 1). */
  private reload(): void {
    this.isLoading = true;
    if (this.isOverview) this.loadOverview();
    else this.loadKindPage(this.filterKind as ReportKind);
  }

  private loadKindPage(kind: ReportKind): void {
    this.searchPageFor(kind, this.currentPage, this.pageSize)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (res) => {
          let rows = res.results.map(raw => this.toRow(kind, raw));
          if (kind === 'Offer' && this.pickForTeamId) rows = [...rows, ...this.benevoleRows];
          this.lastFetchedRows = rows;
          this.applyCommuneFilterAndContactSort();
          this.totalCount = res.count;
          this.totalPages = Math.max(1, Math.ceil(res.count / this.pageSize));
          this.currentPage = Math.min(this.currentPage, this.totalPages);
          this.countByKind[kind] = res.count;
          this.afterRowsLoaded();
        },
        error: () => { this.showError('Impossible de charger les signalements.'); this.isLoading = false; },
      });
    this.refreshOtherCounts(kind);
  }

  /** Onglet « Tout » : 1re page de chaque type, fusionnée et triée par date côté client (≤40 lignes). */
  private loadOverview(): void {
    const OVERVIEW_PAGE_SIZE = 10;
    const kinds: ReportKind[] = ['Crisis', 'Offer', 'Request', 'Information'];
    forkJoin(kinds.map(k => this.searchPageFor(k, 1, OVERVIEW_PAGE_SIZE).pipe(
      catchError(() => of({ count: 0, next: null, previous: null, results: [] } as PageResponse<any>)),
    )))
    .pipe(takeUntil(this.destroy$))
    .subscribe(responses => {
      let rows: ReportRow[] = [];
      responses.forEach((res, i) => {
        const kind = kinds[i];
        this.countByKind[kind] = res.count;
        rows.push(...res.results.map(raw => this.toRow(kind, raw)));
      });
      if (this.pickForTeamId) rows.push(...this.benevoleRows);
      rows.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
      this.lastFetchedRows = rows;
      this.applyCommuneFilterAndContactSort();
      this.countByKind['ALL'] = kinds.reduce((sum, k) => sum + (this.countByKind[k] ?? 0), 0);
      this.totalCount = this.pagedRows.length;
      this.totalPages = 1;
      this.afterRowsLoaded();
    });
  }

  /** Met à jour les compteurs des autres onglets (page_size=1, seul `count` sert). */
  private refreshOtherCounts(activeKind: ReportKind): void {
    const others = (['Crisis', 'Offer', 'Request', 'Information'] as ReportKind[]).filter(k => k !== activeKind);
    forkJoin(others.map(k => this.searchPageFor(k, 1, 1).pipe(
      catchError(() => of({ count: this.countByKind[k] ?? 0, next: null, previous: null, results: [] } as PageResponse<any>)),
    )))
    .pipe(takeUntil(this.destroy$))
    .subscribe(responses => {
      responses.forEach((res, i) => { this.countByKind[others[i]] = res.count; });
      this.countByKind['ALL'] = (['Crisis', 'Offer', 'Request', 'Information'] as ReportKind[])
        .reduce((sum, k) => sum + (this.countByKind[k] ?? 0), 0);
    });
  }

  /** Dernière page reçue, avant filtre commune et tri contact (appliqués côté client). */
  private lastFetchedRows: ReportRow[] = [];

  /** Recalcule `pagedRows` (filtre commune puis tri contact), sans requête. */
  private applyCommuneFilterAndContactSort(): void {
    const q = this.filterCommune.trim().toLowerCase();
    const rows = q ? this.lastFetchedRows.filter(r => r.commune?.toLowerCase().includes(q)) : [...this.lastFetchedRows];
    if (this.sortField === 'contact') this.sortRowsByContact(rows);
    this.pagedRows = rows;
  }

  /** Filtre commune purement client. */
  onCommuneFilterChange(): void {
    this.applyCommuneFilterAndContactSort();
  }

  private sortRowsByContact(rows: ReportRow[]): void {
    rows.sort((a, b) => {
      const va = (a.contact || '').toLowerCase();
      const vb = (b.contact || '').toLowerCase();
      if (va < vb) return this.sortAsc ? -1 : 1;
      if (va > vb) return this.sortAsc ? 1 : -1;
      return 0;
    });
  }

  private afterRowsLoaded(): void {
    this.isLoading = false;
    this.pagedRows.filter(r => r.has_photo).forEach(r => this.loadRowPhoto(r));
  }

  /** Ouvre le détail d'une ligne passée par `?id=`, indépendamment de la page chargée. Le type
   * n'étant pas dans l'URL, les 4 types sont essayés en parallèle. */
  private openByIdFromUrl(): void {
    const targetId = this.route.snapshot.queryParamMap.get('id');
    if (!targetId) return;
    forkJoin({
      Crisis: this.crisisService.getById(targetId).pipe(catchError(() => of(null))),
      Offer: this.offerService.getById(targetId).pipe(catchError(() => of(null))),
      Request: this.requestService.getById(targetId).pipe(catchError(() => of(null))),
      Information: this.informationService.getById(targetId).pipe(catchError(() => of(null))),
    }).pipe(takeUntil(this.destroy$)).subscribe(found => {
      const kind = (Object.keys(found) as ReportKind[]).find(k => found[k] != null);
      if (kind) this.openDetail(this.toRow(kind, found[kind] as any));
    });
  }

  // ────────────────────────────────────────────────────────────────────────────
  // BUILD ROW (un type brut -> ReportRow)
  // ────────────────────────────────────────────────────────────────────────────

  private toRow(kind: ReportKind, raw: Crisis | Offer | Request | Information): ReportRow {
    switch (kind) {
      case 'Crisis': {
        const c = raw as Crisis;
        return {
          id: c.id, kind: 'Crisis', title: c.name, contact: '—', email: '—', telephone: null,
          status: (c.status ?? Status.UNPROCESSED) as Status, date: c.start_date, dateExp: c.end_date,
          crisis: c.id, crisis_nom: null, author: c.author, author_nom: null,
          latitude: c.latitude ?? null, longitude: c.longitude ?? null, has_photo: !!c.has_photo,
          commune: null, distanceFromCrisisKm: null, authorType: null, isSecoursAccount: false,
          competencesLibelles: [], description: c.description ?? null, actif: true, _raw: c,
        };
      }
      case 'Offer': {
        const o = raw as Offer;
        return {
          id: o.id, kind: 'Offer', title: o.title,
          contact: `${o.first_name_offer} ${o.last_name_offer}`, email: o.email_offer,
          telephone: o.phone_offer ?? o.author_phone ?? null, status: o.status, date: o.created_at,
          dateExp: o.expires_at, crisis: o.crisis, crisis_nom: o.crisis_nom ?? null, author: o.author,
          author_nom: o.author_nom ?? null, latitude: o.latitude ?? null, longitude: o.longitude ?? null,
          has_photo: !!o.has_photo, commune: o.commune ?? null,
          distanceFromCrisisKm: o.distance_from_crisis_km ?? null, authorType: o.author_type ?? null,
          isSecoursAccount: o.author_type === 'SECOURS', competencesLibelles: o.competences_libelles ?? [],
          description: o.description ?? null, materielLivraison: o.materiel_livraison ?? null,
          diplomeSecourisme: !!o.diplome_secourisme, ancienSapeurPompier: !!o.ancien_sapeur_pompier,
          confirmationReglementaire: !!o.confirmation_reglementaire, presencePhysique: o.presence_physique ?? null,
          organisationNom: o.organisation_nom ?? null, groupeId: o.groupe_id ?? null,
          actif: o.actif !== false, _raw: o,
        };
      }
      case 'Request': {
        const d = raw as Request;
        return {
          id: d.id, kind: 'Request', title: d.title,
          contact: `${d.first_name_request} ${d.last_name_request}`, email: d.email_request,
          telephone: d.phone_request, status: d.status, date: d.created_at, dateExp: d.expires_at,
          crisis: d.crisis, crisis_nom: d.crisis_nom ?? null, author: d.author,
          author_nom: d.author_nom ?? null, latitude: d.latitude ?? null, longitude: d.longitude ?? null,
          has_photo: !!d.has_photo, commune: d.commune ?? null,
          distanceFromCrisisKm: d.distance_from_crisis_km ?? null, authorType: d.author_type ?? null,
          isSecoursAccount: d.author_type === 'SECOURS', competencesLibelles: [],
          description: d.description ?? null, actif: d.actif !== false, _raw: d,
        };
      }
      case 'Information': {
        const i = raw as Information;
        return {
          id: i.id, kind: 'Information', title: i.title,
          contact: `${i.first_name_information} ${i.last_name_information}`, email: i.email_information,
          telephone: i.phone_information, status: i.status, date: i.created_at, dateExp: i.expires_at,
          crisis: i.crisis, crisis_nom: i.crisis_nom ?? null, author: i.author,
          author_nom: i.author_nom ?? null, latitude: i.latitude ?? null, longitude: i.longitude ?? null,
          has_photo: !!i.has_photo, commune: i.commune ?? null,
          distanceFromCrisisKm: i.distance_from_crisis_km ?? null, authorType: i.author_type ?? null,
          isSecoursAccount: i.author_type === 'SECOURS', competencesLibelles: [], description: null,
          actif: i.actif !== false, _raw: i,
        };
      }
    }
  }

  /** Photo via /preview/ du service du type ; un 403 laisse simplement la vignette vide. */
  private loadRowPhoto(row: ReportRow): void {
    const service = {
      Crisis: this.crisisService,
      Offer: this.offerService,
      Request: this.requestService,
      Information: this.informationService,
    }[row.kind];

    service.preview(row.id).subscribe({
      next: (blob) => { this.photoUrls[row.id] = URL.createObjectURL(blob); },
      error: () => {},
    });
  }

  // ────────────────────────────────────────────────────────────────────────────
  // FILTER / SORT / PAGINATE (déclenchent un rechargement serveur, voir load())
  // ────────────────────────────────────────────────────────────────────────────

  changeKind(kind: FilterKind): void {
    this.filterKind = kind;
    this.currentPage = 1;
    this.load();
  }

  setSort(field: SortField): void {
    if (this.sortField === field) this.sortAsc = !this.sortAsc;
    else { this.sortField = field; this.sortAsc = true; }
    // 'contact' (champ chiffré) : tri local sur la page déjà affichée, pas de rechargement.
    if (field === 'contact') { this.sortRowsByContact(this.pagedRows); return; }
    this.load();
  }

  changePage(p: number): void {
    if (p < 1 || p > this.totalPages || this.isOverview) return;
    this.currentPage = p;
    this.isLoading = true;
    this.loadKindPage(this.filterKind as ReportKind);
  }

  resetFilters(): void {
    this.searchQuery   = '';
    this.filterKind    = 'ALL';
    this.filterStatus  = 'ALL';
    this.filterCommune = '';
    this.filterCompetence = 'ALL';
    this.filterMaterielLivraison = 'ALL';
    this.currentPage   = 1;
    this.load();
  }

  // ────────────────────────────────────────────────────────────────────────────
  // ACTIONS
  // ────────────────────────────────────────────────────────────────────────────

  openDetail(row: ReportRow): void {
    this.selectedRow    = row;
    this.showDetailModal = true;
    this.selectedRowAddress = null;
    this.selectedOfferDispos = [];
    this.assignTeamId = null;
    this.assignDossierId = null;

    // L'API ne renvoie ces coordonnées qu'aux institutionnels : on affiche l'adresse précise.
    if (row.latitude != null && row.longitude != null) {
      this.isLoadingAddress = true;
      this.geolocationService.reverseGeocode(row.latitude, row.longitude).subscribe({
        next: (res) => {
          const props = res?.features?.[0]?.properties;
          this.selectedRowAddress = props?.label ?? null;
          this.isLoadingAddress = false;
        },
        error: () => { this.selectedRowAddress = null; this.isLoadingAddress = false; },
      });
    }

    if (row.kind === 'Offer') {
      this.disponibiliteOffreService.getByOffer(row.id).subscribe({
        next: (dispos) => { this.selectedOfferDispos = dispos; },
        error: () => { this.selectedOfferDispos = []; },
      });
    }
  }

  // ── Visionneuse photo plein écran (avec minimap de localisation) ────────────

  showImageLightbox = false;
  lightboxUrl = '';

  openImageFullsize(url: string): void {
    this.lightboxUrl = url;
    this.showImageLightbox = true;
  }

  closeImageLightbox(): void {
    this.showImageLightbox = false;
    this.lightboxUrl = '';
  }

  private readonly CRENEAUX: { creneau: string; label: string }[] = [
    { creneau: 'MATIN', label: 'Matin' },
    { creneau: 'MIDI', label: 'Midi' },
    { creneau: 'SOIR', label: 'Soir' },
    { creneau: 'NUIT', label: 'Nuit' },
  ];

  /** Calendrier des disponibilités : une ligne par jour déclaré, une colonne par créneau. */
  get dispoCalendrier(): { label: string; creneaux: { creneau: string; label: string; disponible: boolean }[] }[] {
    if (this.selectedOfferDispos.length === 0) return [];

    const dispoSet = new Set(this.selectedOfferDispos.map(d => `${d.date}_${d.creneau}`));
    const dates = [...new Set(this.selectedOfferDispos.map(d => d.date))].sort();
    const minDate = new Date(dates[0]);
    const maxDate = new Date(dates[dates.length - 1]);

    const jours: { label: string; creneaux: { creneau: string; label: string; disponible: boolean }[] }[] = [];
    for (let d = new Date(minDate); d <= maxDate; d.setDate(d.getDate() + 1)) {
      const dateStr = d.toISOString().slice(0, 10);
      jours.push({
        label: d.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' }),
        creneaux: this.CRENEAUX.map(c => ({
          ...c,
          disponible: dispoSet.has(`${dateStr}_${c.creneau}`),
        })),
      });
    }
    return jours;
  }

  /** Dossiers de la même crise que l'offre sélectionnée. */
  get dossiersForSelectedOffer(): Dossier[] {
    if (!this.selectedRow?.crisis) return [];
    return this.dossiers.filter(d => d.crise === this.selectedRow!.crisis);
  }

  submitAssignTeam(): void {
    if (!this.selectedRow || !this.assignTeamId) return;
    const team = this.teams.find(t => t.id === this.assignTeamId);
    if (!team) return;

    const offerIds = team.assigned_offer_ids.includes(this.selectedRow.id)
      ? team.assigned_offer_ids
      : [...team.assigned_offer_ids, this.selectedRow.id];

    // Affecter l'offre ajoute aussi son auteur à l'équipe.
    let memberIds = team.member_ids ?? [];
    const authorId = this.selectedRow.author;
    if (authorId && !memberIds.includes(authorId)) {
      memberIds = [...memberIds, authorId];
    }

    this.teamService.patch(team.id!, { assigned_offer_ids: offerIds, member_ids: memberIds }).subscribe({
      next: (updated) => {
        const idx = this.teams.findIndex(t => t.id === updated.id);
        if (idx !== -1) this.teams[idx] = updated;
        this.showSuccess(`Offre affectée à l'équipe ${teamDisplayName(team)}.`);
        this.assignTeamId = null;
      },
      error: () => this.showError("Impossible d'affecter cette offre à l'équipe."),
    });
  }

  /** Passe par l'action backend dédiée : dossier de suivi, notification du régulateur, email au
   * demandeur. */
  submitAssignTeamRequest(): void {
    if (!this.selectedRow || !this.assignTeamId) return;
    const team = this.teams.find(t => t.id === this.assignTeamId);
    if (!team) return;

    this.requestService.assignTeam(this.selectedRow.id, team.id!).subscribe({
      next: (res) => {
        if (res.already_assigned) {
          this.showSuccess('Cette demande était déjà affectée à cette équipe.');
        } else {
          this.showSuccess(`Demande affectée à l'équipe ${teamDisplayName(team)} — dossier ${res.numero} créé.`);
        }
        this.assignTeamId = null;
      },
      error: (err) => this.showError(err?.error?.error || "Impossible d'affecter cette demande à l'équipe."),
    });
  }

  submitAssignDossier(): void {
    if (!this.selectedRow || !this.assignDossierId) return;
    this.offerService.assignDossier(this.selectedRow.id, this.assignDossierId).subscribe({
      next: () => {
        this.showSuccess('Offre affectée au dossier.');
        this.assignDossierId = null;
      },
      error: (err) => this.showError(err?.error?.error || "Impossible d'affecter cette offre au dossier."),
    });
  }

  // ────────────────────────────────────────────────────────────────────────────
  // SÉLECTION MULTIPLE + ACTIONS GROUPÉES
  // ────────────────────────────────────────────────────────────────────────────

  isRowSelectable(row: ReportRow): boolean {
    return row.kind === 'Offer' || row.kind === 'Request' || row.kind === 'Information';
  }

  isRowSelected(row: ReportRow): boolean {
    if (row.kind === 'Offer') return this.selectedOfferIds.has(row.id);
    if (row.kind === 'Request') return this.selectedRequestIds.has(row.id);
    if (row.kind === 'Information') return this.selectedInformationIds.has(row.id);
    return false;
  }

  toggleRowSelection(row: ReportRow): void {
    if (row.kind === 'Offer') {
      if (this.selectedOfferIds.has(row.id)) { this.selectedOfferIds.delete(row.id); this.selectedOfferRowsMap.delete(row.id); }
      else { this.selectedOfferIds.add(row.id); this.selectedOfferRowsMap.set(row.id, row); }
    } else if (row.kind === 'Request') {
      if (this.selectedRequestIds.has(row.id)) { this.selectedRequestIds.delete(row.id); this.selectedRequestRowsMap.delete(row.id); }
      else { this.selectedRequestIds.add(row.id); this.selectedRequestRowsMap.set(row.id, row); }
    } else if (row.kind === 'Information') {
      if (this.selectedInformationIds.has(row.id)) { this.selectedInformationIds.delete(row.id); this.selectedInformationRowsMap.delete(row.id); }
      else { this.selectedInformationIds.add(row.id); this.selectedInformationRowsMap.set(row.id, row); }
    }
  }

  get pagedOfferIds(): string[] { return this.pagedRows.filter(r => r.kind === 'Offer').map(r => r.id); }
  get pagedRequestIds(): string[] { return this.pagedRows.filter(r => r.kind === 'Request').map(r => r.id); }
  get pagedInformationIds(): string[] { return this.pagedRows.filter(r => r.kind === 'Information').map(r => r.id); }

  get allPagedOffersSelected(): boolean {
    const ids = this.pagedOfferIds;
    return ids.length > 0 && ids.every(id => this.selectedOfferIds.has(id));
  }

  get allPagedRequestsSelected(): boolean {
    const ids = this.pagedRequestIds;
    return ids.length > 0 && ids.every(id => this.selectedRequestIds.has(id));
  }

  get allPagedInformationsSelected(): boolean {
    const ids = this.pagedInformationIds;
    return ids.length > 0 && ids.every(id => this.selectedInformationIds.has(id));
  }

  /** « Tout sélectionner » porte sur la page affichée uniquement. */
  toggleSelectAllOffers(): void {
    const all = this.allPagedOffersSelected;
    this.pagedRows.filter(r => r.kind === 'Offer').forEach(r => {
      if (all) { this.selectedOfferIds.delete(r.id); this.selectedOfferRowsMap.delete(r.id); }
      else { this.selectedOfferIds.add(r.id); this.selectedOfferRowsMap.set(r.id, r); }
    });
  }

  toggleSelectAllRequests(): void {
    const all = this.allPagedRequestsSelected;
    this.pagedRows.filter(r => r.kind === 'Request').forEach(r => {
      if (all) { this.selectedRequestIds.delete(r.id); this.selectedRequestRowsMap.delete(r.id); }
      else { this.selectedRequestIds.add(r.id); this.selectedRequestRowsMap.set(r.id, r); }
    });
  }

  toggleSelectAllInformations(): void {
    const all = this.allPagedInformationsSelected;
    this.pagedRows.filter(r => r.kind === 'Information').forEach(r => {
      if (all) { this.selectedInformationIds.delete(r.id); this.selectedInformationRowsMap.delete(r.id); }
      else { this.selectedInformationIds.add(r.id); this.selectedInformationRowsMap.set(r.id, r); }
    });
  }

  get selectedRequestRows(): ReportRow[] {
    return Array.from(this.selectedRequestRowsMap.values());
  }

  /** Une mission a une seule crise : toutes les demandes sélectionnées doivent la partager
   * (le backend le vérifie aussi). */
  get bulkRequestsShareCrisis(): boolean {
    const crises = new Set(this.selectedRequestRows.map(r => r.crisis));
    return crises.size === 1 && !crises.has(null);
  }

  get existingMissionsForSelection(): Mission[] {
    const rows = this.selectedRequestRows;
    if (rows.length === 0 || !this.bulkRequestsShareCrisis) return [];
    const crisisId = rows[0].crisis;
    return this.missions.filter(m => m.crise === crisisId);
  }

  // ── Barre groupée signalements divers : affecter à une équipe existante ─────

  openBulkInformationModal(): void {
    this.bulkInformationTeamId = null;
    this.bulkInformationTeamQuery = '';
    this.showBulkInformationModal = true;
  }

  get filteredBulkInformationTeams(): Team[] {
    const q = this.bulkInformationTeamQuery.trim().toLowerCase();
    if (!q) return [];
    return this.teams.filter(t => t.name.toLowerCase().includes(q));
  }

  selectBulkInformationTeam(t: Team): void {
    this.bulkInformationTeamId = t.id!;
    this.bulkInformationTeamQuery = t.name;
    this.showBulkInformationTeamResults = false;
  }

  onBulkInformationTeamQueryChange(): void {
    this.bulkInformationTeamId = null;
    this.showBulkInformationTeamResults = true;
  }

  hideBulkInformationTeamResultsDelayed(): void {
    setTimeout(() => this.showBulkInformationTeamResults = false, 150);
  }

  submitBulkInformationTeam(): void {
    if (!this.bulkInformationTeamId || this.selectedInformationIds.size === 0) return;
    this.informationService.bulkAssignTeam([...this.selectedInformationIds], this.bulkInformationTeamId).subscribe({
      next: (result) => {
        let message = `${result.dossiers_created.length} signalement(s) affecté(s) à l'équipe « ${teamDisplayName(result.team)} » (dossier créé pour chacun).`;
        if (result.already_assigned.length > 0) {
          message += ` ${result.already_assigned.length} déjà affecté(s) à cette équipe.`;
        }
        if (result.no_crisis.length > 0) {
          message += ` ${result.no_crisis.length} sans crise associée n'ont pas pu être affecté(s).`;
        }
        this.showSuccess(message);
        this.selectedInformationIds.clear();
        this.selectedInformationRowsMap.clear();
        this.showBulkInformationModal = false;
      },
      error: (err) => this.showError(err?.error?.error || "Impossible d'affecter ces signalements."),
    });
  }

  // ── Barre groupée offres : créer une équipe + assigner un régulateur ────────

  openBulkOfferModal(): void {
    // Pré-remplit le nom d'équipe avec l'organisation si toutes les offres viennent d'un même dépôt groupé.
    const selected = Array.from(this.selectedOfferRowsMap.values());
    const organisations = new Set(selected.map(r => r.organisationNom).filter(Boolean));
    this.bulkTeamName = organisations.size === 1 ? [...organisations][0]! : '';
    this.bulkRegulateurId = null;
    this.bulkRegulateurQuery = '';
    this.showBulkOfferModal = true;
  }

  get filteredBulkRegulateurs(): User[] {
    const q = this.bulkRegulateurQuery.trim().toLowerCase();
    if (!q) return [];
    return this.regulateurs.filter(u =>
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) || u.username.toLowerCase().includes(q)
    );
  }

  selectBulkRegulateur(u: User): void {
    this.bulkRegulateurId = u.id!;
    this.bulkRegulateurQuery = `${u.first_name} ${u.last_name}`.trim() || u.username;
    this.showBulkRegulateurResults = false;
  }

  onBulkRegulateurQueryChange(): void {
    this.bulkRegulateurId = null;
    this.showBulkRegulateurResults = true;
  }

  hideBulkRegulateurResultsDelayed(): void {
    setTimeout(() => this.showBulkRegulateurResults = false, 150);
  }

  submitBulkOfferTeam(): void {
    if (!this.bulkTeamName.trim() || this.selectedOfferIds.size === 0) return;
    this.offerService.bulkCreateTeam([...this.selectedOfferIds], this.bulkTeamName.trim(), this.bulkRegulateurId).subscribe({
      next: (team) => {
        this.teams.push(team);
        this.showSuccess(`Équipe « ${team.name} » créée avec ${this.selectedOfferIds.size} offre(s).`);
        this.selectedOfferIds.clear();
        this.selectedOfferRowsMap.clear();
        this.showBulkOfferModal = false;
      },
      error: (err) => this.showError(err?.error?.error || "Impossible de créer l'équipe."),
    });
  }

  // ── Barre groupée demandes : affecter à une mission + une équipe ────────────

  openBulkRequestModal(): void {
    this.bulkMissionMode = this.existingMissionsForSelection.length > 0 ? 'existing' : 'new';
    this.bulkMissionId = null;
    this.bulkNewMissionTitre = '';
    this.bulkTeamIdForRequests = null;
    this.bulkTeamQuery = '';
    this.showBulkRequestModal = true;
  }

  get filteredBulkTeams(): Team[] {
    const q = this.bulkTeamQuery.trim().toLowerCase();
    if (!q) return [];
    return this.teams.filter(t => t.name.toLowerCase().includes(q));
  }

  selectBulkTeam(t: Team): void {
    this.bulkTeamIdForRequests = t.id!;
    this.bulkTeamQuery = t.name;
    this.showBulkTeamResults = false;
  }

  onBulkTeamQueryChange(): void {
    this.bulkTeamIdForRequests = null;
    this.showBulkTeamResults = true;
  }

  hideBulkTeamResultsDelayed(): void {
    setTimeout(() => this.showBulkTeamResults = false, 150);
  }

  submitBulkRequestMission(): void {
    if (!this.bulkTeamIdForRequests || !this.bulkRequestsShareCrisis) return;
    const missionArg = this.bulkMissionMode === 'existing' && this.bulkMissionId
      ? { missionId: this.bulkMissionId }
      : { newMission: { titre: this.bulkNewMissionTitre.trim() || 'Mission sans titre' } };

    this.requestService.bulkAssignMission([...this.selectedRequestIds], this.bulkTeamIdForRequests, missionArg).subscribe({
      next: (res) => {
        const extra = res.already_assigned.length ? `, ${res.already_assigned.length} déjà affectée(s)` : '';
        this.showSuccess(`${res.dossiers_created.length} dossier(s) créé(s)${extra}.`);
        this.selectedRequestIds.clear();
        this.selectedRequestRowsMap.clear();
        this.showBulkRequestModal = false;
        this.load();
      },
      error: (err) => this.showError(err?.error?.error || "Impossible d'affecter ces demandes."),
    });
  }

  openStatusEdit(row: ReportRow, event: Event): void {
    event.stopPropagation();
    this.selectedRow    = row;
    this.newStatus      = row.status;
    this.showStatusModal = true;
  }

  submitStatus(): void {
    if (!this.selectedRow || !this.newStatus) return;
    this.isSaving = true;
    const id  = this.selectedRow.id;
    const obs = this.getUpdateObservable(this.selectedRow.kind, id, { status: this.newStatus } as any);
    if (!obs) { this.isSaving = false; return; }
    obs.subscribe({
      next: () => {
        this.showSuccess('Statut mis à jour.');
        this.showStatusModal = false;
        this.isSaving        = false;
        this.reload();
      },
      error: () => { this.showError('Erreur lors de la mise à jour.'); this.isSaving = false; },
    });
  }

  openDelete(row: ReportRow, event: Event): void {
    event.stopPropagation();
    this.selectedRow    = row;
    this.showDeleteModal = true;
  }

  confirmDelete(): void {
    if (!this.selectedRow) return;
    const isCrisis = this.selectedRow.kind === 'Crisis';
    const obs = this.getDeleteObservable(this.selectedRow.kind, this.selectedRow.id);
    if (!obs) return;
    obs.subscribe({
      next: () => {
        this.showSuccess(isCrisis ? 'Supprimé.' : 'Désactivé.');
        this.showDeleteModal = false;
        this.selectedRow     = null;
        this.reload();
      },
      error: () => this.showError(isCrisis ? 'Erreur lors de la suppression.' : 'Erreur lors de la désactivation.'),
    });
  }

  reactiver(row: ReportRow, event: Event): void {
    event.stopPropagation();
    const obs = this.getReactiverObservable(row.kind, row.id);
    if (!obs) return;
    obs.subscribe({
      next: () => { this.showSuccess('Réactivé.'); this.reload(); },
      error: () => this.showError('Erreur lors de la réactivation.'),
    });
  }

  private getReactiverObservable(kind: ReportKind, id: string): Observable<any> | undefined {
    switch (kind) {
      case 'Offer':       return this.offerService.reactiver(id);
      case 'Request':     return this.requestService.reactiver(id);
      case 'Information': return this.informationService.reactiver(id);
      default:            return undefined;
    }
  }

  private getUpdateObservable(kind: ReportKind, id: string, data: any): Observable<any> {
    switch (kind) {
      case 'Crisis':       return this.crisisService.update(id, data);
      case 'Offer':       return this.offerService.update(id, data);
      case 'Request':     return this.requestService.update(id, data);
      case 'Information': return this.informationService.update(id, data);
    }
  }

  private getDeleteObservable(kind: ReportKind, id: string): Observable<any> {
    switch (kind) {
      case 'Crisis':       return this.crisisService.delete(id);
      case 'Offer':       return this.offerService.delete(id);
      case 'Request':     return this.requestService.delete(id);
      case 'Information': return this.informationService.delete(id);
    }
  }

  // ────────────────────────────────────────────────────────────────────────────
  // EXPORT CSV (page affichée uniquement ; un export serveur complet reste à faire)
  // ────────────────────────────────────────────────────────────────────────────

  exportCSV(): void {
    const rows = this.pagedRows;
    const headers = ['ID','Type','Titre','Contact','Email','Téléphone','Statut','Date','Date expiration','Latitude','Longitude','Crise','Auteur'];
    const lines = rows.map(r => [
      r.id, r.kind, r.title, r.contact, r.email,
      r.telephone ?? '', r.status,
      this.fmtDate(r.date), r.dateExp ? this.fmtDate(r.dateExp) : '',
      r.latitude ?? '', r.longitude ?? '',
      r.crisis ?? '', r.author ?? '',
    ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));

    const csv = [headers.join(','), ...lines].join('\n');
    const a   = document.createElement('a');
    a.href    = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' }));
    a.download= `signalements_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  exportRow(row: ReportRow, event: Event): void {
    event.stopPropagation();
    const headers = ['ID','Type','Titre','Contact','Email','Téléphone','Statut','Date','Latitude','Longitude'];
    const values  = [row.id, row.kind, row.title, row.contact, row.email,
                     row.telephone ?? '', row.status, this.fmtDate(row.date),
                     row.latitude ?? '', row.longitude ?? ''];
    const csv = [headers.join(','), values.map(v => `"${v}"`).join(',')].join('\n');
    const a   = document.createElement('a');
    a.href    = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' }));
    a.download= `${row.kind}_${row.id.slice(0,8)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ────────────────────────────────────────────────────────────────────────────
  // HELPERS (template)
  // ────────────────────────────────────────────────────────────────────────────

  closeAll(): void {
    this.showDetailModal = this.showDeleteModal = this.showStatusModal = false;
    this.selectedRow = null;
    this.selectedRowAddress = null;
    this.isLoadingAddress = false;
    this.selectedOfferDispos = [];
    this.assignTeamId = null;
    this.assignDossierId = null;
    this.newStatus   = '';
    this.closeImageLightbox();
  }

  kindIcon(kind: ReportKind): string {
    return ({ Crisis: 'local_fire_department', Offer: 'volunteer_activism',
              Request: 'emergency', Information: 'info' })[kind];
  }

  kindClass(kind: ReportKind): string {
    return ({ Crisis: 'kind-crisis', Offer: 'kind-offer',
              Request: 'kind-request', Information: 'kind-info' })[kind];
  }

  kindLabel(kind: ReportKind): string {
    return ({ Crisis: 'Crise', Offer: 'Offre',
              Request: 'Demande', Information: 'Information' })[kind];
  }

  // ────────────────────────────────────────────────────────────────────────────
  // TRANSFORMATION (soumission déposée dans le mauvais formulaire)
  // ────────────────────────────────────────────────────────────────────────────

  isTransforming = false;

  /** Cibles possibles : jamais le type actuel, jamais Crisis. */
  get transformCibles(): { value: 'REQUEST' | 'OFFER' | 'INFORMATION'; label: string }[] {
    if (!this.selectedRow) return [];
    const all: { value: 'REQUEST' | 'OFFER' | 'INFORMATION'; label: string }[] = [
      { value: 'REQUEST', label: 'Demande' },
      { value: 'OFFER', label: 'Offre' },
      { value: 'INFORMATION', label: 'Signalement' },
    ];
    return all.filter(c => c.value !== this.selectedRow!.kind.toUpperCase());
  }

  transformerSoumission(cibleValue: string): void {
    if (!this.selectedRow || !cibleValue) return;
    const cible = cibleValue as 'REQUEST' | 'OFFER' | 'INFORMATION';
    const kind = this.selectedRow.kind;
    const label = this.kindLabel(kind).toLowerCase();
    const cibleLabel = ({ REQUEST: 'demande', OFFER: 'offre', INFORMATION: 'signalement' } as const)[cible];

    if (!confirm(`Transformer cette ${label} en ${cibleLabel} ? La ${label} d'origine sera supprimée.`)) {
      return;
    }

    const id = this.selectedRow.id;
    this.isTransforming = true;

    const obs = kind === 'Request' ? this.requestService.transformer(id, cible as 'OFFER' | 'INFORMATION')
      : kind === 'Offer' ? this.offerService.transformer(id, cible as 'REQUEST' | 'INFORMATION')
      : this.informationService.transformer(id, cible as 'REQUEST' | 'OFFER');

    obs.subscribe({
      next: () => {
        this.isTransforming = false;
        this.showSuccess(`Transformé(e) en ${cibleLabel} avec succès.`);
        this.closeAll();
        this.load();
      },
      error: (err) => {
        this.isTransforming = false;
        alert(err.error?.error || 'Impossible de transformer cet élément.');
      },
    });
  }

  statusClass(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'stat-urgent',
      [Status.IN_PROGRESS]:     'stat-encours',
      [Status.PROCESSED]:      'stat-traitee',
      [Status.AVAILABLE]:   'stat-dispo',
      [Status.UNAVAILABLE]: 'stat-indispo',
    })[s] ?? '';
  }

  statusLabel(s: Status): string {
    return ({
      [Status.UNPROCESSED]:  'Non traitée',
      [Status.IN_PROGRESS]:     'En cours',
      [Status.PROCESSED]:      'Traitée',
      [Status.AVAILABLE]:   'Disponible',
      [Status.UNAVAILABLE]: 'Indisponible',
    })[s] ?? s;
  }

  sortIcon(f: SortField): string {
    if (this.sortField !== f) return 'unfold_more';
    return this.sortAsc ? 'expand_less' : 'expand_more';
  }

  minOf(a: number, b: number): number { return Math.min(a, b); }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day:'2-digit', month:'2-digit', year:'numeric' });
  }

  get pageNumbers(): number[] {
    const pages: number[] = [];
    const start = Math.max(1, this.currentPage - 2);
    const end   = Math.min(this.totalPages, this.currentPage + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }

  isCrisis(r: ReportRow['_raw']): r is Crisis         { return 'name'              in r; }
  isOffer(r: ReportRow['_raw']): r is Offer          { return 'first_name_offer'     in r; }
  isDemande(r: ReportRow['_raw']): r is Request      { return 'first_name_request'   in r; }
  isInfo(r: ReportRow['_raw']): r is Information     { return 'first_name_information' in r; }

  private showSuccess(msg: string): void {
    this.successMessage = msg;
    setTimeout(() => (this.successMessage = ''), 3500);
  }
  private showError(msg: string): void {
    this.errorMessage = msg;
    setTimeout(() => (this.errorMessage = ''), 5000);
  }
}
