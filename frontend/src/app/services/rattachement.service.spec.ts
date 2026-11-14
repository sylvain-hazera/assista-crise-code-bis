import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { RattachementService } from './rattachement.service';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';

/** L'adresse elle-même est testée : le 14/11/2026 la page « Rattachements » répondait
 * « Impossible de charger » en production parce que le service appelait
 * `contacts-institution` — sans le « s » de la route réelle. Les tests de la page simulaient
 * le service, donc rien ne lisait jamais l'adresse. */
describe('RattachementService', () => {
  it('interroge la route réelle des rattachements, paginée', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    const service = TestBed.inject(RattachementService);
    const http = TestBed.inject(HttpTestingController);

    service.rechercher({ page: 1, pageSize: 25, actif: true }).subscribe();

    const requete = http.expectOne(r => r.url === `${environment.apiUrl}/contacts-institutions/`);
    expect(requete.request.params.get('page')).toBe('1');
    expect(requete.request.params.get('actif')).toBe('true');
    requete.flush({ count: 0, next: null, previous: null, results: [] });
    http.verify();
  });
});
