import { Injectable } from '@angular/core';
import { PositionEquipeService } from './position-equipe.service';

const CLE_DESACTIVATION = 'suiviPositionPermanentDesactive';
const CLE_CONSENTEMENT = 'suiviPositionPermanentConsenti';
const INTERVALLE_ENVOI_MS = 2 * 60_000;

/** Suivi de position permanent d'un intervenant, indépendant de Matrix (Element limite le
 * partage en direct à 8 h). Ne fonctionne que tant que l'app est ouverte.
 * Voir DOCUMENTATION.md, § 6.1 et § 6.5.1.
 *
 * **Jamais démarré sans accord explicite** (correction du 07/11/2026). Le service était
 * « actif par défaut, sauf refus mémorisé », en comptant sur l'invite du navigateur comme
 * garde-fou. Conséquence : `AppComponent.ngOnInit` appelait `watchPosition` à **chaque
 * chargement de page, pour tout visiteur**, connecté ou non — donc l'invite de permission
 * surgissait au chargement, sans geste, y compris sur le site public.
 *
 * Sur iOS c'est rédhibitoire : un refus est définitif pour tout le site, Safari ne repropose
 * jamais. Cette invite non sollicitée condamnait donc toutes les autres utilisations de la
 * position (bouton « ma position », signalement géolocalisé) — c'est le « Safari bloque la
 * géoloc » signalé. La correction du matin avait traité les deux appels à
 * `getCurrentPosition` et manqué celui-ci, qui est pourtant le plus visible puisqu'il part à
 * chaque ouverture de page. */
@Injectable({ providedIn: 'root' })
export class SuiviPositionPermanentService {

  private watchId: number | null = null;
  private dernierEnvoiMs = 0;

  constructor(private positionEquipeService: PositionEquipeService) {}

  get actif(): boolean {
    return this.watchId !== null;
  }

  get desactiveExplicitement(): boolean {
    return this.lire(CLE_DESACTIVATION) === 'true';
  }

  /** L'utilisateur a activé le suivi lui-même, par le bouton de l'en-tête ou des paramètres. */
  get consentementExplicite(): boolean {
    return this.lire(CLE_CONSENTEMENT) === 'true';
  }

  /** `localStorage` peut **lever** — Safari en navigation privée, ou avec le blocage total des
   * cookies. Ce service est appelé depuis `AppComponent.ngOnInit` : une exception ici empêchait
   * l'initialisation de l'application entière, pour une simple préférence. On préfère perdre la
   * préférence (le suivi ne reprend pas tout seul) que l'application. */
  private lire(cle: string): string | null {
    try {
      return localStorage.getItem(cle);
    } catch {
      return null;
    }
  }

  private ecrire(cle: string, valeur: string | null): void {
    try {
      if (valeur === null) localStorage.removeItem(cle);
      else localStorage.setItem(cle, valeur);
    } catch {
      /* stockage indisponible : préférence non mémorisée, suivi inchangé pour cette session */
    }
  }

  /** Reprend le suivi au chargement de la page — **sans jamais provoquer d'invite**.
   *
   * Deux cas, et aucun autre :
   *  - l'utilisateur a activé le suivi lui-même : on reprend, l'invite éventuelle est alors
   *    attendue puisqu'il a demandé la fonctionnalité ;
   *  - comptes d'avant cette correction (aucun consentement enregistré, pas de refus non plus) :
   *    on ne reprend que si la permission est **déjà accordée**, ce qui ne déclenche aucune
   *    invite. Sans ce cas, un intervenant déjà suivi aujourd'hui s'arrêterait de l'être en
   *    silence au prochain déploiement.
   */
  async demarrerSiConsentement(): Promise<void> {
    if (this.desactiveExplicitement || this.actif || !navigator.geolocation) return;
    if (this.consentementExplicite) {
      this.activer(false);
      return;
    }
    if (await this.permissionDejaAccordee()) this.activer(false);
  }

  /** Vrai seulement si le navigateur affirme que la permission est accordée. Inconnu = non :
   * on ne parie pas, puisque c'est précisément l'invite qu'on cherche à ne pas déclencher.
   * (Safari ne conserve pas les accords comme Chrome et répond souvent « prompt » : le suivi
   * ne reprendra donc pas tout seul sur iOS, ce qui est le comportement voulu.) */
  private async permissionDejaAccordee(): Promise<boolean> {
    const permissions = (navigator as any).permissions;
    if (!permissions?.query) return false;
    try {
      const statut = await permissions.query({ name: 'geolocation' as PermissionName });
      return statut.state === 'granted';
    } catch {
      return false;
    }
  }

  /** `demarrageManuel` : un clic sur le toggle enregistre le consentement et efface le refus. */
  activer(demarrageManuel = true): void {
    if (this.actif || !navigator.geolocation) return;
    this.watchId = navigator.geolocation.watchPosition(
      (position) => this.surNouvellePosition(position),
      () => { /* refus ou position indisponible : on retentera à la prochaine session */ },
      { enableHighAccuracy: false, maximumAge: 60_000, timeout: 30_000 },
    );
    if (demarrageManuel) {
      this.ecrire(CLE_DESACTIVATION, null);
      this.ecrire(CLE_CONSENTEMENT, 'true');
    }
  }

  desactiver(): void {
    if (this.watchId !== null) navigator.geolocation.clearWatch(this.watchId);
    this.watchId = null;
    this.ecrire(CLE_DESACTIVATION, 'true');
    // Le consentement est retiré, pas seulement le suivi suspendu : sans ça, le prochain
    // chargement de page le relancerait.
    this.ecrire(CLE_CONSENTEMENT, null);
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
