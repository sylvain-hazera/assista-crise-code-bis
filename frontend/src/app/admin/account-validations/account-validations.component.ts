import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ValidationService, ValidationRequest } from '../../../services/validation.service';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole } from '../../../shared/models/user.model';

@Component({
  selector: 'app-account-validations',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './account-validations.component.html',
  styleUrl: './account-validations.component.scss'
})
export class AccountValidationsComponent implements OnInit {
  pendingValidations: ValidationRequest[] = [];
  isLoading = false;
  errorMessage = '';
  isAdmin = false;
  isInstitution = false;
  currentUserPostalCode = '';

  constructor(
    private validationService: ValidationService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    const currentUser = this.authService.getCurrentUser();
    if (!currentUser) {
      this.errorMessage = 'Vous devez être connecté pour accéder à cette page';
      return;
    }

    this.isAdmin = currentUser.userType === UserRole.Admin;
    this.isInstitution = currentUser.userType === UserRole.Organization;
    this.currentUserPostalCode = currentUser.postalCode;

    this.loadValidations();
  }

  loadValidations(): void {
    this.isLoading = true;
    this.errorMessage = '';

    const request$ = this.isAdmin
      ? this.validationService.getPendingValidations()
      : this.validationService.getValidationsByPostalCode(this.currentUserPostalCode);

    request$.subscribe({
      next: (validations) => {
        this.pendingValidations = validations;
        this.isLoading = false;
      },
      error: (error) => {
        console.error('Erreur chargement validations:', error);
        this.errorMessage = 'Erreur lors du chargement des demandes de validation';
        this.isLoading = false;
      }
    });
  }

  approveValidation(request: ValidationRequest): void {
    if (!request.id) return;

    if (confirm(`Êtes-vous sûr de vouloir approuver le compte de ${request.userName} ?`)) {
      this.validationService.approveValidation(request.id).subscribe({
        next: () => {
          alert('Compte approuvé avec succès !');
          this.loadValidations();
        },
        error: (error) => {
          console.error('Erreur approbation:', error);
          alert('Erreur lors de l\'approbation du compte');
        }
      });
    }
  }

  rejectValidation(request: ValidationRequest): void {
    if (!request.id) return;

    const reason = prompt('Raison du rejet (optionnel):');
    if (reason !== null) {
      this.validationService.rejectValidation(request.id, reason).subscribe({
        next: () => {
          alert('Compte rejeté');
          this.loadValidations();
        },
        error: (error) => {
          console.error('Erreur rejet:', error);
          alert('Erreur lors du rejet du compte');
        }
      });
    }
  }

  getUserTypeLabel(userType: string): string {
    const labels: { [key: string]: string } = {
      'ADMIN': 'Admin',
      'AUT_LOCALE': 'Institution',
      'SECOURS': 'Secours organisés',
      'UTIL_SIMPLE': 'Particulier'
    };
    return labels[userType] || userType;
  }

  canValidate(request: ValidationRequest): boolean {
    if (this.isAdmin) return true;
    if (this.isInstitution && request.postalCode === this.currentUserPostalCode) {
      return request.userType === 'AUT_LOCALE';
    }
    return false;
  }
}
