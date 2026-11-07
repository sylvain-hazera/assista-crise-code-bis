import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ZoneModalComponent } from './zone-modal.component';
import { Commune } from '../../../services/location.service';

/** Bug signalé le 07/11/2026 : en saisissant une commune, la carte ne se centrait ni ne zoomait
 * dessus. Le composant de carte savait le faire depuis le début — la modale ne lui passait
 * simplement ni les contours ni la géométrie à cadrer. */
describe('ZoneModalComponent', () => {
  let http: HttpTestingController;

  const SAINT_ETIENNE: Commune = {
    code: '42218', name: 'Saint-Étienne', codesPostaux: ['42000'], codePostal: '42000',
    codeDepartement: '42',
  };
  const CONTOUR = {
    type: 'Polygon' as const,
    coordinates: [[[4.38, 45.42], [4.42, 45.42], [4.42, 45.46], [4.38, 45.46], [4.38, 45.42]]],
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ZoneModalComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  function creer() {
    const fixture = TestBed.createComponent(ZoneModalComponent);
    fixture.componentInstance.ngOnChanges({ zone: {} as any });
    return fixture.componentInstance;
  }

  it('cadre la carte sur la commune qu’on vient de saisir', () => {
    const composant = creer();
    expect(composant.cadrerSur).toBeNull();

    composant.addCommune(SAINT_ETIENNE);
    const requete = http.expectOne(r => r.url.includes('/communes/42218'));
    requete.flush({ code: '42218', nom: 'Saint-Étienne', contour: CONTOUR, codesPostaux: ['42000'] });

    expect(composant.cadrerSur).toEqual(CONTOUR);
    expect(composant.communesGeojson?.features.length).toBe(1);
  });

  it('affiche le contour en calque de référence, pour dessiner sur des limites réelles', () => {
    const composant = creer();
    composant.addCommune(SAINT_ETIENNE);
    http.expectOne(r => r.url.includes('/communes/42218'))
      .flush({ code: '42218', nom: 'Saint-Étienne', contour: CONTOUR, codesPostaux: [] });

    expect(composant.communesGeojson?.features[0].geometry).toEqual(CONTOUR);
  });

  it('ne réinterroge pas l’API pour une commune déjà chargée', () => {
    const composant = creer();
    composant.addCommune(SAINT_ETIENNE);
    http.expectOne(r => r.url.includes('/communes/42218'))
      .flush({ code: '42218', nom: 'Saint-Étienne', contour: CONTOUR, codesPostaux: [] });

    composant.removeCommune('42218');
    composant.addCommune(SAINT_ETIENNE);
    http.expectNone(r => r.url.includes('/communes/42218'));
    expect(composant.cadrerSur).toEqual(CONTOUR);
  });

  it('retire le contour quand on retire la commune', () => {
    const composant = creer();
    composant.addCommune(SAINT_ETIENNE);
    http.expectOne(r => r.url.includes('/communes/42218'))
      .flush({ code: '42218', nom: 'Saint-Étienne', contour: CONTOUR, codesPostaux: [] });

    composant.removeCommune('42218');
    expect(composant.communesGeojson).toBeNull();
  });

  it('reste utilisable si l’API géo ne répond pas', () => {
    // L'aide visuelle manque, la zone reste créable : jamais bloquant.
    const composant = creer();
    composant.addCommune(SAINT_ETIENNE);
    http.expectOne(r => r.url.includes('/communes/42218'))
      .flush(null, { status: 503, statusText: 'Service Unavailable' });

    expect(composant.communesGeojson).toBeNull();
    expect(composant.communes).toEqual(['42218']);
  });

  it('ignore une commune sans contour plutôt que de casser le calque', () => {
    const composant = creer();
    composant.addCommune(SAINT_ETIENNE);
    http.expectOne(r => r.url.includes('/communes/42218'))
      .flush({ code: '42218', nom: 'Saint-Étienne', contour: null, codesPostaux: [] });

    expect(composant.communesGeojson).toBeNull();
    expect(composant.cadrerSur).toBeNull();
  });

  it('n’ajoute pas deux fois la même commune', () => {
    const composant = creer();
    composant.addCommune(SAINT_ETIENNE);
    http.expectOne(r => r.url.includes('/communes/42218'))
      .flush({ code: '42218', nom: 'Saint-Étienne', contour: CONTOUR, codesPostaux: [] });

    composant.addCommune(SAINT_ETIENNE);
    expect(composant.communes).toEqual(['42218']);
    http.expectNone(r => r.url.includes('/communes/42218'));
  });

  afterEach(() => {
    // Les requêtes de NOM des communes d'une zone existante ne concernent pas ces tests.
    http.match(() => true).forEach(r => r.flush({}));
    http.verify();
  });
});
