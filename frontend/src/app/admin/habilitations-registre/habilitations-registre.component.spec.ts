import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { HabilitationsRegistreComponent } from './habilitations-registre.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { HabilitationRegistre } from '../../shared/models/habilitation-registre.model';
import { CandidatHabilitation } from '../../services/vulnerabilite.service';

/**
 * Désignation au registre des personnes vulnérables (art. R. 121-7 du CASF).
 *
 * On couvre ici les règles qui viennent du droit, pas le rendu :
 *
 * 1. **Un agent ne peut pas se désigner lui-même.** Le serveur le refuse ; l'écran doit le dire
 *    au moment du choix plutôt que de laisser découvrir un 400.
 * 2. **L'attestation est obligatoire.** Un formulaire validable sans elle ferait enregistrer une
 *    désignation sans son fondement.
 * 3. **Le retrait ne supprime rien** : les habilitations retirées restent lisibles, séparées des
 *    actives — c'est ce qui permet d'établir qui avait accès à une date donnée.
 */
describe('HabilitationsRegistreComponent', () => {
  let composant: HabilitationsRegistreComponent;
  let http: HttpTestingController;

  const MON_ID = 'moi-1';

  function habilitation(partiel: Partial<HabilitationRegistre>): HabilitationRegistre {
    return {
      id: partiel.id ?? 'h1',
      institution: 'i1',
      utilisateur: partiel.utilisateur ?? 'u1',
      accordee_par: MON_ID,
      qualite_accordant: 'MAIRE',
      attestation_accordant: true,
      date_octroi: '2026-10-01T10:00:00Z',
      actif: true,
      valide: true,
      engagement_signe: false,
      ...partiel,
    } as HabilitationRegistre;
  }

  function candidat(partiel: Partial<CandidatHabilitation>): CandidatHabilitation {
    return {
      id: partiel.id ?? 'u1',
      nom: partiel.nom ?? 'Agent Un',
      email: partiel.email ?? 'agent@test.fr',
      deja_habilite: partiel.deja_habilite ?? false,
      rcsc: partiel.rcsc ?? false,
    };
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ...fournisseursDeTest(),
        provideHttpClientTesting(),
        {
          provide: AuthService,
          useValue: { getCurrentUser: () => ({ id: MON_ID, type: 'AUT_LOCALE' }) },
        },
      ],
      imports: [HabilitationsRegistreComponent],
    });

    composant = TestBed.createComponent(HabilitationsRegistreComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    // Les appels de ngOnInit ne sont pas l'objet de ces tests : on les laisse délibérément sans
    // réponse, et on vérifie seulement qu'aucun autre n'a fui.
    http.match(() => true);
    http.verify();
  });

  describe('l\'auto-désignation', () => {
    it('laisse le maire se désigner lui-même', () => {
      // Sans cela, une commune qui démarre n'aurait personne pour ouvrir le registre : le
      // premier compte de la mairie est celui du maire ou d'un adjoint.
      composant.nouvelle.utilisateur = MON_ID;
      composant.nouvelle.qualite_accordant = 'MAIRE';

      expect(composant.candidatChoisiEstMoiMeme).toBeTrue();
      expect(composant.autoDesignationInterdite).toBeFalse();
    });

    it('laisse un adjoint se désigner lui-même', () => {
      composant.nouvelle.utilisateur = MON_ID;
      composant.nouvelle.qualite_accordant = 'ADJOINT';

      expect(composant.autoDesignationInterdite).toBeFalse();
    });

    it('interdit à un agent de se désigner lui-même', () => {
      composant.nouvelle.utilisateur = MON_ID;
      composant.nouvelle.qualite_accordant = 'AGENT';

      expect(composant.autoDesignationInterdite).toBeTrue();
    });

    it('laisse un agent désigner quelqu\'un d\'autre', () => {
      // L'interdiction porte sur le fait de s'habiliter soi-même, pas sur la qualité d'agent.
      composant.nouvelle.utilisateur = 'quelquun-dautre';
      composant.nouvelle.qualite_accordant = 'AGENT';

      expect(composant.candidatChoisiEstMoiMeme).toBeFalse();
      expect(composant.autoDesignationInterdite).toBeFalse();
    });

    it('ne se prononce pas avant que la qualité soit choisie', () => {
      composant.nouvelle.utilisateur = MON_ID;
      composant.nouvelle.qualite_accordant = '';

      expect(composant.autoDesignationInterdite).toBeFalse();
    });
  });

  describe('la validité du formulaire', () => {
    beforeEach(() => {
      composant.nouvelle = {
        utilisateur: 'u1', qualite_accordant: 'MAIRE', fonction: '', date_fin: '',
        attestation: true,
      };
    });

    it('accepte une désignation complète', () => {
      expect(composant.formValide).toBeTrue();
    });

    it('refuse sans attestation sur l\'honneur', () => {
      // C'est le fondement de la désignation : sans elle, rien n'est attesté et la
      // responsabilité ne porte sur personne.
      composant.nouvelle.attestation = false;

      expect(composant.formValide).toBeFalse();
    });

    it('refuse sans personne désignée', () => {
      composant.nouvelle.utilisateur = '';

      expect(composant.formValide).toBeFalse();
    });

    it('refuse sans qualité déclarée', () => {
      composant.nouvelle.qualite_accordant = '';

      expect(composant.formValide).toBeFalse();
    });

    it('refuse une auto-désignation d\'agent, même attestée', () => {
      composant.nouvelle.utilisateur = MON_ID;
      composant.nouvelle.qualite_accordant = 'AGENT';

      expect(composant.formValide).toBeFalse();
    });
  });

  describe('la liste des candidats', () => {
    it('écarte ceux qui sont déjà habilités', () => {
      // Les laisser mènerait à un refus « déjà habilitée » après coup, alors que l'information
      // est connue avant le clic.
      composant.candidats = [
        candidat({ id: 'a', deja_habilite: false }),
        candidat({ id: 'b', deja_habilite: true }),
      ];

      expect(composant.candidatsDisponibles.map(c => c.id)).toEqual(['a']);
    });
  });

  describe('la séparation des habilitations', () => {
    it('sépare les habilitations en cours de celles retirées', () => {
      composant.habilitations = [
        habilitation({ id: '1', actif: true }),
        habilitation({ id: '2', actif: false }),
        habilitation({ id: '3', actif: true }),
      ];

      expect(composant.actives.map(h => h.id)).toEqual(['1', '3']);
      expect(composant.retirees.map(h => h.id)).toEqual(['2']);
    });

    it('garde les retirées, qui ne sont jamais supprimées', () => {
      // C'est ce qui permet de répondre, un an plus tard, à « qui avait accès le jour de la
      // canicule ? ».
      composant.habilitations = [
        habilitation({ id: '2', actif: false, motif_retrait: 'Mutation' }),
      ];

      expect(composant.retirees.length).toBe(1);
      expect(composant.retirees[0].motif_retrait).toBe('Mutation');
    });
  });
});
