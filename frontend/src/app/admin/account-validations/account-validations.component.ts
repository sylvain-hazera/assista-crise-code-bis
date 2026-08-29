import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../auth/services/auth.service';
import { User, UserRole } from '../../shared/models/user.model';

@Component({
  selector: 'app-account-validations',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './account-validations.component.html',
  styleUrl: './account-validations.component.scss'
})
export class AccountValidationsComponent implements OnInit {
  pendingUsers: User[] = [];
  isLoading = false;
  errorMessage = '';
  isAdmin = false;
  isInstitution = false;
  currentUserPostalCode: string | null = '';

  constructor(
    private userService: UserService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    const currentUser = this.authService.getCurrentUser();
    if (!currentUser) {
      this.errorMessage = 'Vous devez être connecté pour accéder à cette page';
      return;
    }

    // Rôle EFFECTIF (comme le backend, voir get_effective_role côté API) : une mairie en
    // zone de démo avec un rôle démo non institutionnel ne doit pas voir cette page comme
    // opérante alors que l'appel serait de toute façon refusé.
    const role = this.authService.getEffectiveRole();
    this.isAdmin = role === UserRole.ADMIN;
    this.isInstitution = role === UserRole.LOCAL_AUTH;
    this.currentUserPostalCode = currentUser.postal_code;

    this.loadValidations();
  }

  loadValidations(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.userService.getPendingValidations().subscribe({
      next: (users) => {
        this.pendingUsers = users;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = 'Erreur lors du chargement des demandes de validation';
        this.isLoading = false;
      },
    });
  }

  // Le backend ne renvoie déjà que les comptes que l'appelant a le droit de traiter
  // (tous pour un admin, ceux du même code postal pour une mairie — voir
  // UserViewSet.pending_validations) : pas de filtre à refaire côté client.

  approve(user: User): void {
    if (!confirm(`Approuver le compte de ${user.first_name} ${user.last_name} ?`)) return;
    this.userService.approveAccount(user.id).subscribe({
      next: () => this.loadValidations(),
      error: () => alert("Erreur lors de l'approbation du compte."),
    });
  }

  reject(user: User): void {
    const reason = prompt('Raison du refus (optionnel) :');
    if (reason === null) return;
    this.userService.rejectAccount(user.id, reason).subscribe({
      next: () => this.loadValidations(),
      error: () => alert('Erreur lors du refus du compte.'),
    });
  }

  userTypeLabel(type: string): string {
    const labels: Record<string, string> = {
      ADMIN: 'Administrateur',
      AUT_LOCALE: 'Institution',
      SECOURS: 'Secours organisés',
      UTIL_SIMPLE: 'Particulier',
      REGULATEUR: 'Régulateur de crise',
    };
    return labels[type] || type;
  }
}
