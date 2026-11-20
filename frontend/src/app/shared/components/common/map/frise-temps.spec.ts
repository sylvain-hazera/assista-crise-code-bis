import { calquesDuPas, construireFrise, ecartLisible, ImageRadarFrise, rangDeLInstant, rangMaintenant } from './frise-temps';

const T0 = Date.UTC(2026, 10, 20, 20, 0);     // dernière image observée
const MIN = 60_000;
const iso = (t: number) => new Date(t).toISOString();

/** Trois relevés (−10, −5, 0) puis trois estimations (+5, +10, +15). */
function radar(): ImageRadarFrise[] {
  return [-10, -5, 0, 5, 10, 15].map(m => ({
    instant: T0 + m * MIN, heure: iso(T0 + m * MIN), estimation: m > 0, minutes: Math.max(0, m),
  }));
}

/** Les quarts d'heure de Météo-France, de 20:00 à 21:00. */
const echeances = [0, 15, 30, 45, 60].map(m => iso(T0 + m * MIN));

describe('frise de temps unique', () => {
  it('enchaine relevés, nos estimations puis la prévision Météo-France', () => {
    const frise = construireFrise(radar(), echeances);
    expect(frise.map(p => p.nature)).toEqual(
      ['releve', 'releve', 'releve', 'estimation', 'estimation', 'estimation', 'prevision', 'prevision', 'prevision']);
    // Après la dernière estimation (+15) : 20:30, 20:45, 21:00 ; pas de doublon à 20:15.
    expect(frise.slice(6).map(p => (p.instant - T0) / MIN)).toEqual([30, 45, 60]);
    expect(rangMaintenant(frise)).toBe(2);
  });

  it('bascule les calques tout seul : le passé au radar, le futur aux prévisions', () => {
    const frise = construireFrise(radar(), echeances);
    // Passé : le relevé seul, aucune prévision.
    expect(calquesDuPas(frise[0])).toEqual({ radar: true, pluie: false, autresPrevisions: false });
    // Première heure : nos estimations pour la pluie, rafales et neige de Météo-France à côté.
    expect(calquesDuPas(frise[4])).toEqual({ radar: true, pluie: false, autresPrevisions: true });
    expect(frise[4].prevision).toBe(iso(T0 + 15 * MIN));       // +10 min : le quart d'heure le plus proche
    // Au-delà : la prévision Météo-France, pluie comprise.
    expect(calquesDuPas(frise[7])).toEqual({ radar: false, pluie: true, autresPrevisions: true });
  });

  it('sans radar, la frise est celle de la prévision ; sans prévision, celle du radar', () => {
    const seule = construireFrise([], echeances);
    expect(seule.every(p => p.nature === 'prevision' && p.radar === null)).toBeTrue();
    expect(rangMaintenant(seule, T0 + 20 * MIN)).toBe(1);
    expect(construireFrise(radar(), []).length).toBe(6);
    expect(construireFrise(radar(), [])[5].prevision).toBeNull();
  });

  it('retrouve l\'instant choisi quand la frise se reconstruit', () => {
    const frise = construireFrise(radar(), echeances);
    expect(rangDeLInstant(frise, T0 + 44 * MIN)).toBe(7);
  });

  it('dit l\'écart en mots', () => {
    expect(ecartLisible(T0, T0 + MIN)).toBe('maintenant');
    expect(ecartLisible(T0 + 45 * MIN, T0)).toBe('dans 45 min');
    expect(ecartLisible(T0 + 95 * MIN, T0)).toBe('dans 1 h 35');
    expect(ecartLisible(T0 - 10 * MIN, T0)).toBe('il y a 10 min');
  });
});
