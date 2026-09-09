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
import { Team } from '../../shared/models/team.model';
import { PointOperationnel } from '../../shared/models/point-operationnel.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Mission } from '../../shared/models/mission.model';
import { User, UserRole } from '../../shared/models/user.model';

import { Crisis }       from '../../shared/models/crisis.model';
import { Offer }       from '../../shared/models/offer.model';
import { Request }     from '../../shared/models/request.model';
import { Information } from '../../shared/models/information.model';
import { Status }      from '../../shared/models/status.model';

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
  // Offres uniquement — voir propose-help-form pour ce que ces champs signifient.
  materielLivraison?: string | null;
  diplomeSecourisme?: boolean;
  ancienSapeurPompier?: boolean;
  confirmationReglementaire?: boolean;
  presencePhysique?: boolean | null;
  organisationNom?: string | null;   // dépôt groupé : nom de l'entreprise/association déposante
  groupeId?: string | null;
  // Offer/Request/Information uniquement (voir la politique de désactivation) — toujours true
  // pour Crisis, qui n'a pas ce champ et se supprime réellement.
  actif:        boolean;
  // raw originals for detail modal
  _raw:         Crisis | Offer | Request | Information;
}

// ─────────────────────────────────────────────────────────────────────────────

type FilterKind   = ReportKind | 'ALL';
type FilterStatus = Status     | 'ALL';
type SortField    = 'title' | 'kind' | 'status' | 'date' | 'contact' | 'commune' | 'distanceFromCrisisKm';
type EchelleFilter = 'zone' | 'rayon' | 'departement' | 'region' | 'national';

@Component({
  selector: 'app-reporting',
  standalone: true,
  imports: [CommonModule, FormsModule, MinimapComponent],
  templateUrl: './reporting.component.html',
  styleUrls: ['./reporting.component.scss'],
})
export class ReportingComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  // ── Raw data ───────────────────────────────────────────────
  rawCrises:       Crisis[]       = [];
  rawOffers:       Offer[]       = [];
  rawRequests:     Request[]     = [];
  rawInformations: Information[] = [];
  teams:           Team[]        = [];
  dossiers:        Dossier[]     = [];
  missions:        Mission[]     = [];
  regulateurs:     User[]        = [];

  // ── Détail offre : disponibilités + affectation ─────────────
  selectedOfferDispos: DisponibiliteOffre[] = [];
  assignTeamId:    string | null = null;
  assignDossierId: string | null = null;

  // ── Processed rows ─────────────────────────────────────────
  allRows:      ReportRow[] = [];
  filteredRows: ReportRow[] = [];
  pagedRows:    ReportRow[] = [];

  // ── UI state ───────────────────────────────────────────────
  isLoading      = true;
  isSaving       = false;
  errorMessage   = '';
  successMessage = '';

  // ── Filters / sort ─────────────────────────────────────────
  searchQuery   = '';
  filterKind:   FilterKind   = 'ALL';
  filterStatus: FilterStatus = 'ALL';
  filterCommune   = '';
  filterCompetence = 'ALL';
  filterMaterielLivraison: 'ALL' | 'A_RECUPERER' | 'LIVRAISON_POSSIBLE' = 'ALL';
  sortField:    SortField    = 'date';
  sortAsc                    = false;
  // Offres/demandes/signalements désactivés (voir la politique de désactivation) sont masqués
  // par défaut par le backend — ce bouton demande explicitement ?actif=all pour les retrouver
  // et pouvoir les réactiver.
  showDesactives = false;

  // ── Échelle géographique (par défaut : ma zone) ─────────────
  // 'zone' = niveau naturel de l'institution (backend: ?scope=zone, sans ?echelle) ; 'rayon' =
  // ?scope=zone&rayon_km=, n'affecte que les offres/bénévoles côté backend (_apply_rayon_km,
  // OfferViewSet uniquement) ; les autres valeurs élargissent via ?echelle= (toutes listes).
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

  // ── Pagination ─────────────────────────────────────────────
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

  // ── Sélection multiple + actions groupées ───────────────────
  selectedOfferIds   = new Set<string>();
  selectedRequestIds = new Set<string>();
  selectedInformationIds = new Set<string>();

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

  // ── Photos (blob-fetch access-contrôlé, plus d'URL brute côté API) ──────────
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

  /** Présent quand on arrive depuis "Ouvrir le tableau des offres" du détail d'une équipe
   * (voir TeamsComponent) : remplace la barre d'action groupée habituelle par un bouton
   * "Ajouter à l'équipe" par offre. */
  pickForTeamId: string | null = null;
  /** Idem, depuis "Ouvrir le tableau des offres" du détail d'un point (centre) — voir
   * PointModalComponent : remplace la barre par un bouton "Ajouter au stock" par offre de
   * matériel. Mutuellement exclusif avec pickForTeamId (un seul mode sélection à la fois). */
  pickForPointId: string | null = null;
  points: PointOperationnel[] = [];

  /** Vrai dès qu'on arrive en mode picker (équipe ou point) — dans ce mode, la sélection
   * groupée habituelle (case à cocher + barre "Créer une équipe...") n'a pas de sens : on est
   * déjà dans une équipe/un point précis, pas en train d'en créer un nouveau à partir d'une
   * sélection. Voir col-actions, qui garde lui Voir/Télécharger/Supprimer visibles en plus du
   * bouton d'ajout, contrairement à cette sélection groupée qui disparaît entièrement. */
  get pickerModeActive(): boolean {
    return !!(this.pickForTeamId || this.pickForPointId);
  }

  ngOnInit():    void {
    this.pickForTeamId = this.route.snapshot.queryParamMap.get('pickForTeam');
    this.pickForPointId = this.route.snapshot.queryParamMap.get('pickForPoint');
    this.loadAll();
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
  }

  get pickForTeam(): Team | undefined {
    return this.teams.find(t => t.id === this.pickForTeamId);
  }

  get pickForPoint(): PointOperationnel | undefined {
    return this.points.find(p => p.id === this.pickForPointId);
  }

  /** Ajoute l'offre comme ressource de l'équipe visée, rattachée à sa mission active (voir
   * TeamViewSet.assigner_ressource). Reste sur le tableau pour permettre d'en ajouter
   * plusieurs d'affilée — "Retour à l'équipe" (bouton dédié) referme le mode sélection. */
  ajouterCommeRessource(offerId: string, e?: Event): void {
    e?.stopPropagation();
    if (!this.pickForTeamId) return;
    this.teamService.assignerRessource(this.pickForTeamId, offerId).subscribe({
      next: () => this.showSuccess('Ressource ajoutée à l\'équipe.'),
      error: (err) => this.showError(err?.error?.error || "Impossible d'ajouter cette ressource."),
    });
  }

  /** Ajoute l'offre de matériel au stock du point visé (crée un apport individuel — voir
   * OfferViewSet.affecter_stock). */
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
  // LOAD
  // ────────────────────────────────────────────────────────────────────────────

  /** Params d'échelle géographique communs à Crise/Offre/Demande/Signalement : ?scope=zone
   * (opt-in, voir _widen_zone_for_reporting côté backend) + éventuel ?echelle= élargi. Le
   * rayon en km n'affecte que les offres (?rayon_km=, voir _apply_rayon_km côté backend) —
   * les autres types restent à "ma zone" quand ce choix est sélectionné. */
  private buildEchelleParams(forOffer = false): Record<string, string> {
    const params: Record<string, string> = { scope: 'zone' };
    if (this.echelle === 'rayon') {
      if (forOffer) params['rayon_km'] = String(this.rayonKm);
    } else if (this.echelle !== 'zone') {
      params['echelle'] = this.echelle;
    }
    return params;
  }

  loadAll(): void {
    this.isLoading = true;
    this.selectedOfferIds.clear();
    this.selectedRequestIds.clear();
    this.selectedInformationIds.clear();
    const actifParams = this.showDesactives ? { actif: 'all' } : undefined;
    const zoneParams = this.buildEchelleParams();
    // exclude_type=Bénévolat : l'annuaire permanent de bénévoles (potentiellement des
    // milliers de fiches, sans crise rattachée) ne relève pas de ce tableau de triage —
    // consultable via OfferService.vueSecteur à la place.
    const offreParams = { ...(actifParams ?? {}), exclude_type: 'Bénévolat', ...this.buildEchelleParams(true) };
    // En mode "ajouter une ressource à une équipe" (pickForTeamId), l'annuaire de bénévoles
    // (normalement exclu de ce tableau, voir exclude_type ci-dessus) redevient nécessaire :
    // c'est le seul moyen actuel de rattacher un bénévole à une équipe. Scopé au secteur de
    // l'institution (vue_secteur), jamais chargé pour la vue de triage normale. catchError :
    // pas d'institution/secteur résolu ne doit pas casser le reste du chargement.
    const benevoles$ = this.pickForTeamId
      ? this.offerService.vueSecteur().pipe(catchError(() => of([])))
      : of([]);
    forkJoin({
      crises:       this.crisisService.getAll(zoneParams),
      offres:       this.offerService.getAll(offreParams),
      benevoles:    benevoles$,
      demandes:     this.requestService.getAll({ ...(actifParams ?? {}), ...zoneParams }),
      informations: this.informationService.getAll({ ...(actifParams ?? {}), ...zoneParams }),
      teams:        this.teamService.getAll(),
      dossiers:     this.dossierService.getAll(),
      missions:     this.missionService.getAll(),
      users:        this.userService.getAll(),
    })
    .pipe(takeUntil(this.destroy$))
    .subscribe({
      next: ({ crises, offres, benevoles, demandes, informations, teams, dossiers, missions, users }) => {
        this.teams    = teams;
        this.dossiers = dossiers;
        this.missions = missions;
        this.regulateurs = users.filter(u => u.type === UserRole.REGULATEUR);
        this.rawCrises       = crises;
        this.rawOffers       = [...offres, ...benevoles];
        this.rawRequests     = demandes;
        this.rawInformations = informations;
        this.buildRows();
        this.isLoading = false;
      },
      error: () => {
        this.showError('Impossible de charger les signalements.');
        this.isLoading = false;
      },
    });
  }

  // ────────────────────────────────────────────────────────────────────────────
  // BUILD UNIFIED ROWS
  // ────────────────────────────────────────────────────────────────────────────

  private buildRows(): void {
    const crisisRows: ReportRow[] = this.rawCrises.map(c => ({
      id:        c.id,
      kind:      'Crisis',
      title:     c.name,
      contact:   '—',
      email:     '—',
      telephone: null,
      status:    (c.status ?? Status.UNPROCESSED) as Status,
      date:      c.start_date,
      dateExp:   c.end_date,
      crisis:     c.id,
      crisis_nom: null,
      author:    c.author,
      author_nom: null,
      latitude:  c.latitude ?? null,
      longitude: c.longitude ?? null,
      has_photo: !!c.has_photo,
      commune:   null,
      distanceFromCrisisKm: null,
      authorType: null,
      isSecoursAccount: false,
      competencesLibelles: [],
      description: c.description ?? null,
      actif:     true,
      _raw:      c,
    }));

    const offerRows: ReportRow[] = this.rawOffers.map(o => ({
      id:        o.id,
      kind:      'Offer',
      title:     o.title,
      contact:   `${o.first_name_offer} ${o.last_name_offer}`,
      email:     o.email_offer,
      telephone: o.phone_offer ?? o.author_phone ?? null,
      status:    o.status,
      date:      o.created_at,
      dateExp:   o.expires_at,
      crisis:     o.crisis,
      crisis_nom: o.crisis_nom ?? null,
      author:    o.author,
      author_nom: o.author_nom ?? null,
      latitude:  o.latitude ?? null,
      longitude: o.longitude ?? null,
      has_photo: !!o.has_photo,
      commune:   o.commune ?? null,
      distanceFromCrisisKm: o.distance_from_crisis_km ?? null,
      authorType: o.author_type ?? null,
      isSecoursAccount: o.author_type === 'SECOURS',
      competencesLibelles: o.competences_libelles ?? [],
      description: o.description ?? null,
      materielLivraison: o.materiel_livraison ?? null,
      diplomeSecourisme: !!o.diplome_secourisme,
      ancienSapeurPompier: !!o.ancien_sapeur_pompier,
      confirmationReglementaire: !!o.confirmation_reglementaire,
      presencePhysique: o.presence_physique ?? null,
      organisationNom: o.organisation_nom ?? null,
      groupeId: o.groupe_id ?? null,
      actif:     o.actif !== false,
      _raw:      o,
    }));

    const requestRows: ReportRow[] = this.rawRequests.map(d => ({
      id:        d.id,
      kind:      'Request',
      title:     d.title,
      contact:   `${d.first_name_request} ${d.last_name_request}`,
      email:     d.email_request,
      telephone: d.phone_request,
      status:    d.status,
      date:      d.created_at,
      dateExp:   d.expires_at,
      crisis:     d.crisis,
      crisis_nom: d.crisis_nom ?? null,
      author:    d.author,
      author_nom: d.author_nom ?? null,
      latitude:  d.latitude ?? null,
      longitude: d.longitude ?? null,
      has_photo: !!d.has_photo,
      commune:   d.commune ?? null,
      distanceFromCrisisKm: d.distance_from_crisis_km ?? null,
      authorType: d.author_type ?? null,
      isSecoursAccount: d.author_type === 'SECOURS',
      competencesLibelles: [],
      description: d.description ?? null,
      actif:     d.actif !== false,
      _raw:      d,
    }));

    const infoRows: ReportRow[] = this.rawInformations.map(i => ({
      id:        i.id,
      kind:      'Information',
      title:     i.title,
      contact:   `${i.first_name_information} ${i.last_name_information}`,
      email:     i.email_information,
      telephone: i.phone_information,
      status:    i.status,
      date:      i.created_at,
      dateExp:   i.expires_at,
      crisis:     i.crisis,
      crisis_nom: i.crisis_nom ?? null,
      author:    i.author,
      author_nom: i.author_nom ?? null,
      latitude:  i.latitude ?? null,
      longitude: i.longitude ?? null,
      has_photo: !!i.has_photo,
      commune:   i.commune ?? null,
      distanceFromCrisisKm: i.distance_from_crisis_km ?? null,
      authorType: i.author_type ?? null,
      isSecoursAccount: i.author_type === 'SECOURS',
      competencesLibelles: [],
      description: null,
      actif:     i.actif !== false,
      _raw:      i,
    }));

    this.allRows = [...crisisRows, ...offerRows, ...requestRows, ...infoRows];
    this.applyFilters();

    this.allRows.filter(r => r.has_photo).forEach(r => this.loadRowPhoto(r));

    const targetId = this.route.snapshot.queryParamMap.get('id');
    const target = targetId ? this.allRows.find(r => r.id === targetId) : null;
    if (target) this.openDetail(target);
  }

  /** Récupère la photo d'une ligne via l'action /preview/ access-contrôlée du bon
   * service selon `kind` — 403 silencieux si l'utilisateur n'est pas auteur/acteur
   * (pas d'erreur affichée, la vignette reste simplement absente). */
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
  // FILTER / SORT / PAGINATE
  // ────────────────────────────────────────────────────────────────────────────

  applyFilters(): void {
    let list = [...this.allRows];

    // Kind filter
    if (this.filterKind !== 'ALL') {
      list = list.filter(r => r.kind === this.filterKind);
    }

    // Statut filter
    if (this.filterStatus !== 'ALL') {
      list = list.filter(r => r.status === this.filterStatus);
    }

    // Commune filter (sous-chaîne, insensible à la casse — les noms de commune ne sont pas
    // normalisés côté source, ex: "Saint-Étienne" vs "saint etienne")
    const communeQuery = this.filterCommune.trim().toLowerCase();
    if (communeQuery) {
      list = list.filter(r => r.commune?.toLowerCase().includes(communeQuery));
    }

    // Compétence filter — ne concerne que les offres (seules à porter des compétences
    // déclarées) : une demande/un signalement/une crise est exclu dès que ce filtre est actif.
    if (this.filterCompetence !== 'ALL') {
      list = list.filter(r => r.competencesLibelles.includes(this.filterCompetence));
    }

    // Matériel en centre de regroupement des moyens (vs à récupérer sur place) — ne concerne
    // que les offres de type Matériel.
    if (this.filterMaterielLivraison !== 'ALL') {
      list = list.filter(r => r.materielLivraison === this.filterMaterielLivraison);
    }

    // Search
    const q = this.searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(r =>
        r.title?.toLowerCase().includes(q)     ||
        r.contact?.toLowerCase().includes(q)   ||
        r.email?.toLowerCase().includes(q)     ||
        r.telephone?.toLowerCase().includes(q) ||
        r.kind?.toLowerCase().includes(q)
      );
    }

    // Sort
    list.sort((a, b) => {
      let va: any = a[this.sortField] ?? '';
      let vb: any = b[this.sortField] ?? '';
      if (typeof va === 'string') va = va.toLowerCase();
      if (typeof vb === 'string') vb = vb.toLowerCase();
      if (va < vb) return this.sortAsc ? -1 :  1;
      if (va > vb) return this.sortAsc ?  1 : -1;
      return 0;
    });

    this.filteredRows = list;
    this.totalPages   = Math.max(1, Math.ceil(list.length / this.pageSize));
    this.currentPage  = Math.min(this.currentPage, this.totalPages);
    this.paginate();
  }

  private paginate(): void {
    const start   = (this.currentPage - 1) * this.pageSize;
    this.pagedRows = this.filteredRows.slice(start, start + this.pageSize);
  }

  setSort(field: SortField): void {
    if (this.sortField === field) this.sortAsc = !this.sortAsc;
    else { this.sortField = field; this.sortAsc = true; }
    this.applyFilters();
  }

  changePage(p: number): void {
    if (p < 1 || p > this.totalPages) return;
    this.currentPage = p;
    this.paginate();
  }

  resetFilters(): void {
    this.searchQuery   = '';
    this.filterKind    = 'ALL';
    this.filterStatus  = 'ALL';
    this.filterCommune = '';
    this.filterCompetence = 'ALL';
    this.filterMaterielLivraison = 'ALL';
    this.currentPage   = 1;
    this.applyFilters();
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

    // Ces coordonnées ne sont jamais renvoyées par l'API à un consommateur non institutionnel
    // (voir _location_visible côté serializers) : quiconque atteint ce code les voit déjà de
    // plein droit — autant afficher l'adresse la plus précise possible (les services ont
    // besoin de s'y rendre), pas juste la commune.
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

  /** Calendrier des disponibilités : une ligne par jour (couvrant la plage réellement déclarée),
   * une colonne par créneau, chaque case indiquant si le bénévole est disponible. */
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

  /** Dossiers de la même crise que l'offre sélectionnée (une affectation hors-crise n'a pas de sens). */
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

    // Affecter l'offre à l'équipe y ajoute aussi la personne qui la propose, sinon on affecte
    // une "mission" sans jamais rattacher le bénévole lui-même à l'équipe.
    let memberIds = team.member_ids ?? [];
    const authorId = this.selectedRow.author;
    if (authorId && !memberIds.includes(authorId)) {
      memberIds = [...memberIds, authorId];
    }

    this.teamService.patch(team.id!, { assigned_offer_ids: offerIds, member_ids: memberIds }).subscribe({
      next: (updated) => {
        const idx = this.teams.findIndex(t => t.id === updated.id);
        if (idx !== -1) this.teams[idx] = updated;
        this.showSuccess(`Offre affectée à l'équipe ${team.name}.`);
        this.assignTeamId = null;
      },
      error: () => this.showError("Impossible d'affecter cette offre à l'équipe."),
    });
  }

  /** Affectation d'une demande à une équipe : passe par l'action backend dédiée qui crée le
   * dossier de suivi, notifie le régulateur de l'équipe et informe le demandeur par email —
   * contrairement aux offres, pas un simple ajout à assigned_request_ids côté client. */
  submitAssignTeamRequest(): void {
    if (!this.selectedRow || !this.assignTeamId) return;
    const team = this.teams.find(t => t.id === this.assignTeamId);
    if (!team) return;

    this.requestService.assignTeam(this.selectedRow.id, team.id!).subscribe({
      next: (res) => {
        if (res.already_assigned) {
          this.showSuccess('Cette demande était déjà affectée à cette équipe.');
        } else {
          this.showSuccess(`Demande affectée à l'équipe ${team.name} — dossier ${res.numero} créé.`);
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
      this.selectedOfferIds.has(row.id) ? this.selectedOfferIds.delete(row.id) : this.selectedOfferIds.add(row.id);
    } else if (row.kind === 'Request') {
      this.selectedRequestIds.has(row.id) ? this.selectedRequestIds.delete(row.id) : this.selectedRequestIds.add(row.id);
    } else if (row.kind === 'Information') {
      this.selectedInformationIds.has(row.id) ? this.selectedInformationIds.delete(row.id) : this.selectedInformationIds.add(row.id);
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

  toggleSelectAllOffers(): void {
    const ids = this.pagedOfferIds;
    if (this.allPagedOffersSelected) ids.forEach(id => this.selectedOfferIds.delete(id));
    else ids.forEach(id => this.selectedOfferIds.add(id));
  }

  toggleSelectAllRequests(): void {
    const ids = this.pagedRequestIds;
    if (this.allPagedRequestsSelected) ids.forEach(id => this.selectedRequestIds.delete(id));
    else ids.forEach(id => this.selectedRequestIds.add(id));
  }

  toggleSelectAllInformations(): void {
    const ids = this.pagedInformationIds;
    if (this.allPagedInformationsSelected) ids.forEach(id => this.selectedInformationIds.delete(id));
    else ids.forEach(id => this.selectedInformationIds.add(id));
  }

  get selectedRequestRows(): ReportRow[] {
    return this.allRows.filter(r => this.selectedRequestIds.has(r.id));
  }

  /** Une mission est rattachée à une seule crise : la création de mission depuis la sélection
   * n'a de sens que si toutes les demandes sélectionnées partagent la même crise (garde-fou
   * client, le backend refuse aussi explicitement le cas contraire). */
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
        let message = `${result.dossiers_created.length} signalement(s) affecté(s) à l'équipe « ${result.team.name} » (dossier créé pour chacun).`;
        if (result.already_assigned.length > 0) {
          message += ` ${result.already_assigned.length} déjà affecté(s) à cette équipe.`;
        }
        if (result.no_crisis.length > 0) {
          message += ` ${result.no_crisis.length} sans crise associée n'ont pas pu être affecté(s).`;
        }
        this.showSuccess(message);
        this.selectedInformationIds.clear();
        this.showBulkInformationModal = false;
      },
      error: (err) => this.showError(err?.error?.error || "Impossible d'affecter ces signalements."),
    });
  }

  // ── Barre groupée offres : créer une équipe + assigner un régulateur ────────

  openBulkOfferModal(): void {
    // Pré-remplit le nom d'équipe avec l'organisation quand toutes les offres sélectionnées
    // viennent d'un même dépôt groupé — reste modifiable, juste un gain de temps.
    const selected = this.allRows.filter(r => this.selectedOfferIds.has(r.id));
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
        this.showBulkRequestModal = false;
        this.loadAll();
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
        this.loadAll();
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
        this.loadAll();
      },
      error: () => this.showError(isCrisis ? 'Erreur lors de la suppression.' : 'Erreur lors de la désactivation.'),
    });
  }

  reactiver(row: ReportRow, event: Event): void {
    event.stopPropagation();
    const obs = this.getReactiverObservable(row.kind, row.id);
    if (!obs) return;
    obs.subscribe({
      next: () => { this.showSuccess('Réactivé.'); this.loadAll(); },
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
  // EXPORT CSV
  // ────────────────────────────────────────────────────────────────────────────

  exportCSV(): void {
    const rows = this.filteredRows;
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
    a.href    = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' }));
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
    a.href    = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' }));
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
  // TRANSFORMATION (une soumission classée dans le mauvais formulaire, ex: une
  // offre de matériel déposée comme demande d'aide)
  // ────────────────────────────────────────────────────────────────────────────

  isTransforming = false;

  /** Cibles de transformation possibles pour le type de la ligne sélectionnée — jamais vers
   * son propre type, jamais depuis/vers Crisis (pas concerné par cette confusion de formulaire). */
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
        this.loadAll();
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

  get countByKind(): Record<string, number> {
    return {
      ALL:         this.allRows.length,
      Crisis:       this.rawCrises.length,
      Offer:       this.rawOffers.length,
      Request:     this.rawRequests.length,
      Information: this.rawInformations.length,
    };
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