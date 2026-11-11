import { CommonModule } from '@angular/common';
import {
  Component, ElementRef, EventEmitter, OnDestroy, Output, ViewChild, signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  VerdictMobilisation, VerificationMobilisationService,
} from '../../../../services/verification-mobilisation.service';
import { VerdictMobilisationComponent } from '../verdict-mobilisation/verdict-mobilisation.component';

/** `BarcodeDetector` n'est pas dans les types TypeScript du DOM : il est déclaré ici pour ne
 * pas avoir à désactiver le typage sur tout le fichier. */
interface DetecteurCodes {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}
declare const BarcodeDetector: {
  new (options?: { formats?: string[] }): DetecteurCodes;
  getSupportedFormats?: () => Promise<string[]>;
} | undefined;

/**
 * Scanner de QR code d'attestation de mobilisation, avec la caméra du téléphone.
 *
 * Demande de Sylvain du 11/11/2026 : « un bouton pour ouvrir l'appareil photo d'un téléphone,
 * scanner un qrcode d'une demande de mobilisation, et que ça dise si la demande est validée ou
 * non ».
 *
 * **Le décodage utilise `BarcodeDetector`, l'API du navigateur, et aucune bibliothèque.** Le
 * choix est assumé et il a une limite qu'il faut connaître : cette API existe sur Chrome et
 * Edge (Android et bureau), **pas sur Safari ni sur iOS**. Embarquer un décodeur JavaScript
 * aurait couvert l'iPhone au prix d'une dépendance de plus dans un projet qui n'en a aucune de
 * ce genre.
 *
 * La solution de repli n'est donc pas un message d'excuse : l'appareil photo **natif** d'un
 * iPhone lit déjà ce QR et ouvre la page de vérification publique, qui dit la même chose. Et
 * la saisie manuelle de la référence reste ouverte à tous. Un agent sur le terrain n'est jamais
 * bloqué — il passe simplement par un chemin différent.
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
  /** Saisie manuelle : le chemin de repli, et le seul disponible sur iOS. */
  saisieManuelle = '';

  /** Vrai quand le navigateur sait décoder un code-barres. Lu une fois : l'absence de l'API
   * ne change pas en cours de route, et l'écran doit pouvoir proposer autre chose
   * immédiatement plutôt qu'après un échec. */
  readonly decodageDisponible = typeof BarcodeDetector !== 'undefined';

  private flux: MediaStream | null = null;
  private detecteur: DetecteurCodes | null = null;
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
        "Ce navigateur ne sait pas décoder un QR code. Utilisez l'appareil photo de votre "
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
      this.detecteur = new BarcodeDetector!({ formats: ['qr_code'] });
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
        const codes = await this.detecteur.detect(element);
        const brut = codes[0]?.rawValue;
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
