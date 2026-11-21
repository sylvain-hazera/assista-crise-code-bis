import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { CelluleCriseComponent } from './cellule-crise.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { TeamService } from '../../services/team.service';

describe('CelluleCriseComponent', () => {
  let component: CelluleCriseComponent;
  let fixture: ComponentFixture<CelluleCriseComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [CelluleCriseComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(CelluleCriseComponent);
    component = fixture.componentInstance;
  });

  it("affecte une offre par l'action dédiée (engagement, invitation, lien de confirmation)", () => {
    const equipes = TestBed.inject(TeamService);
    const equipe = { id: 'eq-1', name: 'Services techniques', assigned_offer_ids: [], member_ids: [] } as any;
    const assigner = spyOn(equipes, 'assignerRessource').and.returnValue(of(equipe));
    const patch = spyOn(equipes, 'patch');
    component.equipes = [{ team: equipe } as any];
    component.equipeOffre = { 'offre-1': 'eq-1' } as any;
    component.affecterOffre({ id: 'offre-1', title: 'Bénévolat' } as any);
    expect(assigner).toHaveBeenCalledWith('eq-1', 'offre-1');
    expect(patch).not.toHaveBeenCalled();
    expect(component.equipeOffre['offre-1']).toBeUndefined();
  });
});
