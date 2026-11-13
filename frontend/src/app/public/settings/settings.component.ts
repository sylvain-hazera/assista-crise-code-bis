import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule, FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { User } from '../../shared/models/user.model';
import { AuthService } from '../../auth/services/auth.service';
import { RequestService } from '../../services/request.service';
import { OfferService } from '../../services/offer.service';
import { CrisisService } from '../../services/crisis.service';
import { InformationService } from '../../services/information.service';
import { DeclarationSecuriteService } from '../../services/declaration-securite.service';
import { DossierService } from '../../services/dossier.service';
import { UserService } from '../../services/user.service';
import { Request } from '../../shared/models/request.model';
import { Offer } from '../../shared/models/offer.model';
import { Crisis } from '../../shared/models/crisis.model';
import { Information } from '../../shared/models/information.model';
import { DeclarationSecurite } from '../../shared/models/declaration-securite.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Status } from '../../shared/models/status.model';
import { NoeudMeshUtilisateurService } from '../../services/noeud-mesh-utilisateur.service';
import { NoeudUtilisateurMeshtasticService } from '../../services/noeud-utilisateur-meshtastic.service';
import { CompagnonMeshtasticService } from '../../services/compagnon-meshtastic.service';
import { NoeudMeshUtilisateur } from '../../shared/models/noeud-mesh-utilisateur.model';
import { NoeudUtilisateurMeshtastic, ReclamerMeshtasticBrokerRequis } from '../../shared/models/noeud-utilisateur-meshtastic.model';
import { CandidatNoeudMeshCore, CandidatNoeudMeshtastic } from '../../shared/models/candidat-noeud-radio.model';
import { SuiviPositionPermanentService } from '../../services/suivi-position-permanent.service';
import { PieceIdentiteReserveService } from '../../services/piece-identite-reserve.service';
import { PieceIdentiteReserve } from '../../shared/models/piece-identite-reserve.model';

import { TeamService } from '../../services/team.service';
import { Team } from '../../shared/models/team.model';

import { TelephonePipe } from '../../shared/pipes/telephone.pipe';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [TelephonePipe, CommonModule, ReactiveFormsModule, FormsModule, RouterLink],
  templateUrl: './settings.component.html',
  styleUrls: ['./settings.component.scss']
})

export class SettingsComponent implements OnInit {
  currentUser: User | null = null;
  profileForm!: FormGroup;
  passwordForm!: FormGroup;
  selectedFile: File | null = null;
  previewUrl: string | null = null;

  isUpdatingProfile = false;
  isChangingPassword = false;

  // Candidature réserve : null tant qu'aucun fichier n'est envoyé (le prochain upload crée la
  // pièce), ensuite les uploads la mettent à jour.
  maPieceIdentite: PieceIdentiteReserve | null = null;
  uploadPermisEnCours = false;
  uploadPermisErreur = '';

  _successMessage = '';
  _errorMessage = '';

  set successMessage(value: string) {
    this._successMessage = value;
    if (value) {
      setTimeout(() => this._successMessage = '', 1000);
    }
  }

  get successMessage(): string {
    return this._successMessage;
  }

  set errorMessage(value: string) {
    this._errorMessage = value;
    if (value) {
      setTimeout(() => this._successMessage = '', 3000);
    }
  }

  get errorMessage(): string {
    return this._errorMessage;
  }

  // « apercu » par défaut depuis le 13/11/2026 : on arrive sur une VUE D'ENSEMBLE de ses deux
  // rôles, pas sur un formulaire d'identité. Un bénévole qui ouvre son espace veut savoir où en
  // sont ses missions ; un bénéficiaire, où en est sa démarche. Ni l'un ni l'autre n'ouvre cette
  // page pour relire son adresse email.
  activeTab: 'apercu' | 'profile' | 'password' | 'offer' | 'request' | 'crisis' | 'declaration'
    | 'information' | 'dossier' | 'radio' = 'apercu';

  allCrisis:  Crisis[]   = [];  filteredCrisis:  Crisis[]   = [];  isLoadingCrisis  = false;
  allOffers:  Offer[]   = [];  filteredOffers:  Offer[]   = [];  isLoadingOffers  = false;
  allRequests: Request[] = []; filteredRequests: Request[] = []; isLoadingRequests = false;
  allDeclarations: DeclarationSecurite[] = []; filteredDeclarations: DeclarationSecurite[] = []; isLoadingDeclarations = false;
  allInformations: Information[] = []; filteredInformations: Information[] = []; isLoadingInformations = false;
  allDossiers: Dossier[] = []; filteredDossiers: Dossier[] = []; isLoadingDossiers = false;

  showDetailCrisis = false;  showDetailOffer  = false;  showDetailRequest = false;
  showDetailInformation = false; showDetailDeclaration = false;
  selectedReport: Crisis | Offer | Request | Information | DeclarationSecurite | null = null;

  // ── Radio (MeshCore / Meshtastic) ───────────────────────────────
  mesNoeudsMeshCore: NoeudMeshUtilisateur[] = [];
  mesNoeudsMeshtastic: NoeudUtilisateurMeshtastic[] = [];
  isLoadingRadio = false;
  // Réclamer/Libérer sont refusés en zone DEMO : message affiché près du bouton.
  isDemoZone = false;

  /** Nœuds entendus par nos passerelles, proposés au choix. Chargés avec la page : recopier
   * 64 caractères hexadécimaux à la main était la seule façon de se rattacher jusqu'au
   * 11/11/2026, et une faute de frappe rattache un nœud qui n'est pas le sien. */
  candidatsMeshCore: CandidatNoeudMeshCore[] = [];
  candidatsMeshtastic: CandidatNoeudMeshtastic[] = [];
  /** Vrai quand l'utilisateur préfère saisir la clé à la main : son appareil n'a peut-être
   * jamais été entendu par une de nos passerelles, et dans ce cas aucune liste ne l'aura. */
  saisieManuelleMeshCore = false;
  saisieManuelleMeshtastic = false;

  reclamerMeshCorePubkey = '';
  reclamerMeshCoreNom = '';
  reclamerMeshCoreEnCours = false;
  reclamerMeshCoreErreur = '';
  libererMeshCoreErreur = '';
  libererMeshCoreSucces = '';

  reclamerMeshtasticNodeNum: number | null = null;
  reclamerMeshtasticNom = '';
  reclamerMeshtasticEnCours = false;
  reclamerMeshtasticErreur = '';
  libererMeshtasticErreur = '';
  libererMeshtasticSucces = '';
  /** Renseigné quand le backend n'a pas pu déduire le broker (NoeudUtilisateurMeshtasticViewSet.reclamer). */
  meshtasticBrokerRequis: { id: string; nom: string }[] | null = null;
  meshtasticBrokerChoisi = '';
  /** Brokers actifs, chargés seulement si compagnons_candidats est vide. */
  tousLesBrokersMeshtastic: { id: string; nom: string; broker_host: string }[] = [];

  constructor(
    private fb: FormBuilder,
    private authService:    AuthService,
    private criseService:   CrisisService,
    private demandeService: RequestService,
    private offreService:   OfferService,
    private informationService: InformationService,
    private declarationService: DeclarationSecuriteService,
    private dossierService: DossierService,
    private userService: UserService,
    private pieceIdentiteReserveService: PieceIdentiteReserveService,
    private router: Router,
    private route: ActivatedRoute,
    private teamService: TeamService,
    private noeudMeshCoreService: NoeudMeshUtilisateurService,
    private noeudMeshtasticService: NoeudUtilisateurMeshtasticService,
    private compagnonMeshtasticService: CompagnonMeshtasticService,
    public suiviPosition: SuiviPositionPermanentService,
  ) {}

  /** Bascule le suivi de position permanent (accord demandé une fois). Accessible ici à tout
   * utilisateur connecté. */
  basculerSuiviPosition(): void {
    if (this.suiviPosition.actif) {
      this.suiviPosition.desactiver();
    } else {
      this.suiviPosition.activer();
    }
  }

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.isDemoZone = this.authService.getEnvironment() === 'DEMO';
    // photo est write_only : aperçu récupéré en blob.
    this.previewUrl = null;
    if (this.currentUser?.photo_url) {
      this.userService.preview(this.currentUser.id).subscribe({
        next: (blob) => this.previewUrl = URL.createObjectURL(blob),
        error: () => {},
      });
    }
    this.initForms();
    this.loadAll();
    this.loadEquipes();

    if (this.currentUser?.souhaite_rejoindre_reserve) {
      this.chargerPieceIdentiteReserve();
    }

    // Abonnement à queryParams : les liens rapides changent seulement `tab`, Angular réutilise
    // l'instance et ne relance pas ngOnInit.
    const validTabs: (typeof this.activeTab)[] = ['apercu', 'profile', 'password', 'offer',
      'request', 'crisis', 'declaration', 'information', 'dossier', 'radio'];
    this.route.queryParamMap.subscribe(params => {
      const requestedTab = params.get('tab');
      if (requestedTab && (validTabs as string[]).includes(requestedTab)) {
        this.setActiveTab(requestedTab as typeof this.activeTab);
      }
    });
  }

  private initForms(): void {
    this.profileForm = this.fb.group({
      // Champs Django : first_name, last_name, email, telephone_utilisateur
      username:                [this.currentUser?.username,  [Validators.required, Validators.minLength(2)]],
      last_name:               [this.currentUser?.last_name,  [Validators.required, Validators.minLength(2)]],
      first_name:              [this.currentUser?.first_name  ?? ''],
      email:                   [this.currentUser?.email,       [Validators.required, Validators.email]],
      phone_number:            [this.currentUser?.phone_number ?? '']
    });

    this.passwordForm = this.fb.group({
      oldPassword:      ['', Validators.required],
      newPassword:      ['', [Validators.required, Validators.minLength(8)]],
      confirmPassword:  ['', Validators.required]
    }, { validators: this.passwordMatchValidator });
  }

  private passwordMatchValidator(g: FormGroup) {
    return g.get('newPassword')?.value === g.get('confirmPassword')?.value
      ? null : { passwordMismatch: true };
  }

  private loadAll(): void {
    // Toutes ces listes sont filtrées par l'email de l'utilisateur connecté, et quatre d'entre
    // elles l'affirmaient non nul (`currentUser!`). Il peut l'être — session expirée, profil
    // pas encore chargé — et la page partait alors en TypeError pendant ngOnInit : écran
    // blanc, sans message. Un seul garde en amont plutôt que quatre rustines : sans
    // utilisateur, il n'y a rien à charger, c'est la bonne réponse et pas un cas d'erreur.
    //
    // Trouvé par le harnais de test (28/10/2026), jamais vu en usage parce qu'on arrive
    // normalement ici connecté.
    if (!this.currentUser?.email) { return; }
    this.loadCrises();
    this.loadOffres();
    this.loadDemandes();
    this.loadDeclarations();
    this.loadInformations();
    this.loadDossiers();
    this.loadMesNoeuds();
    this.loadCandidats();
  }

  // ── Radio (MeshCore / Meshtastic) ───────────────────────────────

  private loadMesNoeuds(): void {
    this.isLoadingRadio = true;
    this.noeudMeshCoreService.mesNoeuds().subscribe({
      next: list => { this.mesNoeudsMeshCore = list; this.isLoadingRadio = false; },
      error: () => (this.isLoadingRadio = false),
    });
    this.noeudMeshtasticService.mesNoeuds().subscribe({
      next: list => { this.mesNoeudsMeshtastic = list; },
    });
  }

  /** Les nœuds entendus, pour reconnaître le sien au lieu de recopier une clé.
   *
   * Un échec est silencieux et non signalé : la liste est une COMMODITÉ, la saisie manuelle
   * reste disponible. Une erreur rouge sur une aide facultative ferait croire que le
   * rattachement est cassé alors qu'il marche. */
  private loadCandidats(): void {
    this.noeudMeshCoreService.candidats().subscribe({
      next: list => { this.candidatsMeshCore = list; },
      error: () => { this.candidatsMeshCore = []; this.saisieManuelleMeshCore = true; },
    });
    this.noeudMeshtasticService.candidats().subscribe({
      next: list => { this.candidatsMeshtastic = list; },
      error: () => { this.candidatsMeshtastic = []; this.saisieManuelleMeshtastic = true; },
    });
  }

  /** Ceux qu'on peut effectivement réclamer : les nœuds déjà pris par quelqu'un d'autre
   * restent affichés (voir le gabarit) mais ne sont pas proposés au choix. */
  get candidatsMeshCoreLibres(): CandidatNoeudMeshCore[] {
    return this.candidatsMeshCore.filter(c => !c.deja_associe);
  }

  get candidatsMeshtasticLibres(): CandidatNoeudMeshtastic[] {
    return this.candidatsMeshtastic.filter(c => !c.deja_associe);
  }

  /** Choix dans la liste : on remplit la clé ET le nom annoncé par l'appareil, qui est presque
   * toujours le bon libellé — l'utilisateur peut encore le changer. */
  choisirCandidatMeshCore(candidat: CandidatNoeudMeshCore): void {
    this.reclamerMeshCorePubkey = candidat.pubkey_hex;
    if (!this.reclamerMeshCoreNom.trim()) this.reclamerMeshCoreNom = candidat.nom;
  }

  choisirCandidatMeshtastic(candidat: CandidatNoeudMeshtastic): void {
    this.reclamerMeshtasticNodeNum = candidat.node_num;
    if (!this.reclamerMeshtasticNom.trim()) {
      this.reclamerMeshtasticNom = candidat.long_name || candidat.short_name || '';
    }
  }

  get formReclamerMeshCoreValide(): boolean {
    return this.reclamerMeshCorePubkey.trim().length > 0;
  }

  reclamerMeshCore(): void {
    if (!this.formReclamerMeshCoreValide) return;
    this.reclamerMeshCoreEnCours = true;
    this.reclamerMeshCoreErreur = '';
    this.noeudMeshCoreService.reclamer(this.reclamerMeshCorePubkey.trim(), this.reclamerMeshCoreNom.trim()).subscribe({
      next: () => {
        this.reclamerMeshCorePubkey = '';
        this.reclamerMeshCoreNom = '';
        this.reclamerMeshCoreEnCours = false;
        this.loadMesNoeuds();
        this.loadCandidats();
      },
      error: err => {
        this.reclamerMeshCoreErreur = err.error?.detail || 'Impossible de réclamer ce nœud.';
        this.reclamerMeshCoreEnCours = false;
      },
    });
  }

  libererMeshCore(noeud: NoeudMeshUtilisateur): void {
    if (!confirm(`Libérer le nœud « ${noeud.nom_noeud || noeud.pubkey_hex.slice(0, 12) + '…'} » ?`)) return;
    this.libererMeshCoreErreur = '';
    this.libererMeshCoreSucces = '';
    this.noeudMeshCoreService.liberer(noeud.pubkey_hex).subscribe({
      next: () => {
        this.mesNoeudsMeshCore = this.mesNoeudsMeshCore.filter(n => n.id !== noeud.id);
        this.libererMeshCoreSucces = 'Nœud libéré.';
      },
      error: err => { this.libererMeshCoreErreur = err.error?.detail || 'Impossible de libérer ce nœud.'; },
    });
  }

  get formReclamerMeshtasticValide(): boolean {
    return this.reclamerMeshtasticNodeNum != null;
  }

  reclamerMeshtastic(): void {
    if (!this.formReclamerMeshtasticValide) return;
    this.reclamerMeshtasticEnCours = true;
    this.reclamerMeshtasticErreur = '';
    this.noeudMeshtasticService.reclamer(
      this.reclamerMeshtasticNodeNum!, this.reclamerMeshtasticNom.trim(),
      this.meshtasticBrokerRequis ? this.meshtasticBrokerChoisi : undefined,
    ).subscribe({
      next: () => {
        this.reclamerMeshtasticNodeNum = null;
        this.reclamerMeshtasticNom = '';
        this.meshtasticBrokerRequis = null;
        this.meshtasticBrokerChoisi = '';
        this.reclamerMeshtasticEnCours = false;
        this.loadMesNoeuds();
        this.loadCandidats();
      },
      error: err => {
        const body = err.error as ReclamerMeshtasticBrokerRequis | { detail?: string };
        if (body && 'compagnon_requis' in body && body.compagnon_requis) {
          // Broker déduit impossible : soit plusieurs candidats renvoyés directement, soit
          // aucun (nœud jamais détecté) — dans ce dernier cas on charge tous les brokers actifs.
          if (body.compagnons_candidats) {
            this.meshtasticBrokerRequis = body.compagnons_candidats;
            this.reclamerMeshtasticEnCours = false;
          } else {
            this.compagnonMeshtasticService.envoyables().subscribe({
              next: brokers => {
                this.tousLesBrokersMeshtastic = brokers;
                this.meshtasticBrokerRequis = brokers.map(b => ({ id: b.id, nom: `${b.nom} (${b.broker_host})` }));
                this.reclamerMeshtasticEnCours = false;
              },
              error: () => { this.reclamerMeshtasticEnCours = false; },
            });
          }
        } else {
          this.reclamerMeshtasticErreur = (body as { detail?: string })?.detail || 'Impossible de réclamer ce nœud.';
          this.reclamerMeshtasticEnCours = false;
        }
      },
    });
  }

  annulerChoixBrokerMeshtastic(): void {
    this.meshtasticBrokerRequis = null;
    this.meshtasticBrokerChoisi = '';
  }

  libererMeshtastic(noeud: NoeudUtilisateurMeshtastic): void {
    if (!confirm(`Libérer le nœud « ${noeud.nom_noeud || this.nodeNumHex(noeud.node_num)} » ?`)) return;
    this.libererMeshtasticErreur = '';
    this.libererMeshtasticSucces = '';
    this.noeudMeshtasticService.liberer(noeud.node_num).subscribe({
      next: () => {
        this.mesNoeudsMeshtastic = this.mesNoeudsMeshtastic.filter(n => n.id !== noeud.id);
        this.libererMeshtasticSucces = 'Nœud libéré.';
      },
      error: err => { this.libererMeshtasticErreur = err.error?.detail || 'Impossible de libérer ce nœud.'; },
    });
  }

  nodeNumHex(n: number): string {
    return '!' + n.toString(16).padStart(8, '0');
  }

  private loadDeclarations(): void {
    this.isLoadingDeclarations = true;
    this.declarationService.mesDeclarations().subscribe({
      next: list => {
        this.allDeclarations = this.filteredDeclarations = list;
        this.isLoadingDeclarations = false;
      },
      error: () => (this.isLoadingDeclarations = false)
    });
  }

  private loadInformations(): void {
    this.isLoadingInformations = true;
    this.informationService.getMines(this.currentUser!.email).subscribe({
      next: list => {
        this.allInformations = this.filteredInformations = list;
        this.isLoadingInformations = false;
      },
      error: () => (this.isLoadingInformations = false)
    });
  }

  private loadDossiers(): void {
    this.isLoadingDossiers = true;
    this.dossierService.getAll().subscribe({
      next: list => {
        this.allDossiers = this.filteredDossiers = list;
        this.isLoadingDossiers = false;
      },
      error: () => (this.isLoadingDossiers = false)
    });
  }

  private loadCrises(): void {
    this.isLoadingCrisis = true;
    // Django filtre par validateur (UUID de l'utilisateur)
    this.criseService.getMines(this.currentUser!.email).subscribe({
      next: list => {
        this.allCrisis = this.filteredCrisis = list;
        this.isLoadingCrisis = false;
      },
      error: () => (this.isLoadingCrisis = false)
    });
  }

  private loadOffres(): void {
    this.isLoadingOffers = true;
    this.offreService.getMines(this.currentUser!.email).subscribe({
      next: list => {
        this.allOffers = this.filteredOffers = list;
        this.isLoadingOffers = false;
      },
      error: () => (this.isLoadingOffers = false)
    });
  }

  private loadDemandes(): void {
    this.isLoadingRequests = true;
    this.demandeService.getMines(this.currentUser!.email).subscribe({
      next: list => {
        this.allRequests = this.filteredRequests = list;
        this.isLoadingRequests = false;
      },
      error: () => (this.isLoadingRequests = false)
    });
  }

  // ══ Les deux secteurs ═══════════════════════════════════════════════════════════════
  //
  // Demande de Sylvain du 13/11/2026 : « un bénévole ou un bénéficiaire devrait arriver sur
  // cette page certes, mais avec 2 secteurs : le secteur bénéficiaire avec le suivi de ses
  // demandes / démarches ; le secteur bénévole, avec ses offres, ses missions en cours, le
  // récap du passé, ses documents justificatifs ».
  //
  // La page servait neuf onglets de même poids, nommés par le modèle de données (« Offres »,
  // « Besoins », « Crises ») et non par ce que la personne vient y faire. Or ce sont **deux
  // rôles différents**, qu'une même personne porte souvent tous les deux : demander de l'aide
  // et en donner. Les mélanger à plat oblige à relire la liste entière pour retrouver l'un ou
  // l'autre.
  //
  // Rien n'est ajouté côté serveur : tout était déjà servi. Ce qui change est le classement,
  // les mots, et la vue d'ensemble d'arrivée.

  mesEquipes: Team[] = [];

  private loadEquipes(): void {
    // Sert à séparer MES DÉMARCHES (dossiers ouverts pour moi) de MES MISSIONS (dossiers
    // confiés à une équipe dont je fais partie). `getAll()` rend les deux, et les confondre
    // montrerait à un bénévole « vos démarches » en parlant des gens qu'il aide.
    this.teamService.mesEquipes().subscribe({
      next: (teams) => this.mesEquipes = teams,
      error: () => this.mesEquipes = [],
    });
  }

  private get idsDeMesEquipes(): Set<string> {
    return new Set(this.mesEquipes.map(e => e.id).filter((id): id is string => !!id));
  }

  /** Les dossiers ouverts POUR MOI : ma démarche, celle dont j'attends l'issue. */
  get mesDemarches(): Dossier[] {
    const equipes = this.idsDeMesEquipes;
    return this.allDossiers.filter(d => !d.equipe || !equipes.has(d.equipe));
  }

  /** Les dossiers confiés à une équipe dont je fais partie : ce que je fais pour les autres. */
  get mesMissions(): Dossier[] {
    const equipes = this.idsDeMesEquipes;
    return this.allDossiers.filter(d => d.equipe && equipes.has(d.equipe));
  }

  /** Clos ou non : « en cours » est le seul chiffre qui appelle une action. Un compteur qui
   * additionne les dossiers terminés dit « 14 » à quelqu'un qui n'a rien à faire. */
  private estTermine(statut: string | undefined): boolean {
    return ['CLOTURE', 'CLOTUREE', 'RESOLU', 'RESOLUE', 'ANNULE', 'ANNULEE', 'TERMINE',
            'TERMINEE'].includes((statut ?? '').toUpperCase());
  }

  get demarchesEnCours(): Dossier[] {
    return this.mesDemarches.filter(d => !this.estTermine(d.statut));
  }

  get missionsEnCours(): Dossier[] {
    return this.mesMissions.filter(d => !this.estTermine(d.statut));
  }

  get missionsPassees(): Dossier[] {
    return this.mesMissions.filter(d => this.estTermine(d.statut));
  }

  get demandesEnCours(): Request[] {
    return this.allRequests.filter(r => !this.estTermine(String(r.status)));
  }

  get offresEnCours(): Offer[] {
    return this.allOffers.filter(o => !this.estTermine(String(o.status)));
  }

  /** Vrai dès que la personne a fait quelque chose en tant que bénéficiaire. Sert à ouvrir le
   * bon secteur en premier plutôt qu'à masquer l'autre : quelqu'un qui n'a jamais rien demandé
   * doit quand même pouvoir le faire. */
  get aUnVecuDeBeneficiaire(): boolean {
    return this.allRequests.length > 0 || this.mesDemarches.length > 0
      || this.allDeclarations.length > 0 || this.allInformations.length > 0;
  }

  get aUnVecuDeBenevole(): boolean {
    return this.allOffers.length > 0 || this.mesMissions.length > 0
      || this.mesEquipes.length > 0;
  }

  /** L'entrée « Mes justificatifs » ne vaut que pour un adhérent d'association : elle mène à
   * sa fiche de bénévole, qui n'existe pas pour les autres. */
  get estBenevoleAssociation(): boolean {
    return !!this.currentUser?.est_benevole_association;
  }

  // ── Quel groupe est déplié (surtout sur smartphone) ───────────────────────────────
  //
  // Sur un écran large les trois groupes tiennent côte à côte et restent tous ouverts. Sur un
  // téléphone, dix onglets sur une seule bande devenaient des pictogrammes de 24 px sans
  // libellé, impossibles à viser — constaté le 13/11/2026 sur un Android de 412 px. On
  // n'ouvre donc qu'un groupe à la fois, avec les mots en entier et des lignes de la hauteur
  // d'un doigt.
  groupeOuvert: 'aide' | 'benevole' | 'compte' = 'aide';

  private groupeDe(tab: typeof this.activeTab): 'aide' | 'benevole' | 'compte' | null {
    if (['request', 'dossier', 'declaration', 'information', 'crisis'].includes(tab)) {
      return 'aide';
    }
    if (['offer', 'radio'].includes(tab)) { return 'benevole'; }
    if (['profile', 'password'].includes(tab)) { return 'compte'; }
    return null;   // la vue d'ensemble n'appartient à aucun groupe
  }

  ouvrirGroupe(groupe: 'aide' | 'benevole' | 'compte'): void {
    // Replier le groupe courant en recliquant dessus ferait disparaître l'onglet actif de
    // l'écran sans rien mettre à la place : un en-tête de groupe ouvre, il ne ferme pas.
    this.groupeOuvert = groupe;
  }

  setActiveTab(tab: typeof this.activeTab): void {
    // Le groupe suit l'onglet : arriver par un lien `?tab=dossier` doit déplier « J'ai besoin
    // d'aide », sinon l'onglet actif serait invisible dans la barre.
    const groupe = this.groupeDe(tab);
    if (groupe) { this.groupeOuvert = groupe; }
    this.activeTab = tab;
    this.clearMessages();
  }

  updateProfile(): void {
    if (this.profileForm.invalid) return;
    this.isUpdatingProfile = true;
    this.clearMessages();

    // On mappe les champs Angular → champs Django
    this.authService.updateProfile(this.profileForm.getRawValue()).subscribe({
      next: user => {
        this.currentUser = user;
        this.successMessage = 'Profil mis à jour avec succès';
        this.isUpdatingProfile = false;
      },
      error: err => {
        this.errorMessage = err.error?.detail ?? 'Erreur lors de la mise à jour';
        this.isUpdatingProfile = false;
      }
    });
  }

  changePassword(): void {
    if (this.passwordForm.invalid) return;
    this.isChangingPassword = true;
    this.clearMessages();

    const { oldPassword, newPassword } = this.passwordForm.value;
    // Noms de champs Django : old_password / new_password
    this.authService.changePassword(oldPassword, newPassword).subscribe({
      next: () => {
        this.successMessage = 'Mot de passe changé avec succès';
        this.passwordForm.reset();
        this.isChangingPassword = false;
      },
      error: err => {
        this.errorMessage = err.error?.detail ?? 'Erreur lors du changement';
        this.isChangingPassword = false;
      }
    });
  }

  deleteAccount(): void {
  }

  /**
   * Gère la sélection d'un fichier photo
   */
  onFileSelected(event: any): void {
    const file = event.target.files[0];
    if (file) {
      this.selectedFile = file;
      
      // Créer un aperçu
      const reader = new FileReader();
      reader.onload = (e: any) => {
        this.previewUrl = e.target.result;
      };
      reader.readAsDataURL(file);
    }
  }

  /**
   * Supprime la photo sélectionnée
   */
  removeSelectedFile(): void {
    this.selectedFile = null;
    this.previewUrl = null;
  }

  // ── Filtres ──────────────────────────────────────────────────

  onFilterCrisis(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredCrisis = this.allCrisis.filter(c =>
      c.name.toLowerCase().includes(term) ||
      c.description?.toLowerCase().includes(term)
    );
  }

  onFilterOffer(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredOffers = this.allOffers.filter(o =>
      o.title.toLowerCase().includes(term) ||
      o.status.toLowerCase().includes(term)
    );
  }

  onFilterNeed(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredRequests = this.allRequests.filter(d =>
      d.title.toLowerCase().includes(term) ||
      d.status.toLowerCase().includes(term)
    );
  }

  onFilterInformation(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredInformations = this.allInformations.filter(i =>
      i.title.toLowerCase().includes(term) ||
      i.status.toLowerCase().includes(term)
    );
  }

  onFilterDeclaration(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredDeclarations = this.allDeclarations.filter(d =>
      (d.situation_libelle ?? '').toLowerCase().includes(term) ||
      (d.crise_nom ?? '').toLowerCase().includes(term)
    );
  }

  onFilterDossier(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredDossiers = this.allDossiers.filter(d =>
      d.titre.toLowerCase().includes(term) ||
      d.statut.toLowerCase().includes(term) ||
      d.numero.toLowerCase().includes(term)
    );
  }

  // ── Suppression ──────────────────────────────────────────────

  deleteCrisis(crise: Crisis): void {
    if (!confirm(`Supprimer "${crise.name}" ?`)) return;
    this.criseService.delete(crise.id).subscribe({
      next:  () => { this.successMessage = 'Crise supprimée'; this.loadCrises(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  deleteOffer(offre: Offer): void {
    if (!confirm(`Supprimer "${offre.title}" ?`)) return;
    this.offreService.delete(offre.id).subscribe({
      next:  () => { this.successMessage = 'Offre supprimée'; this.loadOffres(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  deleteRequest(demande: Request): void {
    if (!confirm(`Supprimer "${demande.title}" ?`)) return;
    this.demandeService.delete(demande.id).subscribe({
      next:  () => { this.successMessage = 'Demande supprimée'; this.loadDemandes(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  deleteInformation(info: Information): void {
    if (!confirm(`Supprimer "${info.title}" ?`)) return;
    this.informationService.delete(info.id).subscribe({
      next:  () => { this.successMessage = 'Signalement supprimé'; this.loadInformations(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  deleteDeclaration(declaration: DeclarationSecurite): void {
    if (!declaration.id) return;
    if (!confirm(`Supprimer cette déclaration ?`)) return;
    this.declarationService.delete(declaration.id).subscribe({
      next:  () => { this.successMessage = 'Déclaration supprimée'; this.loadDeclarations(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  // ── Édition ──────────────────────────────────────────────────

  editCrisis(c: Crisis):     void { this.router.navigate(['/user/crise/edit',   c.id]); }

  editOffer(offer: Offer): void { 
    if(offer.status == Status.AVAILABLE) {
      offer.status = Status.UNAVAILABLE;
    } else {
      offer.status = Status.AVAILABLE;
    }
    offer.status = Status.UNAVAILABLE;
    this.offreService.update(offer.id, offer).subscribe({
      next:  () => { this.successMessage = 'Offre mise à jour'; this.loadOffres(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    })
  }

  editRequest(demande: Request): void { 
    if(demande.status == Status.PROCESSED) {
      demande.status = Status.UNPROCESSED;
    } else {
      demande.status = Status.PROCESSED;
    }
    this.demandeService.update(demande.id, demande).subscribe({
      next:  () => { this.successMessage = 'Demande mise à jour'; this.loadDemandes(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  // ----- View ----------------------------------------------------------------
  viewCrisis(crisis: Crisis): void {
    this.selectedReport = crisis;

    this.showDetailCrisis = true;
    this.showDetailOffer = false;
    this.showDetailRequest = false;
    this.showDetailInformation = false;
    this.showDetailDeclaration = false;
  }

  viewOffer(offre: Offer): void {
    this.selectedReport = offre;

    this.showDetailOffer = true;
    this.showDetailCrisis = false;
    this.showDetailRequest = false;
    this.showDetailInformation = false;
    this.showDetailDeclaration = false;
  }

  viewRequest(demande: Request): void {
    this.selectedReport = demande;

    this.showDetailRequest = true;
    this.showDetailOffer = false;
    this.showDetailCrisis = false;
    this.showDetailInformation = false;
    this.showDetailDeclaration = false;
  }

  viewInformation(info: Information): void {
    this.selectedReport = info;

    this.showDetailInformation = true;
    this.showDetailRequest = false;
    this.showDetailOffer = false;
    this.showDetailCrisis = false;
    this.showDetailDeclaration = false;
  }

  viewDeclaration(declaration: DeclarationSecurite): void {
    this.selectedReport = declaration;

    this.showDetailDeclaration = true;
    this.showDetailInformation = false;
    this.showDetailRequest = false;
    this.showDetailOffer = false;
    this.showDetailCrisis = false;
  }

  goToDossierSuivi(dossier: Dossier): void {
    this.router.navigate(['/dossier-suivi', dossier.id]);
  }

  // ── Helpers ──────────────────────────────────────────────────

  /** Libellé lisible pour les statuts Django */
  getStatusLabel(statut: string): string {
    const labels: Record<string, string> = {
      [Status.UNPROCESSED]:  'Non traitée',
      [Status.IN_PROGRESS]:     'En cours',
      [Status.PROCESSED]:      'Traitée',
      [Status.AVAILABLE]:   'Disponible',
      [Status.UNAVAILABLE]: 'Indisponible'
    };
    return labels[statut] ?? statut;
  }

  /** Affiche les coordonnées extraites depuis le GeoPoint Django */
  getLocation(lat?: number | null, lng?: number | null): string {
    if (lat == null || lng == null) return '—';
    return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  }

  closeDetail(): void {
    this.showDetailCrisis = false;
    this.showDetailOffer = false;
    this.showDetailRequest = false;
    this.showDetailInformation = false;
    this.showDetailDeclaration = false;
    this.selectedReport = null;
  }

  isCrise(r: Crisis | Offer | Request | Information | DeclarationSecurite): r is Crisis {
    return 'name' in r && 'validator' in r;
  }

  isOffre(r: Crisis | Offer | Request | Information | DeclarationSecurite): r is Offer {
    return 'first_name_offer' in r;
  }

  isDemande(r: Crisis | Offer | Request | Information | DeclarationSecurite): r is Request {
    return 'first_name_request' in r;
  }

  isInformation(r: Crisis | Offer | Request | Information | DeclarationSecurite): r is Information {
    return 'first_name_information' in r;
  }

  isDeclaration(r: Crisis | Offer | Request | Information | DeclarationSecurite): r is DeclarationSecurite {
    return 'nom_referent' in r;
  }
  get isAdmin(): boolean { return this.authService.isAdmin(); }
  get isIndividual(): boolean { return this.currentUser?.type === 'UTIL_SIMPLE'; }

  private clearMessages(): void { this.successMessage = ''; this.errorMessage = ''; }

  private chargerPieceIdentiteReserve(): void {
    // L'API ne renvoie que la pièce du propriétaire (au plus une).
    this.pieceIdentiteReserveService.mesPieces().subscribe({
      next: (pieces) => { this.maPieceIdentite = pieces[0] ?? null; },
      error: () => {},
    });
  }

  onFichierPermisRecto(event: Event): void {
    this.uploaderPermis('permis_recto', event);
  }

  onFichierPermisVerso(event: Event): void {
    this.uploaderPermis('permis_verso', event);
  }

  private uploaderPermis(champ: 'permis_recto' | 'permis_verso', event: Event): void {
    const input = event.target as HTMLInputElement;
    const fichier = input.files?.[0];
    if (!fichier) return;

    this.uploadPermisEnCours = true;
    this.uploadPermisErreur = '';

    const envoi = this.maPieceIdentite
      ? this.pieceIdentiteReserveService.mettreAJour(this.maPieceIdentite.id, { [champ]: fichier })
      : this.pieceIdentiteReserveService.creer({ [champ]: fichier });

    envoi.subscribe({
      next: (piece) => {
        this.maPieceIdentite = piece;
        this.uploadPermisEnCours = false;
        input.value = '';
      },
      error: (err) => {
        this.uploadPermisErreur = err?.error?.[champ]?.[0] || 'Échec de l\'envoi du fichier.';
        this.uploadPermisEnCours = false;
        input.value = '';
      },
    });
  }
}
