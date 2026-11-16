import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { PcsRisquesComponent } from './pcs-risques.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';

/** Paragraphe 1.1 du plan : les risques de la commune ont leur écran, et ce qu'on y écrit est
 * ce que le document du plan reprendra. */
describe('PcsRisquesComponent', () => {
  let fixture: ComponentFixture<PcsRisquesComponent>;
  let http: HttpTestingController;
  const api = environment.apiUrl;
  const RISQUE = { id: 'r1', institution: 'i1', risque_type: 't1', risque_nom: 'Inondation',
                   risque_generalites: 'Texte générique.', etat_des_lieux: '', enjeux: '', actif: true };

  function demarrer(suggestions: unknown[] = []) {
    fixture = TestBed.createComponent(PcsRisquesComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/dossier-pcs/`).flush({ institution: 'i1', commune: { nom: 'Saint-Chamond', code: '42207', population: null } });
    http.expectOne(r => r.url === `${api}/risques-communaux/` && r.params.get('institution') === 'i1').flush([RISQUE]);
    http.expectOne(`${api}/risques-majeurs-types/`).flush([
      { id: 't1', nom: 'Inondation', generalites: '', actif: true }, { id: 't2', nom: 'Feu de forêt', generalites: '', actif: true }]);
    http.expectOne(r => r.url === `${api}/risques-communaux/suggestions-georisques/`).flush({ suggestions, date_maj: null });
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [PcsRisquesComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('montre les risques déclarés, dit à quoi ils servent, et ne propose que ceux qui restent', () => {
    demarrer();

    const texte = (fixture.nativeElement as HTMLElement).textContent!;
    expect(texte).toContain('Inondation');
    expect(texte).toContain('À quoi cela sert ensuite');
    expect(texte).toContain("Rien n'oblige à tout remplir");
    expect(fixture.componentInstance.typesDisponibles.map(t => t.nom)).toEqual(['Feu de forêt']);
  });

  it('enregistre l’état des lieux et les enjeux écrits par la commune', () => {
    demarrer();
    const composant = fixture.componentInstance;
    composant.risques[0].etat_des_lieux = 'Le Gier déborde en rive gauche.';

    composant.enregistrer(composant.risques[0]);

    const requete = http.expectOne(`${api}/risques-communaux/r1/`);
    expect(requete.request.method).toBe('PATCH');
    expect(requete.request.body).toEqual({ etat_des_lieux: 'Le Gier déborde en rive gauche.', enjeux: '' });
    requete.flush(RISQUE);
    expect(composant.enregistre).toBe('r1');
  });

  it('déclare un risque suggéré par Géorisques sans jamais l’appliquer d’office', () => {
    demarrer([{ num_risque: '14', libelle: 'Mouvement de terrain', deja_declare: false }]);

    fixture.componentInstance.accepter(fixture.componentInstance.suggestions[0]);

    http.expectOne(`${api}/risques-majeurs-types/`).flush({ id: 't9', nom: 'Mouvement de terrain', generalites: '', actif: true });
    const creation = http.expectOne(r => r.url === `${api}/risques-communaux/` && r.method === 'POST');
    expect(creation.request.body).toEqual({ institution: 'i1', risque_type: 't9' });
    creation.flush({ ...RISQUE, id: 'r2' });
    http.expectOne(r => r.url === `${api}/risques-communaux/` && r.method === 'GET').flush([RISQUE]);
    expect(fixture.componentInstance.suggestionsADeclarer.length).toBe(0);
  });
});
