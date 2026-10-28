import { TestBed } from '@angular/core/testing';

import { RequestService } from './request.service';
import { fournisseursDeTest } from '../testing/test-providers';

describe('HelpRequestService', () => {
  let service: RequestService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(RequestService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
