import { TestBed } from '@angular/core/testing';

import { OfferService } from './offer.service';
import { fournisseursDeTest } from '../testing/test-providers';

describe('OfferService', () => {
  let service: OfferService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(OfferService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
