import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { brouillonsEnvoiInterceptor } from './brouillons-envoi.interceptor';
import { BrouillonsEnvoiService } from './brouillons-envoi.service';

/** L'intercepteur est ce qui permet a la fenetre de relecture de s'ouvrir apres N'IMPORTE
 * QUELLE action, sans qu'aucun des 25 endpoints concernes ne change de contrat. S'il ne lit pas
 * l'en-tete, la fonctionnalite ne marche pas et rien ne le signale : la requete reussit, et le
 * message attend dans la liste jusqu'a son envoi automatique. */
describe('brouillonsEnvoiInterceptor', () => {
  let http: HttpClient;
  let controleur: HttpTestingController;
  let service: BrouillonsEnvoiService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([brouillonsEnvoiInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controleur = TestBed.inject(HttpTestingController);
    service = TestBed.inject(BrouillonsEnvoiService);
  });

  afterEach(() => controleur.verify());

  it('signale les identifiants annonces par l\'en-tete', () => {
    http.post('/api/users/1/approve_account/', {}).subscribe();
    controleur.expectOne('/api/users/1/approve_account/')
      .flush({}, { headers: { 'X-Brouillons-Envoi': 'abc,def' } });

    expect(service.aRelire()).toEqual(['abc', 'def']);
  });

  it('ne signale rien sans en-tete', () => {
    http.get('/api/teams/').subscribe();
    controleur.expectOne('/api/teams/').flush([]);
    expect(service.aRelire()).toEqual([]);
  });

  it('empile plutot que remplace', () => {
    // Une action peut produire plusieurs messages (inviter trois membres d'un coup), et deux
    // actions de suite aussi. N'en garder qu'un ferait partir les autres sans relecture.
    http.post('/api/a/', {}).subscribe();
    controleur.expectOne('/api/a/').flush({}, { headers: { 'X-Brouillons-Envoi': 'un' } });
    http.post('/api/b/', {}).subscribe();
    controleur.expectOne('/api/b/').flush({}, { headers: { 'X-Brouillons-Envoi': 'deux' } });

    expect(service.aRelire()).toEqual(['un', 'deux']);
  });

  it('ne signale pas deux fois le meme identifiant', () => {
    http.post('/api/a/', {}).subscribe();
    controleur.expectOne('/api/a/').flush({}, { headers: { 'X-Brouillons-Envoi': 'un' } });
    http.post('/api/b/', {}).subscribe();
    controleur.expectOne('/api/b/').flush({}, { headers: { 'X-Brouillons-Envoi': 'un,deux' } });

    expect(service.aRelire()).toEqual(['un', 'deux']);
  });

  it('tolere un en-tete vide ou mal forme', () => {
    http.post('/api/a/', {}).subscribe();
    controleur.expectOne('/api/a/').flush({}, { headers: { 'X-Brouillons-Envoi': ' , ,' } });
    expect(service.aRelire()).toEqual([]);
  });

  it('retirer sort l\'identifiant de la file', () => {
    http.post('/api/a/', {}).subscribe();
    controleur.expectOne('/api/a/').flush({}, { headers: { 'X-Brouillons-Envoi': 'un,deux' } });
    service.retirer('un');
    expect(service.aRelire()).toEqual(['deux']);
  });
});
