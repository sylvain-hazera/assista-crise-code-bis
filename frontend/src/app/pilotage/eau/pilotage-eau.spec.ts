import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { CircuitEau, PilotageService } from '../pilotage.service';
import { PilotageEauComponent } from './pilotage-eau.component';
import { CarteCodisComponent, couleurCodis } from '../../public/codis/carte-codis.component';

const api = environment.apiUrl;
const circuit = (champs: Partial<CircuitEau> = {}): CircuitEau => ({
  crise: 'c1', type: 'INCENDIE', propose: true, peut_piloter: true, activations: [], actifs: 0, lien_codis: null,
  prevenances_codis: [], codis_sans_accuse: 0, interlocuteurs_codis: 1,
  candidats: [{ id: 7, source: 'OSM', ref: '77', type_pei: 'PI', type_libelle: "Poteau d'incendie", ref_terrain: 'BI-12',
                debit: 60, volume: null, etat: 'INCONNU', distance_km: 0.4, latitude: 45.44, longitude: 4.388, attribution: null }],
  equipes: [{ id: 't1', nom: 'RCSC Saint-Étienne', indicatif: 'RCSC', effectif: 6 }],
  ...champs,
});

describe('Pilotage — points d’eau, circuit feu (24/11/2026)', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.removeItem('pilotage-crise');
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(),
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ jeton: 'abc' }), queryParamMap: convertToParamMap({}) } } }] });
    http = TestBed.inject(HttpTestingController);
  });

  it('propose, exige une équipe par point, puis active', async () => {
    const pilotage = TestBed.inject(PilotageService);
    pilotage.choisir('c1');
    const fixture = TestBed.createComponent(PilotageEauComponent);
    fixture.detectChanges();
    http.expectOne(r => r.url === `${api}/circuit-eau/` && !r.params.has('candidats')).flush(circuit());
    fixture.detectChanges();
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('Feu en cours');
    expect(texte).toContain("Poteau d'incendie BI-12");

    const composant = fixture.componentInstance;
    composant.choix[7] = true;
    await composant.activer();
    expect(composant.erreur()).toContain('équipe');
    http.expectNone(`${api}/circuit-eau/activer/`);

    composant.equipes[7] = 't1';
    const promesse = composant.activer();
    const envoi = http.expectOne(`${api}/circuit-eau/activer/`);
    expect(envoi.request.body).toEqual({ crise: 'c1', affectations: [{ pei: 7, equipe: 't1' }] });
    envoi.flush({ activations: [] });
    await promesse;
    http.expectOne(r => r.url === `${api}/circuit-eau/`).flush(circuit({
      propose: false, actifs: 1, codis_sans_accuse: 1,
      activations: [{ id: 'a1', nom: "Poteau d'incendie BI-12", type_pei: 'PI', debit: 60, volume: null, latitude: 45.44, longitude: 4.388,
                      pei: 7, statut: 'ACTIF', statut_libelle: 'Actif : remplissage possible', equipe: 'RCSC Saint-Étienne',
                      indicatif: 'RCSC', equipe_id: 't1', mission: 'm1', demande_le: '2026-11-24T13:00:00Z', en_route_le: null,
                      actif_le: '2026-11-24T13:05:00Z', ferme_le: null, codis_prevenu_le: '2026-11-24T13:05:00Z' }],
    }));
    fixture.detectChanges();
    const apres = fixture.nativeElement.textContent as string;
    expect(apres).toContain('Actif : remplissage possible');
    expect(apres).toContain('sans accusé de réception');
    expect(pilotage.pointsEauActifs()).toBe(1);
  });

  it('dit quand le CODIS manque à l’annuaire', () => {
    TestBed.inject(PilotageService).choisir('c1');
    const fixture = TestBed.createComponent(PilotageEauComponent);
    fixture.detectChanges();
    http.expectOne(r => r.url === `${api}/circuit-eau/`).flush(circuit({ interlocuteurs_codis: 0 }));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Aucun contact SDIS (CODIS)');
  });

  it('la carte du CODIS : sans compte, vert actif, lien périmé expliqué', () => {
    expect(couleurCodis('ACTIF')).toBe('#15803d');
    expect(couleurCodis('FERME')).toBe('#9ca3af');
    const fixture = TestBed.createComponent(CarteCodisComponent);
    fixture.detectChanges();
    const demande = http.expectOne(`${api}/public/codis/abc/`);
    demande.flush({ detail: 'Lien inconnu' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('plus valable');
    fixture.destroy();
  });
});
