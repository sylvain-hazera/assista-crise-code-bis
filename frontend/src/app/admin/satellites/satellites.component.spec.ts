import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { SatellitesComponent } from './satellites.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { environment } from '../../../environments/environment';
import { Satellite, VersionASigner, VersionSatellite } from '../../shared/models/satellite.model';
import {
  EMBALLAGE_DE_TEST, PHRASE_DE_TEST, SIGNATURE_SSH_KEYGEN_A,
} from '../../testing/cle-signature-de-test';

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
    const SIGNATURE = '-----BEGIN SSH SIGNATURE-----\nU1NIU0lHAAAA\nAQAAADMAAAAL\n=\n-----END SSH SIGNATURE-----';
    /** Ce qu'affiche signer-version.sh, tel qu'un terminal de téléphone le rend. */
    const AFFICHAGE = `================\nNumero de version :\n${COMMIT}\n\nSignature :\n${SIGNATURE}\n=================\n`;

    it("refuse un numéro incomplet ou un bloc qui n'est pas une signature, et dit lequel manque", () => {
      composant.nouvelleVersion = { colle: `abc1234\n${SIGNATURE}`, libelle: '' };
      expect(composant.commitReconnu).toBeNull();
      expect(composant.signatureReconnue).not.toBeNull();
      expect(composant.peutPublier).toBeFalse();

      composant.nouvelleVersion = { colle: `${COMMIT}\nbonjour`, libelle: '' };
      expect(composant.commitReconnu).toBe(COMMIT);
      expect(composant.signatureReconnue).toBeNull();
      expect(composant.signatureTronquee).toBeFalse();
      expect(composant.peutPublier).toBeFalse();

      composant.publierVersion();
      http.expectNone(`${api}/versions-satellite/`);
    });

    it('signale une signature dont la fin manque', () => {
      composant.nouvelleVersion = { colle: `${COMMIT}\n-----BEGIN SSH SIGNATURE-----\nU1NIU0lH`, libelle: '' };
      expect(composant.signatureTronquee).toBeTrue();
      expect(composant.commitReconnu).toBe(COMMIT);
      expect(composant.peutPublier).toBeFalse();
    });

    it("retrouve numéro et signature dans tout l'affichage du script collé d'un bloc", () => {
      composant.nouvelleVersion = { colle: AFFICHAGE, libelle: '' };
      expect(composant.commitReconnu).toBe(COMMIT);
      expect(composant.signatureReconnue).toBe(SIGNATURE);
      expect(composant.peutPublier).toBeTrue();
    });

    it('recolle un numéro coupé en deux lignes et accepte les majuscules', () => {
      const coupe = `${COMMIT.slice(0, 25).toUpperCase()}\n ${COMMIT.slice(25)} \n${SIGNATURE}`;
      composant.nouvelleVersion = { colle: coupe, libelle: '' };
      expect(composant.commitReconnu).toBe(COMMIT);
    });

    it('ne prend pas pour numéro une suite de 40 caractères située dans la signature', () => {
      const piege = `-----BEGIN SSH SIGNATURE-----\n${'a'.repeat(40)}\n-----END SSH SIGNATURE-----`;
      composant.nouvelleVersion = { colle: piege, libelle: '' };
      expect(composant.commitReconnu).toBeNull();
    });

    it('envoie le numéro et la signature retrouvés, et affiche le refus du serveur', () => {
      composant.nouvelleVersion = { colle: AFFICHAGE, libelle: ' A ' };
      composant.publierVersion();
      const requete = http.expectOne(r => r.method === 'POST' && r.url === `${api}/versions-satellite/`);
      expect(requete.request.body.commit).toBe(COMMIT);
      expect(requete.request.body.signature).toBe(SIGNATURE);
      expect(requete.request.body.libelle).toBe('A');
      requete.flush({ error: 'La signature ne correspond pas à cette version.' },
        { status: 400, statusText: 'Bad Request' });
      expect(composant.errorMessage).toContain('signature');
    });
  });
  /** Demande du 15/11/2026 : signer d'ici, avec la seule phrase de passe. Ce qui compte :
   * la phrase ne part JAMAIS vers le serveur, et ce qui part est une vraie signature. */
  describe('signer la dernière version depuis la page', () => {
    const A_SIGNER: VersionASigner = {
      version: { commit: COMMIT, titre: 'Veille : mesures des stations', date: '2026-11-15T12:50:00Z' },
      erreur_depot: null, deja_publiee: false, cle: EMBALLAGE_DE_TEST,
    };

    beforeEach(() => {
      composant.estAdministrateur = true;
      composant.aSigner = A_SIGNER;
      composant.libelleASigner = A_SIGNER.version!.titre;
    });

    it('signe dans le navigateur et n’envoie que le numéro et la signature', async () => {
      composant.phraseDePasse = PHRASE_DE_TEST;
      await composant.signerEtPublier();

      const envoi = http.expectOne(r => r.method === 'POST' && r.url === `${api}/versions-satellite/`);
      expect(envoi.request.body).toEqual({
        commit: COMMIT, signature: SIGNATURE_SSH_KEYGEN_A, libelle: 'Veille : mesures des stations' });
      // LE test : la phrase de passe n'est dans aucune requête, et ne reste pas dans la page.
      expect(JSON.stringify(envoi.request.body)).not.toContain(PHRASE_DE_TEST);
      expect(envoi.request.urlWithParams).not.toContain('phrase');
      expect(composant.phraseDePasse).toBe('');

      envoi.flush({ ...VERSION });
      expect(composant.messageSucces).toContain('signée et publiée');
    });

    it('avec une mauvaise phrase, rien ne part et la page le dit', async () => {
      composant.phraseDePasse = 'pas la bonne';
      await composant.signerEtPublier();

      http.expectNone(r => r.method === 'POST');
      expect(composant.erreurSignature).toBe('Phrase de passe incorrecte.');
      expect(composant.phraseDePasse).toBe('');
      expect(composant.signatureEnCours).toBeFalse();
    });

    it('affiche le refus du serveur s’il ne reconnaît pas la signature', async () => {
      composant.phraseDePasse = PHRASE_DE_TEST;
      await composant.signerEtPublier();

      http.expectOne(r => r.method === 'POST').flush(
        { error: "Cette signature ne vient pas d'une clé autorisée." }, { status: 400, statusText: 'Refus' });
      expect(composant.erreurSignature).toContain('clé autorisée');
    });

    it('ne propose pas de signer sans phrase, sans clé préparée, ni une version déjà publiée', () => {
      expect(composant.peutSigner).toBeFalse();                       // pas de phrase
      composant.phraseDePasse = PHRASE_DE_TEST;
      expect(composant.peutSigner).toBeTrue();
      composant.aSigner = { ...A_SIGNER, deja_publiee: true };
      expect(composant.peutSigner).toBeFalse();
      composant.aSigner = { ...A_SIGNER, cle: null };
      expect(composant.peutSigner).toBeFalse();
      composant.aSigner = { ...A_SIGNER, version: null, erreur_depot: 'Le dépôt public n’a pas répondu.' };
      expect(composant.peutSigner).toBeFalse();
    });

    it('ne demande la clé chiffrée que pour un administrateur, hors démonstration', () => {
      composant.estAdministrateur = false;
      composant.chargerVersionASigner();
      http.expectNone(`${api}/versions-satellite/a-signer/`);

      composant.estAdministrateur = true;
      composant.chargerVersionASigner();
      http.expectOne(`${api}/versions-satellite/a-signer/`).flush(A_SIGNER);
      expect(composant.libelleASigner).toBe('Veille : mesures des stations');
    });
  });
});
