import { TestBed } from '@angular/core/testing';
import { CanActivateFn } from '@angular/router';

import { adminGuard } from './admin.guard';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('adminGuard', () => {
  const executeGuard: CanActivateFn = (...guardParameters) => 
      TestBed.runInInjectionContext(() => adminGuard(...guardParameters));

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
  });

  it('should be created', () => {
    expect(executeGuard).toBeTruthy();
  });
});
