import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { MapComponent } from './map.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';
import { PluiePrevue } from '../../../models/veille.model';

describe('MapComponent', () => {
  let component: MapComponent;
  let fixture: ComponentFixture<MapComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [MapComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(MapComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  /** Zone atteignable : le calcul est demandé à NOTRE serveur, jamais à un service tiers. */
  describe('zone atteignable depuis un point', () => {
    const api = environment.apiUrl;
    let http: HttpTestingController;

    beforeEach(() => { http = TestBed.inject(HttpTestingController); });

    it('demande le contour à notre serveur avec la durée et le mode choisis', () => {
      component.zone.minutes = 20;
      component.zone.mode = 'pied';
      component.calculerZone(45.44, 4.39);

      const demande = http.expectOne(r => r.url === `${api}/zone-atteignable/`);
      expect(demande.request.params.get('minutes')).toBe('20');
      expect(demande.request.params.get('mode')).toBe('pied');
      expect(demande.request.params.get('lat')).toBe('45.44');
      demande.flush({ minutes: 20, mode: 'pied', source: 'IGN',
                      contour: { type: 'Polygon', coordinates: [[[4.38, 45.43], [4.4, 45.43], [4.4, 45.45], [4.38, 45.43]]] } });
      expect(component.zone.affichee).toBeTrue();
      expect(component.zone.enCours).toBeFalse();
    });

    it('dit quand le calcul n’aboutit pas, et on peut effacer', () => {
      component.calculerZone(45.44, 4.39);
      http.expectOne(r => r.url === `${api}/zone-atteignable/`).flush(
        { detail: 'Le calcul n\'a pas abouti : réessayez.' }, { status: 503, statusText: 'Indisponible' });

      expect(component.zone.erreur).toContain('pas abouti');
      expect(component.zone.affichee).toBeFalse();
      component.effacerZone();
      expect(component.zone.erreur).toBe('');
    });
  });

  /** Pluie prévue (15/11/2026) : des images nationales copiées par notre serveur, une par
   * quart d'heure. Ce qui est testé : la carte ne les demande qu'à notre serveur, seulement
   * quand le calque est coché, et la réglette dit l'heure sans ambiguïté. */
  describe('pluie prévue', () => {
    const api = environment.apiUrl;
    const dans = (minutes: number) => new Date(Date.now() + minutes * 60000).toISOString();
    const pluie = (): PluiePrevue => ({
      source: 'Météo-France', releve_le: dans(-3), perime: false, calcul: dans(-40),
      coins: [[-5.5, 51.5], [10, 51.5], [10, 41], [-5.5, 41]],
      echeances: [dans(-10), dans(5), dans(20), dans(95)],
    });
    let http: HttpTestingController;

    beforeEach(() => { http = TestBed.inject(HttpTestingController); });
    afterEach(() => component.ngOnDestroy());

    it('ne demande rien tant que le calque n’est pas coché', () => {
      component.onLayerToggle();
      expect(http.match(r => r.url.includes('pluie-prevue')).length).toBe(0);
    });

    it('demande la liste à notre serveur quand on coche, et se place sur l’heure qu’il est', () => {
      component.layerVisibility.pluie = true;
      component.onLayerToggle();

      http.expectOne(`${api}/pluie-prevue/`).flush(pluie());
      expect(component.indicePluie).toBe(1);          // l'échéance à + 5 min, pas celle d'il y a 10 min
      expect(component.ecartPluie).toBe('maintenant');
      component.layerVisibility.pluie = false;
      component.onLayerToggle();
    });

    it('dit l’écart avec maintenant en clair', () => {
      component.pluie = pluie();
      component.choisirEcheancePluie(0);
      expect(component.ecartPluie).toBe('il y a 10 min');
      component.choisirEcheancePluie(2);
      expect(component.ecartPluie).toBe('dans 20 min');
      component.choisirEcheancePluie(3);
      expect(component.ecartPluie).toBe('dans 1 h 35');
    });

    it('ne sort jamais de la liste des échéances', () => {
      component.pluie = pluie();
      component.choisirEcheancePluie(99);
      expect(component.indicePluie).toBe(3);
      component.choisirEcheancePluie(-4);
      expect(component.indicePluie).toBe(0);
    });

    it('l’animation avance d’une échéance à la fois et s’arrête à la demande', () => {
      jasmine.clock().install();
      try {
        component.pluie = pluie();
        component.choisirEcheancePluie(2);
        component.basculerAnimationPluie();
        jasmine.clock().tick(950);
        expect(component.indicePluie).toBe(3);
        jasmine.clock().tick(950);
        expect(component.indicePluie).toBe(0);        // revient au début
        component.basculerAnimationPluie();
        jasmine.clock().tick(5000);
        expect(component.indicePluie).toBe(0);
        expect(component.animationPluie).toBeNull();
      } finally {
        jasmine.clock().uninstall();
      }
    });
  });
});
