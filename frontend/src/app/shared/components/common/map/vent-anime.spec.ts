import { AnimationVent, ChampVent, avancer, decoderChampVent, metresParPixel, ventEn } from './vent-anime';

/** Champ tel que le serveur le rend : `octets` vaut pour chaque point, u puis v. */
function champ(largeur: number, hauteur: number, u: number[], v: number[]): ChampVent {
  const octet = (ms: number) => String.fromCharCode(Math.round((ms + 40) / 80 * 255));
  return { echeance: '2026-11-15T21:00:00Z', largeur, hauteur, ouest: -10, nord: 53, pas: 0.1, vitesse_max_ms: 40,
           donnees: btoa(u.map(octet).join('') + v.map(octet).join('')) };
}

describe('animation du vent', () => {
  /** Grille de 3 × 2 points : le vent d'ouest force d'ouest en est sur la ligne du nord. */
  const grille = () => decoderChampVent(champ(3, 2, [0, 10, 20, 0, 0, 0], [0, 0, 0, -8, -8, -8]));

  it('décode les deux composantes sans les mélanger', () => {
    const g = grille();

    expect(g.u.length).toBe(6);
    expect(g.u[1]).toBeCloseTo(10, 0);
    expect(g.u[2]).toBeCloseTo(20, 0);
    expect(g.v[0]).toBeCloseTo(0, 0);
    expect(g.v[3]).toBeCloseTo(-8, 0);
  });

  it('refuse un champ tronqué plutôt que d’inventer du vent', () => {
    expect(() => decoderChampVent({ ...champ(3, 2, [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]), largeur: 30 })).toThrow();
  });

  it('interpole le vent entre les points de la grille', () => {
    const g = grille();

    expect(ventEn(g, -10, 53)![0]).toBeCloseTo(0, 0);                 // sur un point
    expect(ventEn(g, -9.95, 53)![0]).toBeCloseTo(5, 0);               // à mi-chemin de deux points
    expect(ventEn(g, -9.8, 53)![0]).toBeCloseTo(20, 0);               // le bord est compte
    // À mi-hauteur : la moitié du vent du nord (ligne du sud), la moitié de celui d'ouest.
    const milieu = ventEn(g, -9.9, 52.95)!;
    expect(milieu[0]).toBeCloseTo(5, 0);
    expect(milieu[1]).toBeCloseTo(-4, 0);
  });

  it('ne rend rien hors de la grille', () => {
    const g = grille();

    expect(ventEn(g, -10.01, 53)).toBeNull();
    expect(ventEn(g, -9.79, 53)).toBeNull();
    expect(ventEn(g, -9.9, 53.01)).toBeNull();
    expect(ventEn(g, -9.9, 52.89)).toBeNull();
    expect(ventEn(g, NaN, 53)).toBeNull();
  });

  it('un vent d’ouest pousse vers l’est, un vent du nord vers le sud', () => {
    const [longitude, latitude] = avancer(2, 46, 10, -10, 3600);      // une heure à 10 m/s

    expect(longitude).toBeGreaterThan(2);
    expect(latitude).toBeLessThan(46);
    // 36 km vers le sud font un tiers de degré ; vers l'est, davantage de degrés à cette latitude.
    expect(46 - latitude).toBeCloseTo(0.323, 2);
    expect(longitude - 2).toBeCloseTo(0.323 / Math.cos(46 * Math.PI / 180), 2);
  });

  it('un pixel couvre deux fois moins de terrain à chaque cran de zoom', () => {
    expect(metresParPixel(6, 46) / metresParPixel(7, 46)).toBeCloseTo(2, 5);
    expect(metresParPixel(6, 0)).toBeCloseTo(1223, 0);
  });

  describe('sur la carte', () => {
    /** Carte factice : un degré vaut cent pixels, la vue couvre toute la grille. */
    const carte = {
      project: ([longitude, latitude]: [number, number]) => ({ x: (longitude + 10) * 100, y: (53 - latitude) * 100 }),
      getBounds: () => ({ getWest: () => -10, getEast: () => -9.8, getSouth: () => 52.9, getNorth: () => 53 }),
      getZoom: () => 9,
      getCenter: () => ({ lat: 52.95 }),
    };
    let toile: HTMLCanvasElement;

    beforeEach(() => {
      toile = document.createElement('canvas');
      toile.width = 400;
      toile.height = 300;
    });

    it('sème ses particules dans la partie visible de la grille, en nombre borné', () => {
      const animation = new AnimationVent(carte, toile);
      animation.definirGrille(grille());

      expect(animation.nombreDeParticules).toBeGreaterThanOrEqual(250);
      expect(animation.nombreDeParticules).toBeLessThanOrEqual(2600);
    });

    it('trace des traînes blanches là où le vent souffle', () => {
      const animation = new AnimationVent(carte, toile, () => 0.5);
      animation.definirGrille(grille());
      for (let i = 0; i < 5; i++) animation.pas();

      const pixels = toile.getContext('2d')!.getImageData(0, 0, toile.width, toile.height).data;
      let dessines = 0;
      for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 0) dessines++;
      expect(dessines).toBeGreaterThan(0);
    });

    it('ne dessine rien sans champ de vent, et efface tout à l’arrêt', () => {
      const animation = new AnimationVent(carte, toile);
      animation.pas();
      animation.demarrer();
      expect(animation.enMarche).toBeFalse();

      animation.definirGrille(grille());
      for (let i = 0; i < 5; i++) animation.pas();
      animation.arreter();

      const pixels = toile.getContext('2d')!.getImageData(0, 0, toile.width, toile.height).data;
      expect(pixels.some(valeur => valeur > 0)).toBeFalse();
      expect(animation.enMarche).toBeFalse();
    });
  });
});
