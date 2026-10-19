import { Injectable } from '@angular/core';
import { PositionEquipeService } from './position-equipe.service';

const CLE_DESACTIVATION = 'suiviPositionPermanentDesactive';
const INTERVALLE_ENVOI_MS = 2 * 60_000;

/** Suivi de position permanent d'un intervenant, indépendant de Matrix (Element limite le
 * partage en direct à 8 h). Actif par défaut, sauf refus mémorisé ; l'invite du navigateur
 * reste le vrai garde-fou. Ne fonctionne que tant que l'app est ouverte.
 * Voir DOCUMENTATION.md, § 6.1. */
@Injectable({ providedIn: 'root' })
export class SuiviPositionPermanentService {

  private watchId: number | null = null;
  private dernierEnvoiMs = 0;

  constructor(private positionEquipeService: PositionEquipeService) {}

  get actif(): boolean {
    return this.watchId !== null;
  }

  get desactiveExplicitement(): boolean {
    return localStorage.getItem(CLE_DESACTIVATION) === 'true';
  }

  /** Démarre le suivi, sauf désactivation mémorisée. */
  demarrerSiConsentement(): void {
    if (!this.desactiveExplicitement) this.activer(false);
  }

  /** `demarrageManuel` : un clic sur le toggle efface le refus mémorisé. */
  activer(demarrageManuel = true): void {
    if (this.actif || !navigator.geolocation) return;
    this.watchId = navigator.geolocation.watchPosition(
      (position) => this.surNouvellePosition(position),
      () => { /* refus ou position indisponible : on retentera à la prochaine session */ },
      { enableHighAccuracy: false, maximumAge: 60_000, timeout: 30_000 },
    );
    if (demarrageManuel) localStorage.removeItem(CLE_DESACTIVATION);
  }

  desactiver(): void {
    if (this.watchId !== null) navigator.geolocation.clearWatch(this.watchId);
    this.watchId = null;
    localStorage.setItem(CLE_DESACTIVATION, 'true');
  }

  private surNouvellePosition(position: GeolocationPosition): void {
    const maintenant = Date.now();
    if (maintenant - this.dernierEnvoiMs < INTERVALLE_ENVOI_MS) return;
    this.dernierEnvoiMs = maintenant;
    this.positionEquipeService
      .reportMyPosition(position.coords.latitude, position.coords.longitude)
      .subscribe({ error: () => {} });
  }
}
