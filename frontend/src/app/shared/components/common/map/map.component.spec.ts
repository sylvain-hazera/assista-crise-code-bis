import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { MapComponent } from './map.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';
import { PluiePrevue, PrecipitationsHiver, RafalesPrevues, VentPrevu } from '../../../models/veille.model';

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

    it('la neige et le verglas prévus partagent la même réglette, avec leur légende', () => {
      const hiver: PrecipitationsHiver = {
        ...pluie(), echeances: [instants.proche, instants.suivant], ici: null,
        legende: [{ cle: 'VERGLAS', libelle: 'Pluie ou bruine verglaçante', couleur: '#db2777' },
                  { cle: 'NEIGE', libelle: 'Neige', couleur: '#38bdf8' }],
      };
      component.layerVisibility.hiver = true;
      component.onLayerToggle();
      http.expectOne(`${api}/precipitations-hiver/`).flush(hiver);
      fixture.detectChanges();

      expect(http.match(r => r.url.includes('rafales-prevues') || r.url.includes('pluie-prevue')).length).toBe(0);
      expect(component.echeancesPrevision).toEqual([instants.proche, instants.suivant]);
      const reglette: HTMLElement = fixture.nativeElement.querySelector('.pluie-temps');
      expect(reglette.textContent).toContain('Neige, verglas, grêle prévus — calcul de');
      expect(reglette.querySelector('.hiver-legende')!.textContent).toContain('Pluie ou bruine verglaçante');
      component.layerVisibility.hiver = false;
      component.onLayerToggle();
    });

    it('n’affiche pas de réglette quand aucun calque de prévision n’est coché', () => {
      component.rafales = rafales();
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('.pluie-temps')).toBeNull();
    });
  });

  /** Vent animé (15/11/2026) : le champ de vent vient de notre serveur, pour l'heure la plus
   * proche de celle de la réglette, et une heure déjà chargée n'est pas redemandée. */
  describe('vent animé', () => {
    const api = environment.apiUrl;
    const dans = (minutes: number) => new Date(Date.now() + minutes * 60000).toISOString();
    const heures = { passee: dans(-50), proche: dans(10), suivante: dans(70), loin: dans(130) };
    const liste = (): VentPrevu => ({
      source: 'Météo-France', releve_le: dans(-5), perime: false, calcul: dans(-400),
      echeances: [heures.passee, heures.proche, heures.suivante, heures.loin], champ: null,
    });
    const champ = (echeance: string): VentPrevu => ({
      ...liste(), champ: { echeance, largeur: 2, hauteur: 2, ouest: -10, nord: 53, pas: 0.1, vitesse_max_ms: 40,
                           donnees: btoa(String.fromCharCode(128, 160, 128, 160, 128, 128, 100, 100)) },
    });
    let http: HttpTestingController;

    beforeEach(() => { http = TestBed.inject(HttpTestingController); });
    afterEach(() => component.ngOnDestroy());

    it('ne demande rien tant que le calque n’est pas coché', () => {
      component.onLayerToggle();
      expect(http.match(r => r.url.includes('vent-prevu')).length).toBe(0);
    });

    it('demande la liste, puis le champ de l’heure la plus proche de maintenant', () => {
      component.layerVisibility.vent = true;
      component.onLayerToggle();

      http.expectOne(r => r.url === `${api}/vent-prevu/` && !r.params.has('echeance')).flush(liste());
      const demande = http.expectOne(r => r.url === `${api}/vent-prevu/` && r.params.has('echeance'));
      expect(demande.request.params.get('echeance')).toBe(heures.proche);
      expect(demande.request.params.keys()).toEqual(['echeance']);        // rien sur le lieu regardé
      demande.flush(champ(heures.proche));
      expect(component.echeanceVent).toBe(heures.proche);
    });

    it('suit l’heure de la réglette, sans redemander une heure déjà chargée', () => {
      component.layerVisibility.vent = true;
      component.onLayerToggle();
      http.expectOne(r => r.url === `${api}/vent-prevu/` && !r.params.has('echeance')).flush(liste());
      http.expectOne(r => r.params.get('echeance') === heures.proche).flush(champ(heures.proche));

      // La réglette de la pluie passe à + 2 h 05 : le vent prend l'heure la plus proche.
      component.layerVisibility.pluie = true;
      component.pluie = { source: 'Météo-France', releve_le: dans(-3), perime: false, calcul: dans(-40),
                          coins: [[-5.5, 51.5], [10, 51.5], [10, 41], [-5.5, 41]], echeances: [dans(5), dans(125)] };
      component.choisirEcheance(1);
      http.expectOne(r => r.params.get('echeance') === heures.loin).flush(champ(heures.loin));
      expect(component.echeanceVent).toBe(heures.loin);

      component.choisirEcheance(0);                                        // retour à l'heure déjà chargée
      expect(http.match(r => r.url.includes('vent-prevu')).length).toBe(0);
      expect(component.echeanceVent).toBe(heures.proche);
    });

    it('dit l’heure et la nature du vent affiché, et montre la toile', () => {
      component.layerVisibility.vent = true;
      component.onLayerToggle();
      http.expectOne(r => r.url === `${api}/vent-prevu/` && !r.params.has('echeance')).flush(liste());
      http.expectOne(r => r.params.has('echeance')).flush(champ(heures.proche));
      fixture.detectChanges();

      const note: HTMLElement = fixture.nativeElement.querySelector('.vent-note');
      expect(note.textContent).toContain('Vent prévu à');
      expect(note.textContent).toContain('vent moyen');
      expect(fixture.nativeElement.querySelector('.vent-toile').classList).toContain('visible');
    });

    it('cache la toile quand on décoche', () => {
      component.layerVisibility.vent = true;
      component.onLayerToggle();
      http.match(() => true);
      component.layerVisibility.vent = false;
      component.onLayerToggle();
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('.vent-toile').classList).not.toContain('visible');
      expect(fixture.nativeElement.querySelector('.vent-note')).toBeNull();
    });
  });

  /** « Personne sensible dans les environs » : des cercles, jamais des points, pour les seules
   * personnes qui tiennent le registre — et rien ne filtre au clic. */
  describe('secteurs des personnes vulnérables', () => {
    const api = environment.apiUrl;
    let http: HttpTestingController;
    const caseACocher = (): HTMLElement | null =>
      Array.from(fixture.nativeElement.querySelectorAll('.layer-toggle-item') as NodeListOf<HTMLElement>)
        .find(e => e.textContent!.includes('Personnes sensibles')) ?? null;

    beforeEach(() => { http = TestBed.inject(HttpTestingController); });

    it('ne propose pas le calque au public', () => {
      component.isInstitutional = false;
      component.layersPanelOpen = true;
      fixture.detectChanges();
      expect(caseACocher()).toBeNull();
    });

    it('charge les cercles à la première activation, et ne montre au clic que le libellé du serveur', () => {
      component.isInstitutional = true;
      component.layersPanelOpen = true;   // le panneau des calques est replié par défaut
      fixture.detectChanges();
      expect(caseACocher()).not.toBeNull();
      const affiches: any[] = [];
      spyOn<any>(component, 'afficherTracesVeille').and.callFake((...arguments_: any[]) => affiches.push(arguments_));

      component.layerVisibility.secteursVulnerables = true;
      component.onLayerToggle();
      component.onLayerToggle();   // une seconde bascule ne redemande rien

      const demandes = http.match(r => r.url === `${api}/personnes-vulnerables/secteurs/`);
      expect(demandes.length).toBe(1);
      demandes[0].flush({
        type: 'FeatureCollection', libelle: 'Personne sensible dans les environs', situees: 1, non_situees: 2, releve_disponible: true,
        features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[4.5, 45.4], [4.6, 45.4], [4.5, 45.5], [4.5, 45.4]]] } }],
      });

      const [source, type, donnees, peinture] = affiches[0];
      expect(source).toBe('secteurs-vulnerables');
      expect(type).toBe('fill');
      // Rien d'autre que le libellé fixe : ni nom, ni besoin, ni identifiant.
      expect(donnees.features[0].properties).toEqual({ infobulle: '<strong>Personne sensible dans les environs</strong>' });
      expect(peinture['fill-color']).toBe('#f97316');
      expect(peinture['fill-opacity']).toBeLessThan(0.5);
      expect(component.noteSecteursVulnerables).toBe('2 fiche(s) non située(s)');
    });

    it('dit pourquoi rien ne s’affiche quand le relevé des adresses manque ou que le serveur ne répond pas', () => {
      component.isInstitutional = true;
      spyOn<any>(component, 'afficherTracesVeille');
      component.layerVisibility.secteursVulnerables = true;
      component.onLayerToggle();
      http.expectOne(r => r.url === `${api}/personnes-vulnerables/secteurs/`)
        .flush({ type: 'FeatureCollection', libelle: 'x', situees: 0, non_situees: 3, releve_disponible: false, features: [] });
      expect(component.noteSecteursVulnerables).toContain('relevé des adresses manquant');

      component.layerVisibility.secteursVulnerables = false;
      component.onLayerToggle();
      (component as any).secteursVulnerablesCharges = false;
      component.layerVisibility.secteursVulnerables = true;
      component.onLayerToggle();
      http.expectOne(r => r.url === `${api}/personnes-vulnerables/secteurs/`).flush({ detail: 'refus' }, { status: 403, statusText: 'Forbidden' });
      expect(component.noteSecteursVulnerables).toContain('secteurs indisponibles');
    });
  });
});
