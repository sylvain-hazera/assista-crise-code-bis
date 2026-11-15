/** Animation du vent sur la carte : des particules portées par le champ de vent prévu, qui
 * laissent une courte traîne blanche.
 *
 * Écrit pour ce projet (15/11/2026). La technique est classique -- semer des points, les
 * déplacer avec le vent interpolé à leur position, estomper l'image précédente à chaque pas --
 * et ce fichier n'emprunte le code d'aucune carte existante.
 *
 * Trois choix :
 * - Les particules vivent en longitude/latitude, pas en pixels : elles restent à leur place
 *   quand la carte bouge, et seule leur traîne (dessinée à l'écran) est effacée.
 * - Leur vitesse à l'écran ne dépend pas du zoom : dix mètres par seconde font à peu près un
 *   pixel par image, à toutes les échelles. On lit la force du vent, pas l'échelle de la carte.
 * - Si le système demande de réduire les animations, rien ne bouge : on dessine une fois de
 *   courts traits qui montrent la direction. */

import { ChampVent } from '../../../models/veille.model';

export type { ChampVent };

export interface GrilleVent {
  largeur: number;
  hauteur: number;
  ouest: number;
  nord: number;
  pas: number;
  /** Composantes vers l'est et vers le nord, en m/s, ligne par ligne du nord au sud. */
  u: Float32Array;
  v: Float32Array;
}

export function decoderChampVent(champ: ChampVent): GrilleVent {
  const octets = atob(champ.donnees);
  const nombre = champ.largeur * champ.hauteur;
  if (octets.length < 2 * nombre) throw new Error('champ de vent tronqué');
  const u = new Float32Array(nombre);
  const v = new Float32Array(nombre);
  const echelle = 2 * champ.vitesse_max_ms / 255;
  for (let i = 0; i < nombre; i++) {
    u[i] = octets.charCodeAt(i) * echelle - champ.vitesse_max_ms;
    v[i] = octets.charCodeAt(nombre + i) * echelle - champ.vitesse_max_ms;
  }
  return { largeur: champ.largeur, hauteur: champ.hauteur, ouest: champ.ouest, nord: champ.nord, pas: champ.pas, u, v };
}

/** Vent (vers l'est, vers le nord) en m/s à un endroit, interpolé entre les quatre points
 * voisins de la grille. `null` hors de la grille. */
export function ventEn(grille: GrilleVent, longitude: number, latitude: number): [number, number] | null {
  const x = (longitude - grille.ouest) / grille.pas;
  const y = (grille.nord - latitude) / grille.pas;
  if (!(x >= 0 && y >= 0 && x <= grille.largeur - 1 && y <= grille.hauteur - 1)) return null;
  const x0 = Math.min(Math.floor(x), grille.largeur - 2);
  const y0 = Math.min(Math.floor(y), grille.hauteur - 2);
  const fx = x - x0;
  const fy = y - y0;
  const i = y0 * grille.largeur + x0;
  const melange = (champ: Float32Array) =>
    (champ[i] * (1 - fx) + champ[i + 1] * fx) * (1 - fy)
    + (champ[i + grille.largeur] * (1 - fx) + champ[i + grille.largeur + 1] * fx) * fy;
  return [melange(grille.u), melange(grille.v)];
}

const METRES_PAR_DEGRE = 111_320;

/** Position d'une particule après `secondes` passées dans un vent (u, v) en m/s. */
export function avancer(longitude: number, latitude: number, u: number, v: number, secondes: number): [number, number] {
  const resserrement = Math.max(0.2, Math.cos(latitude * Math.PI / 180));
  return [longitude + u * secondes / (METRES_PAR_DEGRE * resserrement), latitude + v * secondes / METRES_PAR_DEGRE];
}

/** Mètres couverts par un pixel de la carte (tuiles de 512 pixels) à ce zoom et cette latitude. */
export function metresParPixel(zoom: number, latitude: number): number {
  return 78_271.5 * Math.cos(latitude * Math.PI / 180) / Math.pow(2, zoom);
}

/** Ce que l'animation demande à la carte : rien de plus que ces quatre lectures. */
export interface CarteDuVent {
  project(position: [number, number]): { x: number; y: number };
  getBounds(): { getWest(): number; getEast(): number; getSouth(): number; getNorth(): number };
  getZoom(): number;
  getCenter(): { lat: number };
}

/** Pixels parcourus par image pour un vent de 1 m/s. */
const PIXELS_PAR_METRE_SECONDE = 0.1;
const DUREE_DE_VIE = 90;                 // en images
const SURFACE_PAR_PARTICULE = 950;       // pixels d'écran pour une particule
const PARTICULES_MIN = 250;
const PARTICULES_MAX = 2600;

export class AnimationVent {
  private grille: GrilleVent | null = null;
  /** Quatre nombres par particule : longitude, latitude, âge, durée de vie. */
  private particules = new Float32Array(0);
  private cadre: number | null = null;
  private readonly sansMouvement: boolean;

  constructor(private readonly carte: CarteDuVent, private readonly toile: HTMLCanvasElement,
              private readonly hasard: () => number = Math.random) {
    this.sansMouvement = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  get enMarche(): boolean { return this.cadre !== null; }
  get nombreDeParticules(): number { return this.particules.length / 4; }

  definirGrille(grille: GrilleVent): void {
    this.grille = grille;
    this.redimensionner();
  }

  /** À appeler quand la carte change de taille, et au démarrage : ajuste la toile et le nombre
   * de particules à la surface affichée. */
  redimensionner(): void {
    const largeur = this.toile.clientWidth || this.toile.width;
    const hauteur = this.toile.clientHeight || this.toile.height;
    const densite = Math.min(2, (typeof devicePixelRatio === 'number' && devicePixelRatio) || 1);
    this.toile.width = Math.round(largeur * densite);
    this.toile.height = Math.round(hauteur * densite);
    this.toile.getContext('2d')?.setTransform(densite, 0, 0, densite, 0, 0);
    const nombre = Math.max(PARTICULES_MIN, Math.min(PARTICULES_MAX, Math.round(largeur * hauteur / SURFACE_PAR_PARTICULE)));
    this.particules = new Float32Array(nombre * 4);
    for (let i = 0; i < nombre; i++) this.semer(i, true);
    this.effacer();
  }

  /** Efface les traînes (elles sont dessinées à l'écran : un déplacement de la carte les fausse). */
  effacer(): void {
    const contexte = this.toile.getContext('2d');
    if (!contexte) return;
    contexte.save();
    contexte.setTransform(1, 0, 0, 1, 0, 0);
    contexte.clearRect(0, 0, this.toile.width, this.toile.height);
    contexte.restore();
    // Sans animation, l'image fixe doit être redessinée pour la nouvelle vue.
    if (this.sansMouvement && this.grille) this.imageFixe();
  }

  demarrer(): void {
    if (this.cadre !== null || !this.grille) return;
    if (this.sansMouvement) { this.imageFixe(); return; }
    const boucle = () => {
      this.pas();
      this.cadre = requestAnimationFrame(boucle);
    };
    this.cadre = requestAnimationFrame(boucle);
  }

  arreter(): void {
    if (this.cadre !== null) cancelAnimationFrame(this.cadre);
    this.cadre = null;
    this.effacer();
  }

  /** Place une particule au hasard dans la partie visible de la grille. */
  private semer(rang: number, ageAuHasard = false): void {
    const bornes = this.carte.getBounds();
    const grille = this.grille;
    const ouest = grille ? Math.max(bornes.getWest(), grille.ouest) : bornes.getWest();
    const est = grille ? Math.min(bornes.getEast(), grille.ouest + (grille.largeur - 1) * grille.pas) : bornes.getEast();
    const nord = grille ? Math.min(bornes.getNorth(), grille.nord) : bornes.getNorth();
    const sud = grille ? Math.max(bornes.getSouth(), grille.nord - (grille.hauteur - 1) * grille.pas) : bornes.getSouth();
    const p = rang * 4;
    this.particules[p] = ouest + this.hasard() * Math.max(0, est - ouest);
    this.particules[p + 1] = sud + this.hasard() * Math.max(0, nord - sud);
    this.particules[p + 3] = DUREE_DE_VIE * (0.5 + this.hasard());
    // Au premier semis, des âges étalés : sans cela toutes les particules mourraient ensemble.
    this.particules[p + 2] = ageAuHasard ? this.hasard() * this.particules[p + 3] : 0;
  }

  /** Une image : estompe les traînes, avance chaque particule et trace son déplacement. */
  pas(estomper = true): void {
    const contexte = this.toile.getContext('2d');
    const grille = this.grille;
    if (!contexte || !grille) return;
    if (estomper) {
      contexte.globalCompositeOperation = 'destination-in';
      contexte.fillStyle = 'rgba(0, 0, 0, 0.90)';
      contexte.fillRect(0, 0, this.toile.width, this.toile.height);
      contexte.globalCompositeOperation = 'source-over';
    }
    const secondes = PIXELS_PAR_METRE_SECONDE * metresParPixel(this.carte.getZoom(), this.carte.getCenter().lat);
    contexte.strokeStyle = 'rgba(255, 255, 255, 0.9)';
    contexte.lineWidth = 1.3;
    contexte.lineCap = 'round';
    contexte.beginPath();
    for (let rang = 0; rang < this.particules.length / 4; rang++) {
      const p = rang * 4;
      const longitude = this.particules[p];
      const latitude = this.particules[p + 1];
      const vent = ventEn(grille, longitude, latitude);
      if (!vent || this.particules[p + 2]++ > this.particules[p + 3]) { this.semer(rang); continue; }
      const [longitude2, latitude2] = avancer(longitude, latitude, vent[0], vent[1], secondes);
      const depart = this.carte.project([longitude, latitude]);
      const arrivee = this.carte.project([longitude2, latitude2]);
      this.particules[p] = longitude2;
      this.particules[p + 1] = latitude2;
      // Un saut démesuré (bord de carte, repli du monde) n'est pas un déplacement : pas de trait.
      if (Math.abs(arrivee.x - depart.x) + Math.abs(arrivee.y - depart.y) > 60) continue;
      contexte.moveTo(depart.x, depart.y);
      contexte.lineTo(arrivee.x, arrivee.y);
    }
    contexte.stroke();
  }

  /** Animations réduites : quelques pas d'un coup, sans estompage -- de courts traits fixes. */
  private imageFixe(): void {
    for (let i = 0; i < 14; i++) this.pas(false);
  }
}
