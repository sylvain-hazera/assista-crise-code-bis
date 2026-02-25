import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Utilisateur } from '../../shared/models/user.model';
import { AuthService } from '../../auth/services/auth.service';
import { RequestService } from '../../services/request.service';
import { OfferService } from '../../services/offer.service';
import { CrisisService } from '../../services/crisis.service';
import { Demande } from '../../shared/models/request.model';
import { Offre } from '../../shared/models/offer.model';
import { Crise } from '../../shared/models/crisis.model';
import { Statut } from '../../shared/models/status.model';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './settings.component.html',
  styleUrls: ['./settings.component.scss']
})

export class SettingsComponent implements OnInit {
  currentUser: Utilisateur | null = null;
  profileForm!: FormGroup;
  passwordForm!: FormGroup;

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

  activeTab: 'profile' | 'password' | 'offer' | 'request' | 'crisis' = 'profile';

  allCrisis:  Crise[]   = [];  filteredCrisis:  Crise[]   = [];  isLoadingCrisis  = false;
  allOffers:  Offre[]   = [];  filteredOffers:  Offre[]   = [];  isLoadingOffers  = false;
  allRequests: Demande[] = []; filteredRequests: Demande[] = []; isLoadingRequests = false;

  showDetailCrisis = false;  showDetailOffer  = false;  showDetailRequest = false;
  selectedReport: Crise | Offre | Demande | null = null;

  constructor(
    private fb: FormBuilder,
    private authService:    AuthService,
    private criseService:   CrisisService,
    private demandeService: RequestService,
    private offreService:   OfferService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    // if (!this.currentUser) { this.router.navigate(['/login']); return; }
    this.initForms();
    this.loadAll();
  }

  private initForms(): void {
    this.profileForm = this.fb.group({
      // Champs Django : first_name, last_name, email, telephone_utilisateur
      username:                [this.currentUser?.username,  [Validators.required, Validators.minLength(2)]],
      last_name:               [this.currentUser?.last_name,  [Validators.required, Validators.minLength(2)]],
      first_name:              [this.currentUser?.first_name  ?? ''],
      email:                   [this.currentUser?.email,       [Validators.required, Validators.email]],
      telephone_utilisateur:   [this.currentUser?.telephone_utilisateur ?? '']
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

  deleteAccount() {
    throw new Error('Method not implemented.');
  }

  // ── Filtres ──────────────────────────────────────────────────

  onFilterCrisis(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredCrisis = this.allCrisis.filter(c =>
      c.nom.toLowerCase().includes(term)
    );
  }

  onFilterOffer(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredOffers = this.allOffers.filter(o =>
      o.titre.toLowerCase().includes(term) ||
      o.statut.toLowerCase().includes(term)
    );
  }

  onFilterNeed(event: Event): void {
    const term = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredRequests = this.allRequests.filter(d =>
      d.titre.toLowerCase().includes(term) ||
      d.statut.toLowerCase().includes(term)
    );
  }

  // ── Suppression ──────────────────────────────────────────────

  deleteCrisis(crise: Crise): void {
    if (!confirm(`Supprimer "${crise.nom}" ?`)) return;
    this.criseService.delete(crise.id).subscribe({
      next:  () => { this.successMessage = 'Crise supprimée'; this.loadCrises(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  deleteOffer(offre: Offre): void {
    if (!confirm(`Supprimer "${offre.titre}" ?`)) return;
    this.offreService.delete(offre.id).subscribe({
      next:  () => { this.successMessage = 'Offre supprimée'; this.loadOffres(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  deleteRequest(demande: Demande): void {
    if (!confirm(`Supprimer "${demande.titre}" ?`)) return;
    this.demandeService.delete(demande.id).subscribe({
      next:  () => { this.successMessage = 'Demande supprimée'; this.loadDemandes(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
  }

  // ── Édition ──────────────────────────────────────────────────

  editCrisis(c: Crise):     void { this.router.navigate(['/user/crise/edit',   c.id]); }

  editOffer(offer: Offre): void { 
    if(offer.statut == Statut.DISPONIBLE) {
      offer.statut = Statut.INDISPONIBLE;
    } else {
      offer.statut = Statut.DISPONIBLE;
    }
    offer.statut = Statut.INDISPONIBLE;
    this.offreService.update(offer.id, offer).subscribe({
      next:  () => { this.successMessage = 'Offre mise à jour'; this.loadOffres(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    })
    // this.router.navigate(['/user/offre/edit',   o.id]); 
  }

  editRequest(demande: Demande): void { 
    if(demande.statut == Statut.TRAITEE) {
      demande.statut = Statut.NON_TRAITEE;
    } else {
      demande.statut = Statut.TRAITEE;
    }
    this.demandeService.update(demande.id, demande).subscribe({
      next:  () => { this.successMessage = 'Demande mise à jour'; this.loadDemandes(); },
      error: err => (this.errorMessage = err.error?.detail ?? 'Erreur')
    });
    // this.router.navigate(['/user/demande/edit', d.id]); 
  }

  // ----- View ----------------------------------------------------------------
  viewCrisis(crisis: Crise): void {
    this.selectedReport = crisis;

    this.showDetailCrisis = true;
    this.showDetailOffer = false;
    this.showDetailRequest = false;
  }

  viewOffer(offre: Offre): void {
    this.selectedReport = offre;

    this.showDetailOffer = true;
    this.showDetailCrisis = false;
    this.showDetailRequest = false;
  }

  viewRequest(demande: Demande): void {
    this.selectedReport = demande;

    this.showDetailRequest = true;
    this.showDetailOffer = false;
    this.showDetailCrisis = false;
  }


  // ── Helpers ──────────────────────────────────────────────────

  /** Libellé lisible pour les statuts Django */
  getStatusLabel(statut: string): string {
    const labels: Record<string, string> = {
      [Statut.NON_TRAITEE]:  'Non traitée',
      [Statut.EN_COURS]:     'En cours',
      [Statut.TRAITEE]:      'Traitée',
      [Statut.DISPONIBLE]:   'Disponible',
      [Statut.INDISPONIBLE]: 'Indisponible'
    };
    return labels[statut] ?? statut;
  }

  /** Affiche les coordonnées extraites depuis le GeoPoint Django */
  getLocation(lat?: number, lng?: number): string {
    if (lat == null || lng == null) return '—';
    return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  }

  closeDetail(): void {
    this.showDetailCrisis = false;
    this.showDetailOffer = false;
    this.showDetailRequest = false;
    this.selectedReport = null;
  }

  isCrise(r: Crise | Offre | Demande): r is Crise {
    return 'nom' in r && 'validateur' in r;
  }

  isOffre(r: Crise | Offre | Demande): r is Offre {
    return 'prenom_offre' in r;
  }

  isDemande(r: Crise | Offre | Demande): r is Demande {
    return 'prenom_demande' in r;
  }
  get isAdmin(): boolean { return this.authService.isAdmin(); }
  get isIndividual(): boolean { return this.currentUser?.type === 'UTIL_SIMPLE'; }

  private clearMessages(): void { this.successMessage = ''; this.errorMessage = ''; }
}