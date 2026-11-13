import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { ConservationPiecesComponent } from './conservation-pieces.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';
import { TableConservation } from '../../../models/conservation-piece.model';

/**
 * Ce qui est testé ici est ce qui engage : la table vient du serveur, et l'absence de table
 * n'empêche jamais de déposer une pièce.
 *
 * Le détail de la politique n'est PAS retesté côté navigateur. Il est tenu par
 * `core/tests/benevoles/test_conservation_pieces.py`, du côté où il décide vraiment de
 * détruire un fichier. Le vérifier deux fois donnerait l'illusion que le navigateur en est
 * garant.
 */
describe('ConservationPiecesComponent', () => {
  let composant: ConservationPiecesComponent;
  let http: HttpTestingController;

  const TABLE: TableConservation = {
    regimes: [
      { code: 'VERIFIER_DETRUIRE', libelle: 'Vérifier, puis détruire la copie',
        resume: '', pourquoi: '' },
      { code: 'CONSERVER_ENGAGEMENT', libelle: "Conserver le temps de l'engagement",
        resume: '', pourquoi: '' },
      { code: 'DUREE_LEGALE', libelle: 'Durée imposée par la loi', resume: '', pourquoi: '' },
    ],
    familles: [
      { code: 'PERSONNE', libelle: 'Pièces de la personne' },
      { code: 'ASSOCIATION', libelle: "Pièces de l'association" },
    ],
    pieces: [
      { cle: 'PERMIS', libelle: 'Permis de conduire', famille: 'PERSONNE',
        regime: 'VERIFIER_DETRUIRE', duree: 'Copie détruite', base_legale: 'RGPD art. 5.1.e',
        pourquoi: 'Vous confier un véhicule', ferme: false, deposable: true },
      { cle: 'COMPTABILITE', libelle: 'Pièces comptables', famille: 'ASSOCIATION',
        regime: 'DUREE_LEGALE', duree: '10 ans', base_legale: 'Art. L123-22',
        pourquoi: 'Contrôle comptable', ferme: true, deposable: false },
    ],
    jours_avant_purge_non_validee: 30,
    jours_avant_rappel_purge: 7,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest()],
      imports: [ConservationPiecesComponent],
    });
    const fixture = TestBed.createComponent(ConservationPiecesComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  function repondre(table: TableConservation = TABLE): void {
    composant.ngOnInit();
    http.expectOne(`${environment.apiUrl}/conservation-pieces/`).flush(table);
  }

  it('lit la table sur le serveur, jamais une copie locale', () => {
    repondre();

    expect(composant.table).toEqual(TABLE);
  });

  it('ne montre à un bénévole que les pièces qu\'il dépose lui-même', () => {
    composant.seulementDeposables = true;
    repondre();

    const cles = composant.familles.flatMap(f => f.pieces.map(p => p.cle));
    expect(cles).toEqual(['PERMIS']);
  });

  it('montre tout au bureau, qui tient le registre de son association', () => {
    repondre();

    const cles = composant.familles.flatMap(f => f.pieces.map(p => p.cle));
    expect(cles).toContain('COMPTABILITE');
  });

  it('ne garde pas une famille devenue vide', () => {
    composant.seulementDeposables = true;
    repondre();

    expect(composant.familles.map(f => f.code)).toEqual(['PERSONNE']);
  });

  it('reste replié tant qu\'on ne le demande pas', () => {
    // Trente lignes de droit au-dessus d'un bouton « Déposer » ne se lisent pas.
    repondre();

    expect(composant.ouvert).toBeFalse();
    composant.basculer();
    expect(composant.ouvert).toBeTrue();
  });

  it('n\'empêche pas de déposer si la table ne se charge pas', () => {
    composant.ngOnInit();
    http.expectOne(`${environment.apiUrl}/conservation-pieces/`)
      .error(new ProgressEvent('panne'));

    expect(composant.erreur).toBeTruthy();
    expect(composant.familles).toEqual([]);
  });
});
