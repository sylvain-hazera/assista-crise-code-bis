import { Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
import { ApplicationInstallableService } from '../services/application-installable.service';
import { TerrainService } from './terrain.service';

/**
 * Où en sont les notifications poussées sur cet appareil :
 * - `indisponibles` : navigateur sans Web Push, ou serveur sans clé configurée ;
 * - `a-installer` : iPhone ou iPad, application pas encore sur l'écran d'accueil (Apple n'accorde
 *   les notifications qu'aux applications installées) ;
 * - `refusees` : la personne a dit non (à rétablir dans les Réglages) ;
 * - `inactives` : on peut les activer (un geste est exigé) ;
 * - `actives`.
 */
export type EtatNotifications = 'indisponibles' | 'a-installer' | 'refusees' | 'inactives' | 'actives';

/** Notifications poussées de l'application web (DOSSIER-PWA-INTERVENANTS.md, lot 4). */
@Injectable({ providedIn: 'root' })
export class NotificationsPousseesService {
  readonly etat = signal<EtatNotifications>('inactives');

  constructor(private http: HttpClient, private terrain: TerrainService, private installable: ApplicationInstallableService) {}

  private prises(): boolean {
    return typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window
      && typeof Notification !== 'undefined';
  }

  /** À l'ouverture de l'espace terrain : l'état, et l'abonnement redonné au serveur s'il existe
   * (un service de notification peut le renouveler de lui-même). */
  async actualiser(seulementSiAbonne = false): Promise<void> {
    // `seulementSiAbonne` (administration) : un poste de bureau ne doit pas devenir « joignable
    // par l'application » du seul fait d'ouvrir le site ; il ne se déclare qu'abonné.
    if (!this.prises()) {
      this.etat.set(ApplicationInstallableService.estAppareilApple() && !this.installable.estInstallee() ? 'a-installer' : 'indisponibles');
      return;
    }
    if (Notification.permission === 'denied') {
      this.etat.set('refusees');
      if (!seulementSiAbonne) this.presenter(false, '');
      return;
    }
    const abonnement = await this.abonnementActuel();
    if (abonnement && Notification.permission === 'granted') {
      this.etat.set('actives');
      this.presenter(true, abonnement.toJSON());
    } else {
      this.etat.set('inactives');
      if (!seulementSiAbonne) this.presenter(false);
    }
  }

  /** Sur un geste de la personne (exigé par Safari). Rend vrai si tout est en place. */
  async activer(): Promise<boolean> {
    if (!this.prises()) return false;
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') { this.etat.set(permission === 'denied' ? 'refusees' : 'inactives'); return false; }
    let cle: string;
    try {
      cle = (await firstValueFrom(this.http.get<{ cle: string }>(`${environment.apiUrl}/pwa/cle-push/`))).cle;
    } catch {
      this.etat.set('indisponibles');
      return false;
    }
    const enregistrement = await navigator.serviceWorker.ready;
    const abonnement = (await enregistrement.pushManager.getSubscription())
      ?? await enregistrement.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: NotificationsPousseesService.octets(cle) });
    this.presenter(true, abonnement.toJSON());
    this.etat.set('actives');
    return true;
  }

  /** À la déconnexion : ce navigateur ne reçoit plus rien pour cette personne. */
  async desactiver(): Promise<void> {
    const abonnement = await this.abonnementActuel();
    await abonnement?.unsubscribe().catch(() => false);
    this.etat.set('inactives');
  }

  private async abonnementActuel(): Promise<PushSubscription | null> {
    if (!this.prises()) return null;
    const enregistrement = await navigator.serviceWorker.getRegistration();
    return (await enregistrement?.pushManager.getSubscription()) ?? null;
  }

  private presenter(autorisees: boolean, abonnement?: PushSubscriptionJSON | ''): void {
    this.terrain.presenterLAppareil(autorisees, abonnement).subscribe({ error: () => {} });
  }

  /** La clé publique du serveur (base64url) en octets, comme l'attend `subscribe`. */
  static octets(base64url: string): Uint8Array<ArrayBuffer> {
    const base64 = (base64url + '='.repeat((4 - base64url.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/');
    const binaire = atob(base64);
    const octets = new Uint8Array(new ArrayBuffer(binaire.length));
    for (let i = 0; i < binaire.length; i++) octets[i] = binaire.charCodeAt(i);
    return octets;
  }
}
