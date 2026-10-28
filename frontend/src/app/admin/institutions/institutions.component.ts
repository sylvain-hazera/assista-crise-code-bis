import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { InstitutionService } from '../../services/institution.service';
import { InstitutionTypeService } from '../../services/institution-type.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import { InstitutionDomaineService } from '../../services/institution-domaine.service';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../auth/services/auth.service';
import { CompetenceService } from '../../services/competence.service';
import { AffectationRoleOperationnelService } from '../../services/affectation-role-operationnel.service';
import { LocationService, Commune } from '../../services/location.service';
import { ZoneService } from '../../services/zone.service';
import { Zone } from '../../shared/models/zone.model';
import { ConfigurationAlerteSismiqueService } from '../../services/configuration-alerte-sismique.service';
import { ConfigurationAlerteSismique } from '../../shared/models/configuration-alerte-sismique.model';
import { InterlocuteurAlertePCSService } from '../../services/interlocuteur-alerte-pcs.service';
import {
  InterlocuteurAlertePCS, CategorieInterlocuteurPCS, ModeAlertePCS,
  CATEGORIES_INTERLOCUTEUR_PCS, MODES_ALERTE_PCS,
} from '../../shared/models/interlocuteur-alerte-pcs.model';
import { RisqueMajeurTypeService, RisqueCommunalService } from '../../services/risque-majeur.service';
import { RisqueMajeurType, RisqueCommunal, SuggestionGeorisques } from '../../shared/models/risque-majeur.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';
import { BlocAjoutComponent, ChampInvitation } from '../../shared/components/common/bloc-ajout/bloc-ajout.component';
import { environment } from '../../../environments/environment';
import { MatrixSalonChatComponent } from '../teams/matrix-salon-chat/matrix-salon-chat.component';

import {
  Institution,
  InstitutionType,
  RoleOperationnel,
  ContactInstitution,
  InstitutionDomaine,
  AffectationRoleOperationnel,
} from '../../shared/models/institution.model';
import { User } from '../../shared/models/user.model';
import { Competence } from '../../shared/models/competence.model';

type MainTab = 'institutions' | 'types' | 'roles';
type ModalView = 'none' | 'create' | 'edit' | 'delete' | 'detail';
type RefModalView = 'none' | 'create' | 'edit' | 'delete';
type DetailTab = 'contacts' | 'domaines' | 'regulateurs' | 'matrix' | 'alertes' | 'annuaire-pcs' | 'mes-risques';

@Component({
  selector: 'app-institutions',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink, TagSearchInputComponent, MatrixSalonChatComponent, BlocAjoutComponent],
  templateUrl: './institutions.component.html',
  styleUrls: ['./institutions.component.scss'],
})
export class InstitutionsComponent implements OnInit {

  activeTab: MainTab = 'institutions';

  // ── Les trois gestes d'ajout (BlocAjoutComponent) ──────────────────────────
  // URLs plutot que methodes de service : le bloc est generique et sert sept destinations, lui
  // passer un service par destination reviendrait a lui faire connaitre chacune.
  readonly urlExempleInstitutions = `${environment.apiUrl}/imports/institutions/exemple/`;
  readonly urlImportInstitutions = `${environment.apiUrl}/imports/institutions/`;
  readonly urlInvitationInstitution = `${environment.apiUrl}/institutions/inviter/`;
  readonly urlExemplePersonnel = `${environment.apiUrl}/imports/personnel-communal/exemple/`;
  readonly urlImportPersonnel = `${environment.apiUrl}/imports/personnel-communal/`;
  readonly urlInvitationContact = `${environment.apiUrl}/contacts-institutions/inviter/`;

  readonly urlExempleCorrespondants = `${environment.apiUrl}/imports/correspondants-pcs/exemple/`;
  readonly urlImportCorrespondants = `${environment.apiUrl}/imports/correspondants-pcs/`;
  readonly urlExempleInterlocuteurs = `${environment.apiUrl}/imports/interlocuteurs-pcs/exemple/`;
  readonly urlImportInterlocuteurs = `${environment.apiUrl}/imports/interlocuteurs-pcs/`;

  /** Invitations toujours dans SA collectivite : le serveur l'impose aussi, on evite juste
   * d'envoyer une requete vouee au 403. */
  get monInstitutionId(): string {
    return this.authService.getCurrentUser()?.institution_id || '';
  }

  /** Le `+` des correspondants renvoie vers l'assistant, qui sait poser le role en meme temps
   * que le compte -- un formulaire local ne saurait que creer le contact. */
  allerSaisirCorrespondants(): void {
    this.router.navigate(['/admin/import-correspondants-pcs']);
  }

  /** Le `+` de l'annuaire PCS pose le focus sur la recherche juste en dessous : elle cherche
   * un interlocuteur existant AVANT d'en creer un, ce qui est la regle de cet annuaire (un
   * meme SIDPC est partage par plusieurs communes). */
  focusRechercheInterlocuteur(): void {
    const champ = document.querySelector<HTMLInputElement>('app-tag-search-input input');
    champ?.focus();
  }

  readonly champsInvitationContact: ChampInvitation[] = [
    { cle: 'email', label: 'Adresse email', type: 'email', requis: true,
      placeholder: 'dgs@mairie-exemple.fr' },
    { cle: 'fonction', label: 'Fonction', placeholder: 'DGS, secretaire de mairie...' },
    // Prenom et nom facultatifs a dessein : on invite souvent depuis une adresse de service
    // seule, et exiger un nom qu'on ne connait pas conduit a inventer « DGS DGS ».
    { cle: 'first_name', label: 'Prenom' },
    { cle: 'last_name', label: 'Nom' },
  ];

  /** Le type est propose depuis les InstitutionType existants, jamais saisi librement : un type
   * structure les permissions et le niveau de secteur, il ne se cree pas depuis une invitation
   * (meme regle que importer_institutions). */
  get champsInvitationInstitution(): ChampInvitation[] {
    return [
      { cle: 'email', label: 'Adresse email du destinataire', type: 'email', requis: true,
        placeholder: 'contact@mairie-voisine.fr' },
      { cle: 'nom', label: "Nom de l'institution", requis: true,
        placeholder: 'Mairie de Exemple-sur-Loire' },
      { cle: 'type', label: "Type d'institution", type: 'select',
        options: this.types.filter(t => t.actif !== false)
          .map(t => ({ valeur: t.libelle, libelle: t.libelle })),
        aide: 'Laissez vide si vous ne savez pas : le destinataire le renseignera.' },
    ];
  }

  institutions: Institution[] = [];
  types: InstitutionType[] = [];
  roles: RoleOperationnel[] = [];
  users: User[] = [];
  contacts: ContactInstitution[] = [];
  domaines: InstitutionDomaine[] = [];
  competences: Competence[] = [];
  affectationsRoles: AffectationRoleOperationnel[] = [];
  /** Zones de l'institution ouverte, chargées dans openDetail. */
  zones: Zone[] = [];

  isLoading = true;
  isSaving = false;
  errorMessage = '';
  successMessage = '';
  searchQuery = '';

  // ── Institution ──
  modal: ModalView = 'none';
  selectedInstitution: Institution | null = null;
  institutionForm!: FormGroup;

  detailTab: DetailTab = 'contacts';
  showContactForm = false;
  showDomaineForm = false;
  showRegulateurForm = false;
  contactForm!: FormGroup;
  domaineForm!: FormGroup;
  regulateurForm!: FormGroup;

  contactUserQuery = '';
  showContactUserResults = false;

  // ── Type d'institution (référentiel) ──
  typeModal: RefModalView = 'none';
  selectedType: InstitutionType | null = null;
  typeForm!: FormGroup;

  // ── Rôle opérationnel (référentiel) ──
  roleModal: RefModalView = 'none';
  selectedRole: RoleOperationnel | null = null;
  roleForm!: FormGroup;

  constructor(
    private fb: FormBuilder,
    private institutionService: InstitutionService,
    private institutionTypeService: InstitutionTypeService,
    private roleOperationnelService: RoleOperationnelService,
    private contactService: ContactInstitutionService,
    private domaineService: InstitutionDomaineService,
    private userService: UserService,
    private competenceService: CompetenceService,
    private affectationRoleService: AffectationRoleOperationnelService,
    private locationService: LocationService,
    private zoneService: ZoneService,
    private configurationAlerteSismiqueService: ConfigurationAlerteSismiqueService,
    private interlocuteurAlertePCSService: InterlocuteurAlertePCSService,
    private risqueMajeurTypeService: RisqueMajeurTypeService,
    private risqueCommunalService: RisqueCommunalService,
    private authService: AuthService,
    private router: Router,
  ) {}

  readonly categoriesInterlocuteurPCS = CATEGORIES_INTERLOCUTEUR_PCS;
  readonly modesAlertePCS = MODES_ALERTE_PCS;

  ngOnInit(): void {
    this.buildForms();
    this.loadAll();
  }

  // ── Salons Matrix généraux de l'institution (permanents / bénévoles mobilisés) ─────────
  provisionnantSalonsMatrix = false;

  provisionnerSalonsMatrix(): void {
    if (!this.selectedInstitution?.id) return;
    this.provisionnantSalonsMatrix = true;
    this.institutionService.provisionnerSalonsMatrix(this.selectedInstitution.id).subscribe({
      next: () => {
        this.provisionnantSalonsMatrix = false;
        this.institutionService.getById(this.selectedInstitution!.id!).subscribe(inst => {
          this.selectedInstitution = inst;
        });
        this.showSuccess("Salons Matrix activés — le pont les crée côté serveur sous quelques dizaines de secondes.");
      },
      error: () => { this.provisionnantSalonsMatrix = false; this.showError("Erreur lors de l'activation des salons Matrix."); },
    });
  }

  chargerMessagesSalonInstitution = (type: 'PERMANENTS' | 'BENEVOLES') =>
    () => this.institutionService.getSalonMatrixMessages(this.selectedInstitution!.id!, type);

  envoyerMessageSalonInstitution = (type: 'PERMANENTS' | 'BENEVOLES') =>
    (texte: string, _urgent: boolean = false) => this.institutionService.envoyerMessageSalonMatrix(this.selectedInstitution!.id!, type, texte);

  private buildForms(): void {
    this.institutionForm = this.fb.group({
      nom: ['', [Validators.required, Validators.minLength(2)]],
      type: [null, Validators.required],
      description: [''],
      telephone: [''],
      email: ['', Validators.email],
      adresse: [''],
      commune_code: [null],
      commune_nom: [null],
      commune_code_postal: [null],
      actif: [true],
    });

    this.typeForm = this.fb.group({
      code: ['', Validators.required],
      libelle: ['', Validators.required],
      description: [''],
      actif: [true],
    });

    this.roleForm = this.fb.group({
      code: ['', Validators.required],
      libelle: ['', Validators.required],
      description: [''],
      actif: [true],
    });

    this.alerteSismiqueForm = this.fb.group({
      actif: [false],
      rayon_km: [100, [Validators.required, Validators.min(1)]],
      magnitude_min: [3.5, [Validators.required, Validators.min(0)]],
    });

    this.contactForm = this.fb.group({
      utilisateur: [null, Validators.required],
      fonction: ['', Validators.required],
      contact_principal: [false],
      // Facultatifs : créent aussi une affectation rôle/thème.
      role: [null],
      competence: [null],
      // Zone couverte par ce contact (préparation PCS/PICS).
      zone: [null],
    });

    this.domaineForm = this.fb.group({
      domaine: ['', Validators.required],
      valide: [true],
    });

    this.regulateurForm = this.fb.group({
      utilisateur: [null, Validators.required],
      role: [null, Validators.required],
      competence: [null],
      zone: [null],
      responsabilite: [''],
      actif: [true],
    });
  }

  private loadAll(): void {
    this.isLoading = true;
    forkJoin({
      institutions: this.institutionService.getAll(),
      types: this.institutionTypeService.getAll(),
      roles: this.roleOperationnelService.getAll(),
      users: this.userService.getAll(),
      // Au chargement, seulement les miens : ceux d'une institution consultée sont
      // demandés à l'ouverture de son détail (voir openDetail).
      contacts: this.contactService.getAll(),
      domaines: this.domaineService.getAll(),
      competences: this.competenceService.getAll(),
      affectationsRoles: this.affectationRoleService.getAll(),
    }).subscribe({
      next: ({ institutions, types, roles, users, contacts, domaines, competences, affectationsRoles }) => {
        this.institutions = institutions;
        this.types = types;
        this.roles = roles;
        this.users = users;
        this.contacts = contacts;
        this.domaines = domaines;
        this.competences = competences;
        this.affectationsRoles = affectationsRoles;
        this.isLoading = false;
      },
      error: () => {
        this.showError('Impossible de charger les données.');
        this.isLoading = false;
      },
    });
  }

  reloadInstitutions(): void { this.institutionService.getAll().subscribe(data => this.institutions = data); }
  reloadTypes(): void { this.institutionTypeService.getAll().subscribe(data => this.types = data); }
  reloadRoles(): void { this.roleOperationnelService.getAll().subscribe(data => this.roles = data); }
  reloadContacts(): void {
    const id = this.selectedInstitution?.id;
    const source = id ? this.contactService.getForInstitution(id) : this.contactService.getAll();
    source.subscribe(data => this.contacts = data);
  }
  reloadDomaines(): void { this.domaineService.getAll().subscribe(data => this.domaines = data); }
  reloadAffectationsRoles(): void { this.affectationRoleService.getAll().subscribe(data => this.affectationsRoles = data); }

  // ══ Institutions — CRUD ═══════════════════════════════════════
  openCreate(): void {
    this.institutionForm.reset({ actif: true });
    this.modal = 'create';
  }

  submitCreate(): void {
    if (this.institutionForm.invalid) { this.institutionForm.markAllAsTouched(); return; }
    this.isSaving = true;
    this.institutionService.create(this.institutionForm.value).subscribe({
      next: () => { this.reloadInstitutions(); this.showSuccess('Institution créée.'); this.closeModal(); this.isSaving = false; },
      error: (err) => { this.showError('Erreur lors de la création.', err); this.isSaving = false; },
    });
  }

  openEdit(institution: Institution, e?: Event): void {
    e?.stopPropagation();
    this.selectedInstitution = institution;
    this.institutionForm.patchValue({
      nom: institution.nom,
      type: institution.type,
      description: institution.description,
      telephone: institution.telephone,
      email: institution.email,
      adresse: institution.adresse,
      commune_code: institution.commune_code,
      commune_nom: institution.commune_nom,
      commune_code_postal: institution.commune_code_postal,
      actif: institution.actif,
    });
    this.modal = 'edit';
  }

  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);

  onCommuneSelected(commune: Commune): void {
    this.institutionForm.patchValue({
      commune_code: commune.code,
      commune_nom: commune.name,
      commune_code_postal: commune.codePostal ?? null,
    });
  }

  clearCommune(): void {
    this.institutionForm.patchValue({ commune_code: null, commune_nom: null, commune_code_postal: null });
  }

  submitEdit(): void {
    if (!this.selectedInstitution?.id || this.institutionForm.invalid) { this.institutionForm.markAllAsTouched(); return; }
    this.isSaving = true;
    this.institutionService.patch(this.selectedInstitution.id, this.institutionForm.value).subscribe({
      next: () => { this.reloadInstitutions(); this.showSuccess('Institution modifiée.'); this.closeModal(); this.isSaving = false; },
      error: (err) => { this.showError('Erreur lors de la modification.', err); this.isSaving = false; },
    });
  }

  openDelete(institution: Institution, e?: Event): void {
    e?.stopPropagation();
    this.selectedInstitution = institution;
    this.modal = 'delete';
  }

  confirmDelete(): void {
    if (!this.selectedInstitution?.id) return;
    this.institutionService.delete(this.selectedInstitution.id).subscribe({
      next: () => { this.reloadInstitutions(); this.showSuccess('Institution supprimée.'); this.closeModal(); },
      error: (err) => this.showError('Erreur lors de la suppression.', err),
    });
  }

  openDetail(institution: Institution): void {
    this.selectedInstitution = institution;
    // Les contacts de CETTE institution, demandés nommément. La page tirait auparavant la
    // table entière au chargement pour n'en afficher qu'une institution à la fois — et
    // l'endpoint, ouvert à tout compte authentifié, les rendait toutes lisibles.
    this.reloadContacts();
    this.detailTab = 'contacts';
    this.showContactForm = false;
    this.showDomaineForm = false;
    this.showRegulateurForm = false;
    this.contactForm.reset({ contact_principal: false });
    this.contactUserQuery = '';
    this.domaineForm.reset({ valide: true });
    this.regulateurForm.reset({ actif: true });
    this.modal = 'detail';
    this.zones = [];
    if (institution.id) {
      this.zoneService.getAll(institution.id).subscribe(zones => this.zones = zones);
    }
    this.configAlerteSismique = null;
    this.alerteSismiqueForm.reset({ actif: false, rayon_km: 100, magnitude_min: 3.5 });
    if (institution.id) {
      this.configurationAlerteSismiqueService.getForInstitution(institution.id).subscribe(configs => {
        if (configs.length > 0) {
          this.configAlerteSismique = configs[0];
          this.alerteSismiqueForm.patchValue(configs[0]);
        }
      });
    }
    this.chargerInterlocuteursPCS();
    this.chargerRisquesCommunaux();
    this.suggestionsGeorisques = [];
    this.suggestionsGeorisquesDateMaj = null;
    this.suggestionsGeorisquesChargees = false;
    this.suggestionsGeorisquesErreur = '';
  }

  // ══ Catalogue de risques majeurs (détail institution) ═══════════════════
  risquesCommunaux: RisqueCommunal[] = [];
  editionRisqueId: string | null = null;
  editionRisque: Partial<RisqueCommunal> = {};
  savingRisqueId: string | null = null;

  private chargerRisquesCommunaux(): void {
    this.risquesCommunaux = [];
    if (!this.selectedInstitution?.id) return;
    this.risqueCommunalService.getForInstitution(this.selectedInstitution.id).subscribe(
      (liste) => (this.risquesCommunaux = liste),
    );
  }

  /** Cherche un type de risque existant ou en crée un (catalogue extensible, RisqueMajeurType). */
  risqueSearchFn = (q: string) => this.risqueMajeurTypeService.search(q);
  risqueCreateLabelFn = (value: string) => `Créer « ${value} » comme nouveau type de risque`;
  risqueCreateFn = (nom: string) => this.risqueMajeurTypeService.create({ nom });

  onRisqueSelected(item: RisqueMajeurType): void {
    if (!this.selectedInstitution?.id) return;
    if (this.risquesCommunaux.some(r => r.risque_type === item.id)) return;
    this.risqueCommunalService.create({ institution: this.selectedInstitution.id, risque_type: item.id }).subscribe(() => this.chargerRisquesCommunaux());
  }

  // ══ Suggestions Géorisques (détail institution) ═══════════════════════
  suggestionsGeorisques: SuggestionGeorisques[] = [];
  suggestionsGeorisquesDateMaj: string | null = null;
  suggestionsGeorisquesEnCours = false;
  suggestionsGeorisquesChargees = false;
  suggestionsGeorisquesErreur = '';
  acceptationSuggestionEnCours: string | null = null;

  chargerSuggestionsGeorisques(force = false): void {
    if (!this.selectedInstitution?.id) return;
    this.suggestionsGeorisquesEnCours = true;
    this.suggestionsGeorisquesErreur = '';
    this.risqueCommunalService.suggestionsGeorisques(this.selectedInstitution.id, force).subscribe({
      next: ({ suggestions, date_maj }: { suggestions: SuggestionGeorisques[]; date_maj: string | null }) => {
        this.suggestionsGeorisques = suggestions;
        this.suggestionsGeorisquesDateMaj = date_maj;
        this.suggestionsGeorisquesChargees = true;
        this.suggestionsGeorisquesEnCours = false;
      },
      error: (err: any) => {
        this.suggestionsGeorisquesErreur = err?.error?.error || "Impossible de consulter Géorisques pour cette commune.";
        this.suggestionsGeorisquesChargees = true;
        this.suggestionsGeorisquesEnCours = false;
      },
    });
  }

  /** Réutilise ou crée le type de risque (dédoublonné par TagLikeViewSetMixin), puis le déclare. */
  accepterSuggestion(suggestion: SuggestionGeorisques): void {
    if (!this.selectedInstitution?.id || suggestion.deja_declare) return;
    this.acceptationSuggestionEnCours = suggestion.num_risque;
    this.risqueMajeurTypeService.create({ nom: suggestion.libelle }).subscribe({
      next: (type) => {
        this.risqueCommunalService.create({ institution: this.selectedInstitution!.id, risque_type: type.id }).subscribe({
          next: () => {
            suggestion.deja_declare = true;
            this.acceptationSuggestionEnCours = null;
            this.chargerRisquesCommunaux();
          },
          error: () => { this.acceptationSuggestionEnCours = null; },
        });
      },
      error: () => { this.acceptationSuggestionEnCours = null; },
    });
  }

  retirerRisqueCommunal(item: RisqueCommunal): void {
    if (!confirm(`Retirer le risque « ${item.risque_nom} » de cette commune ?`)) return;
    this.risqueCommunalService.delete(item.id).subscribe(() => this.chargerRisquesCommunaux());
  }

  commencerEditionRisque(item: RisqueCommunal): void {
    this.editionRisqueId = item.id;
    this.editionRisque = { ...item };
  }

  annulerEditionRisque(): void {
    this.editionRisqueId = null;
    this.editionRisque = {};
  }

  enregistrerRisqueCommunal(): void {
    if (!this.editionRisqueId) return;
    this.savingRisqueId = this.editionRisqueId;
    const { etat_des_lieux, enjeux } = this.editionRisque;
    this.risqueCommunalService.update(this.editionRisqueId, { etat_des_lieux, enjeux }).subscribe({
      next: () => { this.savingRisqueId = null; this.annulerEditionRisque(); this.chargerRisquesCommunaux(); },
      error: () => { this.savingRisqueId = null; },
    });
  }

  // ══ Annuaire d'alerte PCS/PICS (détail institution) ═══════════════════
  interlocuteursPCS: InterlocuteurAlertePCS[] = [];
  editionInterlocuteurId: string | null = null;
  editionInterlocuteur: Partial<InterlocuteurAlertePCS> = {};
  savingInterlocuteurId: string | null = null;

  private chargerInterlocuteursPCS(): void {
    this.interlocuteursPCS = [];
    if (!this.selectedInstitution?.id) return;
    this.interlocuteurAlertePCSService.getForInstitution(this.selectedInstitution.id).subscribe(
      (liste) => (this.interlocuteursPCS = liste),
    );
  }

  /** Utilisateurs de l'institution, rattachables à un interlocuteur pour l'envoi Matrix. */
  get utilisateursCandidatsPCS(): User[] {
    if (!this.selectedInstitution?.id) return [];
    const ids = this.contacts.filter(c => c.institution === this.selectedInstitution!.id).map(c => c.utilisateur);
    return this.users.filter(u => ids.includes(u.id));
  }

  get interlocuteursPCSParCategorie(): { categorie: CategorieInterlocuteurPCS; libelle: string; items: InterlocuteurAlertePCS[] }[] {
    return this.categoriesInterlocuteurPCS
      .map(c => ({
        categorie: c.value, libelle: c.label,
        items: this.interlocuteursPCS.filter(i => i.categorie === c.value),
      }))
      .filter(g => g.items.length > 0);
  }

  /** Recherche un interlocuteur déjà déclaré (y compris par une autre commune). */
  interlocuteurPCSSearchFn = (q: string) => this.interlocuteurAlertePCSService.search(q);

  /** Création rapide en mode TELEPHONE, complétée ensuite ; le backend rattache l'institution. */
  interlocuteurPCSCreateLabelFn = (value: string) => `Créer « ${value} » comme nouveau contact`;

  modeAlertePCSLabel(mode: ModeAlertePCS): string {
    return this.modesAlertePCS.find(m => m.value === mode)?.label ?? mode;
  }

  interlocuteurPCSCreateFn = (organisme: string) =>
    this.interlocuteurAlertePCSService.create({ organisme, nom: organisme, categorie: 'AUTRE', mode_alerte: 'TELEPHONE' });

  onInterlocuteurPCSSelected(item: InterlocuteurAlertePCS): void {
    // Rattache toujours (no-op si déjà fait) : cas d'un résultat de recherche non rattaché.
    this.interlocuteurAlertePCSService.rattacher(item.id).subscribe(() => this.chargerInterlocuteursPCS());
  }

  retirerInterlocuteurPCS(item: InterlocuteurAlertePCS): void {
    if (!confirm(`Retirer « ${item.nom} » de l'annuaire de cette commune ? (reste visible pour les autres communes qui l'utilisent déjà)`)) return;
    this.interlocuteurAlertePCSService.detacher(item.id).subscribe(() => this.chargerInterlocuteursPCS());
  }

  commencerEditionInterlocuteurPCS(item: InterlocuteurAlertePCS): void {
    this.editionInterlocuteurId = item.id;
    this.editionInterlocuteur = { ...item };
  }

  annulerEditionInterlocuteurPCS(): void {
    this.editionInterlocuteurId = null;
    this.editionInterlocuteur = {};
  }

  enregistrerInterlocuteurPCS(): void {
    if (!this.editionInterlocuteurId) return;
    this.savingInterlocuteurId = this.editionInterlocuteurId;
    const { nom, organisme, categorie, email, telephone, notes, mode_alerte, actif, utilisateur } = this.editionInterlocuteur;
    this.interlocuteurAlertePCSService.update(this.editionInterlocuteurId, {
      nom, organisme, categorie, email, telephone, notes, mode_alerte, actif, utilisateur,
    }).subscribe({
      next: () => { this.savingInterlocuteurId = null; this.annulerEditionInterlocuteurPCS(); this.chargerInterlocuteursPCS(); },
      error: () => { this.savingInterlocuteurId = null; },
    });
  }

  // ══ Alertes sismiques (détail institution) ═══════════════════
  configAlerteSismique: ConfigurationAlerteSismique | null = null;
  savingAlerteSismique = false;
  alerteSismiqueForm!: FormGroup;

  submitAlerteSismique(): void {
    if (!this.selectedInstitution?.id || this.alerteSismiqueForm.invalid) {
      this.alerteSismiqueForm.markAllAsTouched();
      return;
    }
    this.savingAlerteSismique = true;
    const brut = this.alerteSismiqueForm.getRawValue();
    const valeurs = { actif: !!brut.actif, rayon_km: Number(brut.rayon_km), magnitude_min: Number(brut.magnitude_min) };
    const request$ = this.configAlerteSismique
      ? this.configurationAlerteSismiqueService.update(this.configAlerteSismique.id, valeurs)
      : this.configurationAlerteSismiqueService.create({ institution: this.selectedInstitution.id, ...valeurs });
    request$.subscribe({
      next: (config) => {
        this.configAlerteSismique = config;
        this.savingAlerteSismique = false;
      },
      error: () => { this.savingAlerteSismique = false; },
    });
  }

  closeModal(): void {
    this.modal = 'none';
    this.selectedInstitution = null;
  }

  // ══ Contacts (détail institution) ═════════════════════════════
  get institutionContacts(): ContactInstitution[] {
    if (!this.selectedInstitution?.id) return [];
    return this.contacts.filter(c => c.institution === this.selectedInstitution!.id);
  }

  submitContact(): void {
    if (!this.selectedInstitution?.id || this.contactForm.invalid) { this.contactForm.markAllAsTouched(); return; }
    const institution = this.selectedInstitution.id;
    const { utilisateur, fonction, contact_principal, role, competence, zone } = this.contactForm.value;

    this.contactService.create({ utilisateur, fonction, contact_principal, institution, actif: true, zone }).subscribe({
      next: () => {
        this.reloadContacts();

        // Rôle facultatif, créé dans la foulée.
        if (role) {
          this.affectationRoleService.create({ utilisateur, role, competence, institution, actif: true }).subscribe({
            next: () => {
              this.reloadAffectationsRoles();
              this.showSuccess('Contact et affectation ajoutés.');
            },
            error: (err) => this.showError("Contact ajouté, mais l'affectation du rôle a échoué.", err),
          });
        } else {
          this.showSuccess('Contact ajouté.');
        }

        this.contactForm.reset({ contact_principal: false });
        this.contactUserQuery = '';
        this.showContactForm = false;
      },
      error: (err) => this.showError("Erreur lors de l'ajout du contact.", err),
    });
  }

  /** PUT : institution/utilisateur requis en plus de `zone`. */
  setContactZone(contact: ContactInstitution, zoneId: string | null): void {
    this.contactService.update(contact.id!, {
      utilisateur: contact.utilisateur, institution: contact.institution,
      fonction: contact.fonction, contact_principal: contact.contact_principal,
      actif: contact.actif, zone: zoneId,
    }).subscribe({
      next: (updated) => {
        const idx = this.contacts.findIndex(c => c.id === updated.id);
        if (idx !== -1) this.contacts[idx] = updated;
      },
      error: (err) => this.showError('Impossible de mettre à jour la zone.', err),
    });
  }

  onContactCompetenceSearchSelected(item: Competence): void {
    if (!this.competences.find(c => c.id === item.id)) {
      this.competences = [...this.competences, item];
    }
    this.contactForm.get('competence')?.setValue(item.id);
  }

  isContactFieldInvalid(field: string): boolean {
    const control = this.contactForm.get(field);
    return !!control && control.invalid && control.touched;
  }

  get contactUserResults(): User[] {
    const q = this.contactUserQuery.trim().toLowerCase();
    if (!q) return [];
    return this.users.filter(u =>
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q)
      || u.username.toLowerCase().includes(q)
    );
  }

  selectContactUser(user: User): void {
    this.contactForm.get('utilisateur')?.setValue(user.id);
    this.contactUserQuery = `${user.first_name} ${user.last_name}`.trim() || user.username;
    this.showContactUserResults = false;
  }

  onContactUserQueryChange(): void {
    // Retaper invalide la sélection : il faut re-choisir un résultat.
    this.contactForm.get('utilisateur')?.setValue(null);
    this.showContactUserResults = true;
  }

  hideContactUserResultsDelayed(): void {
    // Délai pour que le (click) sur un résultat passe avant la fermeture au blur.
    setTimeout(() => this.showContactUserResults = false, 150);
  }

  deleteContact(contact: ContactInstitution): void {
    if (!contact.id) return;
    this.contactService.delete(contact.id).subscribe({
      next: () => { this.reloadContacts(); this.showSuccess('Contact supprimé.'); },
      error: (err) => this.showError('Erreur lors de la suppression du contact.', err),
    });
  }

  userName(id: string): string {
    const u = this.users.find(user => user.id === id);
    return u ? (`${u.first_name} ${u.last_name}`.trim() || u.username) : id.slice(0, 8);
  }

  // ══ Domaines email (détail institution) ═══════════════════════
  get institutionDomaines(): InstitutionDomaine[] {
    if (!this.selectedInstitution?.id) return [];
    return this.domaines.filter(d => d.institution === this.selectedInstitution!.id);
  }

  submitDomaine(): void {
    if (!this.selectedInstitution?.id || this.domaineForm.invalid) { this.domaineForm.markAllAsTouched(); return; }
    const payload = { ...this.domaineForm.value, institution: this.selectedInstitution.id };
    this.domaineService.create(payload).subscribe({
      next: () => {
        this.reloadDomaines();
        this.showSuccess('Domaine ajouté.');
        this.domaineForm.reset({ valide: true });
        this.showDomaineForm = false;
      },
      error: (err) => this.showError("Erreur lors de l'ajout du domaine.", err),
    });
  }

  deleteDomaine(domaine: InstitutionDomaine): void {
    if (domaine.id === undefined) return;
    this.domaineService.delete(domaine.id).subscribe({
      next: () => { this.reloadDomaines(); this.showSuccess('Domaine supprimé.'); },
      error: (err) => this.showError('Erreur lors de la suppression du domaine.', err),
    });
  }

  // ══ Régulateurs / responsables — thèmes (détail institution) ═══
  get institutionAffectationsRoles(): AffectationRoleOperationnel[] {
    if (!this.selectedInstitution?.id) return [];
    return this.affectationsRoles.filter(a => a.institution === this.selectedInstitution!.id);
  }

  submitRegulateur(): void {
    if (!this.selectedInstitution?.id || this.regulateurForm.invalid) { this.regulateurForm.markAllAsTouched(); return; }
    const payload = { ...this.regulateurForm.value, institution: this.selectedInstitution.id };
    this.affectationRoleService.create(payload).subscribe({
      next: () => {
        this.reloadAffectationsRoles();
        this.showSuccess('Affectation ajoutée.');
        this.regulateurForm.reset({ actif: true });
        this.showRegulateurForm = false;
      },
      error: (err) => this.showError("Erreur lors de l'affectation.", err),
    });
  }

  deleteAffectationRole(affectation: AffectationRoleOperationnel): void {
    if (!affectation.id) return;
    this.affectationRoleService.delete(affectation.id).subscribe({
      next: () => { this.reloadAffectationsRoles(); this.showSuccess('Affectation supprimée.'); },
      error: (err) => this.showError("Erreur lors de la suppression de l'affectation.", err),
    });
  }

  roleLabel(id: string): string {
    return this.roles.find(r => r.id === id)?.libelle ?? id.slice(0, 8);
  }

  competenceLabel(id: string | null): string {
    if (!id) return 'Aucun thème précisé';
    return this.competences.find(c => c.id === id)?.nom ?? id.slice(0, 8);
  }

  zoneLabel(id: string | null): string {
    if (!id) return '—';
    return this.zones.find(z => z.id === id)?.nom ?? id.slice(0, 8);
  }

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  onRegulateurCompetenceSearchSelected(item: Competence): void {
    if (!this.competences.find(c => c.id === item.id)) {
      this.competences = [...this.competences, item];
    }
    this.regulateurForm.get('competence')?.setValue(item.id);
  }

  // ══ Types d'institution (référentiel) ═════════════════════════
  openCreateType(): void {
    this.typeForm.reset({ actif: true });
    this.typeModal = 'create';
  }

  submitCreateType(): void {
    if (this.typeForm.invalid) { this.typeForm.markAllAsTouched(); return; }
    this.institutionTypeService.create(this.typeForm.value).subscribe({
      next: () => { this.reloadTypes(); this.showSuccess("Type d'institution créé."); this.closeTypeModal(); },
      error: (err) => this.showError('Erreur lors de la création.', err),
    });
  }

  openEditType(type: InstitutionType, e?: Event): void {
    e?.stopPropagation();
    this.selectedType = type;
    this.typeForm.patchValue(type);
    this.typeModal = 'edit';
  }

  submitEditType(): void {
    if (!this.selectedType?.id || this.typeForm.invalid) { this.typeForm.markAllAsTouched(); return; }
    this.institutionTypeService.update(this.selectedType.id, this.typeForm.value).subscribe({
      next: () => { this.reloadTypes(); this.showSuccess('Type modifié.'); this.closeTypeModal(); },
      error: (err) => this.showError('Erreur lors de la modification.', err),
    });
  }

  openDeleteType(type: InstitutionType, e?: Event): void {
    e?.stopPropagation();
    this.selectedType = type;
    this.typeModal = 'delete';
  }

  confirmDeleteType(): void {
    if (!this.selectedType?.id) return;
    this.institutionTypeService.delete(this.selectedType.id).subscribe({
      next: () => { this.reloadTypes(); this.showSuccess('Type supprimé.'); this.closeTypeModal(); },
      error: (err) => this.showError('Erreur lors de la suppression (probablement encore utilisé par une institution).', err),
    });
  }

  closeTypeModal(): void { this.typeModal = 'none'; this.selectedType = null; }

  // ══ Rôles opérationnels (référentiel) ═════════════════════════
  openCreateRole(): void {
    this.roleForm.reset({ actif: true });
    this.roleModal = 'create';
  }

  submitCreateRole(): void {
    if (this.roleForm.invalid) { this.roleForm.markAllAsTouched(); return; }
    this.roleOperationnelService.create(this.roleForm.value).subscribe({
      next: () => { this.reloadRoles(); this.showSuccess('Rôle opérationnel créé.'); this.closeRoleModal(); },
      error: (err) => this.showError('Erreur lors de la création.', err),
    });
  }

  openEditRole(role: RoleOperationnel, e?: Event): void {
    e?.stopPropagation();
    this.selectedRole = role;
    this.roleForm.patchValue(role);
    this.roleModal = 'edit';
  }

  submitEditRole(): void {
    if (!this.selectedRole?.id || this.roleForm.invalid) { this.roleForm.markAllAsTouched(); return; }
    this.roleOperationnelService.update(this.selectedRole.id, this.roleForm.value).subscribe({
      next: () => { this.reloadRoles(); this.showSuccess('Rôle modifié.'); this.closeRoleModal(); },
      error: (err) => this.showError('Erreur lors de la modification.', err),
    });
  }

  openDeleteRole(role: RoleOperationnel, e?: Event): void {
    e?.stopPropagation();
    this.selectedRole = role;
    this.roleModal = 'delete';
  }

  confirmDeleteRole(): void {
    if (!this.selectedRole?.id) return;
    this.roleOperationnelService.delete(this.selectedRole.id).subscribe({
      next: () => { this.reloadRoles(); this.showSuccess('Rôle supprimé.'); this.closeRoleModal(); },
      error: (err) => this.showError('Erreur lors de la suppression.', err),
    });
  }

  closeRoleModal(): void { this.roleModal = 'none'; this.selectedRole = null; }

  // ══ Helpers ════════════════════════════════════════════════════
  get filteredInstitutions(): Institution[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.institutions;
    return this.institutions.filter(i => i.nom.toLowerCase().includes(q));
  }

  typeLabel(institution: Institution): string {
    return institution.type_libelle ?? this.types.find(t => t.id === institution.type)?.libelle ?? '—';
  }

  private showSuccess(msg: string): void {
    this.successMessage = msg;
    setTimeout(() => this.successMessage = '', 3000);
  }

  private showError(fallback: string, err?: unknown): void {
    this.errorMessage = this.extractErrorMessage(err) ?? fallback;
    setTimeout(() => this.errorMessage = '', 5000);
  }

  // Affiche le détail exact renvoyé par le backend plutôt qu'un message deviné.
  private extractErrorMessage(err: unknown): string | null {
    const body = (err as any)?.error;
    if (!body) return null;
    if (typeof body === 'string') return body;
    if (typeof body.detail === 'string') return body.detail;
    const messages = Object.values(body)
      .map(v => Array.isArray(v) ? v.join(' ') : v)
      .filter((v): v is string => typeof v === 'string' && v.length > 0);
    return messages.length ? messages.join(' ') : null;
  }

  fmtDate(d?: string): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
}
