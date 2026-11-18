import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { StandardCriseComponent } from './standard-crise.component';
import { fournisseursDeTest } from '../../testing/test-providers';

/** Standard de crise : la fiche d'appel, et le point de situation rassemblé par le serveur. */
describe('StandardCriseComponent', () => {
  let composant: StandardCriseComponent;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [StandardCriseComponent],
    });
    composant = TestBed.createComponent(StandardCriseComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.match(() => true));

  it('refuse une fiche sans objet, sans rien envoyer', () => {
    composant.enregistrer();
    expect(composant.erreur).toContain("objet de l'appel");
    http.expectNone(r => r.method === 'POST');
  });

  it('enregistre la fiche sur la crise choisie et repart d\'une fiche vide', () => {
    composant.criseId = 'c1';
    composant.saisie.objet = 'Cave inondée';
    composant.saisie.appelant_nom = 'Madame Durand';

    composant.enregistrer();

    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/standard-crise/appels/'));
    expect(requete.request.body).toEqual(jasmine.objectContaining({ crise: 'c1', nature: 'RENSEIGNEMENT', objet: 'Cave inondée' }));
    requete.flush({ numero: 7 });
    expect(composant.message).toContain('n° 7');
    expect(composant.saisie.objet).toBe('');
    expect(composant.saisie.appelant_nom).toBe('');
  });

  it('ne demande pas de point de situation sans crise', () => {
    composant.ouvrir('situation');
    http.expectNone(r => r.url.includes('/point-de-situation/'));
  });

  it('demande le point de situation de la crise choisie', () => {
    composant.criseId = 'c1';
    composant.ouvrir('situation');
    const requete = http.expectOne(r => r.url.includes('/point-de-situation/'));
    expect(requete.request.params.get('crise')).toBe('c1');
    requete.flush({ texte: 'POINT DE SITUATION', chiffres: {}, par_centre: [], equipes: [] });
    expect(composant.situation?.texte).toBe('POINT DE SITUATION');
  });
});
