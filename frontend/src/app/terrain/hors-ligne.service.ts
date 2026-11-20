import { Injectable, NgZone, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { CoffreChiffre } from '../services/coffre-chiffre';

/** Une action faite sans réseau, à rejouer telle quelle (les deux sont idempotentes). */
export type ActionTerrain =
  | { genre: 'statut_mission'; mission: string; statut: string; faite_le: string }
  | { genre: 'accuse'; ids: string[]; etape: 'REMISE' | 'VUE' | 'LUE'; faite_le: string };

export interface CopieHorsLigne<T> { valeur: T; enregistree_le: string; }

/**
 * Le terrain sans réseau (DOSSIER-PWA-INTERVENANTS.md, lot 3).
 *
 * - Ce qui a été lu (missions, alertes) est gardé, chiffré, et remontré sans réseau, daté.
 * - Ce qui est fait sans réseau (« Je commence », « Terminé », lu) attend dans une file chiffrée
 *   et part dès que le réseau revient, ou à la prochaine ouverture : sur iPhone, rien ne part
 *   application fermée.
 * - À la déconnexion, tout est effacé, clés comprises.
 */
@Injectable({ providedIn: 'root' })
export class HorsLigneService {
  readonly enLigne = signal(typeof navigator === 'undefined' ? true : navigator.onLine);
  readonly enAttente = signal(0);

  private copies = new CoffreChiffre('assista-crise-terrain-copies');
  private file = new CoffreChiffre('assista-crise-terrain-envois');
  private envoiEnCours: Promise<number> | null = null;
  private demarre = false;

  constructor(private http: HttpClient, private zone: NgZone) {}

  demarrer(): void {
    if (this.demarre || typeof window === 'undefined') return;
    this.demarre = true;
    window.addEventListener('online', () => this.zone.run(() => { this.enLigne.set(true); this.envoyer(); }));
    window.addEventListener('offline', () => this.zone.run(() => this.enLigne.set(false)));
    this.compter().then(() => this.envoyer());
  }

  garder<T>(nom: string, valeur: T): Promise<void> {
    return this.copies.deposer(nom, { valeur, enregistree_le: new Date().toISOString() } satisfies CopieHorsLigne<T>);
  }

  relire<T>(nom: string): Promise<CopieHorsLigne<T> | null> {
    return this.copies.lire<CopieHorsLigne<T>>(nom);
  }

  /** Met une action en file ; son identifiant garde l'ordre dans lequel elle a été faite. */
  async differer(action: ActionTerrain): Promise<void> {
    const identifiant = `${Date.now().toString().padStart(15, '0')}-${crypto.randomUUID()}`;
    await this.file.deposer(identifiant, action);
    await this.compter();
  }

  /** Les actions en attente, dans l'ordre où elles ont été faites. */
  async enFile(): Promise<{ identifiant: string; valeur: ActionTerrain }[]> {
    return (await this.file.tout<ActionTerrain>()).sort((a, b) => a.identifiant.localeCompare(b.identifiant));
  }

  /** Rejoue la file. S'arrête au premier échec de réseau (on reprendra) ; une action que le
   * serveur refuse (mission close, droits retirés) est retirée : la rejouer n'y changerait rien.
   * Rend le nombre d'actions parties. */
  envoyer(): Promise<number> {
    this.envoiEnCours ??= this.vider().finally(() => { this.envoiEnCours = null; });
    return this.envoiEnCours;
  }

  private async vider(): Promise<number> {
    let parties = 0;
    for (const { identifiant, valeur } of await this.enFile()) {
      try {
        await firstValueFrom(this.rejouer(valeur));
        await this.file.retirer(identifiant);
        parties++;
      } catch (erreur) {
        if (erreur instanceof HttpErrorResponse && erreur.status >= 400 && erreur.status < 500 && erreur.status !== 401
            && erreur.status !== 408 && erreur.status !== 429) {
          await this.file.retirer(identifiant);
          continue;
        }
        break;                                          // pas de réseau, serveur indisponible
      }
    }
    await this.compter();
    return parties;
  }

  private rejouer(action: ActionTerrain) {
    const api = environment.apiUrl;
    return action.genre === 'statut_mission'
      ? this.http.patch(`${api}/missions/${action.mission}/`, { statut: action.statut })
      : this.http.post(`${api}/mes-notifications/accuser/`, { ids: action.ids, etape: action.etape });
  }

  private async compter(): Promise<void> {
    const nombre = (await this.file.tout()).length;
    this.zone.run(() => this.enAttente.set(nombre));
  }

  /** À la déconnexion. */
  async effacer(): Promise<void> {
    await Promise.all([this.copies.vider(), this.file.vider()]);
    this.enAttente.set(0);
  }

  /** Une erreur HTTP qui veut dire « pas de réseau » (ou serveur injoignable). */
  static estHorsLigne(erreur: unknown): boolean {
    return erreur instanceof HttpErrorResponse && (erreur.status === 0 || erreur.status >= 502);
  }
}
