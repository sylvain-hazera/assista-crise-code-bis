import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { BehaviorSubject, catchError, delay, Observable, of, tap, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { User, UserRole, UserPayload, Environment } from '../../shared/models/user.model';
import { SuiviPositionPermanentService } from '../../services/suivi-position-permanent.service';

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

  constructor(private http: HttpClient, private suiviPosition: SuiviPositionPermanentService) {}

  /** Stocke la session (access, refresh, utilisateur) ; appelé après /token/ et après activation. */
  setSession(accessToken: string, refreshToken: string, user: User): void {
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    localStorage.setItem('current_user', JSON.stringify(user));
    // Relance le suivi de position permanent s'il avait été activé (sans redemander l'accord).
    this.suiviPosition.demarrerSiConsentement();
  }

  /** POST /api/token/ → { access, refresh, user } */
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

  /** GET /api/activate-account/<uidb64>/<token>/ : active le compte → { user, token, refresh, message } */
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

  /** GET /api/magic-login/<uidb64>/<token>/ : connexion par lien magique → { user, token, refresh, message } */
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

  /** POST /api/token/refresh/. ROTATE_REFRESH_TOKENS : le nouveau refresh doit être stocké,
   * l'ancien est blacklisté. */
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

  /** POST /api/register/ */
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

  /** GET /api/me/ */
  fetchMe(): Observable<User> {
    return this.http
      .get<User>(`${this.url}/me/`)
      .pipe(tap(user => localStorage.setItem('current_user', JSON.stringify(user))));
  }

  /** PATCH /api/me/ (FormData si photo). */
  updateProfile(payload: UserPayload): Observable<User> {
    const body = payload.photo
      ? this.profileToFormData(payload)
      : payload;

    return this.http
      .patch<User>(`${this.url}/me/`, body)
      .pipe(tap(user => localStorage.setItem('current_user', JSON.stringify(user))));
  }

  /** POST /api/change-password/ { old_password, new_password } */
  changePassword(old_password: string, new_password: string): Observable<void> {
    return this.http.post<void>(`${this.url}/change-password/`, {
      old_password,
      new_password
    });
  }

  /** POST /api/reset-password/request/ : réponse identique que l'email existe ou non ; l'UI ne
   * doit pas non plus distinguer les deux cas. */
  requestPasswordReset(email: string): Observable<void> {
    return this.http
      .post<void>(`${this.url}/reset-password/request/`, { email })
      .pipe(
        catchError((error: HttpErrorResponse) => {
          const errorMessage = error.error?.error || 'Une erreur est survenue, réessayez plus tard.';
          return throwError(() => new Error(errorMessage));
        })
      );
  }

  /** POST /api/reset-password/<uidb64>/<token>/ : sans l'ancien mot de passe (lien demandé en
   * libre-service ou par un administrateur). */
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

  /** Révoque le refresh token (best-effort) puis vide toujours la session locale. */
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

  /** Basé uniquement sur le rôle PROD réel : sert à des décisions de confidentialité qui ne doivent
   * pas s'élargir avec un accès démo. Voir DOCUMENTATION.md, § 6.1. */
  isAdmin(): boolean {
    return this.getCurrentUser()?.type === UserRole.RESCUE ||
      this.getCurrentUser()?.type === UserRole.LOCAL_AUTH||
      this.getCurrentUser()?.type === UserRole.ADMIN ||
      this.getCurrentUser()?.type === UserRole.REGULATEUR;
  }

  isSysAdmin(): boolean {
    return this.isAdmin();
  }

  /** Rôle effectif de la requête en cours (miroir de get_effective_role) : pilote la barre latérale. */
  getEffectiveRole(): UserRole | null {
    if (this.getEnvironment() === 'DEMO') {
      return this.getCurrentUser()?.demo_role ?? null;
    }
    return this.getCurrentUser()?.type ?? null;
  }

  isInstitutionalEffective(): boolean {
    const role = this.getEffectiveRole();
    return role === UserRole.RESCUE || role === UserRole.LOCAL_AUTH ||
      role === UserRole.ADMIN || role === UserRole.REGULATEUR;
  }

  /** Zones (découpage PCS/PICS) : collectivités territoriales seulement, comme
   * _institution_est_autorite_locale côté backend. Un admin voit tout. */
  isAutoriteLocaleCommunale(): boolean {
    if (this.isAdmin()) return true;
    const code = this.getCurrentUser()?.institution_type_code;
    return code === 'MAIRIE' || code === 'EPCI' || code === 'CG' || code === 'CR';
  }

  /** Utilisé par adminGuard : un compte avec un simple accès démo n'entre dans /admin qu'en zone DEMO. */
  canEnterAdminArea(): boolean {
    if (this.isAdmin()) return true;
    return this.canAccessDemo() && this.getEnvironment() === 'DEMO';
  }

  isLoggedIn(): boolean {
    return !!this.getToken();
  }

  isEnable(): boolean {
    return this.getCurrentUser()?.enabled === true;
  }

  /** Zone active (PROD par défaut), envoyée par l'intercepteur dans X-Environment. */
  getEnvironment(): Environment {
    return (localStorage.getItem('active_environment') as Environment) || 'PROD';
  }

  /** Rechargement complet : toutes les données repartent sous le nouvel environnement. */
  setEnvironment(env: Environment): void {
    localStorage.setItem('active_environment', env);
    window.location.reload();
  }

  /** Bascule visible seulement si un admin a donné un demo_role à l'utilisateur. */
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
