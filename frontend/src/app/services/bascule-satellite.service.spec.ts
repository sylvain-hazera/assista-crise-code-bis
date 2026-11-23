import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { BasculeSatelliteService } from './bascule-satellite.service';
import { fournisseursDeTest } from '../testing/test-providers';
import { AuthService } from '../auth/services/auth.service';

describe('BasculeSatelliteService', () => {
  let service: BasculeSatelliteService;

  beforeEach(() => {
    localStorage.removeItem(BasculeSatelliteService.CLE_SATELLITES);
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting(),
                  { provide: AuthService, useValue: { getToken: () => 'jeton' } }],
    });
    service = TestBed.inject(BasculeSatelliteService);
  });

  afterEach(() => localStorage.removeItem(BasculeSatelliteService.CLE_SATELLITES));

  it('propose la bascule après trois échecs réseau consécutifs, et la retire dès que le central répond', () => {
    spyOn(service, 'surUnSatellite').and.returnValue(false);
    service.noterReponse(false);
    service.noterReponse(false);
    expect(service.centralInjoignable()).toBeFalse();
    service.noterReponse(false);
    expect(service.centralInjoignable()).toBeTrue();
    service.noterReponse(true);
    expect(service.centralInjoignable()).toBeFalse();
  });

  it('accepte une IP privée ou un nom en .local, refuse le reste', () => {
    expect(BasculeSatelliteService.adresseValide('192.168.1.20')).toBe('http://192.168.1.20/');
    expect(BasculeSatelliteService.adresseValide('http://10.0.0.5:8080/pilotage')).toBe('http://10.0.0.5:8080/');
    expect(BasculeSatelliteService.adresseValide('Assista-Crise.local')).toBe('http://assista-crise.local/');
    expect(BasculeSatelliteService.adresseValide('999.1.1.1')).toBeNull();
    expect(BasculeSatelliteService.adresseValide('exemple.com')).toBeNull();
  });

  it('garde la liste des satellites du central, et ouvre le satellite à la même page', () => {
    spyOn(service, 'surUnSatellite').and.returnValue(false);
    const http = TestBed.inject(HttpTestingController);
    service.rafraichir();
    http.expectOne(r => r.url.endsWith('/satellites/acces-local/')).flush({ satellites: [
      { id: 's1', nom: 'Sat Porge', institution: 'Mairie', urls: ['http://assista-crise.local/'], ips: [], port_web: 80, dernier_contact: null },
    ] });
    expect(service.satellitesConnus().map(s => s.nom)).toEqual(['Sat Porge']);
    const nav = spyOn(service, 'naviguer');
    service.ouvrir('http://assista-crise.local/');
    expect(nav.calls.mostRecent().args[0]).toMatch(/^http:\/\/assista-crise\.local\//);
  });

  it('reconnaît le site d’un satellite', () => {
    expect(service.surUnSatellite('assista-crise.local')).toBeTrue();
    expect(service.surUnSatellite('192.168.1.20')).toBeTrue();
    expect(service.surUnSatellite('www.assista-crise.fr')).toBeFalse();
  });
});
