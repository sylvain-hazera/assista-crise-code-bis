import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { CampagnesDisponibiliteComponent } from './campagnes-disponibilite.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { environment } from '../../../environments/environment';
import {
  CampagneDisponibilite, CanalEnvoi,
} from '../../shared/models/campagne-disponibilite.model';

/**
 * Ce qui est testé ici est ce qui a des conséquences, pas le rendu :
 *
 * 1. **On ne peut pas envoyer sans avoir compté.** Le bouton d'envoi n'existe qu'après un
 *    aperçu : écrire à des centaines de personnes ne se défait pas, et un critère qui ne
 *    filtre pas ce qu'on croyait doit se voir avant, pas à l'arrivée du premier mail.
 * 2. **Les critères conditionnels sont exigés.** Un rayon sans crise, ou un département sans
 *    code, ne filtre rien — donc la campagne partirait à toute l'association.
 * 3. **Le découpage en tours est montré pendant la saisie**, sinon le paramètre de rotation
 *    reste abstrait jusqu'à l'envoi.
 */
describe('CampagnesDisponibiliteComponent', () => {
  let composant: CampagnesDisponibiliteComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const CAMPAGNE: CampagneDisponibilite = {
    id: 'c1', institution: 'i1', intitule: 'Vigilance orange',
    motif: 'CRISE_A_VENIR', texte: '', crise: null,
    periode_debut: '2027-01-12', periode_fin: '2027-01-26', creneaux: [],
    echelon: 'NATIONAL', territoire_code: '', rayon_km: null,
    competences: [], qualifications: [], titres_a_jour: true, equipe: null,
    canaux: ['BREVO_EMAIL'],
    tours_de_garde: false,
    duree_rotation_jours: 3, repos_min_jours: 2, effectif_cible: 0,
    statut: 'BROUILLON',
  };

  const canal = (sur: Partial<CanalEnvoi>): CanalEnvoi => ({
    code: 'BREVO_EMAIL', libelle: 'Email', detail: '', unite: 'crédit email',
    destinataires: 10, non_joignables: 0, disponible: true, credits_restants: null,
    cout_unitaire_centimes: 1, cout_total_centimes: 10, credits_suffisants: null, ...sur,
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ...fournisseursDeTest(),
        { provide: AuthService, useValue: { getCurrentUser: () => ({ id: 'u1', type: 'ADMIN' }) } },
      ],
      imports: [CampagnesDisponibiliteComponent],
    });
    composant = TestBed.createComponent(CampagnesDisponibiliteComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    // Les appels de ngOnInit ne sont pas l'objet de ces tests : on les laisse sans réponse et
    // on vérifie seulement qu'aucun autre n'a fui.
    http.match(() => true);
    http.verify();
  });

  describe('les critères conditionnels', () => {
    it('exige un code de territoire pour un département', () => {
      composant.saisie = { ...CAMPAGNE, echelon: 'DEPARTEMENT', territoire_code: '' };
      expect(composant.demandeUnTerritoire).toBeTrue();
      expect(composant.peutEnregistrer).toBeFalse();

      composant.saisie.territoire_code = '33';
      expect(composant.peutEnregistrer).toBeTrue();
    });

    it('exige une crise ET une distance pour un rayon', () => {
      composant.saisie = { ...CAMPAGNE, echelon: 'RAYON_CRISE' };
      expect(composant.demandeUneCrise).toBeTrue();
      expect(composant.peutEnregistrer).toBeFalse();

      composant.saisie.crise = 'cr1';
      // Une crise sans rayon ne filtre rien : la campagne partirait à tout le monde.
      expect(composant.peutEnregistrer).toBeFalse();

      composant.saisie.rayon_km = 30;
      expect(composant.peutEnregistrer).toBeTrue();
    });

    it('ne demande rien de plus en national', () => {
      composant.saisie = { ...CAMPAGNE, echelon: 'NATIONAL' };
      expect(composant.demandeUnTerritoire).toBeFalse();
      expect(composant.peutEnregistrer).toBeTrue();
    });
  });

  describe('les tours de garde, en option', () => {
    it('sont désactivés par défaut', () => {
      // Le défaut va vers le moins d'effet : c'est une option qui propose d'affecter des gens.
      composant.nouvelle();
      expect(composant.saisie.tours_de_garde).toBeFalse();
      // Et l'absence de tours n'empêche pas d'enregistrer : la plupart des campagnes ne
      // veulent que recueillir des disponibilités.
      composant.saisie.intitule = 'Vigilance';
      composant.saisie.periode_debut = '2027-01-12';
      composant.saisie.periode_fin = '2027-01-26';
      expect(composant.peutEnregistrer).toBeTrue();
    });

    it('proposent un effectif dès qu\'on les active', () => {
      composant.saisie = { ...CAMPAGNE, tours_de_garde: false, effectif_cible: 0 };

      composant.basculerToursDeGarde();

      // On vient de cocher une option, pas de remplir un formulaire : laisser un zéro
      // bloquant obligerait à deviner ce qu'on attend.
      expect(composant.saisie.tours_de_garde).toBeTrue();
      expect(composant.saisie.effectif_cible).toBe(2);
    });

    it('refusent un effectif à zéro', () => {
      composant.saisie = { ...CAMPAGNE, tours_de_garde: true, effectif_cible: 0 };
      // On n'arme pas une garde avec zéro personne par créneau.
      expect(composant.peutEnregistrer).toBeFalse();

      composant.saisie.effectif_cible = 3;
      expect(composant.peutEnregistrer).toBeTrue();
    });

    it('rendent l\'effectif saisi en se réactivant', () => {
      composant.saisie = { ...CAMPAGNE, tours_de_garde: true, effectif_cible: 6 };

      composant.basculerToursDeGarde();
      composant.basculerToursDeGarde();

      // L'effectif déjà choisi n'est pas écrasé par la proposition.
      expect(composant.saisie.effectif_cible).toBe(6);
    });
  });

  describe('la période', () => {
    it('compte les jours et les tours', () => {
      composant.saisie = { ...CAMPAGNE };
      expect(composant.nombreDeJours).toBe(15);
      // Quinze jours par tranches de trois : cinq tours. Montré pendant la saisie, sinon le
      // paramètre reste abstrait.
      expect(composant.nombreDeTours).toBe(5);
    });

    it('refuse une fin antérieure au début', () => {
      composant.saisie = { ...CAMPAGNE, periode_fin: '2027-01-01' };
      expect(composant.periodeIncoherente).toBeTrue();
      expect(composant.peutEnregistrer).toBeFalse();
    });

    it('accepte une période d\'un seul jour', () => {
      composant.saisie = { ...CAMPAGNE, periode_fin: CAMPAGNE.periode_debut };
      expect(composant.nombreDeJours).toBe(1);
      expect(composant.peutEnregistrer).toBeTrue();
    });
  });

  describe('les créneaux interrogés', () => {
    it('tout décoché vaut les quatre', () => {
      composant.saisie = { ...CAMPAGNE, creneaux: [] };
      // La case est cochée quand rien n'est sélectionné : sinon l'écran montrerait quatre
      // cases vides pour dire « les quatre ».
      expect(composant.creneauCoche('MATIN')).toBeTrue();
      expect(composant.creneauCoche('NUIT')).toBeTrue();
    });

    it('une sélection explicite exclut les autres', () => {
      composant.saisie = { ...CAMPAGNE, creneaux: [] };
      composant.basculerCreneau('MATIN');
      expect(composant.saisie.creneaux).toEqual(['MATIN']);
      expect(composant.creneauCoche('NUIT')).toBeFalse();
    });
  });

  describe('l\'envoi', () => {
    it('compte sans écrire à personne', () => {
      composant.campagne = CAMPAGNE;
      composant.verifierLaCible();

      const requete = http.expectOne(`${api}/campagnes-disponibilite/c1/apercu/`);
      requete.flush({
        creees: 2, retirees: 0, total: 2, tronque: false,
        cibles: [
          { id: 'x1', campagne: 'c1', utilisateur: 'u2', nom: 'Marie D.',
            etat: 'A_CONTACTER', date_envoi: null, date_reponse: null, creneaux_declares: 0 },
          { id: 'x2', campagne: 'c1', utilisateur: 'u3', nom: 'Paul M.',
            etat: 'A_CONTACTER', date_envoi: null, date_reponse: null, creneaux_declares: 0 },
        ],
      });

      expect(composant.apercu?.total).toBe(2);
      expect(composant.apercu?.noms).toEqual(['Marie D.', 'Paul M.']);
      // Et surtout : aucun envoi.
      http.expectNone(`${api}/campagnes-disponibilite/c1/envoyer/`);
    });

    it('affiche le critère inapplicable nommé par le serveur', () => {
      composant.campagne = CAMPAGNE;
      composant.verifierLaCible();
      http.expectOne(`${api}/campagnes-disponibilite/c1/apercu/`).flush(
        { error: 'Un ciblage par rayon demande une crise rattachée et localisée.' },
        { status: 400, statusText: 'Bad Request' });

      // Le message du serveur est la seule information utile : le remplacer par « ciblage
      // impossible » ferait chercher lequel des six critères est en cause.
      expect(composant.erreur).toContain('crise rattachée');
      expect(composant.apercu).toBeNull();
    });

    it('n\'envoie pas sans aperçu préalable', () => {
      composant.campagne = CAMPAGNE;
      composant.apercu = null;

      composant.envoyer();

      // Garde-fou : on ne peut pas « dé-écrire » à des centaines de personnes.
      http.expectNone(`${api}/campagnes-disponibilite/c1/envoyer/`);
    });

    it('signale les échecs partiels plutôt que de les taire', () => {
      composant.campagne = CAMPAGNE;
      composant.apercu = { total: 3, noms: [], tronque: false };

      composant.envoyer();
      http.expectOne(`${api}/campagnes-disponibilite/c1/envoyer/`).flush({
        envoyes: 2, echecs: 1, campagne: { ...CAMPAGNE, statut: 'ENVOYEE' },
      });

      // Une campagne « partie » dont un message n'a pas abouti ferait compter quelqu'un qui
      // n'a jamais été prévenu.
      expect(composant.message).toContain('1 échec');
      expect(composant.onglet).toBe('suivi');
      http.match(() => true);
    });
  });

  describe('les tours de garde', () => {
    it('remonte les sous-effectifs nommés', () => {
      composant.campagne = CAMPAGNE;
      composant.genererRotations();
      http.expectOne(`${api}/campagnes-disponibilite/c1/rotations/`).flush({
        bilan: {
          rotations: 5, proposees: 4, conservees: 0,
          manques: [{ rotation: 2, creneau: 'NUIT', attendus: 3, trouves: 1 }],
        },
        rotations: [],
      });

      // Une grille qui paraît complète parce qu'on a caché les trous est pire que pas de
      // grille.
      expect(composant.manques.length).toBe(1);
      expect(composant.manques[0].creneau).toBe('NUIT');
    });
  });

  /**
   * Le choix du canal est une décision de dépense : ce qui compte est que l'écran ne puisse
   * pas sous-estimer le coût ni surestimer la portée.
   */
  describe('le choix des canaux', () => {
    it('part sur email seul quand rien n\'est coché', () => {
      composant.saisie = { ...CAMPAGNE, canaux: [] };
      expect(composant.canauxChoisis).toEqual(['BREVO_EMAIL']);
      expect(composant.canalCoche('BREVO_SMS')).toBeFalse();
    });

    it('refuse de cocher un canal non configuré', () => {
      const sms = canal({ code: 'BREVO_SMS', disponible: false });
      composant.saisie = { ...CAMPAGNE, canaux: ['BREVO_EMAIL'] };

      composant.basculerCanal(sms);

      expect(composant.canalCoche('BREVO_SMS')).toBeFalse();
    });

    it('annonce « coût inconnu » plutôt qu\'un zéro quand le tarif manque', () => {
      // Un total à 0 € ferait partir quatre cents SMS sans y penser.
      composant.saisie = { ...CAMPAGNE, canaux: ['BREVO_SMS'] };
      composant.canaux = [canal({
        code: 'BREVO_SMS', cout_unitaire_centimes: 0, cout_total_centimes: null,
      })];

      expect(composant.coutTotalCentimes).toBeNull();
      expect(composant.euros(composant.coutTotalCentimes)).toBe('coût inconnu');
    });

    it('additionne le coût des canaux cochés, et d\'eux seuls', () => {
      composant.saisie = { ...CAMPAGNE, canaux: ['BREVO_EMAIL'] };
      composant.canaux = [
        canal({ code: 'BREVO_EMAIL', cout_total_centimes: 10 }),
        canal({ code: 'BREVO_SMS', cout_total_centimes: 600 }),
      ];

      expect(composant.coutTotalCentimes).toBe(10);

      composant.basculerCanal(composant.canaux[1]);
      expect(composant.coutTotalCentimes).toBe(610);
    });

    it('nomme les bénévoles qu\'aucun canal coché ne joint', () => {
      composant.apercu = { total: 10, noms: [], tronque: false };
      composant.saisie = { ...CAMPAGNE, canaux: ['BREVO_SMS'] };
      composant.canaux = [canal({
        code: 'BREVO_SMS', destinataires: 6, non_joignables: 4,
      })];

      expect(composant.nonJoignablesParAucunCanal).toBe(4);
    });

    it('signale un solde insuffisant sans empêcher l\'envoi', () => {
      composant.saisie = { ...CAMPAGNE, canaux: ['BREVO_SMS'] };
      composant.canaux = [canal({
        code: 'BREVO_SMS', credits_restants: 2, credits_suffisants: false,
      })];

      expect(composant.creditsInsuffisants).toBeTrue();
      // Rien dans le composant ne bloque : partir quand même est une décision de
      // l'association.
      expect(composant.coutTotalCentimes).toBe(10);
    });

    it('ne dit pas « suffisant » quand le solde est inconnu', () => {
      composant.saisie = { ...CAMPAGNE, canaux: ['MOBIMEL'] };
      composant.canaux = [canal({ code: 'MOBIMEL', credits_suffisants: null })];

      expect(composant.creditsInsuffisants).toBeFalse();
    });
  });
});
