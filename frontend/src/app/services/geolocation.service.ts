import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';
import { HttpClient } from '@angular/common/http';

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

  constructor(private http: HttpClient) {
    this.checkStoredLocation();
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
          
          resolve(coords);
        },
        (error) => {
          let errorMessage = 'Erreur de géolocalisation';
          
          switch (error.code) {
            case error.PERMISSION_DENIED:
              errorMessage = 'Permission refusée. Veuillez autoriser l\'accès à votre position.';
              break;
            case error.POSITION_UNAVAILABLE:
              errorMessage = 'Position indisponible.';
              break;
            case error.TIMEOUT:
              errorMessage = 'Délai d\'attente dépassé.';
              break;
          }
          
          reject(new Error(errorMessage));
        },
        {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0
        }
      );
    });
  }

  hasPermission(): boolean {
    return this.permissionGranted;
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
