import { TelephonePipe } from './telephone.pipe';

/**
 * Les numéros sont enregistrés en E.164 (voir backend/core/telephone.py) : c'est la seule
 * écriture que tous les fournisseurs de SMS acceptent. Mais « +262692123456 » ne se lit pas
 * à l'œil sur une fiche consultée en urgence — ce filtre rend la forme nationale quand le
 * pays est français, et laisse le reste tel quel.
 */
describe('TelephonePipe', () => {
  const pipe = new TelephonePipe();

  it('rend la forme française d\'un numéro métropolitain', () => {
    expect(pipe.transform('+33612345678')).toBe('06 12 34 56 78');
  });

  it('rend la forme locale pour l\'outre-mer', () => {
    // La Réunion : le numéro s'écrit bien 0692… sur place, même s'il voyage en +262.
    expect(pipe.transform('+262692123456')).toBe('06 92 12 34 56');
    expect(pipe.transform('+590690123456')).toBe('06 90 12 34 56');
    expect(pipe.transform('+596696123456')).toBe('06 96 12 34 56');
  });

  it('laisse un numéro étranger en E.164', () => {
    // C'est son écriture correcte : le réduire à une forme nationale le rendrait incomposable.
    expect(pipe.transform('+32470123456')).toBe('+32470123456');
  });

  it('ne touche pas à ce qui n\'est pas en E.164', () => {
    // Saisie ancienne, ou texte libre : on n'interprète pas ce qu'on n'est pas sûr de lire.
    expect(pipe.transform('0612345678')).toBe('0612345678');
    expect(pipe.transform('voir le standard')).toBe('voir le standard');
  });

  it('rend une chaîne vide pour un numéro absent', () => {
    // Et non « undefined » : c'est l'écran qui décide d'afficher « — », via son `|| '—'`.
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
  });
});
