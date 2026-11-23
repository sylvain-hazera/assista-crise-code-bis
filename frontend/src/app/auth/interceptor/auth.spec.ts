import { adresseDeNotreApi } from './auth';

describe('adresseDeNotreApi', () => {
  const site = 'https://www.assista-crise.fr';

  it('garde telle quelle une adresse de l API', () => {
    expect(adresseDeNotreApi('/api/institutions/', '/api', site)).toBe('/api/institutions/');
  });

  it('ramene un lien de pagination absolu du meme hote a la forme relative (23/11/2026)', () => {
    expect(adresseDeNotreApi(`${site}/api/institutions/?page=2`, '/api', site)).toBe('/api/institutions/?page=2');
  });

  it('meme hote mais en http (lien construit derriere le proxy) : ramene aussi', () => {
    expect(adresseDeNotreApi('http://www.assista-crise.fr/api/institutions/?page=3', '/api', site))
      .toBe('/api/institutions/?page=3');
  });

  it('ignore un autre hote ou un chemin hors de l API', () => {
    expect(adresseDeNotreApi('https://api-adresse.data.gouv.fr/search/?q=x', '/api', site)).toBeNull();
    expect(adresseDeNotreApi(`${site}/mobile/version.json`, '/api', site)).toBeNull();
  });

  it('API absolue (developpement) : lien suivant garde sa forme absolue', () => {
    expect(adresseDeNotreApi('http://localhost:8000/api/institutions/?page=2', 'http://localhost:8000/api', 'http://localhost:4200'))
      .toBe('http://localhost:8000/api/institutions/?page=2');
  });
});
