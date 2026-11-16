import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { BehaviorSubject, catchError, delay, map, Observable, of, tap, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { User, UserRole, UserPayload, Environment, EtatSecondFacteur } from '../../shared/models/user.model';
import { SuiviPositionPermanentService } from '../../services/suivi-position-permanent.service';
import { DefiInscriptionService } from './defi-inscription.service';

interface TokenResponse {
  access: string;    // JWT access (simplejwt)
  refresh: string;
}

interface LoginResponse extends TokenResponse {
  user: User;
  appareil?: string;
}

interface ActivationResponse {
  user: User;
  token: string;
  refresh: string;
  message: string;
  appareil?: string;
}

/** Erreur de connexion, avec ce qu'il faut pour que l'écran sache quoi proposer ensuite.
 * `code` reprend celui du serveur : `CODE_REQUIS` (le lien ne suffit pas, il faut le code de
 * sécurité), `SECOND_FACTEUR_A_ACTIVER` (délai passé : activer avant d'entrer),
 * `TROP_D_ESSAIS` (attendre). */
export class ErreurConnexion extends Error {
  constructor(message: string, public code = '') {
    super(message);
  }
}

export const CODE_REQUIS = 'CODE_REQUIS';
/** Lien reçu par e-mail sur un compte dont le code arrive aussi par e-mail : c'est le mot de
 * passe qui sert de second facteur. */
export const MOT_DE_PASSE_REQUIS = 'MOT_DE_PASSE_REQUIS';
export const SECOND_FACTEUR_A_ACTIVER = 'SECOND_FACTEUR_A_ACTIVER';

export interface PreparationSecondFacteur {
  mode: 'application' | 'email';
  /** Mode application : l'adresse otpauth. Mode e-mail : l'adresse du compte, masquée. */
  adresse: string;
  secret?: string;
  qr_svg?: string;
}

export interface ConfirmationSecondFacteur {
  codes_secours: string[];
  etat: EtatSecondFacteur;
  session?: { access: string; refresh: string; user: User; appareil: string };
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly url = `${environment.apiUrl}`;

  private defiInscription = inject(DefiInscriptionService);

  constructor(private http: HttpClient, private suiviPosition: SuiviPositionPermanentService) {}

  /** Stocke la session (access, refresh, utilisateur) ; appelé après /token/ et après activation. */
  setSession(accessToken: string, refreshToken: string, user: User): void {
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    localStorage.setItem('current_user', JSON.stringify(user));
    // Relance le suivi de position permanent s'il avait été activé (sans redemander l'accord).
    this.suiviPosition.demarrerSiConsentement();
  }

  // ── Connexion en étapes (15/11/2026) ───────────────────────────────────────────────────
  //
  // Adresse, puis — si le compte est protégé — code de sécurité, puis mot de passe. Tant que
  // le code n'a pas été donné, le serveur ne regarde pas le mot de passe.

  /** Jeton remis par le serveur à qui s'est identifié mais doit activer son code de sécurité
   * avant d'entrer. En mémoire seulement : il ne vaut que pour cette activation. */
  private jetonEnrolement: string | null = null;

  /** Ce que le navigateur présente pour être reconnu : un appareil déjà connu du compte n'est
   * pas ralenti par les essais ratés de quelqu'un d'autre. Ne dispense de rien. */
  private get appareil(): string {
    try { return localStorage.getItem('appareil_connu') || ''; } catch { return ''; }
  }

  private retenirAppareil(jeton?: string): void {
    if (!jeton) return;
    try { localStorage.setItem('appareil_connu', jeton); } catch { /* stockage indisponible */ }
  }

  private viderSessionLocale(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('current_user');
  }

  /** Traduit un refus du serveur. Retient le jeton d'activation s'il en vient un. */
  private erreurDeConnexion(error: HttpErrorResponse, parDefaut: string): ErreurConnexion {
    const code = error.error?.code || '';
    if (error.status === 403 && code === SECOND_FACTEUR_A_ACTIVER) {
      this.jetonEnrolement = error.error?.jeton_enrolement || null;
      // Une ancienne session expirée partirait avec les requêtes d'activation et les ferait
      // refuser avant même qu'elles soient lues.
      this.viderSessionLocale();
      return new ErreurConnexion(error.error?.detail || 'Activez votre code de sécurité pour continuer.', code);
    }
    if (error.status === 429) {
      return new ErreurConnexion(error.error?.detail || "Trop d'essais. Réessayez dans un moment.", 'TROP_D_ESSAIS');
    }
    if (error.status === 0) {
      return new ErreurConnexion('Impossible de contacter le serveur. Vérifiez votre connexion.');
    }
    if (error.status === 401 && (code === CODE_REQUIS || code === MOT_DE_PASSE_REQUIS)) {
      return new ErreurConnexion(error.error?.detail || 'Une vérification de plus est nécessaire.', code);
    }
    return new ErreurConnexion(error.error?.error || parDefaut, code);
  }

  /** POST /api/connexion/debut/ : ce que demander après l'adresse. Si le serveur ne répond
   * pas à cette question (satellite resté sur une version plus ancienne), on demande le mot
   * de passe, comme avant. */
  debutConnexion(email: string): Observable<'code' | 'mot_de_passe'> {
    return this.http
      .post<{ etape: 'code' | 'mot_de_passe' }>(`${this.url}/connexion/debut/`, { email, appareil: this.appareil })
      .pipe(
        map(res => res.etape),
        catchError((error: HttpErrorResponse) =>
          error.status === 404 ? of('mot_de_passe' as const)
            : throwError(() => this.erreurDeConnexion(error, 'Une erreur est survenue, réessayez.'))),
      );
  }

  /** POST /api/connexion/envoyer-code/ : renvoie le code d'un compte qui les reçoit par
   * e-mail. La réponse est la même pour toute adresse — elle ne dit pas si un message part. */
  renvoyerCode(email: string): Observable<string> {
    return this.http
      .post<{ detail: string }>(`${this.url}/connexion/envoyer-code/`, { email, appareil: this.appareil })
      .pipe(map(res => res.detail));
  }

  /** POST /api/connexion/code/ : rend le jeton d'étape à joindre au mot de passe. */
  verifierCode(email: string, code: string): Observable<string> {
    return this.http
      .post<{ jeton_etape: string }>(`${this.url}/connexion/code/`, { email, code, appareil: this.appareil })
      .pipe(
        map(res => res.jeton_etape),
        catchError((error: HttpErrorResponse) =>
          throwError(() => this.erreurDeConnexion(error, error.status === 401 ? 'Code incorrect.' : 'Une erreur est survenue, réessayez.'))),
      );
  }

  /** POST /api/token/ → { access, refresh, user } */
  login(email: string, password: string, jetonEtape = ''): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${this.url}/token/`, {
        email, password, jeton_etape: jetonEtape, appareil: this.appareil,
      })
      .pipe(
        tap(res => {
          this.retenirAppareil(res.appareil);
          this.setSession(res.access, res.refresh, res.user);
        }),
        catchError((error: HttpErrorResponse) =>
          throwError(() => this.erreurDeConnexion(error,
            error.status === 401 ? 'Email ou mot de passe incorrect'
              : 'Une erreur est survenue lors de la connexion'))),
      );
  }

  /** Lien reçu par e-mail (activation ou lien magique). Sans code : GET, comme toujours.
   * Avec le code de sécurité d'un compte protégé : le même lien, en POST. */
  private sessionParLien(chemin: string, parDefaut: string, code = '', motDePasse = ''): Observable<ActivationResponse> {
    const appel = code || motDePasse
      ? this.http.post<ActivationResponse>(`${this.url}/${chemin}/`, {
          code, mot_de_passe: motDePasse, appareil: this.appareil,
        })
      : this.http.get<ActivationResponse>(`${this.url}/${chemin}/`);
    return appel.pipe(
      tap(res => {
        this.retenirAppareil(res.appareil);
        this.setSession(res.token, res.refresh, res.user);
      }),
      catchError((error: HttpErrorResponse) =>
        throwError(() => this.erreurDeConnexion(error, parDefaut))),
    );
  }

  /** /api/activate-account/<uidb64>/<token>/ : active le compte → { user, token, refresh, message } */
  activateAccount(uidb64: string, token: string, code = '', motDePasse = ''): Observable<ActivationResponse> {
    return this.sessionParLien(`activate-account/${uidb64}/${token}`,
      "Ce lien d'activation est invalide ou a expiré", code, motDePasse);
  }

  /** /api/magic-login/<uidb64>/<token>/ : connexion par lien magique → { user, token, refresh, message } */
  magicLogin(uidb64: string, token: string, code = '', motDePasse = ''): Observable<ActivationResponse> {
    return this.sessionParLien(`magic-login/${uidb64}/${token}`,
      'Ce lien de connexion est invalide ou a expiré', code, motDePasse);
  }

  // ── Code de sécurité (second facteur) ──────────────────────────────────────────────────

  /** Vrai si la personne vient de s'identifier et doit activer son code avant d'entrer. */
  doitActiverSonCode(): boolean {
    return !!this.jetonEnrolement;
  }

  etatSecondFacteur(): Observable<EtatSecondFacteur> {
    return this.http.get<EtatSecondFacteur>(`${this.url}/second-facteur/`);
  }

  /** Tire un secret, pas encore actif. Depuis une session ouverte, le mot de passe est
   * redemandé ; pas depuis une activation obligatoire, où l'on vient de le donner. */
  preparerSecondFacteur(motDePasse = '', mode: 'application' | 'email' = 'application'): Observable<PreparationSecondFacteur> {
    return this.http.post<PreparationSecondFacteur>(`${this.url}/second-facteur/preparer/`, {
      mode, mot_de_passe: motDePasse, jeton_enrolement: this.jetonEnrolement || '',
    });
  }

  /** Mode e-mail : se faire envoyer un code — pendant l'activation, ou avant un acte qui en
   * demande un (retirer le code, tirer de nouveaux codes de secours). */
  envoyerCodeSecondFacteur(): Observable<{ envoye: boolean; detail: string }> {
    return this.http.post<{ envoye: boolean; detail: string }>(
      `${this.url}/second-facteur/envoyer-code/`, { jeton_enrolement: this.jetonEnrolement || '' });
  }

  /** Active le code. Si la personne attendait cela pour entrer, sa session s'ouvre. */
  confirmerSecondFacteur(code: string): Observable<ConfirmationSecondFacteur> {
    return this.http.post<ConfirmationSecondFacteur>(`${this.url}/second-facteur/confirmer/`, {
      code, jeton_enrolement: this.jetonEnrolement || '', appareil: this.appareil,
    }).pipe(tap(res => {
      if (res.session) {
        this.jetonEnrolement = null;
        this.retenirAppareil(res.session.appareil);
        this.setSession(res.session.access, res.session.refresh, res.session.user);
      } else {
        this.majEtatSecondFacteur(res.etat);
      }
    }));
  }

  retirerSecondFacteur(code: string): Observable<{ etat: EtatSecondFacteur }> {
    return this.http.post<{ etat: EtatSecondFacteur }>(`${this.url}/second-facteur/retirer/`, { code })
      .pipe(tap(res => this.majEtatSecondFacteur(res.etat)));
  }

  renouvelerCodesSecours(code: string): Observable<{ codes_secours: string[]; etat: EtatSecondFacteur }> {
    return this.http.post<{ codes_secours: string[]; etat: EtatSecondFacteur }>(
      `${this.url}/second-facteur/codes-secours/`, { code });
  }

  /** Garde le rappel d'échéance à jour sans attendre le prochain chargement du compte. */
  private majEtatSecondFacteur(etat: EtatSecondFacteur): void {
    const utilisateur = this.getCurrentUser();
    if (!utilisateur) return;
    localStorage.setItem('current_user', JSON.stringify({ ...utilisateur, second_facteur: etat }));
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

  /** POST /api/register/, accompagné du calcul anti-robot (voir DefiInscriptionService) :
   * rien à faire pour l'appelant, ni pour la personne. `piege` est la valeur du champ caché
   * du formulaire, que seul un robot remplit. */
  register(payload: UserPayload & { email: string; password: string }, piege = ''): Observable<User> {
    return this.defiInscription.avecDefi((defi) => this.http.post<User>(`${this.url}/register/`, {
      ...payload,
      ...(defi ? { defi } : {}),
      ...(piege ? { site_web: piege } : {}),
    }));
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

  /** Utilisé par adminGuard : un compte avec un simple accès démo n'entre dans /admin qu'en zone DEMO.
   *
   * Depuis le 10/11/2026, `acces_radio` ouvre aussi la porte : le porteur d'un nœud personnel
   * n'est pas forcément institutionnel, et il doit pouvoir atteindre /admin/radio et les écrans
   * radio pour régler son propre matériel. Il n'y gagne rien d'autre — chaque autre page garde
   * sa propre garde et le renvoie vers /admin/acces-refuse. */
  canEnterAdminArea(): boolean {
    if (this.isAdmin()) return true;
    if (this.getCurrentUser()?.acces_radio) return true;
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
