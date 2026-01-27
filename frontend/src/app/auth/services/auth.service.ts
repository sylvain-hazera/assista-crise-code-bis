import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { BehaviorSubject, catchError, delay, Observable, of, tap, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { User, UserRole } from '../../shared/models/user.model';

interface RegisterRequest {
  userType: UserRole;
  lastName: string;
  firstName?: string;
  pseudo?: string;
  password: string;
  email: string;
  phone: string;
  postalCode: string;
}

interface LoginRequest {
  email: string;
  password: string;
}

interface AuthResponse {
  user: User;
  token: string;
  message?: string;
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private apiUrl = `${environment.apiUrl}/auth`;
  
  private currentUserSubject = new BehaviorSubject<User | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  private isAuthenticatedSubject = new BehaviorSubject<boolean>(false);
  public isAuthenticated$ = this.isAuthenticatedSubject.asObservable();

  // Utilisateurs de test
  // private mockUsers: User[] = [
  //   {
  //     id: 1,
  //     userType: UserRole.Admin,
  //     lastName: 'Croix-Rouge Française',
  //     firstName: '',
  //     email: 'admin@croixrouge.fr',
  //     phone: '+33123456789',
  //     postalCode: '75001',
  //     avatar: '🏥',
  //     createdAt: new Date('2024-01-01'),
  //     updatedAt: new Date()
  //   },
  //   {
  //     id: 2,
  //     userType: UserRole.Organization,
  //     lastName: 'Secours Populaire',
  //     firstName: '',
  //     email: 'contact@secourspopulaire.fr',
  //     phone: '+33198765432',
  //     postalCode: '69001',
  //     avatar: '🆘',
  //     createdAt: new Date('2024-01-15'),
  //     updatedAt: new Date()
  //   },
  //   {
  //     id: 3,
  //     userType: UserRole.Rescue,
  //     lastName: 'Pompiers du Rhône',
  //     firstName: '',
  //     email: 'pompiers@sdis69.fr',
  //     phone: '+33412345678',
  //     postalCode: '69100',
  //     avatar: '🚒',
  //     createdAt: new Date('2024-02-01'),
  //     updatedAt: new Date()
  //   },
  //   {
  //     id: 4,
  //     userType: UserRole.Individual,
  //     lastName: 'Martin',
  //     firstName: 'Sophie',
  //     pseudo: 'sophie_m',
  //     email: 'sophie.martin@email.fr',
  //     phone: '+33656781234',
  //     postalCode: '38000',
  //     avatar: '👤',
  //     createdAt: new Date('2024-03-01'),
  //     updatedAt: new Date()
  //   },
  //   {
  //     id: 5,
  //     userType: UserRole.Individual,
  //     lastName: 'Dubois',
  //     firstName: 'Pierre',
  //     pseudo: 'pierre_d',
  //     email: 'pierre.dubois@email.fr',
  //     phone: '+33687654321',
  //     postalCode: '38100',
  //     createdAt: new Date('2024-03-15'),
  //     updatedAt: new Date()
  //   }
  // ];

  // Mots de passe de test (tous : "password123")
  private readonly TEST_PASSWORD = 'password123';

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
    return this.http.post<AuthResponse>(`${this.apiUrl}/register`, data)
      .pipe(
        tap(response => this.handleAuthSuccess(response)),
        catchError(this.handleError)
      );
  }

  // Connexion
  login(credentials: LoginRequest): Observable<AuthResponse> {
    return this.http.post<AuthResponse>(`${this.apiUrl}/login`, credentials)
      .pipe(
        tap(response => this.handleAuthSuccess(response)),
        catchError(this.handleError)
      );
  }

  // Connexion (simulée)
  // login(credentials: LoginRequest): Observable<AuthResponse> {
  //   console.log('🔐 Tentative de connexion:', credentials.email);

  //   // Simuler un délai réseau
  //   return of(null).pipe(
  //     delay(500),
  //     (source) => {
  //       const user = this.mockUsers.find(u => u.email === credentials.email);

  //       if (!user) {
  //         console.error('❌ Utilisateur non trouvé');
  //         return throwError(() => new Error('Email ou mot de passe incorrect'));
  //       }

  //       if (credentials.password !== this.TEST_PASSWORD) {
  //         console.error('❌ Mot de passe incorrect');
  //         return throwError(() => new Error('Email ou mot de passe incorrect'));
  //       }

  //       // Générer un faux token
  //       // const token = this.generateMockToken(user);
  //       const token = 'votre_jwt_ici';
        
  //       const response: AuthResponse = {
  //         user,
  //         token,
  //         message: 'Connexion réussie'
  //       };

  //       console.log('✅ Connexion réussie:', user.email);
  //       this.handleAuthSuccess(response);

  //       return of(response);
  //     }
  //   );
  // }

  // login(credentials: any) {
  //   // Simuler un appel API
  //   this.isAuthenticatedSubject.next(true);
  //   this.currentUser$.next 
  //   localStorage.setItem('token', 'votre_jwt_ici');
  // }

  // logout() {
  //   this.isConnectedSubject.next(false);
  //   this.userRole = null;
  //   this.userName = null;
  //   localStorage.removeItem('token');
  // }

// Déconnexion
  logout(): void {
    this.http.post(`${this.apiUrl}/logout`, {}).subscribe({
      next: () => {
        this.clearAuthData();
        this.router.navigate(['/login']);
      },
      error: () => {
        this.clearAuthData();
        this.router.navigate(['/login']);
      }
    });
  }

  // Vérifier si l'utilisateur est connecté
  isLoggedIn(): boolean {
    return this.isAuthenticatedSubject.value;
  }

  isAdmin(): boolean {
    const user = this.currentUserSubject.value;
    return user ? user.userType !== 'individual' : false;
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
  private handleAuthSuccess(response: AuthResponse): void {
    if (response.token && response.user) {
      localStorage.setItem('auth_token', response.token);
      localStorage.setItem('current_user', JSON.stringify(response.user));
      this.currentUserSubject.next(response.user);
      this.isAuthenticatedSubject.next(true);
    }
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
      errorMessage = error.error?.message || `Code d'erreur: ${error.status}`;
    }
    
    console.error(errorMessage);
    return throwError(() => new Error(errorMessage));
  }
}