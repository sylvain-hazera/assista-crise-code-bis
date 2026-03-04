import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subject, takeUntil, debounceTime, distinctUntilChanged } from 'rxjs';
import { UserService } from '../../services/user.service';
import { User, UserRole } from '../../shared/models/user.model';
import { AuthService } from '../../auth/services/auth.service';

@Component({
  selector: 'app-users',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink],
  templateUrl: './users.component.html',
  styleUrls: ['./users.component.scss']
})
export class UsersComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  // États
  isLoading = false;
  errorMessage = '';
  successMessage = '';
  
  // Données
  users: User[] = [];
  filteredUsers: User[] = [];
  selectedUser: User | null = null;
  
  // Filtres
  searchTerm = '';
  selectedRole: UserRole | 'ALL' = 'ALL';
  selectedStatus: 'ALL' | 'ACTIVE' | 'INACTIVE' = 'ALL';
  showFilters = false;
  
  // Pagination
  currentPage = 1;
  itemsPerPage = 10;
  totalItems = 0;
  
  // Modale
  showUserModal = false;
  isEditMode = false;
  userForm: FormGroup;
  selectedFile: File | null = null;
  previewUrl: string | null = null;
  
  // Options pour les selects
  userRoles = [
    { value: UserRole.ADMIN, label: 'Administrateur' },
    { value: UserRole.LOCAL_AUTH, label: 'Autorité locale' },
    { value: UserRole.RESCUE, label: 'Secours' },
    { value: UserRole.SIMPLE_USER, label: 'Utilisateur simple' }
  ];

  constructor(
    private userService: UserService,
    private fb: FormBuilder,
    private authService: AuthService
  ) {
    this.userForm = this.createForm();
  }

  ngOnInit(): void {
    this.loadUsers();
    this.setupSearchListener();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  /**
   * Crée le formulaire réactif
   */
  private createForm(): FormGroup {
    return this.fb.group({
      username: ['', [Validators.required, Validators.minLength(3)]],
      email: ['', [Validators.required, Validators.email]],
      first_name: ['', Validators.required],
      last_name: ['', Validators.required],
      telephone_utilisateur: ['', [Validators.pattern('^[0-9+\\s-]{10,}$')]],
      type: [UserRole.SIMPLE_USER, Validators.required],
      password: ['', [Validators.minLength(8)]],
      confirmPassword: ['']
    }, { validator: this.passwordMatchValidator });
  }

  /**
   * Validateur pour la confirmation du mot de passe
   */
  private passwordMatchValidator(g: FormGroup) {
    const password = g.get('password')?.value;
    const confirmPassword = g.get('confirmPassword')?.value;
    
    if (password && confirmPassword && password !== confirmPassword) {
      g.get('confirmPassword')?.setErrors({ mismatch: true });
      return { mismatch: true };
    }
    return null;
  }

  /**
   * Configure l'écouteur de recherche avec debounce
   */
  private setupSearchListener(): void {
    // À implémenter si vous voulez une recherche en temps réel
    // Pour l'instant, la recherche se fait côté client
  }

  /**
   * Charge la liste des utilisateurs
   */
  loadUsers(): void {
    this.isLoading = true;
    this.errorMessage = '';

    this.userService.getAll()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (users) => {
          this.users = users;
          this.applyFilters();
          this.isLoading = false;
        },
        error: (error) => {
          console.error('Erreur chargement utilisateurs:', error);
          this.errorMessage = 'Impossible de charger la liste des utilisateurs';
          this.isLoading = false;
        }
      });
  }

  /**
   * Applique les filtres sur la liste des utilisateurs
   */
  applyFilters(): void {
    let filtered = [...this.users];

    // Filtre par recherche (nom, email, username)
    if (this.searchTerm) {
      const term = this.searchTerm.toLowerCase();
      filtered = filtered.filter(user => 
        user.first_name?.toLowerCase().includes(term) ||
        user.last_name?.toLowerCase().includes(term) ||
        user.email?.toLowerCase().includes(term) ||
        user.username?.toLowerCase().includes(term) ||
        user.phone_number?.includes(term)
      );
    }

    // Filtre par rôle
    if (this.selectedRole !== 'ALL') {
      filtered = filtered.filter(user => user.type === this.selectedRole);
    }

    // Filtre par statut (basé sur l'existence de l'utilisateur)
    // Note: Adaptez selon votre modèle (enable, is_active, etc.)
    if (this.selectedStatus !== 'ALL') {
      // À adapter selon votre modèle
      // filtered = filtered.filter(user => user.is_active === (this.selectedStatus === 'ACTIVE'));
    }

    this.filteredUsers = filtered;
    this.totalItems = this.filteredUsers.length;
    this.currentPage = 1; // Reset à la première page
  }

  /**
   * Réinitialise tous les filtres
   */
  resetFilters(): void {
    this.searchTerm = '';
    this.selectedRole = 'ALL';
    this.selectedStatus = 'ALL';
    this.applyFilters();
  }

  /**
   * Ouvre la modale pour créer un nouvel utilisateur
   */
  openCreateModal(): void {
    this.isEditMode = false;
    this.selectedUser = null;
    this.userForm.reset({
      type: UserRole.SIMPLE_USER
    });
    this.previewUrl = null;
    this.selectedFile = null;
    this.showUserModal = true;
  }

  /**
   * Ouvre la modale pour éditer un utilisateur
   */
  openEditModal(user: User): void {
    this.isEditMode = true;
    this.selectedUser = user;
    
    this.userForm.patchValue({
      username: user.username,
      email: user.email,
      first_name: user.first_name,
      last_name: user.last_name,
      telephone_utilisateur: user.phone_number,
      type: user.type
    });
    
    // Ne pas remplir les champs mot de passe en édition
    this.userForm.get('password')?.clearValidators();
    this.userForm.get('confirmPassword')?.clearValidators();
    this.userForm.get('password')?.updateValueAndValidity();
    this.userForm.get('confirmPassword')?.updateValueAndValidity();
    
    this.previewUrl = user.photo ? user.photo : null;
    this.selectedFile = null;
    this.showUserModal = true;
  }

  /**
   * Ferme la modale
   */
  closeModal(): void {
    this.showUserModal = false;
    this.selectedUser = null;
    this.userForm.reset();
    this.previewUrl = null;
    this.selectedFile = null;
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

  /**
   * Sauvegarde l'utilisateur (création ou modification)
   */
  saveUser(): void {
    if (this.userForm.invalid) {
      Object.keys(this.userForm.controls).forEach(key => {
        this.userForm.get(key)?.markAsTouched();
      });
      return;
    }

    this.isLoading = true;
    this.errorMessage = '';

    const formData = new FormData();
    const formValue = this.userForm.value;

    // Ajouter les champs au FormData
    if (formValue.username) formData.append('username', formValue.username);
    if (formValue.email) formData.append('email', formValue.email);
    if (formValue.first_name) formData.append('first_name', formValue.first_name);
    if (formValue.last_name) formData.append('last_name', formValue.last_name);
    if (formValue.phone_number) formData.append('phone_number', formValue.phone_number);
    if (formValue.type) formData.append('type', formValue.type);

    // Ajouter le mot de passe seulement en création ou si modifié
    if (formValue.password && !this.isEditMode) {
      formData.append('password', formValue.password);
    }

    // Ajouter la photo si sélectionnée
    if (this.selectedFile) {
      formData.append('photo', this.selectedFile);
    }

    const request = this.isEditMode && this.selectedUser
      ? this.userService.update(this.selectedUser.id, formData)
      : this.userService.create(formData);

    request.pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (savedUser) => {
          this.successMessage = this.isEditMode 
            ? 'Utilisateur modifié avec succès' 
            : 'Utilisateur créé avec succès';
          
          this.closeModal();
          this.loadUsers(); // Recharger la liste
          
          // Auto-hide success message after 3 seconds
          setTimeout(() => this.successMessage = '', 3000);
        },
        error: (error) => {
          console.error('Erreur sauvegarde utilisateur:', error);
          this.errorMessage = 'Erreur lors de la sauvegarde de l\'utilisateur';
          
          // Gérer les erreurs de validation du backend
          if (error.error && typeof error.error === 'object') {
            const backendErrors = error.error;
            Object.keys(backendErrors).forEach(key => {
              const control = this.userForm.get(key);
              if (control) {
                control.setErrors({ backend: backendErrors[key].join(', ') });
              }
            });
          }
        },
        complete: () => {
          this.isLoading = false;
        }
      });
  }

  /**
   * Supprime un utilisateur après confirmation
   */
  deleteUser(user: User): void {
    if (!confirm(`Êtes-vous sûr de vouloir supprimer l'utilisateur ${user.first_name} ${user.last_name} ?`)) {
      return;
    }

    this.isLoading = true;
    
    this.userService.delete(user.id)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => {
          this.successMessage = 'Utilisateur supprimé avec succès';
          this.loadUsers();
          setTimeout(() => this.successMessage = '', 3000);
        },
        error: (error) => {
          console.error('Erreur suppression utilisateur:', error);
          this.errorMessage = 'Impossible de supprimer l\'utilisateur';
          this.isLoading = false;
        }
      });
  }

  /**
   * Valide un utilisateur (changement de rôle)
   */
  validateUser(user: User): void {
    // Cette méthode change le rôle d'UTIL_SIMPLE vers un rôle plus élevé
    if (user.type !== UserRole.SIMPLE_USER) {
      alert('Cet utilisateur est déjà validé');
      return;
    }

    const newRole = prompt('Choisir le nouveau rôle (ADMIN, AUT_LOCALE, SECOURS):');
    if (!newRole) return;

    const roleMap: { [key: string]: UserRole } = {
      'ADMIN': UserRole.ADMIN,
      'AUT_LOCALE': UserRole.LOCAL_AUTH,
      'SECOURS': UserRole.RESCUE
    };

    if (!roleMap[newRole]) {
      alert('Rôle invalide');
      return;
    }

    const formData = new FormData();
    formData.append('type', roleMap[newRole]);

    this.isLoading = true;
    this.userService.update(user.id, formData)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => {
          this.successMessage = 'Utilisateur validé avec succès';
          this.loadUsers();
          setTimeout(() => this.successMessage = '', 3000);
        },
        error: (error) => {
          console.error('Erreur validation utilisateur:', error);
          this.errorMessage = 'Impossible de valider l\'utilisateur';
          this.isLoading = false;
        }
      });
  }

  /**
   * Active/désactive un utilisateur
   */
  toggleUserStatus(user: User): void {
    const formData = new FormData();
    formData.append('enable', (!user.enabled).toString());
    formData.append('validator', this.authService.getCurrentUser()!.id.toString());
    
    this.userService.update(user.id, formData)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => {
          this.successMessage = `Utilisateur ${user.enabled ? 'désactivé' : 'activé'} avec succès`;
          this.loadUsers();
          setTimeout(() => this.successMessage = '', 3000);
        },
        error: (error) => {
          console.error('Erreur modification statut:', error);
          this.errorMessage = 'Impossible de modifier le statut';
          this.isLoading = false;
        }
      });
  }

  /**
   * Vérifie si un champ du formulaire est invalide
   */
  isFieldInvalid(fieldName: string): boolean {
    const field = this.userForm.get(fieldName);
    return field ? field.invalid && (field.dirty || field.touched) : false;
  }

  /**
   * Obtient le libellé d'un rôle
   */
  getRoleLabel(role: UserRole): string {
    const roleObj = this.userRoles.find(r => r.value === role);
    return roleObj ? roleObj.label : role;
  }

  /**
   * Obtient la classe CSS pour le badge de rôle
   */
  getRoleBadgeClass(role: UserRole): string {
    const classes = {
      [UserRole.ADMIN]: 'badge-admin',
      [UserRole.LOCAL_AUTH]: 'badge-local',
      [UserRole.RESCUE]: 'badge-rescue',
      [UserRole.SIMPLE_USER]: 'badge-simple'
    };
    return classes[role] || 'badge-default';
  }

  /**
   * Obtient les éléments paginés
   */
  get paginatedUsers(): User[] {
    const start = (this.currentPage - 1) * this.itemsPerPage;
    const end = start + this.itemsPerPage;
    return this.filteredUsers.slice(start, end);
  }

  /**
   * Calcule le nombre total de pages
   */
  get totalPages(): number {
    return Math.ceil(this.totalItems / this.itemsPerPage);
  }

  /**
   * Change de page
   */
  changePage(page: number): void {
    if (page >= 1 && page <= this.totalPages) {
      this.currentPage = page;
    }
  }
}