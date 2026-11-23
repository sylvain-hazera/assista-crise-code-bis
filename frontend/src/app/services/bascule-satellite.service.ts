import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from '../../environments/environment';
import { AuthService } from '../auth/services/auth.service';

/** Un satellite complet de mon institution, et où joindre son site sur le réseau du site. */
export interface SatelliteLocal {
  id: string;
  nom: string;
  institution: string;
  urls: string[];
  ips: string[];
  port_web: number;
  dernier_contact: string | null;
}

/**
 * Basculer vers le satellite quand le central ne répond pas (23/11/2026).
 *
 * « Les satellites s'annoncent en mDNS sur le réseau, et l'application, si elle ne se connecte
 * pas au central, détecte le satellite et s'y connecte, et le cas échéant demande l'IP. »
 *
 * Un navigateur ne parcourt pas le mDNS, et une page en https ne peut pas interroger une
 * adresse http du réseau local (contenu mixte bloqué) : la PWA ne SONDE donc pas. Elle garde,
 * tant que le central répond, la liste des satellites de l'institution (GET
 * /api/satellites/acces-local/ : `http://assista-crise.local/`, dernières IP), et quand le
 * central ne répond plus, elle propose de les OUVRIR — une navigation vers http est permise —,
 * ou de saisir l'adresse IP du satellite. On y retrouve ses identifiants habituels (comptes
 * recopiés sur le satellite).
 */
@Injectable({ providedIn: 'root' })
export class BasculeSatelliteService {
  static readonly CLE_SATELLITES = 'ac_satellites_locaux';
  static readonly CLE_IP_SAISIE = 'ac_satellite_ip_saisie';
  static readonly CLE_CENTRAL = 'ac_central_origine';
  /** Échecs réseau consécutifs avant de proposer la bascule : un seul raté n'est pas une panne. */
  static readonly SEUIL_ECHECS = 3;

  readonly centralInjoignable = signal(false);
  private echecs = 0;

  constructor(private http: HttpClient, private auth: AuthService) {}

  /** Appelé par l'intercepteur à chaque réponse de notre API. */
  noterReponse(ok: boolean): void {
    if (ok) {
      this.echecs = 0;
      if (this.centralInjoignable()) this.centralInjoignable.set(false);
      return;
    }
    this.echecs += 1;
    if (this.echecs >= BasculeSatelliteService.SEUIL_ECHECS && !this.surUnSatellite()) {
      this.centralInjoignable.set(true);
    }
  }

  /** Tant que le central répond : retenir les satellites et l'adresse du central. */
  rafraichir(): void {
    if (this.surUnSatellite() || !this.auth.getToken()) return;
    try { localStorage.setItem(BasculeSatelliteService.CLE_CENTRAL, location.origin); } catch { /* navigation privée */ }
    this.http.get<{ satellites: SatelliteLocal[] }>(`${environment.apiUrl}/satellites/acces-local/`).subscribe({
      next: ({ satellites }) => {
        try { localStorage.setItem(BasculeSatelliteService.CLE_SATELLITES, JSON.stringify(satellites)); } catch { /* idem */ }
      },
      error: () => { /* hors ligne ou non connecté : on garde la liste précédente */ },
    });
  }

  satellitesConnus(): SatelliteLocal[] {
    try {
      const brut = localStorage.getItem(BasculeSatelliteService.CLE_SATELLITES);
      const liste = brut ? JSON.parse(brut) : [];
      return Array.isArray(liste) ? liste : [];
    } catch {
      return [];
    }
  }

  ipSaisie(): string {
    try { return localStorage.getItem(BasculeSatelliteService.CLE_IP_SAISIE) || ''; } catch { return ''; }
  }

  /** Une adresse saisie à la main : une IP (avec port facultatif) ou un nom en .local. */
  static adresseValide(saisie: string): string | null {
    const s = saisie.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
    const ip = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(:\d{1,5})?$/.exec(s);
    if (ip) {
      return ip.slice(1, 5).every(o => Number(o) <= 255) ? `http://${s}/` : null;
    }
    return /^[a-z0-9-]{1,63}\.local(:\d{1,5})?$/i.test(s) ? `http://${s.toLowerCase()}/` : null;
  }

  /** Ouvre le satellite, à la même page (le pilotage reste le pilotage). */
  ouvrir(url: string, retenirSaisie?: string): void {
    if (retenirSaisie) {
      try { localStorage.setItem(BasculeSatelliteService.CLE_IP_SAISIE, retenirSaisie.trim()); } catch { /* idem */ }
    }
    this.naviguer(url.replace(/\/$/, '') + location.pathname + location.search);
  }

  /** Sur un satellite : l'adresse du central retenue, pour y revenir. */
  centralRetenu(): string | null {
    try { return localStorage.getItem(BasculeSatelliteService.CLE_CENTRAL); } catch { return null; }
  }

  /** Sur le site d'un satellite (nom en .local ou adresse privée), et non sur le central. */
  surUnSatellite(hote: string = location.hostname): boolean {
    return /\.local$/i.test(hote)
      || /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(hote);
  }

  /** À part pour les tests. */
  naviguer(url: string): void { window.location.href = url; }
}
