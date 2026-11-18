import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { AlerteHabitantsComponent } from './alerte-habitants.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { CanalAlerte } from '../../services/alerte-habitants.service';

/** Alerter les habitants : l'écran dit combien de personnes chaque canal peut joindre avant
 * l'envoi, ne propose pas ce qui n'est pas branché, et rend le bilan réel après. */
describe('AlerteHabitantsComponent', () => {
  let fixture: ComponentFixture<AlerteHabitantsComponent>;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const canal = (code: string, defaut: boolean, disponible = true, joignables: number | null = 3): CanalAlerte =>
    ({ code, libelle: code, detail: 'détail', defaut, disponible, motif: disponible ? '' : "n'est pas encore branché", joignables });
  const ETAT = {
    apercu: { destinataires: 3, canaux: [canal('MATRIX', true), canal('APPLICATION', true, true, 1), canal('SMS', false, false),
                                         canal('INTRAMUROS', false, false, null)] },
    par_defaut: ['MATRIX', 'APPLICATION'], alertes: [],
  };

  function demarrer() {
    fixture = TestBed.createComponent(AlerteHabitantsComponent);
    fixture.detectChanges();
    http.expectOne(r => r.url === `${api}/crises/`).flush([]);
    http.expectOne(r => r.url === `${api}/alertes-population/`).flush(ETAT);
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [AlerteHabitantsComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('coche par défaut la messagerie et l’application, et dit ce qui n’est pas branché', () => {
    demarrer();
    const composant = fixture.componentInstance;
    const texte = (fixture.nativeElement as HTMLElement).textContent!;

    expect(composant.canauxChoisis).toEqual(['MATRIX', 'APPLICATION']);
    expect(texte).toContain('3 personnes recevront');
    expect(texte).toContain("n'est pas encore branché");
    expect(texte).toContain("Ce n'est pas FR-Alert");
    // Un canal indisponible ne se coche pas, même si l'on force.
    composant.choisis['INTRAMUROS'] = true;
    expect(composant.canauxChoisis).not.toContain('INTRAMUROS');
  });

  it('demande confirmation, envoie, et montre ce qui est réellement parti', () => {
    demarrer();
    const composant = fixture.componentInstance;
    composant.titre = ' Crue du Gier ';
    composant.message = 'Évacuez le quartier bas.';
    const confirmer = spyOn(window, 'confirm').and.returnValue(true);

    composant.envoyer();

    expect(confirmer.calls.mostRecent().args[0]).toContain('3 personnes');
    const requete = http.expectOne(r => r.url === `${api}/alertes-population/` && r.method === 'POST');
    expect(requete.request.body).toEqual({ titre: 'Crue du Gier', message: 'Évacuez le quartier bas.',
                                           canaux: ['MATRIX', 'APPLICATION'], urgent: true, terrain: [], relayer: [] });
    requete.flush({ id: 'a1', titre: 'Crue du Gier', message: 'Évacuez le quartier bas.', urgent: true, crise: null, crise_nom: null,
                    canaux: ['MATRIX', 'APPLICATION'], destinataires: 3, auteur: 'Agent', date: '2026-11-16T18:00:00Z',
                    bilan: { MATRIX: { partis: 3, echecs: 0, note: '' }, APPLICATION: { partis: 1, echecs: 0, note: '' } } });
    http.expectOne(r => r.url === `${api}/alertes-population/` && r.method === 'GET').flush(ETAT);
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Alerte envoyée à 3 personnes');
    expect(composant.titre).toBe('');
  });

  it('n’envoie rien sans titre, sans message, sans canal, ou si la personne renonce', () => {
    demarrer();
    const composant = fixture.componentInstance;
    expect(composant.pret).toBeFalse();

    composant.titre = 'Crue';
    composant.message = 'Texte';
    composant.choisis = {};
    expect(composant.pret).toBeFalse();

    composant.choisis = { MATRIX: true };
    spyOn(window, 'confirm').and.returnValue(false);
    composant.envoyer();
    http.expectNone(r => r.method === 'POST');
  });
});
