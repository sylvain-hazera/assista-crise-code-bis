import { TestBed } from '@angular/core/testing';

import { GeolocationService } from './geolocation.service';
import { fournisseursDeTest } from '../testing/test-providers';

describe('GeolocalisationService', () => {
  let service: GeolocationService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(GeolocationService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
