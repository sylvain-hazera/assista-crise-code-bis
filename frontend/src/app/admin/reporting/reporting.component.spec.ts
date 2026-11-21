import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ReportingComponent } from './reporting.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { of } from 'rxjs';
import { TeamService } from '../../services/team.service';

describe('ReportingComponent', () => {
  let component: ReportingComponent;
  let fixture: ComponentFixture<ReportingComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [ReportingComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ReportingComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('élargit par défaut les offres à 15 km autour de ma zone, pas les demandes', () => {
    expect(component.echelle).toBe('rayon');
    expect(component.rayonKm).toBe(15);
    const offres = (component as any).buildEchelleParams(true);
    const demandes = (component as any).buildEchelleParams(false);
    expect(offres).toEqual({ scope: 'zone', rayon_km: '15' });
    expect(demandes).toEqual({ scope: 'zone' });
  });

  it("affecte une offre par l'action dédiée, jamais par un PATCH de l'équipe", () => {
    const equipes = TestBed.inject(TeamService);
    const equipe = { id: 'eq-1', name: 'Services techniques', assigned_offer_ids: [], member_ids: [] } as any;
    const assigner = spyOn(equipes, 'assignerRessource').and.returnValue(of(equipe));
    const patch = spyOn(equipes, 'patch');
    component.teams = [equipe];
    component.selectedRow = { id: 'offre-1', kind: 'Offer' } as any;
    component.assignTeamId = 'eq-1';
    component.submitAssignTeam();
    expect(assigner).toHaveBeenCalledWith('eq-1', 'offre-1');
    expect(patch).not.toHaveBeenCalled();
  });
});
