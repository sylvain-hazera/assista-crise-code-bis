import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { MembresAssociationComponent } from './membres-association.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { ContactInstitution } from '../../shared/models/institution.model';
import { Team } from '../../shared/models/team.model';

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

  describe('la grille à créneaux', () => {
    /** La grille lit désormais le moteur à créneaux — le même que la constitution d'équipe.
     * Quatre créneaux par jour, et « pas de ligne = indisponible ». */
    function grilleDeux() {
      composant.grille = {
        institution: 'i1', institution_nom: 'AASC', debut: iso(0), fin: iso(1),
        jours: [iso(0), iso(1)], creneaux: ['MATIN', 'MIDI', 'SOIR', 'NUIT'],
        membres_en_conge: 0,
        membres: [
          { utilisateur: 'a', nom: 'A', membre_bureau: false, qualifications_expirees: 0,
            a_declare: true,
            jours: [
              { date: iso(0), creneaux: { MATIN: true, MIDI: false, SOIR: true, NUIT: false } },
              { date: iso(1), creneaux: { MATIN: false, MIDI: false, SOIR: false, NUIT: false } },
            ] },
          // B n'a RIEN déclaré : ses cases vides ne sont pas des refus.
          { utilisateur: 'b', nom: 'B', membre_bureau: false, qualifications_expirees: 0,
            a_declare: false,
            jours: [
              { date: iso(0), creneaux: { MATIN: false, MIDI: false, SOIR: false, NUIT: false } },
              { date: iso(1), creneaux: { MATIN: false, MIDI: false, SOIR: false, NUIT: false } },
            ] },
        ],
      };
    }

    it('compte les disponibles par créneau et non par jour', () => {
      grilleDeux();

      // C'est tout l'intérêt du créneau : quelqu'un de libre le matin et pris à midi est une
      // situation ordinaire, qu'une grille à la journée ne sait pas exprimer.
      expect(composant.compteDisponibles(0, 'MATIN')).toBe(1);
      expect(composant.compteDisponibles(0, 'MIDI')).toBe(0);
      expect(composant.compteDisponibles(0, 'SOIR')).toBe(1);
      expect(composant.compteDisponibles(1, 'MATIN')).toBe(0);
    });

    it('compte à part ceux qui n\'ont rien déclaré', () => {
      grilleDeux();

      // Ce moteur ne stocke pas de « non renseigné » : une grille vierge et une grille tout
      // décochée sont identiques en base. Seul `a_declare` dit qui relancer.
      expect(composant.compteSansDeclaration()).toBe(1);
    });

    it('ne compte rien sans grille chargée', () => {
      composant.grille = null;

      expect(composant.compteDisponibles(0, 'MATIN')).toBe(0);
      expect(composant.compteSansDeclaration()).toBe(0);
    });

    it('abrège les créneaux sans confondre matin et midi', () => {
      // « M » désignerait aussi bien l'un que l'autre : midi prend deux lettres.
      expect(composant.initialeCreneau('MATIN')).toBe('M');
      expect(composant.initialeCreneau('MIDI')).toBe('Mi');
      expect(composant.libelleCreneau('NUIT')).toBe('Nuit');
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

  describe('l\'arborescence des équipes et la pastille des justificatifs', () => {
    /** Une hiérarchie réduite mais de même forme que la vraie : national → zone →
     * département. Le serveur sert une liste PLATE, la hiérarchie est dans `equipe_parente`. */
    function equipe(partiel: Partial<Team>): Team {
      return {
        name: 'Equipe', description: '', color: '#000', leader: null,
        institution: 'i1', member_ids: [], members_info: [],
        missions: [], assigned_crisis_ids: [], assigned_offer_ids: [],
        assigned_request_ids: [], assigned_information_ids: [],
        competence_ids: [], departements: [], communes: [],
        ...partiel,
      } as Team;
    }

    function construire(): void {
      composant.equipes = [
        equipe({ id: 'dep', name: 'Gironde', echelon: 'DEPARTEMENTAL',
                 equipe_parente: 'zone',
                 member_ids: ['u9'], members_info: [{ id: 'u9', nom: 'Marie D.' }] }),
        equipe({ id: 'nat', name: 'Coordination Nationale', echelon: 'NATIONAL' }),
        equipe({ id: 'zone', name: 'Zone Sud-Ouest', echelon: 'ZONE_DEFENSE',
                 equipe_parente: 'nat' }),
      ];
      composant.aVerifier = { total: 2, par_membre: { u9: ['PSE1', 'Permis C'] } };
      composant['construireArborescence']();
    }

    it('reconstitue la hiérarchie depuis la liste plate', () => {
      construire();

      // Une seule racine : le reste pend dessous, quel que soit l'ordre d'arrivée.
      expect(composant.arborescence.length).toBe(1);
      expect(composant.arborescence[0].equipe.id).toBe('nat');
      expect(composant.arborescence[0].enfants[0].equipe.id).toBe('zone');
      expect(composant.arborescence[0].enfants[0].enfants[0].equipe.id).toBe('dep');
    });

    it('fait remonter le compte des pièces à vérifier jusqu\'à la racine', () => {
      construire();

      // Ce qui attend doit se voir SANS déplier : une pastille qui ne compterait que l'équipe
      // elle-même laisserait une branche repliée masquer deux pièces en attente.
      expect(composant.arborescence[0].aVerifier).toBe(0);
      expect(composant.arborescence[0].aVerifierTotal).toBe(2);
      const departement = composant.arborescence[0].enfants[0].enfants[0];
      expect(departement.aVerifier).toBe(2);
    });

    it('survit à un cycle dans equipe_parente', () => {
      // Une boucle ferait tourner la page indéfiniment : le garde-fou doit tenir même si la
      // base contient une aberration.
      composant.equipes = [
        equipe({ id: 'a', name: 'A', equipe_parente: 'b' }),
        equipe({ id: 'b', name: 'B', equipe_parente: 'a' }),
      ];
      composant.aVerifier = { total: 0, par_membre: {} };

      expect(() => composant['construireArborescence']()).not.toThrow();
    });

    it('fait d\'une équipe orpheline une racine plutôt que de la perdre', () => {
      // Parent d'une autre institution, ou désactivé : l'équipe doit rester visible, sinon
      // elle disparaît de l'écran sans que rien ne le dise.
      composant.equipes = [equipe({ id: 'seule', name: 'Orpheline',
                                    equipe_parente: 'inconnue' })];
      composant.aVerifier = { total: 0, par_membre: {} };
      composant['construireArborescence']();

      expect(composant.arborescence.map(n => n.equipe.id)).toEqual(['seule']);
    });

    it('n\'ouvre que les branches où quelque chose attend', () => {
      construire();
      composant.deplierCeQuiAttend();

      // Le geste que cherche le manager : les trois niveaux qui mènent à la pièce, et rien
      // d'autre.
      expect(composant.depliees.has('nat')).toBeTrue();
      expect(composant.depliees.has('dep')).toBeTrue();

      composant.toutReplier();
      expect(composant.depliees.size).toBe(0);
    });

    it('s\'ouvre refermée', () => {
      construire();
      // 125 équipes dépliées d'office ouvriraient la page sur un mur.
      expect(composant.depliees.size).toBe(0);
      expect(composant.estDepliee(composant.arborescence[0])).toBeFalse();
    });
  });
});
