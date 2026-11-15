import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { MapComponent } from './map.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';
import { PluiePrevue, RafalesPrevues } from '../../../models/veille.model';

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
      expect(component.indicePrevision).toBe(1);          // l'échéance à + 5 min, pas celle d'il y a 10 min
      expect(component.ecartPrevision).toBe('maintenant');
      component.layerVisibility.pluie = false;
      component.onLayerToggle();
    });

    it('dit l’écart avec maintenant en clair', () => {
      component.layerVisibility.pluie = true;
      component.pluie = pluie();
      component.choisirEcheance(0);
      expect(component.ecartPrevision).toBe('il y a 10 min');
      component.choisirEcheance(2);
      expect(component.ecartPrevision).toBe('dans 20 min');
      component.choisirEcheance(3);
      expect(component.ecartPrevision).toBe('dans 1 h 35');
    });

    it('ne sort jamais de la liste des échéances', () => {
      component.layerVisibility.pluie = true;
      component.pluie = pluie();
      component.choisirEcheance(99);
      expect(component.indicePrevision).toBe(3);
      component.choisirEcheance(-4);
      expect(component.indicePrevision).toBe(0);
    });

    it('l’animation avance d’une échéance à la fois et s’arrête à la demande', () => {
      jasmine.clock().install();
      try {
        component.layerVisibility.pluie = true;
      component.pluie = pluie();
        component.choisirEcheance(2);
        component.basculerAnimationPrevision();
        jasmine.clock().tick(950);
        expect(component.indicePrevision).toBe(3);
        jasmine.clock().tick(950);
        expect(component.indicePrevision).toBe(0);        // revient au début
        component.basculerAnimationPrevision();
        jasmine.clock().tick(5000);
        expect(component.indicePrevision).toBe(0);
        expect(component.animationPrevision).toBeNull();
      } finally {
        jasmine.clock().uninstall();
      }
    });
  });

  /** Rafales prévues (15/11/2026) : même chaîne que la pluie (des images nationales copiées par
   * notre serveur) et MÊME réglette. Ce qui est testé : le calque ne parle qu'à notre serveur,
   * la réglette réunit les quarts d'heure des calques cochés, et la légende vient du serveur. */
  describe('rafales prévues', () => {
    const api = environment.apiUrl;
    const dans = (minutes: number) => new Date(Date.now() + minutes * 60000).toISOString();
    // Instants fixés une fois : les deux séries doivent porter les MÊMES quarts d'heure.
    const instants = { passe: dans(-10), proche: dans(5), suivant: dans(20), loin: dans(95), plusLoin: dans(110) };
    const pluie = (): PluiePrevue => ({
      source: 'Météo-France', releve_le: dans(-3), perime: false, calcul: dans(-40),
      coins: [[-5.5, 51.5], [10, 51.5], [10, 41], [-5.5, 41]],
      echeances: [instants.passe, instants.proche, instants.suivant, instants.loin],
    });
    const rafales = (): RafalesPrevues => ({
      source: 'Météo-France', releve_le: dans(-3), perime: false, calcul: dans(-40),
      coins: [[-5.505, 51.505], [10.005, 51.505], [10.005, 40.995], [-5.505, 40.995]],
      // Il manque le quart d'heure « suivant » (une grille manquée au relevé), et il y en a un de plus.
      echeances: [instants.passe, instants.proche, instants.loin, instants.plusLoin],
      legende: [{ a_partir_de_kmh: 40, couleur: '#d6c6f2' }, { a_partir_de_kmh: 60, couleur: '#ab88e4' }],
      ici: null,
    });
    let http: HttpTestingController;

    beforeEach(() => { http = TestBed.inject(HttpTestingController); });
    afterEach(() => component.ngOnDestroy());

    it('ne demande que les rafales quand seul leur calque est coché, à notre serveur', () => {
      component.layerVisibility.rafales = true;
      component.onLayerToggle();

      const demande = http.expectOne(`${api}/rafales-prevues/`);
      expect(demande.request.params.keys().length).toBe(0);     // rien sur le lieu regardé
      demande.flush(rafales());
      expect(http.match(r => r.url.includes('pluie-prevue')).length).toBe(0);
      expect(component.echeancesPrevision.length).toBe(4);
      expect(component.ecartPrevision).toBe('maintenant');
    });

    it('ne recharge pas une série déjà suivie quand on coche l’autre', () => {
      component.layerVisibility.pluie = true;
      component.onLayerToggle();
      http.expectOne(`${api}/pluie-prevue/`).flush(pluie());

      component.layerVisibility.rafales = true;
      component.onLayerToggle();

      http.expectOne(`${api}/rafales-prevues/`).flush(rafales());
      expect(http.match(r => r.url.includes('pluie-prevue')).length).toBe(0);
    });

    it('réunit sur une seule réglette les quarts d’heure des deux calques', () => {
      component.layerVisibility.pluie = component.layerVisibility.rafales = true;
      component.pluie = pluie();
      component.rafales = rafales();

      expect(component.echeancesPrevision).toEqual(
        [instants.passe, instants.proche, instants.suivant, instants.loin, instants.plusLoin]);
    });

    it('garde l’heure choisie quand on décoche un calque, ou la plus proche qui reste', () => {
      component.layerVisibility.pluie = component.layerVisibility.rafales = true;
      component.pluie = pluie();
      component.rafales = rafales();
      component.choisirEcheance(3);                               // « loin », connue des deux
      component.layerVisibility.pluie = false;
      expect(component.echeancePrevision).toBe(instants.loin);

      component.layerVisibility.pluie = true;
      component.choisirEcheance(2);                               // « suivant », connue de la pluie seule
      component.layerVisibility.pluie = false;
      expect(component.echeancePrevision).toBe(instants.proche);  // la plus proche côté rafales
    });

    it('suit l’heure qu’il est tant qu’on n’a pas touché à la réglette', () => {
      component.layerVisibility.rafales = true;
      component.rafales = rafales();

      expect(component.echeanceChoisie).toBeNull();
      expect(component.echeancePrevision).toBe(instants.proche);
    });

    it('affiche la légende que le serveur donne, en km/h', () => {
      component.layerVisibility.rafales = true;
      component.rafales = rafales();
      fixture.detectChanges();

      const legende: HTMLElement = fixture.nativeElement.querySelector('.rafales-legende');
      expect(legende.textContent).toContain('40');
      expect(legende.textContent).toContain('km/h et plus');
      expect(legende.querySelectorAll('i').length).toBe(2);
      expect(fixture.nativeElement.querySelector('.pluie-temps').textContent).toContain('Rafales prévues — calcul de');
      expect(fixture.nativeElement.querySelector('.pluie-temps').textContent).not.toContain('Pluie prévue');
    });

    it('n’affiche pas de réglette quand aucun calque de prévision n’est coché', () => {
      component.rafales = rafales();
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('.pluie-temps')).toBeNull();
    });
  });
});
