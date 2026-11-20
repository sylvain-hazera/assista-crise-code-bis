import { Injectable, NgZone, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs/operators';
import { environment } from '../../environments/environment';

/**
 * Le site installable comme une application (DOSSIER-PWA-INTERVENANTS.md, 20/11/2026).
 *
 * - Deux applications sur le même site : « Terrain » (`/terrain`) et « Pilotage » (`/admin`,
 *   pour un poste de commandement sur iPad). La page dit lequel installer selon où l'on est.
 * - « Une nouvelle version est disponible » : la page publiée est relue de temps en temps ;
 *   si son code a changé, on le dit (un bouton recharge).
 * - Sur iPhone et iPad, Safari ne propose pas l'installation de lui-même : on explique comment.
 */
@Injectable({ providedIn: 'root' })
export class ApplicationInstallableService {
  /** Une version plus récente du site est publiée. */
  readonly nouvelleVersion = signal(false);
  /** Proposer d'installer l'application (iPhone ou iPad, pas encore installée). */
  readonly installationProposee = signal(false);
  readonly espace = signal<'terrain' | 'pilotage'>('terrain');

  static readonly ECARTEE = 'application-installation-ecartee';
  static readonly PERIODE_VERIFICATION_MS = 10 * 60_000;

  private demarre = false;

  constructor(private router: Router, private zone: NgZone) {}

  demarrer(): void {
    if (this.demarre) return;
    this.demarre = true;
    if (environment.production && typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => { /* site utilisable sans */ });
    }
    this.router.events.pipe(filter(e => e instanceof NavigationEnd)).subscribe(e => {
      this.suivreLEspace((e as NavigationEnd).urlAfterRedirects);
    });
    this.suivreLEspace(this.router.url);
    if (environment.production) {
      // Hors de la zone d'Angular : une minuterie dedans empêcherait la page d'être « stable ».
      this.zone.runOutsideAngular(() => setInterval(() => this.verifierLaVersion(), ApplicationInstallableService.PERIODE_VERIFICATION_MS));
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') this.verifierLaVersion(); });
    }
  }

  /** Terrain ou Pilotage : le manifeste et le nom de l'icône suivent l'espace affiché. */
  suivreLEspace(url: string): void {
    const espace = url.startsWith('/admin') ? 'pilotage' : 'terrain';
    this.espace.set(espace);
    document.querySelector('link[rel="manifest"]')?.setAttribute('href', `/api/pwa/manifeste/?espace=${espace}`);
    document.querySelector('meta[name="apple-mobile-web-app-title"]')
      ?.setAttribute('content', espace === 'pilotage' ? 'Pilotage' : 'Terrain');
    const concerne = url.startsWith('/admin') || url.startsWith('/terrain');
    this.installationProposee.set(concerne && ApplicationInstallableService.estAppareilApple() && !this.estInstallee()
      && localStorage.getItem(ApplicationInstallableService.ECARTEE) !== '1');
  }

  ecarterLInstallation(): void {
    localStorage.setItem(ApplicationInstallableService.ECARTEE, '1');
    this.installationProposee.set(false);
  }

  recharger(): void { location.reload(); }

  /** Relit la page publiée et compare son code (main-<empreinte>.js) à celui qui tourne. */
  async verifierLaVersion(): Promise<boolean> {
    const actuel = ApplicationInstallableService.codeDeLaPage(document.documentElement.outerHTML);
    if (!actuel) return false;
    try {
      const reponse = await fetch('/index.html', { cache: 'no-store' });
      if (!reponse.ok) return false;
      const publie = ApplicationInstallableService.codeDeLaPage(await reponse.text());
      const changee = !!publie && publie !== actuel;
      if (changee) this.zone.run(() => this.nouvelleVersion.set(true));
      return changee;
    } catch {
      return false;                       // hors ligne : on reverra au retour du réseau
    }
  }

  static codeDeLaPage(html: string): string | null {
    return html.match(/main-[A-Za-z0-9]+\.js/)?.[0] ?? null;
  }

  /** iPhone, iPod ou iPad (un iPad récent se présente comme un Mac, mais tactile). */
  static estAppareilApple(agent = navigator.userAgent, pointsTactiles = navigator.maxTouchPoints ?? 0): boolean {
    return /iPhone|iPad|iPod/.test(agent) || (/Macintosh/.test(agent) && pointsTactiles > 1);
  }

  estInstallee(): boolean {
    return (navigator as unknown as { standalone?: boolean }).standalone === true
      || (typeof matchMedia !== 'undefined' && matchMedia('(display-mode: standalone)').matches);
  }
}
