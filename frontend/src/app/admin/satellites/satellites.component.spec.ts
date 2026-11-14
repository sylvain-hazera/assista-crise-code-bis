import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { SatellitesComponent } from './satellites.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { environment } from '../../../environments/environment';
import { Satellite, VersionSatellite } from '../../shared/models/satellite.model';

/**
 * Mises à jour des satellites ordonnées d'ici. Ce qui est testé est ce qui a des conséquences :
 *
 * 1. **Le bouton n'existe que là où l'ordre serait accepté** — pas d'agent, déjà à jour, ordre
 *    déjà ouvert : rien à cliquer.
 * 2. **Pendant une crise, il faut le dire deux fois** : le refus du serveur devient une
 *    question, et seule une réponse explicite relance avec `malgre_crise`.
 * 3. **On ne publie pas n'importe quoi** : un numéro de version incomplet n'est pas envoyé.
 */
describe('SatellitesComponent — mises à jour', () => {
  let composant: SatellitesComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const COMMIT = 'a'.repeat(40);
  const VERSION: VersionSatellite = {
    id: 'v1', commit: COMMIT, libelle: 'Version A', signature: 'sig',
    date_publication: '2026-11-14T20:00:00Z', retiree: false, publiee_par_nom: null,
  };
  const SATELLITE: Satellite = {
    id: 's1', institution: 'i1', institution_nom: 'Mairie', nom: 'satellite-essai',
    profil: 'FULL', profil_libelle: 'Complet', statut_enrolement: 'APPROUVE',
    statut_enrolement_libelle: 'Approuvé', compte_service: 'u9',
    dernier_contact: '2026-11-14T20:00:00Z', version_logicielle: 'b'.repeat(40),
    date_creation: '2026-10-01T00:00:00Z', etat: 'ACTIF',
    etat_version: 'EN_RETARD', agent_present: true, mise_a_jour: null,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ...fournisseursDeTest(),
        { provide: AuthService, useValue: {
          getEnvironment: () => 'PROD', getCurrentUser: () => ({ id: 'u1', type: 'ADMIN' }),
        } },
      ],
      imports: [SatellitesComponent],
    });
    composant = TestBed.createComponent(SatellitesComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
    composant.versions = [VERSION];
    composant.satellites = [SATELLITE];
  });

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  describe('le bouton « Mettre à jour »', () => {
    it('est proposé à un satellite en retard qui a son agent', () => {
      expect(composant.peutMettreAJour(SATELLITE)).toBeTrue();
    });

    it("n'est pas proposé sans agent, et dit quoi faire sur place", () => {
      const sansAgent = { ...SATELLITE, agent_present: false };
      expect(composant.peutMettreAJour(sansAgent)).toBeFalse();
      expect(composant.raisonSansMiseAJour(sansAgent)).toContain('installer.sh mettre-a-jour');
    });

    it("n'est pas proposé à jour, ni quand un ordre est déjà ouvert, ni sans version", () => {
      expect(composant.peutMettreAJour({ ...SATELLITE, etat_version: 'A_JOUR' })).toBeFalse();
      const ouvert = { ...SATELLITE, mise_a_jour: { statut: 'DEMANDEE' } as never };
      expect(composant.peutMettreAJour(ouvert)).toBeFalse();
      composant.versions = [{ ...VERSION, retiree: true }];
      expect(composant.versionDeReference).toBeNull();
      expect(composant.peutMettreAJour(SATELLITE)).toBeFalse();
    });

    it('prend pour référence la dernière version NON retirée', () => {
      composant.versions = [{ ...VERSION, id: 'v2', retiree: true }, VERSION];
      expect(composant.versionDeReference?.id).toBe('v1');
    });
  });

  describe('pendant une crise', () => {
    it("ne relance avec malgre_crise qu'après une confirmation explicite", () => {
      const confirmer = spyOn(window, 'confirm').and.returnValues(true, true);
      composant.mettreAJour(SATELLITE);

      const premier = http.expectOne(`${api}/satellites/s1/mettre-a-jour/`);
      expect(premier.request.body).toEqual({});
      premier.flush({ error: 'Une crise est en cours', code: 'CRISE_EN_COURS', crises: ['Crue'] },
        { status: 409, statusText: 'Conflict' });

      // La question nomme la crise : c'est ce qui permet de décider.
      expect(confirmer.calls.mostRecent().args[0]).toContain('Crue');
      const second = http.expectOne(`${api}/satellites/s1/mettre-a-jour/`);
      expect(second.request.body).toEqual({ malgre_crise: true });
      second.flush({ ...SATELLITE, mise_a_jour: { statut: 'DEMANDEE' } });
      expect(composant.miseAJourOuverte(composant.satellites[0])).toBeTrue();
    });

    it("n'insiste pas si l'on répond non", () => {
      spyOn(window, 'confirm').and.returnValues(true, false);
      composant.mettreAJour(SATELLITE);
      http.expectOne(`${api}/satellites/s1/mettre-a-jour/`).flush(
        { code: 'CRISE_EN_COURS', crises: ['Crue'] }, { status: 409, statusText: 'Conflict' });
      http.expectNone(`${api}/satellites/s1/mettre-a-jour/`);
    });

    it("ne demande rien au serveur si l'on renonce dès la première question", () => {
      spyOn(window, 'confirm').and.returnValue(false);
      composant.mettreAJour(SATELLITE);
      http.expectNone(`${api}/satellites/s1/mettre-a-jour/`);
    });
  });

  describe('publier une version', () => {
    it("refuse un numéro incomplet ou un bloc qui n'est pas une signature", () => {
      composant.nouvelleVersion = { commit: 'abc1234', signature: '-----BEGIN SSH SIGNATURE-----', libelle: '' };
      expect(composant.peutPublier).toBeFalse();
      composant.nouvelleVersion = { commit: COMMIT, signature: 'bonjour', libelle: '' };
      expect(composant.peutPublier).toBeFalse();
      composant.publierVersion();
      http.expectNone(`${api}/versions-satellite/`);
    });

    it('envoie le numéro en minuscules, sans espaces, et affiche le refus du serveur', () => {
      composant.nouvelleVersion = {
        commit: `  ${COMMIT.toUpperCase()} `, signature: '-----BEGIN SSH SIGNATURE-----\nxx', libelle: ' A ',
      };
      expect(composant.peutPublier).toBeTrue();
      composant.publierVersion();
      const requete = http.expectOne(r => r.method === 'POST' && r.url === `${api}/versions-satellite/`);
      expect(requete.request.body.commit).toBe(COMMIT);
      expect(requete.request.body.libelle).toBe('A');
      requete.flush({ error: 'La signature ne correspond pas à cette version.' },
        { status: 400, statusText: 'Bad Request' });
      expect(composant.errorMessage).toContain('signature');
    });
  });
});
