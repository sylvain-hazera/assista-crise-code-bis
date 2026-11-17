import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { CandidatureCriseModalComponent, CandidatureEnvoyee } from './candidature-crise-modal.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { CriseACandidater } from '../../../models/crisis.model';

/**
 * Candidater sur une crise depuis le tableau de bord (17/11/2026) : « elle nous touche » et
 * « nous pouvons aider » ne partent pas au même endroit et ne disent pas la même chose.
 */
describe('CandidatureCriseModalComponent', () => {
  let composant: CandidatureCriseModalComponent;
  let http: HttpTestingController;
  let envoyees: CandidatureEnvoyee[];

  function crise(situation: Partial<CriseACandidater['situation']> = {}): CriseACandidater {
    return {
      id: 'c1', name: 'Crue', type_display: 'Inondation', commune: 'Firminy',
      start_date: '2026-11-17T08:00:00Z', nb_communes: 1,
      situation: { impliquee: false, acteur: null, dans_la_zone: false, ...situation },
    };
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [CandidatureCriseModalComponent],
    });
    composant = TestBed.createComponent(CandidatureCriseModalComponent).componentInstance;
    composant.crise = crise();
    composant.institution = { id: 'i1', nom: 'Mairie' };
    http = TestBed.inject(HttpTestingController);
    envoyees = [];
    composant.envoyee.subscribe(e => envoyees.push(e));
  });

  afterEach(() => http.verify());

  it('n\'envoie rien tant que la situation n\'est pas dite', () => {
    expect(composant.peutEnvoyer).toBeFalse();
  });

  it('« elle nous touche » déclare l\'institution impliquée, tout le territoire par défaut', () => {
    composant.situation = 'touchee';
    composant.envoyer();

    const requete = http.expectOne(r => r.url.endsWith('/implications-crises/'));
    expect(requete.request.body).toEqual(jasmine.objectContaining({
      crise: 'c1', institution: 'i1', type_implication: 'IMPLIQUE', territoire_partiel: false,
    }));
    requete.flush({});
    expect(envoyees[0].zoneADessiner).toBeFalse();
  });

  it('une partie seulement : la commune est emmenée dessiner sa zone', () => {
    composant.situation = 'touchee';
    composant.territoire = 'dessine';
    composant.envoyer();

    const requete = http.expectOne(r => r.url.endsWith('/implications-crises/'));
    expect(requete.request.body.territoire_partiel).toBeTrue();
    requete.flush({});
    expect(envoyees[0].zoneADessiner).toBeTrue();
  });

  it('« nous pouvons aider » exige de dire avec quoi', () => {
    composant.situation = 'aide';
    expect(composant.peutEnvoyer).toBeFalse();

    composant.basculerAide('PERSONNEL');
    composant.message = '  4 agents demain  ';
    composant.envoyer();

    const requete = http.expectOne(r => r.url.endsWith('/crises/c1/proposer-aide/'));
    expect(requete.request.body).toEqual({ themes: [], message: '4 agents demain', aides: ['PERSONNEL'] });
    requete.flush({});
    expect(envoyees.length).toBe(1);
  });

  it('ne propose pas de se redéclarer', () => {
    composant.crise = crise({ impliquee: true, acteur: 'EN_ATTENTE' });
    expect(composant.peutSeDireTouchee).toBeFalse();
    expect(composant.peutProposerSonAide).toBeFalse();
  });

  it('montre le refus du serveur sans fermer la fenêtre', () => {
    composant.situation = 'aide';
    composant.basculerAide('PERSONNEL');
    composant.envoyer();

    http.expectOne(r => r.url.endsWith('/proposer-aide/'))
      .flush({ error: 'Votre proposition a déjà été transmise.' }, { status: 409, statusText: 'Conflict' });

    expect(composant.errorMessage).toBe('Votre proposition a déjà été transmise.');
    expect(envoyees.length).toBe(0);
  });
});
