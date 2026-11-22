import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { PilotageDepartementComponent } from './pilotage-departement.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { DelegationGestionService } from '../../services/delegation-gestion.service';

describe('PilotageDepartementComponent', () => {
  let service: DelegationGestionService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [PilotageDepartementComponent] });
    service = TestBed.inject(DelegationGestionService);
  });

  it("lance l'amorçage d'une étape et garde son état", () => {
    const amorcer = spyOn(service, 'amorcer').and.returnValue(of({ id: 'a', debut: '', fin: null,
      etapes: { annuaire: { statut: 'EN_ATTENTE' } }, sites: [] }));
    const c = TestBed.createComponent(PilotageDepartementComponent).componentInstance;
    c.amorcer({ id: 'd1' } as any, 'annuaire');
    expect(amorcer).toHaveBeenCalledWith('d1', ['annuaire']);
    expect(c.amorcages['d1']?.etapes['annuaire'].statut).toBe('EN_ATTENTE');
    expect(c.comptesLisibles({ mairies_creees: 3 })).toBe('mairies creees : 3');
  });

  it("filtre l'arborescence par nom de commune, sans accents", () => {
    const c = TestBed.createComponent(PilotageDepartementComponent).componentInstance;
    const communes = [{ code: '42218', nom: 'Saint-Étienne', population: 1, mairie: null },
                      { code: '42186', nom: 'Rive-de-Gier', population: 1, mairie: null }];
    c.filtreArbre['d1'] = 'etienne';
    expect(c.communesFiltrees({ id: 'd1' } as any, communes).map(x => x.code)).toEqual(['42218']);
    c.filtreArbre['d1'] = '4218';
    expect(c.communesFiltrees({ id: 'd1' } as any, communes).map(x => x.code)).toEqual(['42186']);
  });

  it('coche les collectivités sans compte et les invite', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    const inviter = spyOn(service, 'inviterCollectivites').and.returnValue(of({ envoyees: 2, sans_email: ['Mairie X'], deja_membres: 0 }));
    spyOn(service, 'arborescence').and.returnValue(of(null));
    const c = TestBed.createComponent(PilotageDepartementComponent).componentInstance;
    const d = { id: 'd1' } as any;
    const fiche = (id: string, membres = 0) => ({ id, nom: id, email: null, telephone: null, adresse: null, membres, delegation: false });
    c.arbres['d1'] = { departement: { code: '42', nom: 'Loire', institution: null }, totaux: { communes: 3, mairies_sur_la_plateforme: 3, epcis: 1 },
      epcis: [{ code: 'e', nom: 'Métropole', institution: fiche('epci'),
        communes: [{ code: '1', nom: 'A', population: 1, mairie: fiche('m1') }, { code: '2', nom: 'B', population: 1, mairie: fiche('m2', 3) }] }] };
    c.cocherToutesSansCompte(d);
    expect([...c.selection['d1']].sort()).toEqual(['epci', 'm1']);
    c.inviterSelection(d);
    expect(inviter.calls.mostRecent().args[1].sort()).toEqual(['epci', 'm1']);
    expect(c.message).toContain('Sans adresse officielle : Mairie X');
  });

  it('exporte les coordonnées de la sélection en CSV', () => {
    const exporter = spyOn(service, 'exporterCoordonnees').and.returnValue(of(new Blob(['a;b'])));
    const c = TestBed.createComponent(PilotageDepartementComponent).componentInstance;
    spyOn(URL, 'createObjectURL').and.returnValue('blob:x');
    spyOn(URL, 'revokeObjectURL');
    spyOn(HTMLAnchorElement.prototype, 'click');
    c.selection['d1'] = new Set(['m1', 'epci']);
    c.exporterSelection({ id: 'd1' } as any);
    expect(exporter).toHaveBeenCalledWith('d1', ['m1', 'epci']);
    expect(c.message).toContain('2 collectivité(s)');
  });

  it("charge l'historique quand on ouvre l'onglet", () => {
    const historique = spyOn(service, 'historique').and.returnValue(of([
      { date: '2026-11-22T08:00:00Z', type: 'journal', action: 'Export', par: 'Sylvain', texte: 'Export des coordonnées' } as any]));
    const c = TestBed.createComponent(PilotageDepartementComponent).componentInstance;
    c.delegation = { id: 'd1' } as any;
    c.vue = 'historique';
    c.ngOnChanges();
    expect(historique).toHaveBeenCalledWith('d1');
    expect(c.historique?.length).toBe(1);
  });

  it("n'envoie rien sans confirmation", () => {
    spyOn(window, 'confirm').and.returnValue(false);
    const inviter = spyOn(service, 'inviterCollectivites');
    const c = TestBed.createComponent(PilotageDepartementComponent).componentInstance;
    c.selection['d1'] = new Set(['m1']);
    c.inviterSelection({ id: 'd1' } as any);
    expect(inviter).not.toHaveBeenCalled();
  });
});
