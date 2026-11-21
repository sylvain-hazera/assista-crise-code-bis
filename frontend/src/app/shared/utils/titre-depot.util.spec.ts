import { titreDepot } from './titre-depot.util';

describe('titreDepot', () => {
  it('nature, puis lieu, puis complément', () => {
    expect(titreDepot('Bénévolat', 'Saint-Chamond', 'Garage Martin')).toBe('Bénévolat — Saint-Chamond — Garage Martin');
  });
  it('ignore les morceaux vides', () => {
    expect(titreDepot('Pompage', '', null)).toBe('Pompage');
    expect(titreDepot('  ', undefined)).toBe('Dépôt');
  });
});
