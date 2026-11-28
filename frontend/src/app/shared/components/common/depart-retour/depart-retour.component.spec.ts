import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { DepartRetourComponent, MonEngagement } from './depart-retour.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';

/** « Je pars », « je rentre » : deux gestes, rien à saisir. */
describe('DepartRetourComponent', () => {
  let fixture: ComponentFixture<DepartRetourComponent>;
  let http: HttpTestingController;

  const LIBRE: MonEngagement = {
    en_cours: null, crises: [{ id: 'c1', nom: 'Crue du Gier' }], equipes: [{ id: 'e1', nom: 'Services techniques' }],
  };
  const PARTI: MonEngagement = {
    ...LIBRE, en_cours: { crise: 'c1', crise_nom: 'Crue du Gier', equipe_nom: 'Services techniques', parti_le: '2026-11-17T08:00:00Z' },
  };

  function ouvrir(etat: MonEngagement): void {
    fixture.detectChanges();
    http.expectOne(r => r.method === 'GET' && r.url.endsWith('/mon-engagement/')).flush(etat);
    fixture.detectChanges();
  }
  const texte = () => (fixture.nativeElement as HTMLElement).textContent ?? '';

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [DepartRetourComponent],
    });
    fixture = TestBed.createComponent(DepartRetourComponent);
    http = TestBed.inject(HttpTestingController);
  });

  it('ne montre rien quand aucune crise ne concerne la personne', () => {
    ouvrir({ en_cours: null, crises: [], equipes: [] });
    expect(texte().trim()).toBe('');
  });

  it('part avec sa seule équipe, sans la demander', () => {
    ouvrir(LIBRE);
    expect(texte()).toContain('Je pars');
    fixture.componentInstance.geste('partir');
    const requete = http.expectOne(r => r.method === 'POST');
    expect(requete.request.body).toEqual({ geste: 'partir', crise: 'c1', equipe: 'e1', depart_de: 'DOMICILE' });
    requete.flush(PARTI);
    fixture.detectChanges();
    expect(texte()).toContain('Je rentre');
    expect(texte()).toContain('Crue du Gier');
  });

  it('propose de rentrer à qui est parti, même si la crise n\'est plus dans la liste', () => {
    ouvrir({ ...PARTI, crises: [] });
    expect(texte()).toContain('Je rentre');
    fixture.componentInstance.geste('rentrer');
    const requete = http.expectOne(r => r.method === 'POST');
    expect(requete.request.body).toEqual({ geste: 'rentrer', retour_a: 'DOMICILE' });
    requete.flush({ en_cours: null, crises: [], equipes: [] });
  });

  it('logé sur site, on part de son hébergement et on y rentre', () => {
    ouvrir({ ...LIBRE, crises: [{ id: 'c1', nom: 'Crue du Gier', hebergement: 'Gîte communal' }] });
    expect(fixture.componentInstance.lieu).toBe('HEBERGEMENT');
    expect(texte()).toContain('Gîte communal');
    fixture.componentInstance.geste('partir');
    const depart = http.expectOne(r => r.method === 'POST');
    expect(depart.request.body.depart_de).toBe('HEBERGEMENT');
    depart.flush({ ...PARTI, en_cours: { ...PARTI.en_cours!, depart_de: 'HEBERGEMENT', hebergement: 'Gîte communal' } });
    expect(fixture.componentInstance.lieu).toBe('HEBERGEMENT');
  });

  it('montre le refus du serveur', () => {
    ouvrir(LIBRE);
    fixture.componentInstance.geste('partir');
    http.expectOne(r => r.method === 'POST').flush({ detail: 'Vous êtes déjà parti.' }, { status: 400, statusText: 'Bad Request' });
    fixture.detectChanges();
    expect(texte()).toContain('Vous êtes déjà parti.');
  });

  it('part pour la manifestation du jour où il est inscrit (26/11/2026)', () => {
    ouvrir({ en_cours: null, crises: [], equipes: [{ id: 'e1', nom: 'Services techniques' }],
             manifestations: [{ id: 'm1', nom: 'Course des 10 km', debut: '2026-11-26T08:00:00Z', fin: '2026-11-26T12:00:00Z' }] });
    expect(texte()).toContain('la manifestation');
    fixture.componentInstance.geste('partir');
    const requete = http.expectOne(r => r.method === 'POST');
    expect(requete.request.body).toEqual({ geste: 'partir', manifestation: 'm1', depart_de: 'DOMICILE' });
    requete.flush({ en_cours: null, crises: [], equipes: [] });
  });

  it('part avec son véhicule et son compteur, rentre avec le compteur et un péage (28/11/2026)', () => {
    ouvrir({ ...LIBRE, vehicules: [{ id: 'v1', designation: 'Clio · AB-123-CD · 5 CV' }] });
    const c = fixture.componentInstance;
    expect(c.vehicule).toBe('v1');
    c.compteurDepart = '45210';
    c.geste('partir');
    const depart = http.expectOne(r => r.method === 'POST');
    expect(depart.request.body).toEqual(jasmine.objectContaining({ vehicule_personnel: 'v1', compteur_depart: '45210' }));
    depart.flush({ ...PARTI, en_cours: { ...PARTI.en_cours!, vehicule_personnel: 'v1', compteur_depart: '45210' } });
    fixture.detectChanges();
    expect(texte()).toContain("Compteur à l'arrivée");
    c.compteurArrivee = '45262';
    c.peage = '3,40';
    c.geste('rentrer');
    const retour = http.expectOne(r => r.method === 'POST');
    expect(retour.request.body).toEqual({ geste: 'rentrer', retour_a: 'DOMICILE', compteur_arrivee: '45262', peage: '3,40' });
  });
});
