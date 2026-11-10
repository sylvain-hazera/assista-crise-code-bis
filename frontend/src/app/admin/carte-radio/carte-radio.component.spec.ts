import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { CarteRadioComponent } from './carte-radio.component';
import { environment } from '../../../environments/environment';

/** La carte elle-même n'est pas testable ici : le harnais n'a pas de contexte WebGL, et c'est
 * précisément ce que le garde `carteIndisponible` protège. Ce qui est testé est tout le reste —
 * le choix des données, le filtrage, et le fait que les deux calques coûteux ne partent pas au
 * chargement. */
describe('CarteRadioComponent', () => {
  let http: HttpTestingController;
  const api = environment.apiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [CarteRadioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function demarrer() {
    const fixture = TestBed.createComponent(CarteRadioComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('charge l\'infrastructure au démarrage, mais NI les liaisons NI la couverture', () => {
    const fixture = demarrer();

    http.expectOne(`${api}/compagnons-meshcore/`).flush([]);
    http.expectOne(`${api}/relais-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshtastic/`).flush([]);
    http.expectOne(`${api}/couvertures-radio/`).flush([]);

    // Les deux calques coûteux : rien ne doit partir tant qu'on ne les a pas cochés.
    http.expectNone(r => r.url.includes('/liaisons-meshtastic/'));
    expect(fixture.componentInstance.calques.liaisons).toBeFalse();
    expect(fixture.componentInstance.calques.couverture).toBeFalse();
  });

  it('ne garde que les répéteurs et room servers positionnés', () => {
    const fixture = demarrer();
    http.expectOne(`${api}/compagnons-meshcore/`).flush([]);
    http.expectOne(`${api}/relais-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshcore/`).flush([
      { id: '1', pubkey_hex: 'aa', nom: 'Pilat', type_contact: 'REPEATER', latitude: 45.3, longitude: 4.6 },
      { id: '2', pubkey_hex: 'bb', nom: 'Salon', type_contact: 'ROOM', latitude: 45.4, longitude: 4.7 },
      // Un COMPANION peut être le terminal d'une personne : jamais sur cette carte.
      { id: '3', pubkey_hex: 'cc', nom: 'Moi', type_contact: 'COMPANION', latitude: 45.5, longitude: 4.8 },
      // Sans position, rien à dessiner.
      { id: '4', pubkey_hex: 'dd', nom: 'Muet', type_contact: 'REPEATER', latitude: null, longitude: null },
    ]);
    http.expectOne(`${api}/contacts-meshtastic/`).flush([]);
    http.expectOne(`${api}/couvertures-radio/`).flush([]);

    expect(fixture.componentInstance.comptes.repeteursEntendus).toBe(2);
  });

  it('le sélecteur ne propose que les couvertures calculées et non vides', () => {
    const fixture = demarrer();
    http.expectOne(`${api}/compagnons-meshcore/`).flush([]);
    http.expectOne(`${api}/relais-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshtastic/`).flush([]);
    http.expectOne(`${api}/couvertures-radio/`).flush([
      { id: 'c1', nom: 'Château d\'eau', statut: 'TERMINEE', nombre_points: 1200, calibre: true },
      { id: 'c2', nom: 'En cours', statut: 'EN_COURS', nombre_points: 0, calibre: false },
      { id: 'c3', nom: 'Échouée', statut: 'ECHEC', nombre_points: 0, calibre: false },
      // Terminée mais sans aucun point atteint : un calque vide ne se lit pas, il inquiète.
      { id: 'c4', nom: 'Vide', statut: 'TERMINEE', nombre_points: 0, calibre: true },
    ] as any);

    expect(fixture.componentInstance.couvertures.map(c => c.id)).toEqual(['c1']);
  });

  it('une erreur de chargement est dite, pas avalée', () => {
    const fixture = demarrer();
    http.expectOne(`${api}/compagnons-meshcore/`).flush(null, { status: 500, statusText: 'Erreur' });
    http.expectOne(`${api}/relais-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshtastic/`).flush([]);
    http.expectOne(`${api}/couvertures-radio/`).flush([]);

    // Sinon une carte vide ne dit pas si elle est vide parce qu'il n'y a rien, ou parce que le
    // chargement a échoué.
    expect(fixture.componentInstance.erreurs).toContain('Passerelles indisponibles.');
    expect(fixture.componentInstance.comptes.passerelles).toBeNull();
  });

  it('le garde WebGL affiche un message au lieu de laisser la page blanche', async () => {
    const fixture = demarrer();
    http.expectOne(`${api}/compagnons-meshcore/`).flush([]);
    http.expectOne(`${api}/relais-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshcore/`).flush([]);
    http.expectOne(`${api}/contacts-meshtastic/`).flush([]);
    http.expectOne(`${api}/couvertures-radio/`).flush([]);

    // Le harnais n'a pas de WebGL : le constructeur de MapLibre a levé, et le composant doit
    // avoir survécu. C'est ce qui fait que la PAGE s'affiche quand la carte ne peut pas.
    await Promise.resolve();
    fixture.detectChanges();
    expect(fixture.componentInstance.carteIndisponible).toBeTrue();
    expect(fixture.nativeElement.textContent).toContain('Carte indisponible sur ce poste');
  });
});
