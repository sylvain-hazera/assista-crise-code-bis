import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { SuiviDepartementComponent } from './suivi-departement.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { DelegationGestionService } from '../../services/delegation-gestion.service';

const SUIVI = {
  departement: { code: '42', nom: 'Loire' },
  totaux: { communes: 3, epcis: 1, mairies_sur_la_plateforme: 2, ont_rejoint: 1, invitees: 1, sans_adresse: 1 },
  epcis: [{ code: '244200770', nom: 'Saint-Étienne Métropole', enrolement: 'invitee', communes: 3, ont_rejoint: 1, invitees: 1, sans_adresse: 1 }],
};

describe('SuiviDepartementComponent', () => {
  let service: DelegationGestionService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [SuiviDepartementComponent] });
    service = TestBed.inject(DelegationGestionService);
    spyOn(service, 'lister').and.returnValue(of([
      { id: 'd1', en_vigueur: true } as any, { id: 'd2', en_vigueur: true } as any, { id: 'd3', en_vigueur: false } as any]));
    spyOn(service, 'suivi').and.callFake((id: string) => of(id === 'd1' ? SUIVI as any : null));
  });

  it('ne garde que les délégations départementales en vigueur, et affiche leurs intercommunalités', () => {
    const f = TestBed.createComponent(SuiviDepartementComponent);
    f.detectChanges();
    expect(f.componentInstance.departements.length).toBe(1);
    expect(f.nativeElement.textContent).toContain('Saint-Étienne Métropole');
    expect(f.nativeElement.textContent).toContain('1 / 3 communes ont rejoint');
  });

  it('déplie une intercommunalité à la demande, et la replie', () => {
    const branche = spyOn(service, 'suiviBranche').and.returnValue(of({ code: '244200770', nom: 'Métropole', enrolement: null,
      pics: null, communes: [{ code: '42186', nom: 'Rive-de-Gier', population: 15000, enrolement: 'a_rejoint',
        pcs: { parties_faites: 11, parties_total: 16, pourcentage: 69, restantes: ['Exercices'], arrete_date: null, date_maj: null } }] } as any));
    const f = TestBed.createComponent(SuiviDepartementComponent);
    f.detectChanges();
    const c = f.componentInstance;
    c.ouvrir('244200770');
    expect(branche).toHaveBeenCalledWith('d1', '244200770');
    expect(c.branche?.communes[0].pcs?.pourcentage).toBe(69);
    expect(c.niveau(69)).toBe('moyen');
    c.ouvrir('244200770');
    expect(c.branche).toBeNull();
  });

  it("enregistre la personne référente puis ouvre la fenêtre d'invitation", () => {
    const coord = spyOn(service, 'coordonnees').and.returnValue(of({ ok: true }));
    const inviter = spyOn(service, 'inviterCollectivites');
    spyOn(service, 'suiviBranche').and.returnValue(of({ code: 'e', nom: 'M', enrolement: null, pics: null, institution: null, communes: [] } as any));
    const f = TestBed.createComponent(SuiviDepartementComponent);
    f.detectChanges();
    const c = f.componentInstance;
    c.epciOuvert = 'e';
    const mairie = { id: 'm1', nom: 'Mairie - Aboën', email: null, telephone: null, adresse: null, membres: 0, delegation: false } as any;
    c.modifierCoordonnees(mairie);
    c.saisie!.refNom = 'Julie Martin';
    c.saisie!.refEmail = 'j.martin@commune.exemple';
    c.enregistrerCoordonnees();
    expect(coord.calls.mostRecent().args[3]).toEqual({ nom: 'Julie Martin', fonction: '', email: 'j.martin@commune.exemple', telephone: null });
    c.inviterMaintenant(mairie);
    expect(inviter).not.toHaveBeenCalled();
    expect(c.fenetreInvitation).toEqual(['m1']);
  });
});
