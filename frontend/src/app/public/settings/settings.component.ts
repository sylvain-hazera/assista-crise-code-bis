import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { User } from '../../shared/models/user.model';
import { AuthService } from '../../auth/services/auth.service';
import { RequestService } from '../../services/request.service';
import { OfferService } from '../../services/offer.service';
import { CrisisService } from '../../services/crisis.service';
import { Request } from '../../shared/models/request.model';
import { Offer } from '../../shared/models/offer.model';
import { Crisis } from '../../shared/models/crisis.model';

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
  
  isUpdatingProfile = false;
  isChangingPassword = false;
  
  successMessage = '';
  errorMessage = '';

  activeTab: 'profile' | 'password' | 'offer' | 'need' | 'crisis' = 'profile';

  // Data arrays
  allCrises: Crisis[] = [];
  allOffers: Offer[] = [];
  allNeeds: Request[] = [];

  // Filtered arrays
  filteredCrises: Crisis[] = [];
  filteredOffers: Offer[] = [];
  filteredNeeds: Request[] = [];

  // Loading states
  isLoadingCrises = false;
  isLoadingOffers = false;
  isLoadingNeeds = false;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private requestService: RequestService,
    private offerService: OfferService,
    private crisisService: CrisisService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();

    if (!this.currentUser) {
      this.router.navigate(['/login']);
      return;
    }

    this.initForms();
    this.loadUserData();
  }

  private initForms(): void {
    // Formulaire de profil
    this.profileForm = this.fb.group({
      lastName: [this.currentUser?.lastName, [Validators.required, Validators.minLength(2)]],
      firstName: [this.currentUser?.firstName || ''],
      pseudo: [this.currentUser?.pseudo || ''],
      email: [this.currentUser?.email, [Validators.required, Validators.email]],
      phone: [this.currentUser?.phone, [Validators.required]],
      postalCode: [this.currentUser?.postalCode, [Validators.required, Validators.pattern(/^\d{5}$/)]]
    });

    // Désactiver les champs selon le type d'utilisateur
    if (this.authService.isAdmin()) {
      this.profileForm.get('firstName')?.disable();
      this.profileForm.get('pseudo')?.disable();
    }

    // Formulaire de changement de mot de passe
    this.passwordForm = this.fb.group({
      oldPassword: ['', Validators.required],
      newPassword: ['', [Validators.required, Validators.minLength(8)]],
      confirmPassword: ['', Validators.required]
    }, {
      validators: this.passwordMatchValidator
    });
  }

  private passwordMatchValidator(group: FormGroup): any {
    const newPassword = group.get('newPassword')?.value;
    const confirmPassword = group.get('confirmPassword')?.value;
    return newPassword === confirmPassword ? null : { passwordMismatch: true };
  }

  private loadUserData(): void {
    // Load data based on active tab to avoid unnecessary requests
    this.loadCrises();
    this.loadOffers();
    this.loadNeeds();
  }

  private loadCrises(): void {
    this.isLoadingCrises = true;
    this.crisisService.getMyCrisis(this.currentUser!.id!).subscribe({
      next: (crises) => {
        this.allCrises = crises;
        this.filteredCrises = crises;
        this.isLoadingCrises = false;
      },
      error: (error) => {
        console.error('Error loading crises:', error);
        this.isLoadingCrises = false;
      }
    });
  }

  private loadOffers(): void {
    this.isLoadingOffers = true;
    this.offerService.getOffers().subscribe({
      next: (offers) => {
        this.allOffers = offers;
        this.filteredOffers = offers;
        this.isLoadingOffers = false;
      },
      error: (error) => {
        console.error('Error loading offers:', error);
        this.isLoadingOffers = false;
      }
    });
  }

  private loadNeeds(): void {
    this.isLoadingNeeds = true;
    this.requestService.getRequests().subscribe({
      next: (needs) => {
        this.allNeeds = needs;
        this.filteredNeeds = needs;
        this.isLoadingNeeds = false;
      },
      error: (error) => {
        console.error('Error loading needs:', error);
        this.isLoadingNeeds = false;
      }
    });
  }

  setActiveTab(tab: 'profile' | 'password' | 'offer' | 'need' | 'crisis'): void {
    this.activeTab = tab;
    this.clearMessages();
  }

  updateProfile(): void {
    if (this.profileForm.invalid) {
      return;
    }

    this.isUpdatingProfile = true;
    this.clearMessages();

    const formData = this.profileForm.getRawValue();

    this.authService.updateProfile(formData).subscribe({
      next: (user) => {
        this.currentUser = user;
        this.successMessage = 'Profil mis à jour avec succès';
        this.isUpdatingProfile = false;
      },
      error: (error) => {
        this.errorMessage = error.message || 'Erreur lors de la mise à jour';
        this.isUpdatingProfile = false;
      }
    });
  }

  changePassword(): void {
    if (this.passwordForm.invalid) {
      return;
    }

    this.isChangingPassword = true;
    this.clearMessages();

    const { oldPassword, newPassword } = this.passwordForm.value;

    this.authService.changePassword(oldPassword, newPassword).subscribe({
      next: () => {
        this.successMessage = 'Mot de passe changé avec succès';
        this.passwordForm.reset();
        this.isChangingPassword = false;
      },
      error: (error) => {
        this.errorMessage = error.message || 'Erreur lors du changement de mot de passe';
        this.isChangingPassword = false;
      }
    });
  }

  // Filter methods
  onFilterCrisis(event: Event): void {
    const searchTerm = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredCrises = this.allCrises.filter(crisis =>
      crisis.name?.toLowerCase().includes(searchTerm) ||
      crisis.description?.toLowerCase().includes(searchTerm)
    );
  }

  onFilterOffer(event: Event): void {
    const searchTerm = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredOffers = this.allOffers.filter(offer =>
      offer.titre.toLowerCase().includes(searchTerm) 
      // offer.statut.toLowerCase().includes(searchTerm)
    );
  }

  onFilterNeed(event: Event): void {
    const searchTerm = (event.target as HTMLInputElement).value.toLowerCase();
    this.filteredNeeds = this.allNeeds.filter(need =>
      need.titre.toLowerCase().includes(searchTerm) 
      // need.statut.toLowerCase().includes(searchTerm)
    );
  }

  // Edit methods
  editCrisis(crisis: Crisis): void {
    // Navigate to edit page or open modal
    this.router.navigate(['/user/crisis/edit', crisis.id]);
  }

  editOffer(offer: Offer): void {
    this.router.navigate(['/user/offer/edit', offer.id]);
  }

  editNeed(need: Request): void {
    this.router.navigate(['/user/request/edit', need.id]);
  }

  // Delete methods
  deleteCrisis(crisis: Crisis): void {
    if (!confirm(`Êtes-vous sûr de vouloir supprimer la crise "${crisis.name}" ?`)) {
      return;
    }

    this.crisisService.deleteCrisis(crisis.id?.toString()!).subscribe({
      next: () => {
        this.successMessage = 'Crise supprimée avec succès';
        this.loadCrises();
      },
      error: (error) => {
        this.errorMessage = error.message || 'Erreur lors de la suppression';
      }
    });
  }

  deleteOffer(offer: Offer): void {
    if (!confirm(`Êtes-vous sûr de vouloir supprimer l'offre "${offer.titre}" ?`)) {
      return;
    }

    this.offerService.deleteOffer(offer.id!).subscribe({
      next: () => {
        this.successMessage = 'Offre supprimée avec succès';
        this.loadOffers();
      },
      error: (error) => {
        this.errorMessage = error.message || 'Erreur lors de la suppression';
      }
    });
  }

  deleteNeed(need: Request): void {
    if (!confirm(`Êtes-vous sûr de vouloir supprimer le besoin "${need.titre}" ?`)) {
      return;
    }

    this.requestService.deleteRequest(need.id!).subscribe({
      next: () => {
        this.successMessage = 'Besoin supprimé avec succès';
        this.loadNeeds();
      },
      error: (error) => {
        this.errorMessage = error.message || 'Erreur lors de la suppression';
      }
    });
  }

  deleteAccount(): void {
    if (!confirm('Êtes-vous sûr de vouloir supprimer votre compte ? Cette action est irréversible.')) {
      return;
    }

    // this.authService.deleteAccount().subscribe({
    //   next: () => {
    //     alert('Compte supprimé avec succès');
    //     this.router.navigate(['/']);
    //   },
    //   error: (error) => {
    //     this.errorMessage = error.message || 'Erreur lors de la suppression du compte';
    //   }
    // });
  }

  private clearMessages(): void {
    this.successMessage = '';
    this.errorMessage = '';
  }

  get isAdmin(): boolean {
    return this.authService.isAdmin();
  }

  get isIndividual(): boolean {
    return this.currentUser?.userType === 'individual';
  }

  // Helper method to get status label
  getStatusLabel(status: string): string {
    const statusMap: { [key: string]: string } = {
      'NON_TRAITEE': 'Non traitée',
      'EN_COURS': 'En cours',
      'TRAITEE': 'Traitée',
      'DISPONIBLE': 'Disponible',
      'INDISPONIBLE': 'Indisponible'
    };
    return statusMap[status] || status;
  }

  // Helper method to format location
  getLocation(lat: number, lng: number): string {
    return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  }
}