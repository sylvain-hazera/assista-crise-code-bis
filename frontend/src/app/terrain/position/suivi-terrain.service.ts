import { Injectable, NgZone, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { CoffreChiffre } from '../../services/coffre-chiffre';
import { HorsLigneService } from '../hors-ligne.service';
import {
  ETAT_INITIAL, EtatSuivi, MotifArret, Releve, doitDemarrer, doitEnvoyer, engagementCourant, estActif, motifArret,
} from './regles-suivi';

interface EquipeEngagee { engagement_debut?: string | null; }

/** L'écran maintenu allumé (Safari 18.4 et plus) ; absent des types du DOM de ce projet. */
interface VerrouEcran { release(): Promise<void>; addEventListener(type: 'release', f: () => void): void; }
type NavigateurAvecVerrou = Navigator & { wakeLock?: { request(type: 'screen'): Promise<VerrouEcran> } };

const MOTIFS: Record<MotifArret, string> = {
  FIN_D_ENGAGEMENT: 'L\'engagement de votre équipe est terminé : le partage de position s\'est arrêté.',
  PLAFOND: 'Douze heures de partage : il s\'est arrêté. Relancez-le si l\'engagement continue.',
  MANUEL: 'Partage de position arrêté.',
};

/**
 * Le suivi de position en mission, dans l'application web (DOSSIER-PWA-INTERVENANTS.md, lot 5).
 *
 * Les règles sont celles de l'application Android (`regles-suivi.ts`) : jamais sans accord,
 * seulement pendant un engagement de l'équipe, douze heures au plus, une position toutes les
 * 30 s au plus vite et toutes les 5 min à l'arrêt. Le serveur ne garde que la dernière.
 *
 * **La limite d'iPhone, acceptée le 20/11/2026 :** rien ne part application fermée ou écran
 * éteint. Pendant le suivi, l'écran est donc maintenu allumé (Wake Lock), et l'écran le dit.
 * Sans réseau, seule la dernière position attend, et part au retour du réseau.
 */
@Injectable({ providedIn: 'root' })
export class SuiviTerrainService {
  readonly etat = signal<EtatSuivi>(ETAT_INITIAL);
  readonly actif = computed(() => estActif(this.etat()));
  /** Une équipe de la personne est engagée en ce moment (null : on ne sait pas encore). */
  readonly engagementEnCours = signal<boolean | null>(null);
  /** L'engagement en cours a été arrêté à la main : on propose de reprendre. */
  readonly arreteALaMain = computed(() => !this.actif() && !!this.etat().engagement_arrete
    && this.etat().engagement_arrete === this.engagement());
  readonly ecranMaintenu = signal(false);
  readonly message = signal<string | null>(null);
  /** La dernière position connue, pour les photos et la tournée. */
  readonly dernierePosition = signal<Releve | null>(null);

  private coffre = new CoffreChiffre('assista-crise-terrain-suivi');
  private readonly engagement = signal<string | null>(null);
  private surveillance: number | null = null;
  private verrou: VerrouEcran | null = null;
  private minuterie: number | null = null;
  private demarre = false;

  constructor(private http: HttpClient, private horsLigne: HorsLigneService, private zone: NgZone) {}

  /** À l'ouverture de l'espace terrain : reprend l'état, puis regarde s'il faut suivre. */
  async demarrer(): Promise<void> {
    if (this.demarre || typeof window === 'undefined') return;
    this.demarre = true;
    this.etat.set((await this.coffre.lire<EtatSuivi>('etat')) ?? ETAT_INITIAL);
    document.addEventListener('visibilitychange', () => {
      // Safari relâche l'écran allumé dès que l'application passe derrière : on le reprend.
      if (document.visibilityState === 'visible') this.zone.run(() => { this.maintenirEcran(); this.verifier(); });
    });
    this.minuterie = window.setInterval(() => this.verifier(), 5 * 60_000);
    await this.verifier();
  }

  /** Relit les équipes, puis démarre, poursuit ou arrête le suivi. */
  async verifier(): Promise<void> {
    let equipes: EquipeEngagee[] | null = null;
    try {
      equipes = await firstValueFrom(this.http.get<EquipeEngagee[]>(`${environment.apiUrl}/teams/mes-equipes/`));
    } catch {
      equipes = null;                                   // pas de nouvelles n'arrête rien
    }
    if (equipes) {
      this.engagement.set(engagementCourant(equipes));
      this.engagementEnCours.set(this.engagement() !== null);
    }
    const motif = motifArret(this.etat(), equipes, Date.now());
    if (motif) {
      await this.arreter(motif);
    } else if (equipes && doitDemarrer(this.etat(), equipes)) {
      await this.garder({ ...this.etat(), depuis: Date.now(), dernier_envoi: null });
      this.lancer();
    } else if (this.actif()) {
      this.lancer();                                    // reprise après un rechargement de la page
    }
  }

  /** « Partager ma position » : un geste de la personne, qui vaut accord pour les engagements
   * suivants (comme sur Android), jusqu'à ce qu'elle le retire. */
  async consentir(): Promise<void> {
    this.message.set(null);
    await this.garder({ ...this.etat(), consentement: true, engagement_arrete: null });
    await this.verifier();
    if (!this.actif() && this.engagementEnCours() === false) {
      this.message.set('C\'est noté : le partage démarrera au prochain engagement de votre équipe, application ouverte.');
    }
  }

  async retirerConsentement(): Promise<void> {
    await this.arreter('MANUEL');
    await this.garder({ ...ETAT_INITIAL });
  }

  /** Arrêt à la main : il vaut pour l'engagement en cours, pas pour le suivant. */
  async arreterALaMainMaintenant(): Promise<void> {
    await this.arreter('MANUEL');
    await this.garder({ ...this.etat(), engagement_arrete: this.engagement() });
  }

  async reprendre(): Promise<void> {
    await this.garder({ ...this.etat(), engagement_arrete: null });
    await this.verifier();
  }

  /** À la déconnexion : rien ne reste. */
  async toutEffacer(): Promise<void> {
    this.couper();
    if (this.minuterie !== null) window.clearInterval(this.minuterie);
    this.minuterie = null;
    this.demarre = false;
    this.etat.set(ETAT_INITIAL);
    this.dernierePosition.set(null);
    await this.coffre.vider();
  }

  private async arreter(motif: MotifArret): Promise<void> {
    const etaitActif = this.actif();
    this.couper();
    if (etaitActif) {
      await this.garder({ ...this.etat(), depuis: null });
      this.message.set(MOTIFS[motif]);
    }
  }

  private lancer(): void {
    if (this.surveillance !== null || !navigator.geolocation) return;
    this.surveillance = navigator.geolocation.watchPosition(
      p => this.zone.run(() => this.surReleve({
        latitude: p.coords.latitude, longitude: p.coords.longitude, instant: p.timestamp || Date.now(),
        precision_m: p.coords.accuracy ?? 0,
      })),
      erreur => this.zone.run(() => {
        if (erreur.code === erreur.PERMISSION_DENIED) {
          this.message.set('La position est refusée à cette application. Autorisez-la dans les réglages du téléphone '
            + '(sur iPhone : Réglages > Confidentialité > Service de localisation), puis rouvrez l\'application.');
          this.arreter('MANUEL');
        }
      }),
      { enableHighAccuracy: true, maximumAge: 15_000, timeout: 60_000 },
    );
    this.maintenirEcran();
  }

  private couper(): void {
    if (this.surveillance !== null) navigator.geolocation.clearWatch(this.surveillance);
    this.surveillance = null;
    this.verrou?.release().catch(() => {});
    this.verrou = null;
    this.ecranMaintenu.set(false);
  }

  private async maintenirEcran(): Promise<void> {
    const verrous = (navigator as NavigateurAvecVerrou).wakeLock;
    if (!this.actif() || this.verrou || !verrous || document.visibilityState !== 'visible') return;
    try {
      this.verrou = await verrous.request('screen');
      this.ecranMaintenu.set(true);
      this.verrou.addEventListener('release', () => this.zone.run(() => { this.verrou = null; this.ecranMaintenu.set(false); }));
    } catch {
      this.ecranMaintenu.set(false);                    // batterie faible, ou navigateur trop ancien
    }
  }

  private async surReleve(releve: Releve): Promise<void> {
    this.dernierePosition.set(releve);
    const etat = this.etat();
    if (!estActif(etat) || !doitEnvoyer(etat.dernier_envoi, releve)) return;
    await this.garder({ ...etat, dernier_envoi: releve });
    try {
      await firstValueFrom(this.http.post(`${environment.apiUrl}/ma-position/`, { latitude: releve.latitude, longitude: releve.longitude }));
    } catch (erreur) {
      if (HorsLigneService.estHorsLigne(erreur)) {
        await this.horsLigne.remplacer({ genre: 'position', latitude: releve.latitude, longitude: releve.longitude,
                                         faite_le: new Date(releve.instant).toISOString() });
      }
    }
  }

  private async garder(etat: EtatSuivi): Promise<void> {
    this.etat.set(etat);
    await this.coffre.deposer('etat', etat);
  }
}
