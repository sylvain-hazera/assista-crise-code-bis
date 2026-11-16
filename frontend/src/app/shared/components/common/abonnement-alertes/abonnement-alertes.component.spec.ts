import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { AbonnementAlertesComponent } from './abonnement-alertes.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';

/** « Recevoir les alertes de ma commune » : c'est l'habitant qui demande, et qui retire. */
describe('AbonnementAlertesComponent', () => {
  let fixture: ComponentFixture<AbonnementAlertesComponent>;
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/alertes-population/`;

  function demarrer(abonnements: unknown[] = []) {
    fixture = TestBed.createComponent(AbonnementAlertesComponent);
    fixture.detectChanges();
    http.expectOne(`${url}abonnement/`).flush(abonnements);
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [AbonnementAlertesComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('cherche une commune par son nom et s’y abonne', () => {
    demarrer();
    const composant = fixture.componentInstance;
    composant.recherche = 'Saint-Cha';
    composant.chercher();
    http.expectOne(r => r.url === `${url}collectivites/` && r.params.get('q') === 'Saint-Cha')
      .flush([{ id: 'i1', nom: 'Mairie de Saint-Chamond' }]);

    composant.abonner('i1');

    const requete = http.expectOne(r => r.url === `${url}abonnement/` && r.method === 'POST');
    expect(requete.request.body).toEqual({ institution: 'i1' });
    requete.flush({ institution: 'i1', institution_nom: 'Mairie de Saint-Chamond' });
    http.expectOne(r => r.url === `${url}abonnement/` && r.method === 'GET')
      .flush([{ institution: 'i1', institution_nom: 'Mairie de Saint-Chamond' }]);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Mairie de Saint-Chamond');
    expect(composant.recherche).toBe('');
  });

  it('ne cherche pas avant deux lettres, et ne repropose pas une commune déjà suivie', () => {
    demarrer([{ institution: 'i1', institution_nom: 'Mairie de Saint-Chamond' }]);
    const composant = fixture.componentInstance;

    composant.recherche = 'S';
    composant.chercher();
    http.expectNone(r => r.url === `${url}collectivites/`);

    composant.recherche = 'Saint';
    composant.chercher();
    http.expectOne(r => r.url === `${url}collectivites/`)
      .flush([{ id: 'i1', nom: 'Mairie de Saint-Chamond' }, { id: 'i2', nom: 'Mairie de Saint-Étienne' }]);
    expect(composant.resultats.map(r => r.id)).toEqual(['i2']);
  });

  it('se désabonne après confirmation', () => {
    demarrer([{ institution: 'i1', institution_nom: 'Mairie de Saint-Chamond' }]);
    spyOn(window, 'confirm').and.returnValue(true);

    fixture.componentInstance.desabonner(fixture.componentInstance.abonnements[0]);

    const requete = http.expectOne(r => r.url === `${url}abonnement/` && r.method === 'DELETE');
    expect(requete.request.body).toEqual({ institution: 'i1' });
    requete.flush(null);
    http.expectOne(r => r.url === `${url}abonnement/` && r.method === 'GET').flush([]);
  });
});
