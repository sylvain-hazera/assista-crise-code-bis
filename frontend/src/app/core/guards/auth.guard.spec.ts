import { TestBed } from '@angular/core/testing';
import { CanActivateFn } from '@angular/router';

import { authGuard } from './auth.guard';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('authGuard', () => {
  const executeGuard: CanActivateFn = (...guardParameters) => 
      TestBed.runInInjectionContext(() => authGuard(...guardParameters));

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
  });

  it('should be created', () => {
    expect(executeGuard).toBeTruthy();
  });
});
