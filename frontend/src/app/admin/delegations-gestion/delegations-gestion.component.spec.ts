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

  it("lance l'amorçage d'une étape et garde son état", () => {
    const amorcer = spyOn(service, 'amorcer').and.returnValue(of({ id: 'a', debut: '', fin: null,
      etapes: { annuaire: { statut: 'EN_ATTENTE' } }, sites: [] }));
    const c = TestBed.createComponent(DelegationsGestionComponent).componentInstance;
    c.amorcer({ id: 'd1' } as any, 'annuaire');
    expect(amorcer).toHaveBeenCalledWith('d1', ['annuaire']);
    expect(c.amorcages['d1']?.etapes['annuaire'].statut).toBe('EN_ATTENTE');
    expect(c.comptesLisibles({ mairies_creees: 3 })).toBe('mairies creees : 3');
  });

  it("filtre l'arborescence par nom de commune, sans accents", () => {
    const c = TestBed.createComponent(DelegationsGestionComponent).componentInstance;
    const communes = [{ code: '42218', nom: 'Saint-Étienne', population: 1, mairie: null },
                      { code: '42186', nom: 'Rive-de-Gier', population: 1, mairie: null }];
    c.filtreArbre['d1'] = 'etienne';
    expect(c.communesFiltrees({ id: 'd1' } as any, communes).map(x => x.code)).toEqual(['42218']);
    c.filtreArbre['d1'] = '4218';
    expect(c.communesFiltrees({ id: 'd1' } as any, communes).map(x => x.code)).toEqual(['42186']);
  });

  it('coche les collectivités sans compte et les invite', () => {
    const inviter = spyOn(service, 'inviterCollectivites').and.returnValue(of({ envoyees: 2, sans_email: ['Mairie X'], deja_membres: 0 }));
    spyOn(service, 'arborescence').and.returnValue(of(null));
    const c = TestBed.createComponent(DelegationsGestionComponent).componentInstance;
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
});
