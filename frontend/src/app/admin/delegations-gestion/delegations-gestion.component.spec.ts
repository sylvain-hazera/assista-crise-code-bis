import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { DelegationsGestionComponent } from './delegations-gestion.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { DelegationGestionService } from '../../services/delegation-gestion.service';

describe('DelegationsGestionComponent', () => {
  let service: DelegationGestionService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [DelegationsGestionComponent] });
    service = TestBed.inject(DelegationGestionService);
    spyOn(service, 'lister').and.returnValue(of([]));
  });

  it("n'engage pas une commune sans commune ni date de signature", () => {
    const c = TestBed.createComponent(DelegationsGestionComponent).componentInstance;
    c.portee = 'commune';
    expect(c.peutEngager).toBeFalse();
    c.choisir({ code: '42186', name: 'Rive-de-Gier', codesPostaux: ['42800'] } as any);
    expect(c.peutEngager).toBeFalse();
    c.saisie.signeeLe = '2026-11-15';
    expect(c.peutEngager).toBeTrue();
  });

  it('envoie la commune et la convention signée', () => {
    const creer = spyOn(service, 'creer').and.returnValue(of({ collectivite_nom: 'Mairie de Rive-de-Gier' } as any));
    const c = TestBed.createComponent(DelegationsGestionComponent).componentInstance;
    c.portee = 'commune';
    c.choisir({ code: '42186', name: 'Rive-de-Gier', codesPostaux: ['42800'] } as any);
    c.saisie = { reference: 'CONV-12', signeeLe: '2026-11-15', signataire: 'Claire Fontaine', qualite: 'Maire', dateFin: '' };
    c.engager();
    const envoye = creer.calls.mostRecent().args[0] as FormData;
    expect(envoye.get('commune_code')).toBe('42186');
    expect(envoye.get('convention_signee_le')).toBe('2026-11-15');
    expect(envoye.has('date_fin')).toBeFalse();
    expect(c.message).toContain('Mairie de Rive-de-Gier');
  });

  it('engage par défaut un département, par son numéro', () => {
    const creer = spyOn(service, 'creer').and.returnValue(of({ collectivite_nom: 'Conseil départemental — Loire' } as any));
    const c = TestBed.createComponent(DelegationsGestionComponent).componentInstance;
    expect(c.portee).toBe('departement');
    c.departementCode = '42';
    c.saisie.signeeLe = '2026-10-01';
    expect(c.peutEngager).toBeTrue();
    c.engager();
    expect((creer.calls.mostRecent().args[0] as FormData).get('departement_code')).toBe('42');
  });

  it('pendant une crise ouverte, affiche la confirmation demandée par le serveur', () => {
    spyOn(service, 'retirer').and.returnValue(throwError(() => ({
      error: { error: 'Une crise est ouverte', confirmation_requise: true, crises_ouvertes: ['Crue du Gier'] } })));
    const c = TestBed.createComponent(DelegationsGestionComponent).componentInstance;
    c.retirer({ id: 'd1', collectivite_nom: 'Mairie' } as any);
    expect(c.crisesOuvertes['d1']).toEqual(['Crue du Gier']);
  });
});
