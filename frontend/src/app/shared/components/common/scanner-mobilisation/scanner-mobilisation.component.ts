import { CommonModule } from '@angular/common';
import {
  Component, ElementRef, EventEmitter, OnDestroy, Output, ViewChild, signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  VerdictMobilisation, VerificationMobilisationService,
} from '../../../../services/verification-mobilisation.service';
import { VerdictMobilisationComponent } from '../verdict-mobilisation/verdict-mobilisation.component';
import { LecteurQr, cameraDisponible, creerLecteurQr } from '../../../../services/lecteur-qr';

/**
 * Scanner de QR code d'attestation de mobilisation, avec la caméra du téléphone.
 *
 * Demande de Sylvain du 11/11/2026 : « un bouton pour ouvrir l'appareil photo d'un téléphone,
 * scanner un qrcode d'une demande de mobilisation, et que ça dise si la demande est validée ou
 * non ».
 *
 * **Le décodage** passe par `services/lecteur-qr.ts` : `BarcodeDetector` quand le navigateur
 * l'a (Chrome, Edge), sinon un décodeur intégré au site, chargé à la demande (Safari et iPhone,
 * depuis le 21/11/2026 — avant, l'iPhone n'avait que son appareil photo natif ou la saisie). La
 * saisie manuelle de la référence reste ouverte à tous.
 *
 * Deux garde-fous :
 *
 * - **la caméra est arrêtée dès qu'on ferme**, et à la destruction du composant. Une diode
 *   verte qui reste allumée après fermeture est le genre de détail qui fait désinstaller une
 *   application.
 * - **le texte lu est validé avant d'interroger le serveur** : un QR de carte de visite ne doit
 *   pas partir en requête, et l'écran doit dire « ce code n'est pas une attestation » plutôt
 *   que « introuvable », qui laisserait croire à une attestation périmée.
 */
@Component({
  selector: 'app-scanner-mobilisation',
  standalone: true,
  imports: [CommonModule, FormsModule, VerdictMobilisationComponent],
  templateUrl: './scanner-mobilisation.component.html',
  styleUrl: './scanner-mobilisation.component.scss',
})
export class ScannerMobilisationComponent implements OnDestroy {

  @Output() ferme = new EventEmitter<void>();
  @ViewChild('video') video?: ElementRef<HTMLVideoElement>;

  etat = signal<'inactif' | 'demarrage' | 'scan' | 'verdict'>('inactif');
  erreur = signal('');
  verdict = signal<VerdictMobilisation | null>(null);
  /** Saisie manuelle : le chemin de repli (pas de caméra, ou caméra refusée). */
  saisieManuelle = '';

  /** Vrai quand le navigateur donne accès à une caméra : le décodage, lui, est toujours
   * possible (décodeur du navigateur ou décodeur intégré). Lu une fois. */
  readonly decodageDisponible = cameraDisponible();

  private flux: MediaStream | null = null;
  private detecteur: LecteurQr | null = null;
  private boucle: number | null = null;

  constructor(private service: VerificationMobilisationService) {}

  ngOnDestroy(): void {
    this.arreter();
  }

  async demarrer(): Promise<void> {
    this.erreur.set('');
    this.verdict.set(null);
    if (!this.decodageDisponible) {
      this.erreur.set(
        "Ce navigateur ne donne pas accès à la caméra. Utilisez l'appareil photo de votre "
        + 'téléphone — il ouvrira directement la page de vérification — ou saisissez la '
        + 'référence ci-dessous.');
      return;
    }
    this.etat.set('demarrage');
    try {
      // `facingMode: environment` : la caméra arrière. Sans ça, un téléphone ouvre la caméra
      // selfie et on scanne un document qu'on ne voit pas.
      this.flux = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      });
      this.detecteur = await creerLecteurQr();
      this.etat.set('scan');
      // Après le changement d'état : l'élément <video> n'existe dans le DOM qu'une fois
      // `etat` à 'scan'.
      setTimeout(() => this.brancherLeFlux(), 0);
    } catch (err) {
      this.etat.set('inactif');
      this.arreter();
      // Le refus de permission est le cas le plus fréquent, et le message doit dire quoi
      // faire : « erreur caméra » n'aide personne.
      this.erreur.set(
        "Accès à la caméra refusé ou indisponible. Autorisez l'appareil photo pour ce site, "
        + 'ou saisissez la référence à la main.');
    }
  }

  private brancherLeFlux(): void {
    const element = this.video?.nativeElement;
    if (!element || !this.flux) { return; }
    element.srcObject = this.flux;
    element.play().catch(() => undefined);
    this.scruter();
  }

  /** Une image toutes les 400 ms : un QR tenu à la main n'a pas besoin de 60 images par
   * seconde, et décoder en continu chauffe le téléphone pour rien. */
  private scruter(): void {
    const element = this.video?.nativeElement;
    if (!element || !this.detecteur) { return; }
    this.boucle = window.setInterval(async () => {
      if (this.etat() !== 'scan' || !this.detecteur) { return; }
      try {
        const brut = await this.detecteur.lire(element);
        if (brut) { this.traiter(brut); }
      } catch {
        // Une image illisible n'est pas une erreur : on attend la suivante. Afficher un
        // message à chaque image floue rendrait l'écran inutilisable.
      }
    }, 400);
  }

  /** Ce qu'on fait d'un texte lu, qu'il vienne de la caméra ou de la saisie manuelle. */
  traiter(texte: string): void {
    const jeton = this.service.jetonDepuisTexte(texte);
    if (!jeton) {
      this.erreur.set("Ce code n'est pas une attestation de mobilisation.");
      return;
    }
    this.arreterLaCamera();
    this.etat.set('verdict');
    this.erreur.set('');
    this.service.verifier(jeton).subscribe({
      next: (verdict) => this.verdict.set(verdict),
      error: () => {
        this.verdict.set(null);
        // Distinct d'une attestation invalide, et c'est important : « révoquée » et « je n'ai
        // pas pu joindre le serveur » n'appellent pas la même décision sur le terrain.
        this.erreur.set(
          'Vérification impossible : le serveur est injoignable. Ne concluez rien de cet '
          + 'échec.');
      },
    });
  }

  verifierLaSaisie(): void {
    const texte = this.saisieManuelle.trim();
    if (!texte) { return; }
    this.traiter(texte);
  }

  /** Scanner le suivant : on repart sur la caméra sans refermer la fenêtre, parce qu'on
   * contrôle rarement une seule personne. */
  scannerLeSuivant(): void {
    this.verdict.set(null);
    this.saisieManuelle = '';
    this.etat.set('inactif');
    this.demarrer();
  }

  fermer(): void {
    this.arreter();
    this.ferme.emit();
  }

  private arreterLaCamera(): void {
    if (this.boucle !== null) {
      window.clearInterval(this.boucle);
      this.boucle = null;
    }
    this.flux?.getTracks().forEach(piste => piste.stop());
    this.flux = null;
  }

  private arreter(): void {
    this.arreterLaCamera();
    this.detecteur = null;
    this.etat.set('inactif');
  }
}
