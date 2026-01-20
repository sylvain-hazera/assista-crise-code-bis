import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { BehaviorSubject, catchError, Observable, tap, throwError } from 'rxjs';

export interface User {
  id?: number;
  userType: 'individual' | 'organization';
  lastName: string;
  firstName?: string;
  pseudo?: string;
  email: string;
  phone: string;
  postalCode: string;
  acceptTerms: boolean;
  token?: string;
}

export interface RegisterRequest {
  userType: string;
  lastName: string;
  firstName?: string;
  pseudo?: string;
  password: string;
  email: string;
  phone: string;
  postalCode: string;
  acceptTerms: boolean;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthResponse {
  user: User;
  token: string;
  message?: string;
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private apiUrl = 'http://localhost:8000/api/auth';
  
  private currentUserSubject = new BehaviorSubject<User | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  private isAuthenticatedSubject = new BehaviorSubject<boolean>(false);
  public isAuthenticated$ = this.isAuthenticatedSubject.asObservable();

  // constructor() {
  //   const token = localStorage.getItem('token');
  //   if (token) {
  //     this.isConnectedSubject.next(true);
  //     // Simuler la récupération du nom et du rôle
  //     // this.userName = "Utilisateur"; 
  //   }
  // }

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
  // login(credentials: any) {
    // Simuler un appel API
    // this.isConnectedSubject.next(true);
    // this.userRole = 'admin'; // Pour le test
    // this.userName = 'Jean Dupont';
    // localStorage.setItem('token', 'votre_jwt_ici');
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