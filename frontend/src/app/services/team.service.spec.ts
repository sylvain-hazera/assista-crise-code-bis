import { TestBed } from '@angular/core/testing';

import { TeamService } from './team.service';
import { fournisseursDeTest } from '../testing/test-providers';

describe('TeamService', () => {
  let service: TeamService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(TeamService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
