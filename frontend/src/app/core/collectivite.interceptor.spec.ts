import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { collectiviteInterceptor } from './collectivite.interceptor';
import { CollectiviteConsulteeService } from './collectivite-consultee.service';

/**
 * « En précisant la collectivité » (28/10/2026).
 *
 * Ce qui compte ici n'est pas que le paramètre soit ajouté — c'est qu'il le soit UNIQUEMENT
 * sur les appels territoriaux. Un intercepteur qui ajoute un paramètre à des appels qui ne
 * l'attendent pas est une source de bugs qu'on ne relie jamais à leur cause.
 */
describe('collectiviteInterceptor', () => {
  let http: HttpClient;
  let controleur: HttpTestingController;
  let contexte: CollectiviteConsulteeService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([collectiviteInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controleur = TestBed.inject(HttpTestingController);
    contexte = TestBed.inject(CollectiviteConsulteeService);
    contexte.choisir(null);
  });

  afterEach(() => {
    contexte.choisir(null);
    controleur.verify();
  });

  it('n\'ajoute rien quand on consulte sa propre collectivité', () => {
    http.get('/api/demandes/vue_secteur/').subscribe();

    const requete = controleur.expectOne(r => r.url === '/api/demandes/vue_secteur/');
    expect(requete.request.params.has('commune')).toBeFalse();
    requete.flush([]);
  });

  it('ajoute la commune choisie sur un appel territorial', () => {
    contexte.choisir('29026');

    http.get('/api/demandes/vue_secteur/').subscribe();

    const requete = controleur.expectOne(r => r.url === '/api/demandes/vue_secteur/');
    expect(requete.request.params.get('commune')).toBe('29026');
    requete.flush([]);
  });

  it('n\'ajoute rien sur un appel qui n\'est pas territorial', () => {
    // Le point crucial : une liste de crises ou un profil n'attend pas ce paramètre.
    contexte.choisir('29026');

    http.get('/api/crises/').subscribe();

    const requete = controleur.expectOne('/api/crises/');
    expect(requete.request.params.has('commune')).toBeFalse();
    requete.flush([]);
  });

  it('n\'écrase pas une commune déjà posée par l\'appelant', () => {
    // Un écran qui demande explicitement une commune sait mieux que ce contexte global.
    contexte.choisir('29026');

    http.get('/api/demandes/vue_secteur/', { params: { commune: '29027' } }).subscribe();

    const requete = controleur.expectOne(r => r.url === '/api/demandes/vue_secteur/');
    expect(requete.request.params.get('commune')).toBe('29027');
    requete.flush([]);
  });

  it('conserve les autres paramètres', () => {
    contexte.choisir('29026');

    http.get('/api/offres/vue_secteur/', { params: { page: '1', type: 'Bénévolat' } }).subscribe();

    const requete = controleur.expectOne(r => r.url === '/api/offres/vue_secteur/');
    expect(requete.request.params.get('page')).toBe('1');
    expect(requete.request.params.get('type')).toBe('Bénévolat');
    expect(requete.request.params.get('commune')).toBe('29026');
    requete.flush([]);
  });
});
