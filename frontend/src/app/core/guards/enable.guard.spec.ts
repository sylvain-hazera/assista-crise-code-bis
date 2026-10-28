import { TestBed } from '@angular/core/testing';
import { CanActivateFn } from '@angular/router';

import { enableGuard } from './enable.guard';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('enableGuard', () => {
  const executeGuard: CanActivateFn = (...guardParameters) => 
      TestBed.runInInjectionContext(() => enableGuard(...guardParameters));

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
  });

  it('should be created', () => {
    expect(executeGuard).toBeTruthy();
  });
});
