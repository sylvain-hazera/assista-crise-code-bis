import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { VeilleService } from './veille.service';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';

/** Le radar a une mosaique par territoire (metropole, La Reunion, 20/11/2026) : la carte dit
 * ou elle regarde, et chaque image rappelle sa mosaique. Sans cela, une carte centree sur
 * La Reunion recevait la pluie de la metropole. */
describe('VeilleService : radar par mosaique', () => {
  it('envoie le centre de la carte et rappelle la mosaique dans les images', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    const service = TestBed.inject(VeilleService);
    const http = TestBed.inject(HttpTestingController);

    service.pluieRadar({ lat: -21.1234, lon: 55.4567 }).subscribe();
    const requete = http.expectOne(r => r.url === `${environment.apiUrl}/orages/radar/`);
    expect(requete.request.params.get('lat')).toBe('-21.123');
    expect(requete.request.params.get('lon')).toBe('55.457');
    requete.flush({});

    service.pluieRadar().subscribe();
    expect(http.expectOne(r => r.url === `${environment.apiUrl}/orages/radar/`).request.params.keys()).toEqual([]);
    http.verify();

    expect(service.imagePluieRadarUrl('2026-11-20T19:50:00Z', 'REUNION')).toContain('&zone=REUNION');
    expect(service.imagePluieEstimeeUrl(15, '2026-11-20T19:50:00Z', 'REUNION')).toContain('&zone=REUNION');
    expect(service.imagePluieRadarUrl('2026-11-20T19:50:00Z')).toContain('&zone=METROPOLE');
  });
});
