import { TestBed } from '@angular/core/testing';

import { CrisisService } from './crisis.service';
import { fournisseursDeTest } from '../testing/test-providers';

describe('CrisisService', () => {
  let service: CrisisService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(CrisisService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
