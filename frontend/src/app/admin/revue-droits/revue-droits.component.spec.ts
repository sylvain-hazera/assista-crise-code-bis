import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { RevueDroitsComponent } from './revue-droits.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { LigneRevueDroits, MatriceRevueDroits } from '../../services/revue-droits.service';

function ligne(p: Partial<LigneRevueDroits>): LigneRevueDroits {
  return {
    contact: 'c', utilisateur: 'u', nom: 'Dominique Reserve', email: 'd@test.fr', institution: 'r', institution_nom: 'Réserve',
    fonction: 'Réserviste', actif: true, contact_principal: false, membre_bureau: false, type_compte: 'AUT_LOCALE',
    type_compte_libelle: 'Autorité locale', institution_travail: 'Mairie', roles: [], equipes: [], encadre: [],
    habilite_registre: false, engagement_signe: false, acces_formation: false, compte_actif: true,
    derniere_connexion: null, derniere_revue: null, anomalies: [], ...p,
  };
}

describe('RevueDroitsComponent', () => {
  let composant: RevueDroitsComponent;
  let http: HttpTestingController;
  const matrice: MatriceRevueDroits = {
    institution: { id: 'm', nom: 'Mairie' }, institutions: [], choix: [{ id: 'm', nom: 'Mairie' }],
    lignes: [
      ligne({ contact: 'a', nom: 'Alice', anomalies: [{ code: 'JAMAIS_REVU', libelle: 'Jamais revu' }] }),
      ligne({ contact: 'b', nom: 'Bruno', anomalies: [{ code: 'INACTIF_AVEC_DROITS', libelle: 'Inactif' }],
              derniere_revue: { le: '2026-11-01', par: 'X', decision: 'Droits confirmés' } }),
      ligne({ contact: 'c', nom: 'Chloé', actif: false }),
    ],
    resume: { fiches: 3, actives: 2, a_revoir: 1, anomalies: 1, prochaine_echeance: null, sans_responsable: [],
              periode_jours: 183, seuil_inactivite_jours: 90 },
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting()], imports: [RevueDroitsComponent] });
    composant = TestBed.createComponent(RevueDroitsComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
    composant.ngOnInit();
    http.expectOne(r => r.url.endsWith('/revue-droits/')).flush(matrice);
  });

  afterEach(() => http.verify());

  it('masque les fiches retirées, et filtre « à revoir » et « anomalies »', () => {
    expect(composant.lignes.map(l => l.nom)).toEqual(['Alice', 'Bruno']);
    composant.filtre = 'a-revoir';
    expect(composant.lignes.map(l => l.nom)).toEqual(['Alice']);
    composant.filtre = 'anomalies';
    expect(composant.lignes.map(l => l.nom)).toEqual(['Bruno']);
    composant.filtre = 'toutes';
    composant.voirInactives = true;
    expect(composant.lignes.length).toBe(3);
  });

  it('enregistre une décision puis recharge la matrice', () => {
    composant.proposer(matrice.lignes[0], 'CONFIRME', 'Confirmer les droits');
    composant.enCours!.commentaire = 'Vu en réunion';
    composant.confirmerDecision();
    const req = http.expectOne(r => r.url.endsWith('/revue-droits/decision/'));
    expect(req.request.body).toEqual(jasmine.objectContaining({ contact: 'a', decision: 'CONFIRME', commentaire: 'Vu en réunion' }));
    req.flush({ id: 'x', decision: 'Droits confirmés' });
    http.expectOne(r => r.url.endsWith('/revue-droits/')).flush(matrice);
    expect(composant.enCours).toBeNull();
    expect(composant.message).toContain('Alice');
  });
});
