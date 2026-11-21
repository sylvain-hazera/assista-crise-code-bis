/**
 * Lire un QR code dans l'image de la caméra, sur tous les téléphones (DOSSIER-PWA-INTERVENANTS.md,
 * lot 5).
 *
 * `BarcodeDetector`, l'API du navigateur, existe sur Chrome et Edge mais **pas sur Safari** : sans
 * autre décodeur, l'iPhone ne pouvait lire un QR qu'avec son appareil photo natif, hors de
 * l'application installée. Quand l'API manque, on charge donc `jsqr` (Apache-2.0, sans
 * dépendance), servi par le site comme le reste de l'application — aucun service tiers — et
 * seulement à ce moment-là : les autres navigateurs ne le téléchargent jamais.
 *
 * Les images sont analysées une à une en mémoire et jetées aussitôt : rien n'est enregistré, rien
 * n'est envoyé, sinon le texte lu.
 */

interface DetecteurCodes { detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>; }
declare const BarcodeDetector: (new (options?: { formats?: string[] }) => DetecteurCodes) | undefined;

export interface LecteurQr {
  /** Le texte du QR code visible dans l'image, ou null (le cas ordinaire : pas encore cadré). */
  lire(video: HTMLVideoElement): Promise<string | null>;
  /** 'navigateur' (BarcodeDetector) ou 'integre' (jsqr) : pour les essais et le diagnostic. */
  readonly moteur: 'navigateur' | 'integre';
}

/** Une image de 640 px de large suffit pour un QR tenu à la main, et se décode vite. */
const LARGEUR_ANALYSE = 640;

export function cameraDisponible(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

export async function creerLecteurQr(): Promise<LecteurQr> {
  if (typeof BarcodeDetector !== 'undefined') {
    try {
      const detecteur = new BarcodeDetector({ formats: ['qr_code'] });
      return {
        moteur: 'navigateur',
        lire: async (video) => (await detecteur.detect(video))[0]?.rawValue ?? null,
      };
    } catch {
      /* format non pris en charge : on passe au décodeur intégré */
    }
  }
  const jsQR = (await import('jsqr')).default;
  const canevas = document.createElement('canvas');
  const contexte = canevas.getContext('2d', { willReadFrequently: true })!;
  return {
    moteur: 'integre',
    lire: async (video) => {
      if (!video.videoWidth || !video.videoHeight) return null;
      const echelle = Math.min(1, LARGEUR_ANALYSE / video.videoWidth);
      canevas.width = Math.round(video.videoWidth * echelle);
      canevas.height = Math.round(video.videoHeight * echelle);
      contexte.drawImage(video, 0, 0, canevas.width, canevas.height);
      const image = contexte.getImageData(0, 0, canevas.width, canevas.height);
      return jsQR(image.data, image.width, image.height, { inversionAttempts: 'dontInvert' })?.data || null;
    },
  };
}
