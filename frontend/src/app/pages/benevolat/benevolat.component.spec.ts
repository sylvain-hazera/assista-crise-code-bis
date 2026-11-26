import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { BenevolatComponent, Valorisation } from './benevolat.component';
import { fournisseursDeTest } from '../../testing/test-providers';

/** Bénévolat d'une association : valorisation, réglages, reçus (26/11/2026). */
describe('BenevolatComponent', () => {
  let fixture: ComponentFixture<BenevolatComponent>;
  let composant: BenevolatComponent;
  let http: HttpTestingController;

  const D: Valorisation = {
    annee: 2026, heures: '12.5', kilometres: '120', frais: '48.00', valorisation_heures: '150.25',
    reglages: { annee: 2026, taux_horaire: '12.02', tarif_km_voiture: '0.400', tarif_km_deux_roues: null, recus_fiscaux: false,
                fondement_recus: '', signataire_nom: '', signataire_qualite: '', dernier_recu: 0 },
    benevoles: [{ utilisateur: 'u1', nom: 'Léa Martin', heures: '12.5', kilometres: '120', frais: '48.00', valorisation: '150.25' }],
    activites: [], mois: [{ mois: '2026-03', heures: '12.5' }], lignes_a_valider: 0,
    abandons: [{ id: 'ab1', utilisateur: 'u1', nom: 'Léa Martin', annee: 2026, statut: 'DEMANDE', statut_libelle: 'Demandé',
                 montant: '48.00', kilometres: 120, deplacements: 2, numero_recu: '', date_recu: null, motif_refus: '', date_demande: '' }],
    associations_organisees: [{ id: 'a1', nom: 'Radio-club' }], taux_reduction_informatif: 66,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting()], imports: [BenevolatComponent] });
    fixture = TestBed.createComponent(BenevolatComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.method === 'GET' && r.url.endsWith('/benevolat/') && !r.params.has('institution'))
      .flush({ associations_organisees: [{ id: 'a1', nom: 'Radio-club' }] });
    http.expectOne(r => r.method === 'GET' && r.params.get('institution') === 'a1').flush(D);
    fixture.detectChanges();
  });

  afterEach(() => http.match(() => true));

  it('affiche la valorisation de l\'année', () => {
    const texte = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(texte).toContain('Léa Martin');
    expect(texte).toMatch(/150[.,]25/);
  });

  it('exige un signataire pour délivrer des reçus', () => {
    composant.reglages!.recus_fiscaux = true;
    composant.enregistrerReglages();
    expect(composant.erreur).toContain('signe');
    http.expectNone(r => r.method === 'PUT');
  });

  it('refuse une renonciation seulement avec un motif', () => {
    composant.traiter(D.abandons[0], 'refuser');
    expect(composant.erreur).toContain('pourquoi');
    composant.motif = 'Trajets non justifiés';
    composant.traiter(D.abandons[0], 'refuser');
    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/benevolat/abandons/ab1/'));
    expect(requete.request.body).toEqual({ geste: 'refuser', motif: 'Trajets non justifiés' });
    requete.flush({ ...D.abandons[0], statut: 'REFUSE', numero_recu: '' });
  });
});
