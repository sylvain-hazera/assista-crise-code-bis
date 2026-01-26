import { TestBed } from '@angular/core/testing';

import { HelpRequestService } from './help-request.service';

describe('HelpRequestService', () => {
  let service: HelpRequestService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(HelpRequestService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
