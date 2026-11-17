import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { RapportService } from './rapport.service';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';

describe('RapportService', () => {
  let service: RapportService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(RapportService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('demande chaque rapport à son adresse et le remet au navigateur', () => {
    spyOn(URL, 'createObjectURL').and.returnValue('blob:essai');
    spyOn(URL, 'revokeObjectURL');
    const remis: boolean[] = [];

    service.telecharger('dossier', 'd1', 'rapport-dossier').subscribe(r => remis.push(r));
    service.telecharger('mission', 'm1', 'rapport-mission').subscribe(r => remis.push(r));
    service.telecharger('crise', 'c1', 'rapport-crise').subscribe(r => remis.push(r));

    for (const chemin of ['dossiers/d1', 'missions/m1', 'crises/c1']) {
      const requete = http.expectOne(r => r.url === `${environment.apiUrl}/${chemin}/rapport/`);
      expect(requete.request.responseType).toBe('blob');
      requete.flush(new Blob(['%PDF'], { type: 'application/pdf' }));
    }
    expect(remis).toEqual([true, true, true]);

    service.telecharger('dossier', 'd1', 'rapport-dossier', true).subscribe();
    const toutes = http.expectOne(r => r.url === `${environment.apiUrl}/dossiers/d1/rapport/`);
    expect(toutes.request.params.get('photos')).toBe('toutes');
    toutes.flush(new Blob(['%PDF'], { type: 'application/pdf' }));
    expect(URL.createObjectURL).toHaveBeenCalled();
  });
});
