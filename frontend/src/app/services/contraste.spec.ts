import {
  BLANC, ENCRE, ajusterPourFond, hexVersRgb, luminanceRelative,
  rapportContraste, rgbVersHex, texteLisibleSur,
} from './contraste';

/** Fonds réels du produit : clair = carte blanche, sombre = --ac-surface de styles.scss. */
const FOND_CLAIR = '#ffffff';
const FOND_SOMBRE = '#1c1f26';

describe('contraste', () => {
  describe('hexVersRgb', () => {
    it('lit les formes courte, longue, avec et sans diese', () => {
      expect(hexVersRgb('#fff')).toEqual({ r: 255, g: 255, b: 255 });
      expect(hexVersRgb('2563eb')).toEqual({ r: 37, g: 99, b: 235 });
      expect(hexVersRgb('  #2563EB ')).toEqual({ r: 37, g: 99, b: 235 });
    });

    it('rend null sur une valeur illisible plutot que de deviner', () => {
      for (const mauvais of ['', 'bleu', '#12345', '#xyzxyz', null as never]) {
        expect(hexVersRgb(mauvais)).toBeNull();
      }
    });
  });

  describe('rapportContraste', () => {
    it('donne 21 pour noir sur blanc et 1 pour une couleur sur elle-meme', () => {
      expect(rapportContraste(hexVersRgb('#000')!, hexVersRgb('#fff')!)).toBeCloseTo(21, 1);
      expect(rapportContraste(hexVersRgb('#2563eb')!, hexVersRgb('#2563eb')!)).toBeCloseTo(1, 5);
    });

    it('est symetrique', () => {
      const a = hexVersRgb('#2563eb')!;
      const b = hexVersRgb('#1c1f26')!;
      expect(rapportContraste(a, b)).toBeCloseTo(rapportContraste(b, a), 10);
    });
  });

  it('luminanceRelative encadre le noir et le blanc', () => {
    expect(luminanceRelative(hexVersRgb('#000')!)).toBeCloseTo(0, 5);
    expect(luminanceRelative(hexVersRgb('#fff')!)).toBeCloseTo(1, 5);
  });

  describe('texteLisibleSur', () => {
    it('met du blanc sur une marque foncee et de l encre sur une marque claire', () => {
      expect(texteLisibleSur('#1d4ed8')).toBe(BLANC);   // bleu Assista-Crise
      expect(texteLisibleSur('#ffd700')).toBe(ENCRE);   // or : le blanc y serait illisible
      expect(texteLisibleSur('#9acd32')).toBe(ENCRE);   // vert tilleul
    });

    it('retombe sur le blanc si la couleur est illisible', () => {
      expect(texteLisibleSur('pas-une-couleur')).toBe(BLANC);
    });
  });

  describe('ajusterPourFond', () => {
    it('ne touche pas une couleur deja conforme', () => {
      // #1d4ed8 sur blanc passe deja AA.
      expect(ajusterPourFond('#1d4ed8', FOND_CLAIR)).toBe('#1d4ed8');
    });

    it('eclaircit une marque foncee pour le fond sombre', () => {
      const ajustee = ajusterPourFond('#1d4ed8', FOND_SOMBRE);
      expect(ajustee).not.toBe('#1d4ed8');
      expect(rapportContraste(hexVersRgb(ajustee)!, hexVersRgb(FOND_SOMBRE)!)).toBeGreaterThanOrEqual(4.5);
    });

    it('assombrit une marque claire pour le fond clair', () => {
      const ajustee = ajusterPourFond('#ffd700', FOND_CLAIR);
      expect(rapportContraste(hexVersRgb(ajustee)!, hexVersRgb(FOND_CLAIR)!)).toBeGreaterThanOrEqual(4.5);
    });

    it('atteint AA sur les deux fonds pour un echantillon de marques plausibles', () => {
      const marques = [
        '#2563eb', '#1d4ed8', '#c1121f', '#006400', '#ffd700', '#9acd32',
        '#000000', '#ffffff', '#808080', '#ff00ff', '#00ffff', '#4b0082',
      ];
      for (const marque of marques) {
        for (const fond of [FOND_CLAIR, FOND_SOMBRE]) {
          const ajustee = ajusterPourFond(marque, fond);
          const rapport = rapportContraste(hexVersRgb(ajustee)!, hexVersRgb(fond)!);
          expect(rapport)
            .withContext(`${marque} sur ${fond} -> ${ajustee} (${rapport.toFixed(2)}:1)`)
            .toBeGreaterThanOrEqual(4.5);
        }
      }
    });

    it('conserve la teinte : une marque rouge reste rouge', () => {
      const ajustee = hexVersRgb(ajusterPourFond('#c1121f', FOND_SOMBRE))!;
      expect(ajustee.r).toBeGreaterThan(ajustee.g);
      expect(ajustee.r).toBeGreaterThan(ajustee.b);
    });

    it('rend la couleur telle quelle si elle est illisible', () => {
      expect(ajusterPourFond('bleu-marine', FOND_SOMBRE)).toBe('bleu-marine');
    });

    it('rend une couleur deja conforme sans y toucher, meme extreme', () => {
      // Blanc sur fond sombre et noir sur fond clair contrastent deja : aucun ajustement.
      expect(ajusterPourFond('#ffffff', FOND_SOMBRE)).toBe('#ffffff');
      expect(ajusterPourFond('#000000', FOND_CLAIR)).toBe('#000000');
    });

    it('quand il faut ajuster, ne bascule pas vers le blanc pur ni le noir pur', () => {
      // Les deux cas qui obligent reellement a bouger la luminosite.
      expect(ajusterPourFond('#ffffff', FOND_CLAIR)).not.toBe('#000000');
      expect(ajusterPourFond('#000000', FOND_SOMBRE)).not.toBe('#ffffff');
    });
  });

  it('rgbVersHex borne les valeurs hors plage', () => {
    expect(rgbVersHex({ r: -10, g: 300, b: 128 })).toBe('#00ff80');
  });
});
