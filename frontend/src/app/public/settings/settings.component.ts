import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { User } from '../../shared/models/user.model';
import { AuthService } from '../../auth/services/auth.service';
import { RequestService } from '../../services/request.service';
import { OfferService } from '../../services/offer.service';
import { CrisisService } from '../../services/crisis.service';
import { InformationService } from '../../services/information.service';
import { DeclarationSecuriteService } from '../../services/declaration-securite.service';
import { DossierService } from '../../services/dossier.service';
import { Request } from '../../shared/models/request.model';
import { Offer } from '../../shared/models/offer.model';
import { Crisis } from '../../shared/models/crisis.model';
import { Information } from '../../shared/models/information.model';
import { DeclarationSecurite } from '../../shared/models/declaration-securite.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Status } from '../../shared/models/status.model';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
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

  activeTab: 'profile' | 'password' | 'offer' | 'request' | 'crisis' | 'declaration' | 'information' | 'dossier' = 'profile';

  allCrisis:  Crisis[]   = [];  filteredCrisis:  Crisis[]   = [];  isLoadingCrisis  = false;
  allOffers:  Offer[]   = [];  filteredOffers:  Offer[]   = [];  isLoadingOffers  = false;
  allRequests: Request[] = []; filteredRequests: Request[] = []; isLoadingRequests = false;
  allDeclarations: DeclarationSecurite[] = []; filteredDeclarations: DeclarationSecurite[] = []; isLoadingDeclarations = false;
  allInformations: Information[] = []; filteredInformations: Information[] = []; isLoadingInformations = false;
  allDossiers: Dossier[] = []; filteredDossiers: Dossier[] = []; isLoadingDossiers = false;

  showDetailCrisis = false;  showDetailOffer  = false;  showDetailRequest = false;
  showDetailInformation = false; showDetailDeclaration = false;
  selectedReport: Crisis | Offer | Request | Information | DeclarationSecurite | null = null;

  constructor(
    private fb: FormBuilder,
    private authService:    AuthService,
    private criseService:   CrisisService,
    private demandeService: RequestService,
    private offreService:   OfferService,
    private informationService: InformationService,
    private declarationService: DeclarationSecuriteService,
    private dossierService: DossierService,
    private router: Router,
    private route: ActivatedRoute,
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.previewUrl = this.currentUser?.photo ?? null;
    this.initForms();
    this.loadAll();

    // Abonnement réactif (pas juste route.snapshot, lu une seule fois) : les liens rapides de
    // l'en-tête (`quick-link`) pointent tous vers /settings avec un `tab` différent — Angular
    // réutilise la même instance de ce composant d'un tab à l'autre puisque la route ne change
    // pas, donc ngOnInit ne se relance jamais. Sans cet abonnement, cliquer sur ces liens
    // depuis l'écran /settings lui-même ne changeait jamais l'onglet affiché.
    const validTabs: (typeof this.activeTab)[] = ['profile', 'password', 'offer', 'request', 'crisis', 'declaration', 'information', 'dossier'];
    this.route.queryParamMap.subscribe(params => {
      const requestedTab = params.get('tab');
      if (requestedTab && (validTabs as string[]).includes(requestedTab)) {
        this.activeTab = requestedTab as typeof this.activeTab;
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
    // Toutes les données de l'utilisateur connecté
    this.loadCrises();
    this.loadOffres();
    this.loadDemandes();
    this.loadDeclarations();
    this.loadInformations();
    this.loadDossiers();
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

  setActiveTab(tab: typeof this.activeTab): void {
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
    // this.authService.delete().subscribe({
    //   next: () => {
    //     this.successMessage = 'Compte supprimé avec succès';
    //     this.authService.logout();
    //     this.router.navigate(['/login']);
    //   },
    //   error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    // });
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
    // this.router.navigate(['/user/offre/edit',   o.id]); 
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
    // this.router.navigate(['/user/demande/edit', d.id]); 
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
}
