import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

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

  constructor() {
    this.checkStoredLocation();
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

  clearLocation(): void {
    localStorage.removeItem('userLocation');
    this.locationSubject.next(null);
    this.permissionGranted = false;
  }
}
