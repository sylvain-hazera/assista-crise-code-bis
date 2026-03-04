import { TestBed } from '@angular/core/testing';
import { CanActivateFn } from '@angular/router';

import { enableGuard } from './enable.guard';

describe('enableGuard', () => {
  const executeGuard: CanActivateFn = (...guardParameters) => 
      TestBed.runInInjectionContext(() => enableGuard(...guardParameters));

  beforeEach(() => {
    TestBed.configureTestingModule({});
  });

  it('should be created', () => {
    expect(executeGuard).toBeTruthy();
  });
});
