import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { BehaviorSubject, catchError, delay, Observable, of, tap, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { User, UserRole, UserPayload, Environment } from '../../shared/models/user.model';

// interface RegisterRequest {
//   username: string;
//   email: string;
//   password: string;
//   type: string;  // UserRole
//   telephone_utilisateur: string;
//   last_name: string;
//   first_name?: string;
// }

// interface LoginRequest {
//   email: string;
//   password: string;
// }

// interface AuthResponse {
//   user: User;
//   token: string;
//   message?: string;
// }

// @Injectable({
//   providedIn: 'root'
// })
// export class AuthService {
//   deleteAccount() {
//     throw new Error('Method not implemented.');
//   }
//   private apiUrl = `${environment.apiUrl}/users`;  // Utilise /api/users pour register/login
  
//   private currentUserSubject = new BehaviorSubject<Utilisateur | null>(null);
//   public currentUser$ = this.currentUserSubject.asObservable();

//   private isAuthenticatedSubject = new BehaviorSubject<boolean>(false);
//   public isAuthenticated$ = this.isAuthenticatedSubject.asObservable();

//   constructor(
//     private http: HttpClient,
//     private router: Router
//   ) {
//     this.loadUserFromStorage();
//   }

//   // Charger l'utilisateur depuis le localStorage
//   private loadUserFromStorage(): void {
//     const token = localStorage.getItem('auth_token');
//     const userJson = localStorage.getItem('current_user');
      
//     if (token && userJson) {
//       try {
//         const user = JSON.parse(userJson);
//         this.currentUserSubject.next(user);
//         this.isAuthenticatedSubject.next(true);
//       } catch (error) {
//         this.clearAuthData();
//       }
//     }
//   }

//   // Enregistrer un nouvel utilisateur
//   register(data: RegisterRequest): Observable<AuthResponse> {
//     return this.http.post<AuthResponse>(`${this.apiUrl}/register/`, data)
//       .pipe(
//         tap(response => this.handleAuthSuccess(response)),
//         catchError(this.handleError)
//       );
//   }

//   // Connexion
//   login(credentials: LoginRequest): Observable<AuthResponse> {
//     return this.http.post<AuthResponse>(`${this.apiUrl}/login/`, credentials)
//       .pipe(
//         tap(response => this.handleAuthSuccess(response)),
//         catchError(this.handleError)
//       );
//   }

// // Déconnexion
//   logout(): void {
//     this.http.post(`${this.apiUrl}/logout/`, {}).subscribe({
//       next: () => {
//         this.clearAuthData();
//         this.router.navigate(['/accueil']);
//       },
//       error: () => {
//         this.clearAuthData();
//         this.router.navigate(['/accueil']);
//       }
//     });
//   }

//   // Vérifier si l'utilisateur est connecté
//   isLoggedIn(): boolean {
//     return this.isAuthenticatedSubject.value;
//   }

//   isAdmin(): boolean {
//     const user = this.currentUserSubject.value;
//     if (!user) return false;
    
//     return user.userType === UserRole.Admin || 
//           user.userType === UserRole.Rescue || 
//           user.userType === UserRole.Organization;
//   }

//   isSysAdmin(): boolean {
//     const user = this.currentUserSubject.value;
//     return user ? user.userType === UserRole.Admin : false;
//   }


//   // Obtenir l'utilisateur actuel
//   getCurrentUser(): User | null {
//     return this.currentUserSubject.value;
//   }

//   // Obtenir le token
//   getToken(): string | null {
//     return localStorage.getItem('auth_token');
//   }

//   // Mettre à jour le profil
//   updateProfile(data: Partial<User>): Observable<User> {
//     return this.http.put<User>(`${this.apiUrl}/profile`, data)
//       .pipe(
//         tap(user => {
//           this.currentUserSubject.next(user);
//           localStorage.setItem('current_user', JSON.stringify(user));
//         }),
//         catchError(this.handleError)
//       );
//   }

//   // Changer le mot de passe
//   changePassword(oldPassword: string, newPassword: string): Observable<any> {
//     return this.http.post(`${this.apiUrl}/change-password`, {
//       oldPassword,
//       newPassword
//     }).pipe(catchError(this.handleError));
//   }

//   // Réinitialiser le mot de passe
//   resetPassword(email: string): Observable<any> {
//     return this.http.post(`${this.apiUrl}/reset-password`, { email })
//       .pipe(catchError(this.handleError));
//   }

//   // Gérer le succès de l'authentification
//   // private handleAuthSuccess(response: AuthResponse): void {
//   //   if (response.token && response.user) {
//   //     localStorage.setItem('auth_token', response.token);
//   //     localStorage.setItem('current_user', JSON.stringify(response.user));
//   //     this.currentUserSubject.next(response.user);
//   //     this.isAuthenticatedSubject.next(true);
//   //   }
//   // }

//   private handleAuthSuccess(response: AuthResponse): void {
//     if (response.token && response.user) {
//       // 1. On récupère l'utilisateur "brut" du serveur (type any pour manipuler les champs snake_case)
//       const rawUser = response.user as any;

//       // 2. On crée un objet propre qui respecte l'interface Utilisateur (camelCase)
//       const mappedUser: User = {
//         ...rawUser, // Garde les champs déjà corrects (id, email, etc.)
//         pseudo: rawUser.username || rawUser.pseudo,
//         lastName: rawUser.last_name || rawUser.lastName,
//         firstName: rawUser.first_name || rawUser.firstName,
//         phone: rawUser.phone_number || rawUser.phone,
//         postalCode: rawUser.postal_code || rawUser.postalCode,
//         // Utilisation du mapper de rôle que nous avons vu précédemment
//         userType: this.mapBackendRoleToEnum(rawUser.type || rawUser.userType)
//       };

//       localStorage.setItem('auth_token', response.token);
//       localStorage.setItem('current_user', JSON.stringify(mappedUser));
      
//       this.currentUserSubject.next(mappedUser);
//       this.isAuthenticatedSubject.next(true);
//     }
//   }

//   // Ajoute cette petite fonction helper dans AuthService pour le rôle
//   private mapBackendRoleToEnum(backendRole: string): UserRole {
//     const mapping: Record<string, UserRole> = {
//       'UTIL_SIMPLE': UserRole.Individual,
//       'AUT_LOCALE': UserRole.Organization,
//       'SECOURS': UserRole.Rescue,
//       'ADMIN': UserRole.Admin
//     };
//     return mapping[backendRole] || UserRole.Individual;
//   }

//   // Nettoyer les données d'authentification
//   private clearAuthData(): void {
//     localStorage.removeItem('auth_token');
//     localStorage.removeItem('current_user');
//     this.currentUserSubject.next(null);
//     this.isAuthenticatedSubject.next(false);
//   }

//   // Gérer les erreurs
//   private handleError(error: HttpErrorResponse): Observable<never> {
//     let errorMessage = 'Une erreur est survenue';
    
//     if (error.error instanceof ErrorEvent) {
//       // Erreur côté client
//       errorMessage = `Erreur: ${error.error.message}`;
//     } else {
//       // Erreur côté serveur
//       errorMessage = error.error?.message || `Code d'erreur: ${error.status}`;
//     }
    
//     console.error(errorMessage);
//     return throwError(() => new Error(errorMessage));
//   }
// }

interface TokenResponse {
  access: string;    // JWT access (simplejwt)
  refresh: string;
}

interface LoginResponse extends TokenResponse {
  user: User;
}

interface ActivationResponse {
  user: User;
  token: string;
  refresh: string;
  message: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly url = `${environment.apiUrl}`;
  // private readonly url = `${environment.apiUrl}/auth`;
  // private readonly url = `${environment.apiUrl}/users`;

  constructor(private http: HttpClient) {}

  /**
   * Stocke la session (token d'accès, refresh, utilisateur) en localStorage.
   * Factorisé pour être appelé aussi bien après /token/ qu'après activation de compte.
   */
  setSession(accessToken: string, refreshToken: string, user: User): void {
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    localStorage.setItem('current_user', JSON.stringify(user));
  }

  /**
   * POST /api/auth/token/
   * Réponse : { access, refresh, user }
   * (Nécessite un serializer custom côté Django pour inclure `user`)
   */
  login(email: string, password: string): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${this.url}/token/`, { email, password })
      .pipe(
        tap(res => this.setSession(res.access, res.refresh, res.user)),
        catchError((error: HttpErrorResponse) => {
          let errorMessage = 'Une erreur est survenue lors de la connexion';
          
          if (error.status === 401) {
            errorMessage = 'Email ou mot de passe incorrect';
          } else if (error.status === 403) {
            errorMessage = error.error?.error || 'Accès refusé';
          } else if (error.status === 0) {
            errorMessage = 'Impossible de contacter le serveur. Vérifiez votre connexion.';
          } else if (error.error?.error) {
            errorMessage = error.error.error;
          }
          
          return throwError(() => new Error(errorMessage));
        })
      );
  }

  /**
   * GET /api/activate-account/<uidb64>/<token>/
   * Confirme la possession de l'email (lien reçu à l'inscription) et active le compte.
   * Réponse : { user, token, refresh, message }
   */
  activateAccount(uidb64: string, token: string): Observable<ActivationResponse> {
    return this.http
      .get<ActivationResponse>(`${this.url}/activate-account/${uidb64}/${token}/`)
      .pipe(
        tap(res => this.setSession(res.token, res.refresh, res.user)),
        catchError((error: HttpErrorResponse) => {
          const errorMessage = error.error?.error || "Ce lien d'activation est invalide ou a expiré";
          return throwError(() => new Error(errorMessage));
        })
      );
  }

  /**
   * GET /api/magic-login/<uidb64>/<token>/
   * Connexion sans mot de passe via lien magique (ex : suivi de dossier envoyé par email).
   * Réponse : { user, token, refresh, message }
   */
  magicLogin(uidb64: string, token: string): Observable<ActivationResponse> {
    return this.http
      .get<ActivationResponse>(`${this.url}/magic-login/${uidb64}/${token}/`)
      .pipe(
        tap(res => this.setSession(res.token, res.refresh, res.user)),
        catchError((error: HttpErrorResponse) => {
          const errorMessage = error.error?.error || 'Ce lien de connexion est invalide ou a expiré';
          return throwError(() => new Error(errorMessage));
        })
      );
  }

  /**
   * POST /api/auth/token/refresh/
   * Renouveler l'access token depuis le refresh token. Avec ROTATE_REFRESH_TOKENS actif
   * côté serveur, la réponse contient aussi un nouveau refresh token (l'ancien est
   * blacklisté) — il faut donc aussi le stocker, sinon le prochain rafraîchissement
   * échouerait avec un refresh token déjà consommé.
   */
  refreshToken(): Observable<TokenResponse> {
    const refresh = localStorage.getItem('refresh_token');
    return this.http
      .post<TokenResponse>(`${this.url}/token/refresh/`, { refresh })
      .pipe(tap(res => {
        localStorage.setItem('access_token', res.access);
        if (res.refresh) {
          localStorage.setItem('refresh_token', res.refresh);
        }
      }));
  }

  /**
   * POST /api/auth/register/
   */
  register(payload: UserPayload & { email: string; password: string }): Observable<User> {
    return this.http.post<User>(`${this.url}/register/`, payload);
  }

  validateInstitution(payload: {
    email: string;
    institution_name: string;
    institution_type: string;
    commune_name: string;
    commune_code: string;
  }): Observable<{ valid: boolean; message: string; details: any }> {
    return this.http.post<{ valid: boolean; message: string; details: any }>(`${this.url}/validate-institution/`, payload);
  }

  /**
   * GET /api/auth/me/
   * Récupère le profil de l'utilisateur connecté depuis le backend.
   */
  fetchMe(): Observable<User> {
    return this.http
      .get<User>(`${this.url}/me/`)
      .pipe(tap(user => localStorage.setItem('current_user', JSON.stringify(user))));
  }

  /**
   * PATCH /api/auth/me/
   * Met à jour le profil (photo via FormData si besoin).
   */
  updateProfile(payload: UserPayload): Observable<User> {
    // Si photo présente → FormData ; sinon JSON
    const body = payload.photo
      ? this.profileToFormData(payload)
      : payload;

    return this.http
      .patch<User>(`${this.url}/me/`, body)
      .pipe(tap(user => localStorage.setItem('current_user', JSON.stringify(user))));
  }

  /**
   * POST /api/auth/change-password/
   * Payload attendu par Django : { old_password, new_password }
   */
  changePassword(old_password: string, new_password: string): Observable<void> {
    return this.http.post<void>(`${this.url}/change-password/`, {
      old_password,
      new_password
    });
  }

  /**
   * POST /api/reset-password/<uidb64>/<token>/
   * Consomme le lien reçu par email suite à une demande de réinitialisation déclenchée par un
   * administrateur (page Utilisateurs) : contrairement à changePassword, ne nécessite pas de
   * connaître l'ancien mot de passe.
   */
  resetPasswordConfirm(uidb64: string, token: string, new_password: string): Observable<void> {
    return this.http
      .post<void>(`${this.url}/reset-password/${uidb64}/${token}/`, { new_password })
      .pipe(
        catchError((error: HttpErrorResponse) => {
          const errorMessage = error.error?.error || 'Ce lien est invalide ou a expiré';
          return throwError(() => new Error(errorMessage));
        })
      );
  }

  /**
   * Révoque le refresh token côté serveur (best-effort — ne bloque jamais le nettoyage
   * local, même si l'appel réseau échoue, ex. hors-ligne ou token déjà expiré) puis
   * vide la session locale.
   */
  logout(): void {
    const refresh = localStorage.getItem('refresh_token');
    if (refresh) {
      this.http.post(`${this.url}/token/blacklist/`, { refresh }).subscribe({
        next: () => {},
        error: () => {},
      });
    }
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('current_user');
  }

  getCurrentUser(): User | null {
    const raw = localStorage.getItem('current_user');
    return raw ? (JSON.parse(raw) as User) : null;
  }

  getToken(): string | null {
    return localStorage.getItem('access_token');
  }

  /** À dessein basé uniquement sur le rôle PROD réel — d'autres endroits (ex: floutage des
   * coordonnées précises sur la carte publique, map.component.ts) s'appuient dessus pour des
   * décisions de confidentialité qui ne doivent JAMAIS s'élargir simplement parce qu'un compte
   * a reçu un accès démo. Pour l'entrée dans la zone /admin elle-même, voir canEnterAdminArea()
   * ci-dessous — c'est une question différente ("peut-il atteindre la bascule PROD/DEMO ?"),
   * pas "a-t-il des droits institutionnels réels en ce moment ?".
   */
  isAdmin(): boolean {
    return this.getCurrentUser()?.type === UserRole.RESCUE ||
      this.getCurrentUser()?.type === UserRole.LOCAL_AUTH||
      this.getCurrentUser()?.type === UserRole.ADMIN ||
      this.getCurrentUser()?.type === UserRole.REGULATEUR;
  }

  isSysAdmin(): boolean {
    return this.isAdmin();
  }

  /** Utilisé uniquement par adminGuard : doit aussi laisser passer un compte qui n'a de rôle
   * élevé qu'en DEMO (demo_role réglé, type PROD resté simple), sinon le garde bloque l'accès
   * à la mise en page qui contient justement la bascule PROD/DEMO — personne n'ayant reçu
   * qu'un accès démo ne pourrait alors jamais l'atteindre. Une fois entré, les droits réels
   * restent bornés par le rôle effectif (get_effective_role côté backend) : tant que la
   * bascule n'est pas activée, ce compte garde ses droits PROD réels (simples), rien n'est
   * élargi côté données — seul l'accès à la mise en page /admin l'est. */
  canEnterAdminArea(): boolean {
    return this.isAdmin() || !!this.getCurrentUser()?.demo_role;
  }

  isLoggedIn(): boolean {
    return !!this.getToken();
  }

  isEnable(): boolean {
    return this.getCurrentUser()?.enabled === true;
  }

  /** Zone active (PROD par défaut) — lue par l'intercepteur pour l'en-tête X-Environment
   * envoyé à chaque requête, et par le header pour la bannière "ZONE DE DÉMONSTRATION". */
  getEnvironment(): Environment {
    return (localStorage.getItem('active_environment') as Environment) || 'PROD';
  }

  /** Change de zone puis recharge la page entière : le moyen le plus simple de garantir que
   * toutes les listes/pages déjà chargées se rafraîchissent sous le nouvel environnement, sans
   * rendre tout AuthService réactif (aujourd'hui 100% synchrone/localStorage). */
  setEnvironment(env: Environment): void {
    localStorage.setItem('active_environment', env);
    window.location.reload();
  }

  /** La bascule ne doit être visible que pour un utilisateur ayant reçu un accès démo explicite
   * (demo_role non nul) — réglé manuellement par un admin sur la page Utilisateurs. */
  canAccessDemo(): boolean {
    return !!this.getCurrentUser()?.demo_role;
  }

  private profileToFormData(payload: UserPayload): FormData {
    const fd = new FormData();
    if (payload.username)              fd.append('username', payload.username);
    if (payload.email)                 fd.append('email', payload.email);
    if (payload.first_name)            fd.append('first_name', payload.first_name);
    if (payload.last_name)             fd.append('last_name', payload.last_name);
    if (payload.phone_number) fd.append('phone_number', payload.phone_number);
    if (payload.photo)                 fd.append('photo', payload.photo);
    return fd;
  }
}
