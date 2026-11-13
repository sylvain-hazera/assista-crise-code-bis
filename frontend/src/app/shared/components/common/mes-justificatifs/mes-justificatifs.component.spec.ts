import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { MesJustificatifsComponent } from './mes-justificatifs.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';
import { QualificationMembre } from '../../../models/association.model';

/**
 * Le dépôt et le suivi des pièces, extraits de « Ma fiche de bénévole » le 13/11/2026 pour
 * être partagés avec « Mon espace ». Les tests ont suivi le code : les laisser sur la page
 * aurait testé une page qui ne porte plus ce formulaire.
 *
 * Ce qui est tenu ici est ce qui a des conséquences : l'échéance préremplie (une date fausse
 * fait croire à un titre valide), le refus de déposer sans fichier, et surtout la mise en
 * avant de ce qui attend une action — un refus qu'on découvrirait par hasard ne serait jamais
 * corrigé.
 */
describe('MesJustificatifsComponent', () => {
  let composant: MesJustificatifsComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const piece = (sur: Partial<QualificationMembre>): QualificationMembre => ({
    id: 'p1', utilisateur: 'u1', qualification: 'q1', qualification_nom: 'PSE1',
    expiree: false, jours_avant_expiration: null, statut: 'DECLAREE',
    a_justificatif: true, ...sur,
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest()],
      imports: [MesJustificatifsComponent],
    });
    composant = TestBed.createComponent(MesJustificatifsComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  function charger(miennes: QualificationMembre[] = []): void {
    composant.ngOnInit();
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

  it('déduit l\'échéance de la durée de validité du titre', () => {
    // Une échéance fausse fait croire à un titre valide le jour de la mobilisation.
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

  it('met en avant ce qui attend une action, refus comme pièce manquante', () => {
    // Un refus qu'on découvrirait en rouvrant la page par hasard ne serait jamais corrigé.
    charger([
      piece({ id: 'a', statut: 'VERIFIEE' }),
      piece({ id: 'b', statut: 'REFUSEE', motif_refus: 'Document illisible' }),
      piece({ id: 'c', statut: 'DECLAREE', a_justificatif: false }),
    ]);

    expect(composant.aCorriger.map(q => q.id)).toEqual(['b', 'c']);
    expect(composant.aUnRefus).toBeTrue();
  });

  it('distingue une pièce en attente de vérification d\'une pièce absente', () => {
    charger([
      piece({ id: 'a', statut: 'DECLAREE', a_justificatif: true }),
      piece({ id: 'b', statut: 'DECLAREE', a_justificatif: false }),
    ]);

    expect(composant.enAttenteDeVerification.map(q => q.id)).toEqual(['a']);
  });

  it('annonce la règle de conservation du titre choisi', () => {
    // Apprendre après coup que sa photo de permis a été détruite n'est pas un consentement.
    composant.ngOnInit();
    http.expectOne(`${api}/qualifications/`).flush([
      { id: 'q1', nom: 'Permis B', actif: true,
        conservation: { cle: 'PERMIS', libelle: 'Permis de conduire', famille: 'PERSONNE',
                        regime: 'VERIFIER_DETRUIRE', duree: 'Copie détruite',
                        base_legale: 'RGPD art. 5.1.e', pourquoi: 'Vous confier un véhicule',
                        ferme: false, deposable: true } },
    ]);
    http.match(r => r.url.includes('/qualifications-membres')).forEach(r => r.flush([]));

    composant.depot.qualification = 'q1';
    expect(composant.regleDuTitreChoisi?.regime).toBe('VERIFIER_DETRUIRE');
  });

  /**
   * Le statut dit en clair (13/11/2026). « Validé » ne dit rien du sort du FICHIER, et c'est
   * pourtant la question qu'on se pose en revenant sur cette page : est-ce que mon permis est
   * encore quelque part ? Deux documents au même statut ont connu deux sorts opposés selon
   * leur régime de conservation, et une pièce disparue sans explication passe pour un bug.
   */
  describe('le statut lisible', () => {

    it('dit que la copie a été détruite, et que c\'était prévu', () => {
      const permis = piece({
        statut: 'VERIFIEE', a_justificatif: false,
        piece_detruite_le: '2026-11-10T09:00:00Z',
      });

      expect(composant.etatLisible(permis)).toContain('détruite');
      expect(composant.etatLisible(permis)).toContain('comme prévu');
      // Pas d'œil : il ouvrirait une erreur, ce qui est pire que pas d'icône.
      expect(composant.peutConsulter(permis)).toBeFalse();
    });

    it('dit qu\'un document conservé reste consultable', () => {
      const attestation = piece({ statut: 'VERIFIEE', a_justificatif: true });

      expect(composant.etatLisible(attestation)).toContain('reconsulter');
      expect(composant.peutConsulter(attestation)).toBeTrue();
    });

    it('rend le motif du refus, qui est la seule chose actionnable', () => {
      const refusee = piece({ statut: 'REFUSEE', motif_refus: 'Document illisible' });

      expect(composant.etatLisible(refusee)).toContain('Document illisible');
    });

    it('distingue « en attente » de « rien déposé »', () => {
      expect(composant.etatLisible(piece({ statut: 'DECLAREE', a_justificatif: true })))
        .toContain('attente');
      expect(composant.etatLisible(piece({ statut: 'DECLAREE', a_justificatif: false })))
        .toContain('Aucun document');
    });
  });
});
