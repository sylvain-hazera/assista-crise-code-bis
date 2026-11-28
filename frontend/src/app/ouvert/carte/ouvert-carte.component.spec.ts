import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';

import { OuvertCarteComponent } from './ouvert-carte.component';
import { fournisseursDeTest } from '../../testing/test-providers';

/** `/ouvert/carte` : la carte en mode ouvert ne demande rien qui touche une crise. */
describe('OuvertCarteComponent', () => {
  function creer(vue: string | null) {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting(), provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(vue ? { vue } : {}) } } }],
      imports: [OuvertCarteComponent],
    });
    const fixture = TestBed.createComponent(OuvertCarteComponent);
    return { fixture, http: TestBed.inject(HttpTestingController) };
  }

  it('ne charge ni crises, ni demandes, ni offres, ni centres', () => {
    const { fixture, http } = creer(null);
    fixture.detectChanges();
    const demandes = http.match(() => true).map(r => r.request.url);
    expect(demandes.some(u => /crises|requests|offers|demandes|offres|points-operationnels|carte-publique/.test(u))).toBeFalse();
    expect(demandes.some(u => u.endsWith('/carte-ouverte/propagation/'))).toBeTrue();
    expect(demandes.some(u => u.endsWith('/carte-ouverte/radio/couvertures/'))).toBeTrue();
  });

  it('ouvre sur la propagation avec ?vue=propagation', () => {
    const { fixture, http } = creer('propagation');
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/carte-ouverte/propagation/')).flush({
      hf: { kp: 2.67, kp_le: null, kp_max_prevu_3j: 4.33, flux_10cm: 91, eruption_max_24h: { classe: 'C2.1', le: '' }, g: 0, r: 0,
            g_libelle: 'aucun', r_libelle: 'aucun', effet_g: 'Champ magnétique calme.', effet_r: 'Pas de coupure radio liée aux éruptions.',
            prevision: [], releve_le: '' },
      hf_source: { source: 'NOAA', releve_le: null, perime: false },
      tropo: { nos_estimations: true, source: '', calcul: null, coins: [[0, 0], [1, 0], [1, 1], [0, 1]], limite: 'Maille ARPEGE.',
               legende: [], echeances: [{ echeance: '2026-11-28T12:00:00Z', classe_max: 2, part_conduit_pct: 4 }] },
    });
    fixture.detectChanges();
    const c = fixture.componentInstance;
    expect(c.vue).toBe('propagation');
    expect(c.tropo).toBeTrue();
    expect(c.echeance).toBe('2026-11-28T12:00:00Z');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Champ magnétique calme');
  });

  it('dit quand trop de calculs ont été demandés', () => {
    const { fixture, http } = creer('liaison');
    fixture.detectChanges();
    const c = fixture.componentInstance;
    c.liaison.a = { lat: 45.4, lng: 4.4 } as never;
    c.liaison.b = { lat: 45.5, lng: 4.5 } as never;
    c.calculerLiaison();
    http.expectOne(r => r.url.endsWith('/carte-ouverte/radio/liaison/')).flush({ detail: 'x' }, { status: 429, statusText: 'Trop' });
    expect(c.liaison.erreur).toContain('Trop de calculs');
  });
});
