import { TestBed } from '@angular/core/testing';
import { ApplicationInstallableService } from './application-installable.service';
import { fournisseursDeTest } from '../testing/test-providers';

describe('ApplicationInstallableService', () => {
  let service: ApplicationInstallableService;
  let lien: HTMLLinkElement;
  let titre: HTMLMetaElement;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    service = TestBed.inject(ApplicationInstallableService);
    lien = document.createElement('link'); lien.rel = 'manifest'; document.head.appendChild(lien);
    titre = document.createElement('meta'); titre.name = 'apple-mobile-web-app-title'; document.head.appendChild(titre);
    localStorage.removeItem(ApplicationInstallableService.ECARTEE);
  });
  afterEach(() => { lien.remove(); titre.remove(); });

  it('installe Terrain sur le terrain, Pilotage dans l\'administration', () => {
    service.suivreLEspace('/terrain/missions');
    expect(lien.getAttribute('href')).toBe('/api/pwa/manifeste/?espace=terrain');
    expect(titre.getAttribute('content')).toBe('Terrain');
    service.suivreLEspace('/admin/crises');
    expect(lien.getAttribute('href')).toBe('/api/pwa/manifeste/?espace=pilotage');
    expect(titre.getAttribute('content')).toBe('Pilotage');
    expect(service.espace()).toBe('pilotage');
  });

  it('reconnait un iPhone, et un iPad qui se dit Mac', () => {
    expect(ApplicationInstallableService.estAppareilApple('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', 5)).toBeTrue();
    expect(ApplicationInstallableService.estAppareilApple('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 5)).toBeTrue();
    expect(ApplicationInstallableService.estAppareilApple('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 0)).toBeFalse();
    expect(ApplicationInstallableService.estAppareilApple('Mozilla/5.0 (Linux; Android 14)', 5)).toBeFalse();
  });

  it('propose l\'installation sur un appareil Apple, sur Terrain ou Pilotage, jusqu\'à ce qu\'on l\'écarte', () => {
    spyOn(ApplicationInstallableService, 'estAppareilApple').and.returnValue(true);
    spyOn(service, 'estInstallee').and.returnValue(false);
    service.suivreLEspace('/');
    expect(service.installationProposee()).toBeFalse();            // page d'accueil publique : non
    service.suivreLEspace('/terrain');
    expect(service.installationProposee()).toBeTrue();
    service.ecarterLInstallation();
    service.suivreLEspace('/admin');
    expect(service.installationProposee()).toBeFalse();
  });

  it('annonce une nouvelle version quand le code publié a changé', async () => {
    const script = document.createElement('script');
    script.src = 'main-AAAA1111.js';
    document.body.appendChild(script);
    const fetchEspion = spyOn(window, 'fetch').and.resolveTo(new Response('<script src="main-AAAA1111.js"></script>'));
    expect(await service.verifierLaVersion()).toBeFalse();
    expect(service.nouvelleVersion()).toBeFalse();
    fetchEspion.and.resolveTo(new Response('<script src="main-BBBB2222.js"></script>'));
    expect(await service.verifierLaVersion()).toBeTrue();
    expect(service.nouvelleVersion()).toBeTrue();
    expect(fetchEspion.calls.mostRecent().args[1]).toEqual({ cache: 'no-store' });
    fetchEspion.and.rejectWith(new TypeError('hors ligne'));
    expect(await service.verifierLaVersion()).toBeFalse();
    script.remove();
  });
});
