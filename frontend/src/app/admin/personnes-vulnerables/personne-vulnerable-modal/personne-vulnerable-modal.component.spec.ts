import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { PersonneVulnerableModalComponent } from './personne-vulnerable-modal.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';

/** L'adresse d'une fiche se choisit parmi celles de la commune : le lien est enregistré une
 * fois, et ce que l'agent tape n'est cherché que sur notre serveur. */
describe('PersonneVulnerableModalComponent — adresse rattachée', () => {
  let fixture: ComponentFixture<PersonneVulnerableModalComponent>;
  let composant: PersonneVulnerableModalComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [PersonneVulnerableModalComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(PersonneVulnerableModalComponent);
    composant = fixture.componentInstance;
    fixture.detectChanges();
    http.match(() => true).forEach(r => r.flush([]));      // zones, catalogue
  });

  it('propose les adresses de la commune pendant la saisie, et enregistre le lien de celle qu’on choisit', fakeAsync(() => {
    composant.form.patchValue({ nom: 'Martin', prenom: 'Paul', adresse: '12 rue de l egl' });
    composant.surSaisieAdresse();
    tick(300);
    const recherche = http.expectOne(r => r.url === `${api}/personnes-vulnerables/adresses/`);
    expect(recherche.request.params.get('q')).toBe('12 rue de l egl');
    recherche.flush({ releve_disponible: true, adresses: [{ ban_id: 'b12', adresse: '12 Rue de l\'Église 42400 Saint-Chamond' }] });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.propositions-adresse button').length).toBe(1);

    composant.choisirAdresse(composant.propositions[0]);
    fixture.detectChanges();
    expect(composant.form.value.adresse).toBe('12 Rue de l\'Église 42400 Saint-Chamond');
    expect(fixture.nativeElement.querySelector('.adresse-rattachee')).not.toBeNull();

    composant.submit();
    const envoi = http.expectOne(`${api}/personnes-vulnerables/`);
    expect(envoi.request.body.adresse_ban_id).toBe('b12');
    envoi.flush({});
  }));

  it('retaper l’adresse défait le lien : une adresse libre reste enregistrable', fakeAsync(() => {
    composant.form.patchValue({ nom: 'Martin', prenom: 'Paul', adresse: 'Lieu-dit Les Granges' });
    composant.adresseBanId = 'b12';
    composant.surSaisieAdresse();
    tick(300);
    http.expectOne(r => r.url === `${api}/personnes-vulnerables/adresses/`).flush({ releve_disponible: true, adresses: [] });

    composant.submit();
    const envoi = http.expectOne(`${api}/personnes-vulnerables/`);
    expect(envoi.request.body.adresse_ban_id).toBeNull();
    envoi.flush({});
  }));

  it('dit quand la commune n’a pas encore de relevé d’adresses', fakeAsync(() => {
    composant.form.patchValue({ adresse: '12 rue du Test' });
    composant.surSaisieAdresse();
    tick(300);
    http.expectOne(r => r.url === `${api}/personnes-vulnerables/adresses/`).flush({ releve_disponible: false, adresses: [] });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain("pas encore de relevé d'adresses");
  }));
});
