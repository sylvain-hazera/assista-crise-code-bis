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

  it('constitue une équipe à partir des bénévoles cochés (23/11/2026)', () => {
    const equipes = TestBed.inject(TeamService);
    const creer = spyOn(equipes, 'depuisOffres').and.returnValue(of({ id: 'eq-9', name: 'Bénévoles — Rive-de-Gier' } as any));
    spyOn(component as any, 'chargerEquipes');
    component.criseId = 'crise-1';
    component.offresDisponibles = [
      { id: 'b1', title: 'Bras', offer_type_nom: 'Bénévolat', commune: 'Rive-de-Gier' },
      { id: 'b2', title: 'Bras 2', offer_type_nom: 'Bénévolat', commune: 'Rive-de-Gier' },
      { id: 'm1', title: 'Cuve', offer_type_nom: 'Matériel', commune: 'Lorette' },
    ] as any;
    component.seulementBenevoles = true;
    expect(component.offresAffichees.map(o => o.id)).toEqual(['b1', 'b2']);
    component.basculerBenevole(component.offresDisponibles[0]);
    component.basculerBenevole(component.offresDisponibles[1]);
    component.ouvrirEquipeBenevoles();
    expect(component.equipeBenevoles?.nom).toBe('Bénévoles — Rive-de-Gier');
    component.creerEquipeBenevoles();
    expect(creer).toHaveBeenCalledWith(jasmine.objectContaining({ crise: 'crise-1', offres: ['b1', 'b2'] }));
    expect(component.offresDisponibles.map(o => o.id)).toEqual(['m1']);
    expect(component.equipeBenevoles).toBeNull();
  });
});
