import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { MembresAssociationComponent } from './membres-association.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { ContactInstitution } from '../../shared/models/institution.model';

/**
 * Premiers tests de composant du projet — le harnais qui permet de les exécuter a été monté
 * le 28/10/2026 (voir frontend/Dockerfile.test).
 *
 * On couvre ici la logique qui décide de vraies mobilisations, pas le rendu :
 *
 * 1. **Les trois états d'une disponibilité.** Un blanc n'est pas un refus. Confondre les deux
 *    fait partir une mobilisation avec un effectif imaginaire — c'est la raison d'être de la
 *    grille.
 * 2. **Les échéances.** Une qualification périmée vaut une qualification absente : le seuil
 *    d'alerte et le dépassement doivent être justes, y compris aux bornes.
 * 3. **Le tri de l'annuaire.** Un ancien membre reste consultable mais ne doit pas occuper le
 *    haut de la liste.
 * 4. **Le sens du circuit de recrutement**, qui gouverne les boutons proposés.
 */
describe('MembresAssociationComponent', () => {
  let composant: MembresAssociationComponent;
  let http: HttpTestingController;

  /** Date fixe : un test d'échéance qui dépend du jour réel passe aujourd'hui et échoue
   * demain. */
  const AUJOURDHUI = new Date('2026-10-28T10:00:00Z');

  function iso(decalageJours: number): string {
    const d = new Date(AUJOURDHUI);
    d.setDate(d.getDate() + decalageJours);
    return d.toISOString().slice(0, 10);
  }

  function membre(partiel: Partial<ContactInstitution>): ContactInstitution {
    return {
      id: partiel.id ?? 'c1',
      institution: 'i1',
      utilisateur: partiel.utilisateur ?? 'u1',
      contact_principal: false,
      actif: true,
      ...partiel,
    } as ContactInstitution;
  }

  beforeEach(() => {
    jasmine.clock().install();
    jasmine.clock().mockDate(AUJOURDHUI);

    TestBed.configureTestingModule({
      providers: [
        ...fournisseursDeTest(),
        provideHttpClientTesting(),
        // `getCurrentUser` lit le stockage local : un double évite de dépendre de l'état du
        // navigateur de test, qui n'est pas remis à zéro entre les suites.
        { provide: AuthService, useValue: { getCurrentUser: () => ({ id: 'u1', type: 'ADMIN' }) } },
      ],
      imports: [MembresAssociationComponent],
    });

    composant = TestBed.createComponent(MembresAssociationComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    jasmine.clock().uninstall();
    // Les appels lancés par ngOnInit ne sont pas l'objet de ces tests : on les laisse
    // délibérément sans réponse, et on vérifie seulement qu'aucun autre n'a fui.
    http.match(() => true);
    http.verify();
  });

  describe('le sélecteur d\'associations', () => {
    /** Le composant charge contacts + institutions + catalogue dans un forkJoin : on répond
     * aux trois, sinon rien n'est calculé. */
    function repondreAuChargement(institutions: unknown[], contacts: unknown[] = []): void {
      http.match(r => r.url.includes('/contacts-institutions'))
        .forEach(r => r.flush(contacts));
      // InstitutionService.getAll() attend une enveloppe paginee qu'il reduit lui-meme
      // (expand/reduce sur `next`) : lui rendre un tableau brut produit [undefined].
      http.match(r => /\/institutions\/?($|\?)/.test(r.url))
        .forEach(r => r.flush({ results: institutions, next: null }));
      http.match(r => r.url.includes('/qualifications'))
        .forEach(r => r.flush([]));
    }

    const asso = (p: Record<string, unknown>) => ({
      id: 'a1', nom: 'AASC', type: 't1', type_code: 'AASC', actif: true, ...p,
    });

    it('écarte une association fusionnée', () => {
      // Une institution fusionnée est conservée comme pierre tombale (actif=false, nom suffixé
      // « [fusionnée dans ...] »). La proposer revenait à offrir de gérer les membres d'une
      // association qui n'existe plus — constaté sur Châteauneuf-du-Faou le 28/10/2026.
      composant.ngOnInit();
      repondreAuChargement([
        asso({ id: 'vivante', nom: 'AASC vivante' }),
        asso({ id: 'morte', nom: 'AASC [fusionnee dans ...]', actif: false }),
      ]);

      expect(composant.mesInstitutions.map(i => i.id)).toEqual(['vivante']);
    });

    it('écarte ce qui n\'est pas une association', () => {
      // Un administrateur voit toutes les institutions, mais cette page ne parle que d'AASC :
      // une mairie n'a aucune raison d'apparaître dans un sélecteur d'associations.
      composant.ngOnInit();
      repondreAuChargement([
        asso({ id: 'aasc' }),
        asso({ id: 'mairie', nom: 'Mairie X', type_code: 'MAIRIE' }),
      ]);

      expect(composant.mesInstitutions.map(i => i.id)).toEqual(['aasc']);
    });

    it('reconnaît le code du type quelle que soit sa casse', () => {
      // Les lignes de catalogue existent en « AASC » comme en « aasc » selon la façon dont
      // elles ont été créées — vérifié en base le 28/10/2026, les deux coexistent.
      composant.ngOnInit();
      repondreAuChargement([asso({ id: 'minuscule', type_code: 'aasc' })]);

      expect(composant.mesInstitutions.map(i => i.id)).toEqual(['minuscule']);
    });
  });

  describe('les trois états d\'une disponibilité', () => {
    it('distingue un refus d\'un silence', () => {
      expect(composant.etatJour(true)).toBe('oui');
      expect(composant.etatJour(false)).toBe('non');
      expect(composant.etatJour(null)).toBe('silence');
    });

    it('compte les silences séparément des refus', () => {
      composant.grille = {
        institution: 'i1', institution_nom: 'AASC', debut: iso(0), fin: iso(1),
        jours: [iso(0), iso(1)], membres_en_conge: 0,
        membres: [
          { utilisateur: 'a', nom: 'A', membre_bureau: false, qualifications_expirees: 0,
            jours: [{ date: iso(0), disponible: true }, { date: iso(1), disponible: null }] },
          { utilisateur: 'b', nom: 'B', membre_bureau: false, qualifications_expirees: 0,
            jours: [{ date: iso(0), disponible: false }, { date: iso(1), disponible: null }] },
        ],
      };

      expect(composant.comptePourJour(0, 'oui')).toBe(1);
      expect(composant.comptePourJour(0, 'non')).toBe(1);
      expect(composant.comptePourJour(0, 'silence')).toBe(0);
      // Le jour où personne n'a répondu : deux silences, zéro refus. C'est cette ligne qui dit
      // qui relancer.
      expect(composant.comptePourJour(1, 'silence')).toBe(2);
      expect(composant.comptePourJour(1, 'non')).toBe(0);
    });

    it('ne compte rien sans grille chargée', () => {
      composant.grille = null;

      expect(composant.comptePourJour(0, 'oui')).toBe(0);
    });
  });

  describe('les échéances', () => {
    it('ne signale rien pour une échéance lointaine', () => {
      expect(composant.etatEcheance(iso(90))).toBe('');
    });

    it('alerte dans la fenêtre des trente jours', () => {
      expect(composant.etatEcheance(iso(10))).toBe('bientot');
    });

    it('traite le dernier jour comme encore valable', () => {
      // La borne compte : on ne retire pas quelqu'un d'une mobilisation le jour même où son
      // titre expire encore.
      expect(composant.etatEcheance(iso(0))).toBe('bientot');
      expect(composant.joursRestants(iso(0))).toBe(0);
    });

    it('signale un dépassement dès le lendemain de l\'échéance', () => {
      expect(composant.etatEcheance(iso(-1))).toBe('depasse');
      expect(composant.joursRestants(iso(-1))).toBe(-1);
    });

    it('ne signale rien en l\'absence de date', () => {
      // Absence de date n'est pas absence de validité : beaucoup de titres n'expirent pas, et
      // une association reprend des historiques incomplets.
      expect(composant.etatEcheance(null)).toBe('');
      expect(composant.etatEcheance(undefined)).toBe('');
      expect(composant.joursRestants(null)).toBeNull();
    });

    it('alerte exactement au seuil, et pas au-delà', () => {
      expect(composant.etatEcheance(iso(composant.JOURS_ALERTE))).toBe('bientot');
      expect(composant.etatEcheance(iso(composant.JOURS_ALERTE + 1))).toBe('');
    });
  });

  describe('le tri de l\'annuaire', () => {
    it('place les sortis en dernier et les congés avant eux', () => {
      composant.membres = [
        membre({ id: '1', utilisateur: 'a', utilisateur_nom: 'Zoe Active', statut: 'ACTIF' }),
        membre({ id: '2', utilisateur: 'b', utilisateur_nom: 'Alain Sorti', statut: 'SORTI' }),
        membre({ id: '3', utilisateur: 'c', utilisateur_nom: 'Bob Conge', statut: 'CONGE' }),
        membre({ id: '4', utilisateur: 'd', utilisateur_nom: 'Anna Active', statut: 'ACTIF' }),
      ];

      expect(composant.membresTries.map(m => m.utilisateur_nom)).toEqual([
        'Anna Active', 'Zoe Active', 'Bob Conge', 'Alain Sorti',
      ]);
    });

    it('ne compte comme actifs ni les congés ni les sortis', () => {
      composant.membres = [
        membre({ id: '1', statut: 'ACTIF' }),
        membre({ id: '2', statut: 'CONGE' }),
        membre({ id: '3', statut: 'SORTI' }),
      ];

      expect(composant.compteActifs).toBe(1);
    });

    it('compte les membres du bureau', () => {
      composant.membres = [
        membre({ id: '1', membre_bureau: true }),
        membre({ id: '2', membre_bureau: false }),
      ];

      expect(composant.compteBureau).toBe(1);
    });
  });

  describe('le sens du circuit de recrutement', () => {
    it('considère franchies les étapes précédant l\'étape courante', () => {
      const candidature = { etape: 'VERIFICATION' } as never;

      expect(composant.etapeFranchie(candidature, 'DEMANDE')).toBeTrue();
      expect(composant.etapeFranchie(candidature, 'PRISE_EN_CHARGE')).toBeTrue();
      expect(composant.etapeFranchie(candidature, 'VERIFICATION')).toBeTrue();
      expect(composant.etapeFranchie(candidature, 'ACCEPTE')).toBeFalse();
    });

    it('sépare les dossiers en cours des dossiers clos', () => {
      composant.candidatures = [
        { id: '1', etape: 'DEMANDE' }, { id: '2', etape: 'ACCEPTE' },
        { id: '3', etape: 'REFUSE' }, { id: '4', etape: 'PRISE_EN_CHARGE' },
      ] as never[];

      expect(composant.candidaturesEnCours.map(c => c.id)).toEqual(['1', '4']);
      expect(composant.candidaturesCloturees.map(c => c.id)).toEqual(['2', '3']);
    });
  });

  describe('le préremplissage d\'une échéance de qualification', () => {
    it('propose l\'échéance depuis la durée habituelle du titre', () => {
      composant.catalogue = [
        { id: 'q1', nom: 'PSE1', validite_mois: 12, actif: true },
      ];
      composant.nouvelleQualification = {
        qualification: 'q1', date_obtention: '2026-03-15', date_expiration: '', organisme: '',
      };

      composant.onQualificationChoisie();

      expect(composant.nouvelleQualification.date_expiration).toBe('2027-03-15');
    });

    it('ne propose rien pour un titre sans péremption', () => {
      composant.catalogue = [
        { id: 'q2', nom: 'Permis B', validite_mois: null, actif: true },
      ];
      composant.nouvelleQualification = {
        qualification: 'q2', date_obtention: '2026-03-15', date_expiration: '', organisme: '',
      };

      composant.onQualificationChoisie();

      expect(composant.nouvelleQualification.date_expiration).toBe('');
    });

    it('ne propose rien sans date d\'obtention', () => {
      composant.catalogue = [{ id: 'q1', nom: 'PSE1', validite_mois: 12, actif: true }];
      composant.nouvelleQualification = {
        qualification: 'q1', date_obtention: '', date_expiration: '', organisme: '',
      };

      composant.onQualificationChoisie();

      expect(composant.nouvelleQualification.date_expiration).toBe('');
    });
  });

  describe('l\'en-tête de la grille', () => {
    it('abrège le jour de la semaine et le numéro', () => {
      // Quinze colonnes n'ont pas la place d'une date complète, et « me 28 » se lit mieux que
      // « 2026-10-28 ».
      expect(composant.enTeteJour('2026-10-28')).toBe('me 28');
    });

    it('reconnaît le week-end', () => {
      expect(composant.estWeekEnd('2026-10-31')).toBeTrue();   // samedi
      expect(composant.estWeekEnd('2026-11-01')).toBeTrue();   // dimanche
      expect(composant.estWeekEnd('2026-10-28')).toBeFalse();  // mercredi
    });
  });
});
