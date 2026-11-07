import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { AuthService } from '../auth/services/auth.service';
import { PositionEquipeService } from './position-equipe.service';

export interface Coordinates {
  latitude: number;
  longitude: number;
}

@Injectable({
  providedIn: 'root'
})
export class GeolocationService {
  private locationSubject = new BehaviorSubject<Coordinates | null>(null);
  public location$ = this.locationSubject.asObservable();

  private permissionGranted = false;

  private banApiUrl = 'https://api-adresse.data.gouv.fr/search/';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
    private positionEquipeService: PositionEquipeService
  ) {
    this.checkStoredLocation();
  }

  /** Capture opportuniste de la position d'un acteur institutionnel : à chaque fois que
   * l'app obtient une position GPS fraîche pour une autre raison (carte, adresse...), on en
   * profite pour rafraîchir sa "dernière position connue" affichée sur la carte admin — jamais
   * un traçage continu en tâche de fond, et pas grave si un appel échoue silencieusement. */
  private reportPositionIfInstitutional(coords: Coordinates): void {
    if (!this.authService.isAdmin()) return;
    this.positionEquipeService.reportMyPosition(coords.latitude, coords.longitude).subscribe({
      error: () => {}
    });
  }

  getCoordinates(addressQuery: string): Observable<any> {
    const url = `${this.banApiUrl}?q=${encodeURIComponent(addressQuery)}&limit=1`;
    return this.http.get<any>(url);
  }

  /** Autocomplétion d'adresse (plusieurs résultats). Si `bias` est fourni (position GPS de
   * l'utilisateur), la Base Adresse Nationale priorise les adresses proches — sans jamais
   * présumer que l'utilisateur s'y trouve réellement, juste un tri plus pertinent. */
  searchAddresses(query: string, bias?: { lat: number; lon: number }): Observable<any> {
    let url = `${this.banApiUrl}?q=${encodeURIComponent(query)}&limit=5`;
    if (bias) {
      url += `&lat=${bias.lat}&lon=${bias.lon}`;
    }
    return this.http.get<any>(url);
  }

  /** Géocodage inverse (coordonnées -> adresse/commune) via la Base Adresse Nationale. */
  reverseGeocode(lat: number, lng: number): Observable<any> {
    const url = `https://api-adresse.data.gouv.fr/reverse/?lon=${lng}&lat=${lat}`;
    return this.http.get<any>(url);
  }

  private checkStoredLocation(): void {
    const stored = localStorage.getItem('userLocation');
    if (stored) {
      this.locationSubject.next(JSON.parse(stored));
      this.permissionGranted = true;
    }
  }

  /** Dernière position connue, sans jamais rien demander au navigateur. */
  positionEnCache(): Coordinates | null {
    return this.locationSubject.value;
  }

  /** État de l'autorisation, quand le navigateur sait le dire (`navigator.permissions`,
   * Safari 16+). `null` = inconnu, ce qui n'est PAS un refus : on ne décide rien dessus. */
  async etatPermission(): Promise<PermissionState | null> {
    const permissions = (navigator as any).permissions;
    if (!permissions?.query) return null;
    try {
      const statut = await permissions.query({ name: 'geolocation' as PermissionName });
      return statut.state as PermissionState;
    } catch {
      // Certains navigateurs lèvent sur un nom de permission qu'ils ne connaissent pas.
      return null;
    }
  }

  /** Position pour un usage OPPORTUNISTE (biaiser une recherche d'adresse, centrer une carte
   * à l'ouverture) : ne déclenche **jamais** l'invite du navigateur. Résout `null` si on ne
   * sait pas déjà.
   *
   * C'est la correction du 07/11/2026, et elle n'est pas cosmétique. Deux appels demandaient la
   * position depuis `ngOnInit`, sans geste utilisateur : le champ d'adresse des formulaires
   * publics et la carte. Sur iOS, l'utilisateur voyait donc l'invite de Safari surgir au
   * CHARGEMENT de la page, sans comprendre pourquoi — et la refusait, ce qui est la réaction
   * normale. Or Safari mémorise ce refus pour tout le site et **ne repropose plus jamais** :
   * tous les usages légitimes qui suivent (bouton « utiliser ma position », signalement avec
   * photo géolocalisée) échouaient alors définitivement. Du point de vue de l'utilisateur,
   * « Safari bloque la géolocalisation ».
   *
   * Règle qui en découle : l'invite ne doit partir que d'un geste explicite, pour une
   * fonctionnalité que l'utilisateur vient de demander. */
  async positionSansInvite(): Promise<Coordinates | null> {
    const connue = this.positionEnCache();
    if (connue) return connue;
    if (!navigator.geolocation) return null;
    // Sans l'API Permissions (Safari < 16), on s'abstient : impossible de savoir si un appel
    // déclencherait une invite, et une invite non sollicitée est précisément le problème.
    if ((await this.etatPermission()) !== 'granted') return null;
    try {
      return await this.requestLocation();
    } catch {
      return null;
    }
  }

  requestLocation(): Promise<Coordinates> {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error('La géolocalisation n\'est pas supportée par votre navigateur'));
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (position) => {
          const coords: Coordinates = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude
          };
          
          this.locationSubject.next(coords);
          localStorage.setItem('userLocation', JSON.stringify(coords));
          this.permissionGranted = true;
          this.reportPositionIfInstitutional(coords);

          resolve(coords);
        },
        (error) => {
          let errorMessage = 'Erreur de géolocalisation';

          switch (error.code) {
            case error.PERMISSION_DENIED:
              // Sur iOS, Safari ne repropose jamais l'invite après un refus : dire où la
              // rétablir, sinon le message n'est pas actionnable et l'utilisateur conclut que
              // l'application est cassée.
              errorMessage = this.estIOS()
                ? 'Position refusée pour ce site. Safari ne redemandera pas : '
                  + 'Réglages > Apps > Safari > Position, puis « Demander » ou « Autoriser », '
                  + 'et rechargez la page.'
                : 'Permission refusée. Veuillez autoriser l\'accès à votre position.';
              break;
            case error.POSITION_UNAVAILABLE:
              errorMessage = 'Position indisponible.';
              break;
            case error.TIMEOUT:
              errorMessage = 'Délai d\'attente dépassé : le GPS n\'a pas répondu à temps.';
              break;
          }

          reject(new Error(errorMessage));
        },
        {
          // Haute précision conservée : un signalement de terrain doit être posé au bon
          // endroit. Mais deux réglages assouplis pour iOS, où le PREMIER point GPS demande
          // couramment plus de dix secondes :
          //  - délai porté à 20 s, sinon l'appel échoue alors que le téléphone cherchait ;
          //  - un point de moins d'une minute est accepté (`maximumAge`), au lieu d'exiger une
          //    mesure neuve à chaque appel — à cette échelle de temps on n'a pas bougé, et ça
          //    évite de rallumer le GPS pour rien.
          enableHighAccuracy: true,
          timeout: 20000,
          maximumAge: 60000
        }
      );
    });
  }

  hasPermission(): boolean {
    return this.permissionGranted;
  }

  /** iOS (iPhone/iPad), y compris iPadOS qui s'annonce « Macintosh » avec un écran tactile. */
  private estIOS(): boolean {
    const ua = navigator.userAgent || '';
    return /iPad|iPhone|iPod/.test(ua)
      || (/Macintosh/.test(ua) && (navigator as any).maxTouchPoints > 1);
  }

  /** Azimut (0-360°, 0=Nord) donné par la boussole du téléphone au moment de l'appel — doit
   * être invoqué depuis un geste utilisateur direct (ex: clic sur "Prendre une photo") car
   * iOS 13+ exige `DeviceOrientationEvent.requestPermission()` dans ce contexte précis pour
   * autoriser l'accès aux capteurs. Résout `null` si l'appareil/navigateur ne fournit aucune
   * lecture exploitable dans le délai imparti (desktop, permission refusée, capteur absent)
   * — l'azimut reste une donnée best-effort, jamais bloquante pour le signalement lui-même. */
  async getCurrentAzimuth(timeoutMs = 1500): Promise<number | null> {
    const DeviceOrientationEventTyped = (window as any).DeviceOrientationEvent;

    if (DeviceOrientationEventTyped?.requestPermission) {
      try {
        const permission = await DeviceOrientationEventTyped.requestPermission();
        if (permission !== 'granted') {
          return null;
        }
      } catch {
        return null;
      }
    }

    return new Promise<number | null>(resolve => {
      let settled = false;
      const finish = (value: number | null) => {
        if (settled) return;
        settled = true;
        window.removeEventListener('deviceorientationabsolute', onOrientation as any);
        window.removeEventListener('deviceorientation', onOrientation as any);
        resolve(value);
      };

      const onOrientation = (event: any) => {
        if (typeof event.webkitCompassHeading === 'number') {
          finish(event.webkitCompassHeading); // Safari iOS : déjà un cap boussole absolu.
        } else if (event.absolute && typeof event.alpha === 'number') {
          finish((360 - event.alpha) % 360); // Android/Chrome : alpha compte depuis le Nord, sens inverse.
        }
      };

      window.addEventListener('deviceorientationabsolute', onOrientation as any);
      window.addEventListener('deviceorientation', onOrientation as any);
      setTimeout(() => finish(null), timeoutMs);
    });
  }

  clearLocation(): void {
    localStorage.removeItem('userLocation');
    this.locationSubject.next(null);
    this.permissionGranted = false;
  }

}
