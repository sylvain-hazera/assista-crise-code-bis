import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { BehaviorSubject, catchError, delay, Observable, of, tap, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { User, UserRole } from '../../shared/models/user.model';

interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  type: string;  // RoleUtilisateur
  telephone_utilisateur: string;
  last_name: string;
  first_name?: string;
}

interface LoginRequest {
  email: string;
  password: string;
}

interface AuthResponse {
  user: User;
  token?: string;  // Optionnel - absent si le compte nécessite validation
  refresh?: string;
  message?: string;
  requires_validation?: boolean;  // Indique si le compte est en attente de validation
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  deleteAccount() {
    throw new Error('Method not implemented.');
  }
  private apiUrl = `${environment.apiUrl}/users`;  // Utilise /api/users pour register/login
  
  private currentUserSubject = new BehaviorSubject<User | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  private isAuthenticatedSubject = new BehaviorSubject<boolean>(false);
  public isAuthenticated$ = this.isAuthenticatedSubject.asObservable();

  constructor(
    private http: HttpClient,
    private router: Router
  ) {
    this.loadUserFromStorage();
  }

  // Charger l'utilisateur depuis le localStorage
  private loadUserFromStorage(): void {
    const token = localStorage.getItem('auth_token');
    const userJson = localStorage.getItem('current_user');
      
    if (token && userJson) {
      try {
        const user = JSON.parse(userJson);
        this.currentUserSubject.next(user);
        this.isAuthenticatedSubject.next(true);
      } catch (error) {
        this.clearAuthData();
      }
    }
  }

  // Enregistrer un nouvel utilisateur
  register(data: RegisterRequest): Observable<AuthResponse> {
    return this.http.post<AuthResponse>(`${this.apiUrl}/register/`, data)
      .pipe(
        tap(response => this.handleAuthSuccess(response)),
        catchError(this.handleError)
      );
  }

  // Connexion
  login(credentials: LoginRequest): Observable<AuthResponse> {
    return this.http.post<AuthResponse>(`${this.apiUrl}/login/`, credentials)
      .pipe(
        tap(response => this.handleAuthSuccess(response)),
        catchError(this.handleError)
      );
  }

// Déconnexion
  logout(): void {
    this.http.post(`${this.apiUrl}/logout/`, {}).subscribe({
      next: () => {
        this.clearAuthData();
        this.router.navigate(['/accueil']);
      },
      error: () => {
        this.clearAuthData();
        this.router.navigate(['/accueil']);
      }
    });
  }

  // Vérifier si l'utilisateur est connecté
  isLoggedIn(): boolean {
    return this.isAuthenticatedSubject.value;
  }

  isAdmin(): boolean {
    const user = this.currentUserSubject.value;
    if (!user) return false;
    
    return user.userType === UserRole.Admin || 
          user.userType === UserRole.Rescue || 
          user.userType === UserRole.Organization;
  }

  isSysAdmin(): boolean {
    const user = this.currentUserSubject.value;
    return user ? user.userType === UserRole.Admin : false;
  }


  // Obtenir l'utilisateur actuel
  getCurrentUser(): User | null {
    return this.currentUserSubject.value;
  }

  // Obtenir le token
  getToken(): string | null {
    return localStorage.getItem('auth_token');
  }

  // Mettre à jour le profil
  updateProfile(data: Partial<User>): Observable<User> {
    return this.http.put<User>(`${this.apiUrl}/profile`, data)
      .pipe(
        tap(user => {
          this.currentUserSubject.next(user);
          localStorage.setItem('current_user', JSON.stringify(user));
        }),
        catchError(this.handleError)
      );
  }

  // Changer le mot de passe
  changePassword(oldPassword: string, newPassword: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/change-password`, {
      oldPassword,
      newPassword
    }).pipe(catchError(this.handleError));
  }

  // Réinitialiser le mot de passe
  resetPassword(email: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/reset-password`, { email })
      .pipe(catchError(this.handleError));
  }

  // Gérer le succès de l'authentification
  // private handleAuthSuccess(response: AuthResponse): void {
  //   if (response.token && response.user) {
  //     localStorage.setItem('auth_token', response.token);
  //     localStorage.setItem('current_user', JSON.stringify(response.user));
  //     this.currentUserSubject.next(response.user);
  //     this.isAuthenticatedSubject.next(true);
  //   }
  // }

  private handleAuthSuccess(response: AuthResponse): void {
    // Ne stocker le token que si le compte est validé (token présent)
    if (response.token && response.user) {
      // 1. On récupère l'utilisateur "brut" du serveur (type any pour manipuler les champs snake_case)
      const rawUser = response.user as any;

      // 2. On crée un objet propre qui respecte l'interface User (camelCase)
      const mappedUser: User = {
        ...rawUser, // Garde les champs déjà corrects (id, email, etc.)
        pseudo: rawUser.username || rawUser.pseudo,
        lastName: rawUser.last_name || rawUser.lastName,
        firstName: rawUser.first_name || rawUser.firstName,
        phone: rawUser.telephone_utilisateur || rawUser.phone,
        postalCode: rawUser.postal_code || rawUser.postalCode,
        // Utilisation du mapper de rôle que nous avons vu précédemment
        userType: this.mapBackendRoleToEnum(rawUser.type || rawUser.userType)
      };

      localStorage.setItem('auth_token', response.token);
      localStorage.setItem('current_user', JSON.stringify(mappedUser));
      
      this.currentUserSubject.next(mappedUser);
      this.isAuthenticatedSubject.next(true);
    } else if (response.user && !response.token) {
      // Compte créé mais en attente de validation - ne pas authentifier
      console.log('Compte créé en attente de validation - pas de token fourni');
    }
  }

  // Ajoute cette petite fonction helper dans AuthService pour le rôle
  private mapBackendRoleToEnum(backendRole: string): UserRole {
    const mapping: Record<string, UserRole> = {
      'UTIL_SIMPLE': UserRole.Individual,
      'AUT_LOCALE': UserRole.Organization,
      'SECOURS': UserRole.Rescue,
      'ADMIN': UserRole.Admin
    };
    return mapping[backendRole] || UserRole.Individual;
  }

  // Nettoyer les données d'authentification
  private clearAuthData(): void {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('current_user');
    this.currentUserSubject.next(null);
    this.isAuthenticatedSubject.next(false);
  }

  // Gérer les erreurs
  private handleError(error: HttpErrorResponse): Observable<never> {
    let errorMessage = 'Une erreur est survenue';
    
    if (error.error instanceof ErrorEvent) {
      // Erreur côté client
      errorMessage = `Erreur: ${error.error.message}`;
    } else {
      // Erreur côté serveur
      if (error.error?.message) {
        errorMessage = error.error.message;
      } else if (error.error?.error) {
        errorMessage = error.error.error;
      } else if (typeof error.error === 'object') {
        // Erreurs de validation Django (format: {"field": ["error message"]})
        const validationErrors: string[] = [];
        for (const field in error.error) {
          if (Array.isArray(error.error[field])) {
            validationErrors.push(...error.error[field]);
          } else if (typeof error.error[field] === 'string') {
            validationErrors.push(error.error[field]);
          }
        }
        if (validationErrors.length > 0) {
          errorMessage = validationErrors.join(', ');
        } else {
          errorMessage = `Code d'erreur: ${error.status}`;
        }
      } else {
        errorMessage = `Code d'erreur: ${error.status}`;
      }
    }
    
    console.error(errorMessage);
    return throwError(() => new Error(errorMessage));
  }
}