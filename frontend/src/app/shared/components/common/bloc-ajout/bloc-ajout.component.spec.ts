import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { BlocAjoutComponent } from './bloc-ajout.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';

/**
 * Les trois gestes d'ajout, mutualisés (28/10/2026).
 *
 * On couvre la logique qui décide de l'expérience réelle, pas le rendu :
 *
 * 1. **Le `+` n'ouvre rien ici**, il émet — les formulaires de saisie restent aux pages, qui en
 *    ont de meilleurs que ce qu'un formulaire générique produirait.
 * 2. **Les champs requis de l'invitation**, parce qu'ils diffèrent d'une destination à l'autre
 *    et que c'est tout l'intérêt de les déclarer.
 * 3. **Le renvoi vers l'assistant de correspondance** : il ne doit apparaître QUE quand le
 *    refus vient d'en-têtes non reconnues. L'offrir sur n'importe quelle erreur enverrait vers
 *    un écran qui n'y changerait rien.
 */
describe('BlocAjoutComponent', () => {
  let composant: BlocAjoutComponent;
  let http: HttpTestingController;

  const URL_IMPORT = '/api/imports/personnel-communal/';
  const URL_INVITATION = '/api/contacts-institutions/inviter/';

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [BlocAjoutComponent],
    });

    composant = TestBed.createComponent(BlocAjoutComponent).componentInstance;
    composant.quoi = 'un contact';
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  describe('le bouton de saisie manuelle', () => {
    it('émet au lieu d\'ouvrir un formulaire', () => {
      // Les sept destinations ont des formulaires très différents (une institution a un type et
      // une commune, un contact une fonction) : les absorber ici produirait un formulaire
      // générique moins bon que chacun de ceux qu'il remplacerait.
      let emis = 0;
      composant.ajoutManuel.subscribe(() => emis++);

      composant.ajoutManuel.emit();

      expect(emis).toBe(1);
      expect(composant.panneau).toBe('aucun');
    });

    it('reprend le libellé de la page, sinon le déduit', () => {
      expect(composant.libelleBoutonManuel).toBe('Ajouter un contact');

      composant.libelleManuel = 'Nouvelle institution';

      expect(composant.libelleBoutonManuel).toBe('Nouvelle institution');
    });
  });

  describe('l\'ouverture des panneaux', () => {
    it('referme le panneau déjà ouvert', () => {
      composant.ouvrir('csv');
      expect(composant.panneau).toBe('csv');

      composant.ouvrir('csv');
      expect(composant.panneau).toBe('aucun');
    });

    it('remet à zéro en changeant de panneau', () => {
      // Un message d'erreur d'import qui survivrait à l'ouverture de l'invitation donnerait à
      // croire que c'est l'invitation qui a échoué.
      composant.errorMessage = 'Import impossible';
      composant.successMessage = '2 créés';
      composant.mappingAFaire = true;

      composant.ouvrir('invitation');

      expect(composant.errorMessage).toBe('');
      expect(composant.successMessage).toBe('');
      expect(composant.mappingAFaire).toBeFalse();
    });
  });

  describe('les champs requis de l\'invitation', () => {
    beforeEach(() => {
      composant.urlInvitation = URL_INVITATION;
      composant.champsInvitation = [
        { cle: 'email', label: 'Email', requis: true },
        { cle: 'nom', label: 'Nom', requis: true },
        { cle: 'fonction', label: 'Fonction' },
      ];
    });

    it('refuse tant qu\'un champ requis manque', () => {
      composant.invitation = { email: 'a@b.fr' };

      expect(composant.invitationValide).toBeFalse();
    });

    it('ne compte pas un champ rempli d\'espaces', () => {
      composant.invitation = { email: 'a@b.fr', nom: '   ' };

      expect(composant.invitationValide).toBeFalse();
    });

    it('accepte sans les champs facultatifs', () => {
      composant.invitation = { email: 'a@b.fr', nom: 'Mairie X' };

      expect(composant.invitationValide).toBeTrue();
    });

    it('n\'envoie pas les champs vides, et joint les champs de contexte', () => {
      composant.champsInvitationSupplementaires = { institution: 'inst-1' };
      composant.invitation = { email: 'a@b.fr', nom: 'Mairie X', fonction: '  ' };

      composant.inviter();

      const requete = http.expectOne(URL_INVITATION);
      expect(requete.request.body).toEqual({
        institution: 'inst-1', email: 'a@b.fr', nom: 'Mairie X',
      });
      requete.flush({ detail: 'Invitation envoyée.' });
    });

    it('n\'envoie rien si la validation échoue', () => {
      composant.invitation = { email: 'a@b.fr' };

      composant.inviter();

      http.expectNone(URL_INVITATION);
    });

    it('prévient la page qu\'il faut recharger', () => {
      let recharges = 0;
      composant.ajoute.subscribe(() => recharges++);
      composant.invitation = { email: 'a@b.fr', nom: 'Mairie X' };

      composant.inviter();
      http.expectOne(URL_INVITATION).flush({ detail: 'Invitation envoyée.' });

      expect(recharges).toBe(1);
      expect(composant.successMessage).toBe('Invitation envoyée.');
      // Le formulaire est vidé : sans cela, un second envoi renverrait la même invitation.
      expect(composant.invitation).toEqual({});
    });

    it('remonte le message du serveur, qui explique le refus', () => {
      composant.invitation = { email: 'a@b.fr', nom: 'Mairie X' };

      composant.inviter();
      http.expectOne(URL_INVITATION).flush(
        { error: '« Mairie X » existe déjà sur la plateforme.' },
        { status: 400, statusText: 'Bad Request' });

      expect(composant.errorMessage).toContain('existe déjà');
    });
  });

  describe('le renvoi vers l\'assistant de correspondance', () => {
    beforeEach(() => {
      composant.urlImport = URL_IMPORT;
      composant.routeAssistant = '/admin/import-personnel';
      composant.fichier = new File(['x'], 'liste.csv');
    });

    it('est proposé quand le serveur signale des en-têtes non reconnues', () => {
      composant.importer();
      http.expectOne(URL_IMPORT).flush(
        { error: 'Colonne(s) non reconnue(s) dans votre fichier : Nom, Email.' },
        { status: 400, statusText: 'Bad Request' });

      expect(composant.mappingAFaire).toBeTrue();
    });

    it('n\'est PAS proposé pour une autre erreur', () => {
      // Renvoyer vers l'écran de correspondance quand le fichier est illisible ou l'accès
      // refusé ferait perdre du temps sur un écran qui n'y changerait rien.
      composant.importer();
      http.expectOne(URL_IMPORT).flush(
        { error: 'Format de fichier non reconnu — utilisez un fichier .csv ou .xlsx.' },
        { status: 400, statusText: 'Bad Request' });

      expect(composant.errorMessage).toContain('Format de fichier');
      expect(composant.mappingAFaire).toBeFalse();
    });

    it('n\'est pas proposé si la page n\'a pas d\'assistant', () => {
      composant.routeAssistant = undefined;

      composant.importer();
      http.expectOne(URL_IMPORT).flush(
        { error: 'Colonne(s) non reconnue(s) : Nom.' },
        { status: 400, statusText: 'Bad Request' });

      expect(composant.mappingAFaire).toBeFalse();
    });
  });

  describe('le compte rendu d\'import', () => {
    beforeEach(() => {
      composant.urlImport = URL_IMPORT;
      composant.fichier = new File(['x'], 'liste.csv');
    });

    it('résume créations, rattachements et erreurs', () => {
      composant.importer();
      http.expectOne(URL_IMPORT).flush({
        crees: 3, rattaches: 2,
        erreurs: [{ ligne: 5, message: 'Email invalide' }],
      });

      expect(composant.successMessage).toContain('3 créé(s)');
      expect(composant.successMessage).toContain('2 rattaché(s)');
      expect(composant.successMessage).toContain('1 ligne(s) en erreur');
      // Les lignes rejetées sont conservées pour être listées une par une : un compte sans les
      // motifs obligerait à rejouer tout le fichier pour les retrouver.
      expect(composant.resultat?.erreurs?.length).toBe(1);
    });

    it('joint les champs de contexte au fichier', () => {
      composant.champsImportSupplementaires = { institution: 'inst-1', vide: '' };

      composant.importer();

      const requete = http.expectOne(URL_IMPORT);
      const corps = requete.request.body as FormData;
      expect(corps.get('institution')).toBe('inst-1');
      // Un champ vide n'est pas envoyé : le serveur distinguerait mal « absent » de « vide ».
      expect(corps.has('vide')).toBeFalse();
      requete.flush({ crees: 0 });
    });
  });
});
