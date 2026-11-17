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
    expect(requete.request.body).toEqual({ geste: 'partir', crise: 'c1', equipe: 'e1' });
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
    expect(requete.request.body).toEqual({ geste: 'rentrer' });
    requete.flush({ en_cours: null, crises: [], equipes: [] });
  });

  it('montre le refus du serveur', () => {
    ouvrir(LIBRE);
    fixture.componentInstance.geste('partir');
    http.expectOne(r => r.method === 'POST').flush({ detail: 'Vous êtes déjà parti.' }, { status: 400, statusText: 'Bad Request' });
    fixture.detectChanges();
    expect(texte()).toContain('Vous êtes déjà parti.');
  });
});
