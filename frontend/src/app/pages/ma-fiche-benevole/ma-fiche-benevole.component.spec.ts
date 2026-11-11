import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { MaFicheBenevoleComponent } from './ma-fiche-benevole.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { environment } from '../../../environments/environment';
import { FicheBenevole, MesDisponibilites } from '../../shared/models/fiche-benevole.model';
import { QualificationMembre } from '../../shared/models/association.model';

/**
 * Ce qui est testé ici est ce qui a des conséquences, pas le rendu :
 *
 * 1. **la détection d'un changement d'adresse.** Enregistrer une adresse modifiée fait
 *    regéocoder, donc peut faire changer d'équipe départementale. La personne doit le savoir
 *    AVANT de valider, pas le découvrir après.
 * 2. **la date vide envoyée en `null`.** L'API attend une date ou rien ; une chaîne vide est
 *    refusée, et le formulaire deviendrait impossible à enregistrer pour qui ne connaît pas
 *    sa date de naissance.
 * 3. **la concordance des mots de passe**, vérifiée avant l'appel : rien ne la rattraperait
 *    côté serveur, qui ne reçoit qu'une valeur.
 */
describe('MaFicheBenevoleComponent', () => {
  let composant: MaFicheBenevoleComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const FICHE: FicheBenevole = {
    id: 'f1', utilisateur: 'u1',
    adresse: '12 rue des Lilas', code_postal: '33000', ville: 'Bordeaux',
    latitude: 44.8, longitude: -0.57,
    commune_code: '33063', epci_code: null, departement_code: '33', region_code: '75',
    date_naissance: null, metier: 'Infirmier', situation: 'SALARIE',
    frequence_engagement: 'REGULIERE', message: '', diplome_premier_secours: false,
    date_adhesion: null, completee_le: null, est_complete: true,
    date_modification: '2026-11-11T08:00:00Z', mot_de_passe_defini: false,
  };

  function piece(partiel: Partial<QualificationMembre>): QualificationMembre {
    return {
      id: 'qm1', utilisateur: 'u1', qualification: 'q1', qualification_nom: 'PSE1',
      expiree: false, jours_avant_expiration: null, statut: 'DECLAREE',
      a_justificatif: true, ...partiel,
    } as QualificationMembre;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ...fournisseursDeTest(),
        { provide: AuthService, useValue: { getCurrentUser: () => ({
          id: 'u1', first_name: 'Marie', last_name: 'Durand',
        }) } },
      ],
      imports: [MaFicheBenevoleComponent],
    });
    composant = TestBed.createComponent(MaFicheBenevoleComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  /** Le composant charge fiche + catalogue + ses propres qualifications dans un forkJoin : il
   * faut répondre aux trois, sinon rien n'est appliqué. */
  function charger(fiche: FicheBenevole = FICHE,
                   miennes: QualificationMembre[] = []): void {
    composant.ngOnInit();
    http.expectOne(`${api}/ma-fiche-benevole/`).flush(fiche);
    http.expectOne(`${api}/qualifications/`).flush([
      { id: 'q1', nom: 'PSE1', validite_mois: 12, actif: true },
      { id: 'q2', nom: 'Permis C', actif: false },
    ]);
    http.match(r => r.url.includes('/qualifications-membres'))
      .forEach(r => r.flush(miennes));
  }

  it('écarte du catalogue les titres désactivés', () => {
    charger();
    expect(composant.catalogue.map(q => q.id)).toEqual(['q1']);
  });

  it('ne signale aucun changement d\'adresse tant qu\'on n\'y touche pas', () => {
    charger();
    expect(composant.adresseModifiee).toBeFalse();
    expect(composant.secteurConnu).toBeTrue();
  });

  it('annonce le changement d\'équipe dès que l\'adresse bouge', () => {
    charger();
    composant.saisie.ville = 'Mérignac';
    // C'est ce qui déclenche l'avertissement : un déménagement change de département, donc
    // d'équipe. Le découvrir après coup ferait croire à une perte d'affectation.
    expect(composant.adresseModifiee).toBeTrue();
  });

  it('envoie une date de naissance vide en null', () => {
    charger();
    composant.saisie.date_naissance = '';
    composant.enregistrer();

    const requete = http.expectOne(r => r.url === `${api}/ma-fiche-benevole/`
                                        && r.method === 'PATCH');
    expect(requete.request.body.date_naissance).toBeNull();
    requete.flush(FICHE);
  });

  it('remonte l\'avertissement quand l\'adresse n\'a pas pu être géolocalisée', () => {
    charger();
    composant.saisie.adresse = '99 rue introuvable';
    composant.enregistrer();
    http.expectOne(r => r.method === 'PATCH')
      .flush({ ...FICHE, avertissement: 'Adresse introuvable dans la BAN.' });

    // La fiche est enregistrée quand même : on ne sait simplement pas situer la personne.
    expect(composant.avertissement).toContain('introuvable');
  });

  it('refuse deux mots de passe différents sans appeler le serveur', () => {
    charger();
    composant.motDePasse = 'unMotDePasseSolide1';
    composant.motDePasseConfirme = 'autreChose';

    expect(composant.motsDePasseConcordent).toBeFalse();
    composant.definirMotDePasse();
    expect(composant.erreur).toContain('identiques');
    http.expectNone(`${api}/definir-mon-mot-de-passe/`);
  });

  it('affiche la règle refusée par le serveur plutôt qu\'un message générique', () => {
    charger();
    composant.motDePasse = '1234';
    composant.motDePasseConfirme = '1234';
    composant.definirMotDePasse();

    http.expectOne(`${api}/definir-mon-mot-de-passe/`).flush(
      { error: 'Ce mot de passe est trop courant.' },
      { status: 400, statusText: 'Bad Request' });

    // Remplacer ce message par « mot de passe invalide » ferait perdre la seule information
    // utile : laquelle des règles n'est pas respectée.
    expect(composant.erreur).toContain('trop courant');
  });

  it('déduit l\'échéance de la durée de validité du titre', () => {
    charger();
    composant.depot.qualification = 'q1';
    composant.depot.date_obtention = '2026-01-15';
    composant.onTitreChoisi();

    expect(composant.depot.date_expiration).toBe('2027-01-15');
  });

  it('ne dépose rien sans fichier', () => {
    charger();
    composant.depot.qualification = 'q1';
    expect(composant.depotPret).toBeFalse();
  });

  describe('les disponibilités (moteur unique)', () => {
    const DISPOS: MesDisponibilites = {
      rattachements: [{ affectation: 'a1', institution: 'i1', institution_nom: 'Reserve' }],
      jours: [
        { date: '2026-11-12', disponible: null },
        { date: '2026-11-13', disponible: true },
      ],
    };

    function ouvrirDispos(grille: MesDisponibilites = DISPOS): void {
      charger();
      composant.ouvrirOnglet('disponibilites');
      http.expectOne(r => r.url === `${api}/mes-disponibilites/`).flush(grille);
    }

    it('écrit dans le moteur des personnes ressources, pas dans la fiche', () => {
      ouvrirDispos();
      // C'est tout l'objet de la correction : une seule source, celle que lit la
      // constitution d'équipe.
      expect(composant.disponibilites?.jours.length).toBe(2);
      http.expectNone(r => r.method === 'PATCH');
    });

    it('parcourt les trois états : silence → disponible → indisponible → silence', () => {
      ouvrirDispos();
      const jour = composant.disponibilites!.jours[0];

      composant.basculerJour(jour);
      let requete = http.expectOne(`${api}/mes-disponibilites/`);
      expect(requete.request.body).toEqual({ date: '2026-11-12', disponible: true });
      requete.flush({ date: '2026-11-12', disponible: true, remplacees: 0 });
      expect(jour.disponible).toBeTrue();

      composant.basculerJour(jour);
      requete = http.expectOne(`${api}/mes-disponibilites/`);
      expect(requete.request.body.disponible).toBeFalse();
      requete.flush({ date: '2026-11-12', disponible: false, remplacees: 1 });
      expect(jour.disponible).toBeFalse();

      // Troisième clic : retour au silence. Sans lui, retirer un engagement obligerait à
      // affirmer un refus.
      composant.basculerJour(jour);
      requete = http.expectOne(`${api}/mes-disponibilites/`);
      expect(requete.request.body.disponible).toBeNull();
      requete.flush({ date: '2026-11-12', disponible: null, remplacees: 1 });
      expect(jour.disponible).toBeNull();
    });

    it('ne modifie pas la case si le serveur refuse', () => {
      ouvrirDispos();
      const jour = composant.disponibilites!.jours[1];

      composant.basculerJour(jour);
      http.expectOne(`${api}/mes-disponibilites/`).flush(
        { error: 'Ce rattachement n\'est pas le vôtre.' },
        { status: 403, statusText: 'Forbidden' });

      // Une case qui change d'apparence sans que le serveur l'ait enregistrée est pire qu'un
      // refus visible : on partirait sur une disponibilité imaginaire.
      expect(jour.disponible).toBeTrue();
      expect(composant.erreur).toContain('rattachement');
    });

    it('dit quand il n\'y a rien à déclarer plutôt que de montrer une grille vide', () => {
      ouvrirDispos({ rattachements: [], jours: [] });
      expect(composant.sansRattachement).toBeTrue();
    });

    it('distingue les trois états pour l\'affichage', () => {
      expect(composant.etatJour(true)).toBe('oui');
      expect(composant.etatJour(false)).toBe('non');
      // Un blanc n'est pas un refus.
      expect(composant.etatJour(null)).toBe('silence');
    });

    it('ne recharge pas la grille à chaque ouverture d\'onglet', () => {
      ouvrirDispos();
      composant.ouvrirOnglet('fiche');
      composant.ouvrirOnglet('disponibilites');
      http.expectNone(r => r.url === `${api}/mes-disponibilites/`);
    });
  });

  it('signale un refus pour que la pastille attire l\'œil', () => {
    charger(FICHE, [
      piece({ id: 'a', statut: 'VERIFIEE' }),
      piece({ id: 'b', statut: 'REFUSEE', motif_refus: 'Document illisible' }),
    ]);

    expect(composant.aUnRefus).toBeTrue();
    expect(composant.titresSansPiece).toEqual([]);
  });
});
