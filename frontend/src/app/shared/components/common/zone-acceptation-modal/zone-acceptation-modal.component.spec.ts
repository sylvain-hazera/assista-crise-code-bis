import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ZoneAcceptationModalComponent } from './zone-acceptation-modal.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { ImplicationInstitution } from '../../../models/implication.model';

/**
 * Choisir la zone en acceptant une institution sur une crise.
 *
 * La règle posée le 28/10/2026 : « je ne donne pas les droits sur une commune sur laquelle je
 * n'ai pas les droits ». Elle est appliquée par le SERVEUR ; ce qui se vérifie ici, c'est que
 * l'écran n'invente rien par-dessus et traduit fidèlement les deux manières d'accorder —
 * des communes nommées, ou toute la zone de la crise.
 */
describe('ZoneAcceptationModalComponent', () => {
  let composant: ZoneAcceptationModalComponent;
  let http: HttpTestingController;

  const IMPLICATION = { id: 'i1', institution_nom: 'Casques Jaunes' } as ImplicationInstitution;
  const URL = '/implications-crises/i1/zone-delegable/';

  function repondre(zone: Partial<{ communes: { code: string; nom: string }[];
                                    couvre_toute_la_crise: boolean;
                                    deja_accordees: string[] }>): void {
    http.expectOne(r => r.url.includes(URL)).flush({
      communes: zone.communes ?? [],
      couvre_toute_la_crise: zone.couvre_toute_la_crise ?? false,
      deja_accordees: zone.deja_accordees ?? [],
    });
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [ZoneAcceptationModalComponent],
    });
    composant = TestBed.createComponent(ZoneAcceptationModalComponent).componentInstance;
    composant.implication = IMPLICATION;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  it('coche d\'emblée la seule commune accordable', () => {
    // Demander de cocher l'unique case possible est une formalité vide, et en pleine crise
    // chaque geste compte.
    composant.ngOnInit();
    repondre({ communes: [{ code: '29026', nom: 'Châteauneuf' }] });

    expect(composant.estCochee('29026')).toBeTrue();
    expect(composant.peutValider).toBeTrue();
  });

  it('ne coche rien quand plusieurs communes sont possibles', () => {
    composant.ngOnInit();
    repondre({ communes: [
      { code: '29026', nom: 'Châteauneuf' }, { code: '29027', nom: 'Beuzec' },
    ] });

    expect(composant.selection.size).toBe(0);
    expect(composant.peutValider).toBeFalse();
  });

  it('reprend les communes déjà accordées', () => {
    composant.ngOnInit();
    repondre({
      communes: [{ code: '29026', nom: 'A' }, { code: '29027', nom: 'B' }],
      deja_accordees: ['29027'],
    });

    expect(composant.estCochee('29027')).toBeTrue();
    expect(composant.estCochee('29026')).toBeFalse();
  });

  it('n\'envoie aucune commune pour « toute la crise »', () => {
    // Et c'est volontaire : l'acceptation reste juste si la crise s'étend ensuite.
    composant.ngOnInit();
    repondre({ communes: [{ code: '29026', nom: 'A' }], couvre_toute_la_crise: true });
    composant.basculerToutLeCrise();

    composant.accepter();

    const requete = http.expectOne(r => r.url.includes('/valider/'));
    expect(requete.request.body).toEqual({});
    requete.flush({});
  });

  it('envoie les communes cochées', () => {
    composant.ngOnInit();
    repondre({ communes: [{ code: '29026', nom: 'A' }, { code: '29027', nom: 'B' }] });
    composant.basculer('29026');
    composant.basculer('29027');

    composant.accepter();

    const requete = http.expectOne(r => r.url.includes('/valider/'));
    expect((requete.request.body as { communes: string[] }).communes.sort())
      .toEqual(['29026', '29027']);
    requete.flush({});
  });

  it('cocher une commune sort du mode « toute la crise »', () => {
    // Les deux diraient la même chose aujourd'hui, mais pas demain si la crise s'étend.
    composant.ngOnInit();
    repondre({ communes: [{ code: '29026', nom: 'A' }], couvre_toute_la_crise: true });
    composant.basculerToutLeCrise();
    expect(composant.touteLaCrise).toBeTrue();

    composant.basculer('29026');

    expect(composant.touteLaCrise).toBeFalse();
    expect(composant.estCochee('29026')).toBeTrue();
  });

  it('n\'accorde rien quand le donneur n\'a de droits sur aucune commune', () => {
    composant.ngOnInit();
    repondre({ communes: [] });

    expect(composant.peutValider).toBeFalse();
    expect(composant.resume).toBe('aucune commune');
  });
});
