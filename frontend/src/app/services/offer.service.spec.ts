import { TestBed } from '@angular/core/testing';

import { HelpProposeService } from './offer.service';

describe('HelpProposeService', () => {
  let service: HelpProposeService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(HelpProposeService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
