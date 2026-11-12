import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { MembresAssociationComponent } from './membres-association.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { ContactInstitution } from '../../shared/models/institution.model';
import { Team } from '../../shared/models/team.model';
import { GrilleDisponibilites, MembreAnnuaire } from '../../shared/models/association.model';

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
        // Servies avec la grille depuis le 12/11/2026 : le sélecteur de fenêtre en a besoin
        // dès l'ouverture de l'onglet.
        campagnes: [], campagne: null, tronquee: false,
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

  describe('l\'arborescence enrichie : cadres, fiches, recherche et affectation', () => {
    /** Une branche de même forme que la vraie : une zone avec un département dessous.
     *
     * Les rôles viennent du SERVEUR (`roles_par_equipe`) et ne sont pas redéduits ici : la
     * même personne peut être cadre dans une équipe et intervenante dans une autre, et un
     * rôle recomposé côté navigateur finirait par diverger. */
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

    function fiche(partiel: Partial<MembreAnnuaire>): MembreAnnuaire {
      return {
        utilisateur: 'u', contact: 'c', nom: 'Nom', fonction: '', membre_bureau: false,
        statut: 'ACTIF', competences: [], a_declare: true, a_ressource: true,
        a_fiche: true, fiche_complete: true, titres: 0, titres_verifies: 0,
        titres_perimes: 0,
        ...partiel,
      } as MembreAnnuaire;
    }

    /** Zone Sud-Ouest (un cadre, un équipier) → Gironde (un cadre, deux équipiers). */
    function construire(coordonnees = true): void {
      composant.equipes = [
        equipe({ id: 'zone', name: 'Zone Sud-Ouest', echelon: 'ZONE_DEFENSE',
                 member_ids: ['uz1', 'uz2'],
                 members_info: [{ id: 'uz1', nom: 'Zoe Cadre' },
                                { id: 'uz2', nom: 'Zacharie Equipier' }] }),
        equipe({ id: 'dep', name: 'Gironde', echelon: 'DEPARTEMENTAL',
                 equipe_parente: 'zone', member_ids: ['ud1', 'ud2', 'ud3'],
                 members_info: [{ id: 'ud1', nom: 'Diane Chef' },
                                { id: 'ud2', nom: 'Denis Equipier' },
                                { id: 'ud3', nom: 'Dora Plongeuse' }] }),
      ];
      composant.rolesParEquipe = {
        zone: { uz1: 'CADRE', uz2: 'INTERVENANT' },
        dep: { ud1: 'CHEF', ud2: 'INTERVENANT', ud3: 'INTERVENANT' },
      };
      composant.coordonneesVisibles = coordonnees;
      composant.annuaire = new Map([
        ['uz1', fiche({ utilisateur: 'uz1', nom: 'Zoe Cadre', fonction: 'Présidente',
                        membre_bureau: true, ville: 'Bordeaux' })],
        ['uz2', fiche({ utilisateur: 'uz2', nom: 'Zacharie Equipier', a_declare: false })],
        ['ud1', fiche({ utilisateur: 'ud1', nom: 'Diane Chef', titres_perimes: 2 })],
        ['ud2', fiche({ utilisateur: 'ud2', nom: 'Denis Equipier', ville: 'Pessac' })],
        ['ud3', fiche({ utilisateur: 'ud3', nom: 'Dora Plongeuse', a_declare: false,
                        competences: [{ id: 'k1', nom: 'Plongée' }] })],
      ]);
      composant.aVerifier = { total: 0, par_membre: {} };
      composant['construireArborescence']();
    }

    function zone() { return composant.arborescence[0]; }
    function departement() { return composant.arborescence[0].enfants[0]; }

    it('sépare les cadres de l\'équipe et le niveau N-1', () => {
      // LE test de cette vue. Le premier cadre, ce sont les cadres de l'équipe ; le second,
      // ce qu'il y a un cran en dessous — et pour une équipe de coordination, ce sont les
      // CADRES des équipes rattachées, pas leurs équipiers. C'est ainsi qu'on lit une chaîne
      // de commandement.
      construire();

      expect(zone().cadres.map(m => m.nom)).toEqual(['Zoe Cadre']);
      const groupes = zone().groupes;
      expect(groupes.find(g => g.libelle === 'Gironde')!.membres.map(m => m.nom))
        .toEqual(['Diane Chef']);
    });

    it('pour une équipe départementale, le second cadre, ce sont ses intervenants', () => {
      // Elle n'a rien en dessous : « N-1 » ne peut plus vouloir dire autre chose.
      construire();

      expect(departement().cadres.map(m => m.nom)).toEqual(['Diane Chef']);
      const propres = departement().groupes.find(g => g.cle === 'dep:propres');
      expect(propres!.membres.map(m => m.nom)).toEqual(['Denis Equipier', 'Dora Plongeuse']);
    });

    it('montre AUSSI les intervenants d\'une équipe qui a des sous-équipes', () => {
      // Une équipe peut avoir des sous-équipes ET des équipiers en propre. Les taire les
      // ferait disparaître de l'écran.
      construire();

      expect(zone().groupes.map(g => g.cle)).toContain('zone:propres');
    });

    it('cherche dans tous les critères, pas seulement le nom', () => {
      construire();

      composant.recherche = 'plongée';
      composant.filtresChanges();
      expect(departement().groupes[0].membres.map(m => m.nom)).toEqual(['Dora Plongeuse']);

      composant.recherche = 'pessac';
      composant.filtresChanges();
      expect(departement().groupes[0].membres.map(m => m.nom)).toEqual(['Denis Equipier']);

      composant.recherche = 'présidente';
      composant.filtresChanges();
      expect(zone().cadres.map(m => m.nom)).toEqual(['Zoe Cadre']);
    });

    it('filtre ceux qui n\'ont rien déclaré — ceux qu\'il faut relancer', () => {
      construire();
      composant.filtreSansDeclaration = true;
      composant.filtresChanges();

      expect(zone().groupes.find(g => g.cle === 'zone:propres')!.membres.map(m => m.nom))
        .toEqual(['Zacharie Equipier']);
      expect(departement().groupes.find(g => g.cle === 'dep:propres')!.membres
        .map(m => m.nom)).toEqual(['Dora Plongeuse']);
    });

    it('remonte les titres périmés quand on trie dessus', () => {
      // Un titre périmé vaut un titre absent le jour du départ : c'est le tri qu'on ouvre
      // avant une mobilisation.
      construire();
      composant.tri = 'perimes';
      composant.filtresChanges();

      expect(zone().groupes.find(g => g.libelle === 'Gironde')!.membres[0].nom)
        .toBe('Diane Chef');
    });

    it('compte les correspondances par branche pour pouvoir ouvrir ce qui correspond', () => {
      construire();
      composant.recherche = 'plongée';
      composant.filtresChanges();

      expect(composant.nombreCorrespondants).toBe(1);
      composant.ouvrirCeQuiCorrespond();
      // La zone s'ouvre parce que la personne est DESSOUS : sinon on ne l'atteindrait pas.
      expect(composant.depliees.has('zone')).toBeTrue();
      expect(composant.depliees.has('dep')).toBeTrue();
    });

    it('ne propose pas de compétence que personne ne détient', () => {
      construire();
      expect(composant.competencesDeLEffectif.map(c => c.nom)).toEqual(['Plongée']);
    });

    it('affiche une personne absente de l\'annuaire au lieu de la masquer', () => {
      // Membre d'une équipe sans rattachement actif à l'association : la masquer ferait
      // mentir l'effectif affiché juste au-dessus.
      construire();
      composant.annuaire.delete('ud3');
      composant['recalculerLesVues']();

      const noms = departement().groupes.find(g => g.cle === 'dep:propres')!.membres
        .map(m => m.nom);
      expect(noms).toContain('Dora Plongeuse');
      expect(composant.ficheDe('ud3')).toBeUndefined();
    });

    it('sélectionne en masse, en travers des branches', () => {
      construire();
      composant.basculerSelection('uz1');
      composant.basculerGroupe(departement().groupes.find(g => g.cle === 'dep:propres')!
        .membres);

      expect(composant.selection.size).toBe(3);
      expect(composant.nomsSelectionnes)
        .toEqual(['Denis Equipier', 'Dora Plongeuse', 'Zoe Cadre']);
    });

    it('décoche tout un cadre quand il est déjà entièrement coché', () => {
      construire();
      const membres = departement().groupes.find(g => g.cle === 'dep:propres')!.membres;
      composant.basculerGroupe(membres);
      expect(composant.groupeEntierSelectionne(membres)).toBeTrue();

      composant.basculerGroupe(membres);
      expect(composant.selection.size).toBe(0);
    });

    it('affecte par POST ajouter-membres, jamais par un PATCH de la liste entière', () => {
      // LE test de l'affectation. Un PATCH `member_ids` envoie la liste telle que CE
      // navigateur la connaissait : deux régulateurs en même temps, et le second efface les
      // ajouts du premier.
      construire();
      composant.institutionChoisie = 'i1';
      composant.selection = new Set(['ud2', 'ud3']);
      composant.equipeCible = 'dep';
      composant.missionTitre = 'Reconnaissance berges';

      composant.affecter();

      const requete = http.expectOne(r => r.url.endsWith('/teams/dep/ajouter-membres/'));
      expect(requete.request.method).toBe('POST');
      expect(requete.request.body.utilisateurs.sort()).toEqual(['ud2', 'ud3']);
      expect(requete.request.body.mission_titre).toBe('Reconnaissance berges');
      requete.flush({ team: {}, ajoutes: 2, deja_presents: 0, refuses: [] });

      expect(composant.selection.size).toBe(0);
      expect(composant.message).toContain('2 personne(s) affectée(s)');
    });

    it('nomme les personnes refusées au lieu de les fondre dans un succès', () => {
      // Une affectation partielle présentée comme un succès fait partir une équipe
      // incomplète en croyant l'avoir au complet.
      construire();
      composant.institutionChoisie = 'i1';
      composant.selection = new Set(['ud2']);
      composant.equipeCible = 'dep';

      composant.affecter();
      http.expectOne(r => r.url.endsWith('/teams/dep/ajouter-membres/')).flush({
        team: {}, ajoutes: 0, deja_presents: 0,
        refuses: [{ utilisateur: 'ud2', motif: 'Membre sorti de l\'association.' }],
      });

      expect(composant.refusAffectation).toEqual([
        { nom: 'Denis Equipier', motif: 'Membre sorti de l\'association.' },
      ]);
    });

    it('vide la sélection quand on change d\'association', () => {
      // Une sélection faite ailleurs ferait proposer d'affecter des gens que l'équipe cible
      // ne peut pas accueillir.
      construire();
      composant.selection = new Set(['ud2']);

      composant.changerInstitution('i2');

      expect(composant.selection.size).toBe(0);
      expect(composant.equipeCible).toBeNull();
    });

    it('dit que les coordonnées sont absentes, et ne les affiche pas vides', () => {
      // « — » affirmerait qu'il n'y a pas de téléphone, alors qu'on n'a pas le droit de le
      // savoir. C'est `coordonneesVisibles` qui distingue les deux cas, et l'écran s'en sert
      // pour écrire la phrase au lieu de laisser un tiret.
      construire(false);
      expect(composant.coordonneesVisibles).toBeFalse();
      expect(composant.ficheDe('uz1')!.telephone).toBeUndefined();
    });

    it('propose les équipes opérationnelles avant les équipes de coordination', () => {
      construire();
      composant.equipes = [...composant.equipes,
        { ...composant.equipes[0], id: 'terrain', name: 'Équipe terrain 1',
          echelon: '' } as Team];

      expect(composant.equipesAffectables[0].id).toBe('terrain');
    });
  });

  describe('la grille de disponibilités', () => {
    /** Une grille minimale, à deux jours et deux créneaux : assez pour pointer, pas assez
     * pour noyer l'assertion. */
    function grille(partiel: Record<string, unknown> = {}): GrilleDisponibilites {
      return {
        institution: 'a1', institution_nom: 'AASC', debut: '2027-01-12', fin: '2027-01-13',
        jours: ['2027-01-12', '2027-01-13'], creneaux: ['MATIN', 'SOIR'],
        membres: [
          {
            utilisateur: 'u-libre', nom: 'LIBRE', membre_bureau: false,
            qualifications_expirees: 0, a_declare: true,
            jours: [
              { date: '2027-01-12', creneaux: { MATIN: true, SOIR: false } },
              { date: '2027-01-13', creneaux: { MATIN: false, SOIR: true } },
            ],
          },
        ],
        membres_en_conge: 0, campagnes: [], campagne: null, tronquee: false,
        ...partiel,
      } as GrilleDisponibilites;
    }

    it('cliquer une case prend la personne SUR ce créneau', () => {
      // La demande : on ne prend pas quelqu'un « en général », on le prend sur un créneau.
      composant.grille = grille();

      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');

      expect(composant.creneauPointe('u-libre', '2027-01-12', 'MATIN')).toBeTrue();
      expect(composant.creneauPointe('u-libre', '2027-01-12', 'SOIR')).toBeFalse();
      // Et la personne entre dans la sélection : pointer un créneau EST la sélectionner.
      expect(composant.selection.has('u-libre')).toBeTrue();
      expect(composant.totalCreneauxPointes).toBe(1);
    });

    it('décocher le nom efface ses créneaux', () => {
      // Les garder enverrait au serveur des gardes pointées pour quelqu'un d'absent de
      // l'affectation.
      composant.grille = grille();
      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');

      composant.basculerSelection('u-libre');

      expect(composant.selection.size).toBe(0);
      expect(composant.totalCreneauxPointes).toBe(0);
    });

    it('décocher la dernière case ne retire PAS la personne de la sélection', () => {
      // On vient de la choisir explicitement : la voir disparaître de la barre d'affectation
      // au moment où l'on corrige un créneau serait déroutant.
      composant.grille = grille();
      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');

      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');

      expect(composant.nombreCreneauxPointes('u-libre')).toBe(0);
      expect(composant.selection.has('u-libre')).toBeTrue();
    });

    it('« tout prendre » ne coche que les créneaux déclarés', () => {
      composant.grille = grille();

      composant.pointerToutesSesDispos(composant.grille!.membres[0]);

      expect(composant.nombreCreneauxPointes('u-libre')).toBe(2);
      expect(composant.creneauPointe('u-libre', '2027-01-12', 'MATIN')).toBeTrue();
      expect(composant.creneauPointe('u-libre', '2027-01-13', 'SOIR')).toBeTrue();
      expect(composant.creneauPointe('u-libre', '2027-01-12', 'SOIR')).toBeFalse();
    });

    it('changer de fenêtre oublie les créneaux pointés', () => {
      // « Le soir du 14 » n'a pas le même sens d'une période à l'autre : garder des cases
      // cochées invisibles ferait partir une affectation sur des créneaux que personne n'a
      // plus sous les yeux.
      composant.institutionChoisie = 'a1';
      composant.grille = grille();
      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');

      composant.campagneChoisie = 'camp-1';
      composant.changerFenetre();

      expect(composant.totalCreneauxPointes).toBe(0);
      const appel = http.expectOne(r => r.url.includes('/grille/'));
      expect(appel.request.params.get('campagne')).toBe('camp-1');
      // La durée n'est PAS envoyée avec une campagne : c'est sa période qui fait la fenêtre.
      expect(appel.request.params.get('jours')).toBeNull();
      appel.flush(grille());
    });

    it('n\'exige pas la même chose selon qu\'on affecte ou qu\'on constitue', () => {
      composant.selection = new Set(['u-libre']);

      composant.modeAffectation = 'existante';
      expect(composant.affectationPossible).toBeFalse();
      composant.equipeCible = 'e1';
      expect(composant.affectationPossible).toBeTrue();

      composant.modeAffectation = 'nouvelle';
      expect(composant.affectationPossible).toBeFalse();
      composant.nouvelleEquipeNom = '  ';
      expect(composant.affectationPossible).toBeFalse();
      composant.nouvelleEquipeNom = 'Intervention Nord';
      expect(composant.affectationPossible).toBeTrue();
    });

    it('constituer une équipe passe par creer-avec-membres, avec les créneaux', () => {
      composant.institutionChoisie = 'a1';
      composant.grille = grille();
      composant.campagneChoisie = 'camp-1';
      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');
      // `basculerSelection` déclenche le chargement des crises : on le solde ici.
      http.match(r => r.url.includes('/crises')).forEach(r => r.flush([]));
      composant.modeAffectation = 'nouvelle';
      composant.nouvelleEquipeNom = 'Intervention Nord';

      composant.affecter();

      const appel = http.expectOne(r => r.url.includes('/teams/creer-avec-membres/'));
      expect(appel.request.body.nom).toBe('Intervention Nord');
      expect(appel.request.body.institution).toBe('a1');
      expect(appel.request.body.campagne).toBe('camp-1');
      expect(appel.request.body.creneaux).toEqual([
        { utilisateur: 'u-libre', date: '2027-01-12', creneau: 'MATIN' }]);
      appel.flush({ team: {}, ajoutes: 1, deja_presents: 0, refuses: [],
                    creneaux_pointes: 1, creneaux_enregistres: 1, creneaux_ignores: [] });
    });

    it('dit où sont allés les créneaux pointés', () => {
      // Depuis `CreneauEquipe` (12/11/2026), ils vont au planning de l'équipe — dans tous les
      // cas, campagne ou non. Le dire est ce qui évite de croire à un planning qui n'existe
      // pas, ou d'ignorer celui qui vient d'être écrit.
      composant.institutionChoisie = 'a1';
      composant.grille = grille();
      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');
      http.match(r => r.url.includes('/crises')).forEach(r => r.flush([]));
      composant.equipeCible = 'e1';

      composant.affecter();

      http.expectOne(r => r.url.includes('/ajouter-membres/')).flush(
        { team: {}, ajoutes: 1, deja_presents: 0, refuses: [],
          creneaux_pointes: 1, creneaux_enregistres: 0, creneaux_ignores: [],
          creneaux_planning: 1, conflits_planning: [] });

      expect(composant.derniereNoteCreneaux).toContain("planning de l'équipe");
    });

    it('nomme les doubles engagements rapportés par le serveur', () => {
      // Quelqu'un attendu par deux équipes au même moment : « 3 conflits » n'aiderait
      // personne, il faut le nom, le jour et l'équipe concurrente.
      composant.institutionChoisie = 'a1';
      composant.grille = grille();
      composant.basculerCreneau('u-libre', '2027-01-12', 'MATIN');
      http.match(r => r.url.includes('/crises')).forEach(r => r.flush([]));
      composant.equipeCible = 'e1';

      composant.affecter();

      http.expectOne(r => r.url.includes('/ajouter-membres/')).flush(
        { team: {}, ajoutes: 1, deja_presents: 0, refuses: [],
          creneaux_pointes: 1, creneaux_enregistres: 0, creneaux_ignores: [],
          creneaux_planning: 1,
          conflits_planning: [{ utilisateur: 'u-libre', nom: 'LIBRE',
                                date: '2027-01-12', creneau: 'MATIN', equipe: 'e2',
                                equipe_nom: 'Garde voisine',
                                motif: 'Déjà engagé sur ce créneau dans l\'équipe « Garde voisine ».' }] });

      expect(composant.conflitsPlanning.length).toBe(1);
      expect(composant.conflitsPlanning[0].nom).toBe('LIBRE');
    });
  });
});
