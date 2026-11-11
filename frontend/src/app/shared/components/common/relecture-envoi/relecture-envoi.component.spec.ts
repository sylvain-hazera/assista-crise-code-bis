import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { BrouillonsEnvoiService } from '../../../../core/brouillons-envoi.service';
import { BrouillonEnvoi } from '../../../../shared/models/brouillon-envoi.model';
import { environment } from '../../../../../environments/environment';
import { RelectureEnvoiComponent } from './relecture-envoi.component';

/** La fenetre de relecture.
 *
 * Deux comportements valent d'etre verrouilles : l'avertissement quand un [LIEN_n] est perdu
 * (les vraies URL ne sortent jamais du serveur, un lien retire donne un message inutilisable),
 * et le compteur de segments SMS (la facturation est au segment, 161 caracteres coutent deux
 * fois 160). */
describe('RelectureEnvoiComponent', () => {
  let fixture: ComponentFixture<RelectureEnvoiComponent>;
  let composant: RelectureEnvoiComponent;
  let http: HttpTestingController;
  let service: BrouillonsEnvoiService;
  const api = environment.apiUrl;

  const BROUILLON: BrouillonEnvoi = {
    id: 'b1', institution: 'i1', institution_nom: 'Reserve Essai', cree_par_nom: 'Jean D.',
    canal: 'EMAIL', statut: 'A_RELIRE', statut_libelle: 'À relire',
    sujet: 'Compte valide', corps: 'Bonjour,\n\nActivez : [LIEN_1]\n\nCordialement',
    destinataires: ['benevole@essai.invalide'], segments: null,
    modifie_par_relecteur: false, erreur: '', date_creation: '2026-11-11T08:00:00Z',
    date_traitement: null,
    // Message isolé : pas de lot, un seul destinataire.
    lot: null, effectif: 1,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [RelectureEnvoiComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    fixture = TestBed.createComponent(RelectureEnvoiComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    service = TestBed.inject(BrouillonsEnvoiService);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  /** La fenetre demande les LOTS a relire et ouvre celui qui contient l'identifiant annonce :
   * un import de deux cents benevoles produit deux cents messages identiques a un nom pres,
   * et les relire un par un serait une corvee que personne ne ferait. */
  function ouvrir(brouillon: BrouillonEnvoi = BROUILLON, lots?: BrouillonEnvoi[]) {
    service.signaler([brouillon.id]);
    fixture.detectChanges();
    http.expectOne(`${api}/brouillons-envoi/lots-a-relire/`).flush(lots ?? [brouillon]);
    fixture.detectChanges();
  }

  it('ne s\'affiche pas tant qu\'aucun brouillon n\'est signale', () => {
    expect(composant.brouillon()).toBeNull();
    expect(fixture.nativeElement.querySelector('.fenetre')).toBeNull();
  });

  it('s\'ouvre sur le brouillon signale et montre a qui il part', () => {
    ouvrir();
    expect(composant.corps()).toContain('[LIEN_1]');
    const texte = fixture.nativeElement.textContent;
    expect(texte).toContain('Reserve Essai');
    expect(texte).toContain('benevole@essai.invalide');
  });

  it('avertit quand un lien est retire du message', () => {
    ouvrir();
    expect(composant.liensPerdus()).toEqual([]);

    composant.corps.set('Bonjour, sans le lien.');
    fixture.detectChanges();
    // Avertissement et NON blocage : il peut y avoir une raison de retirer un lien, mais pas
    // par accident.
    expect(composant.liensPerdus()).toEqual(['[LIEN_1]']);
    expect(fixture.nativeElement.textContent).toContain('Lien retiré du message');
  });

  it('refuse un message vide', () => {
    ouvrir();
    composant.corps.set('   ');
    composant.envoyer();
    expect(composant.erreur()).toContain('vide');
    http.expectNone(`${api}/brouillons-envoi/b1/envoyer-lot/`);
  });

  it('envoie le texte relu et vide la file', () => {
    ouvrir();
    composant.corps.set('Texte reecrit : [LIEN_1]');
    composant.envoyer();

    const requete = http.expectOne(`${api}/brouillons-envoi/b1/envoyer-lot/`);
    expect(requete.request.body.corps).toBe('Texte reecrit : [LIEN_1]');
    requete.flush({ envoyes: 1, echecs: [] });

    expect(composant.brouillon()).toBeNull();
    expect(service.aRelire()).toEqual([]);
  });

  it('exige un motif pour abandonner', () => {
    ouvrir();
    composant.demandeAbandon.set(true);
    composant.abandonner();
    expect(composant.erreur()).toContain('motif');
    http.expectNone(`${api}/brouillons-envoi/b1/abandonner/`);

    composant.motifAbandon.set('Prevenu par telephone');
    composant.abandonner();
    http.expectOne(`${api}/brouillons-envoi/b1/abandonner/`)
      .flush({ ...BROUILLON, statut: 'ABANDONNE' });
    expect(composant.brouillon()).toBeNull();
  });

  it('« plus tard » ferme sans rien envoyer', () => {
    ouvrir();
    composant.reporter();
    expect(composant.brouillon()).toBeNull();
    expect(service.aRelire()).toEqual([]);
    http.expectNone(`${api}/brouillons-envoi/b1/envoyer-lot/`);
  });

  it('compte les segments d\'un SMS', () => {
    ouvrir({ ...BROUILLON, canal: 'SMS', corps: 'court' });
    expect(composant.segments()).toEqual({ segments: 1, restants: 155 });

    // 161 caracteres : DEUX segments factures. C'est ce que personne ne devine.
    composant.corps.set('x'.repeat(161));
    expect(composant.segments()?.segments).toBe(2);
  });

  it('ne compte pas de segments pour un email', () => {
    ouvrir();
    expect(composant.segments()).toBeNull();
  });

  it('annonce l\'ampleur d\'un lot et ne le valide qu\'une fois', () => {
    // Le cas qui a motive les lots : six messages identiques a un nom pres. Le relecteur voit
    // le texte generique, l'effectif, et valide une seule fois -- chaque message repart
    // personnalise cote serveur.
    const LOT: BrouillonEnvoi = {
      ...BROUILLON, id: 'rep', lot: 'l1', effectif: 6,
      corps: 'Bonjour [PRENOM],\n\nActivez : [LIEN_1]',
      destinataires: ['a@essai.invalide'],
      destinataires_du_lot: [
        'a@essai.invalide', 'b@essai.invalide', 'c@essai.invalide',
        'd@essai.invalide', 'e@essai.invalide', 'f@essai.invalide',
      ],
    };
    ouvrir(LOT);

    expect(composant.estUnLot()).toBe(true);
    expect(composant.effectif()).toBe(6);
    // Les champs de personnalisation sont montres pour que « [PRENOM] » ne passe pas pour une
    // coquille ; les liens n'en font pas partie, ils restent masques.
    expect(composant.champsAttendus()).toEqual(['[PRENOM]']);
    expect(fixture.nativeElement.textContent).toContain('6');

    composant.envoyer();
    const requete = http.expectOne(`${api}/brouillons-envoi/rep/envoyer-lot/`);
    requete.flush({ envoyes: 6, echecs: [] });
    expect(composant.brouillon()).toBeNull();
  });

  it('garde la fenetre ouverte et NOMME les destinataires en echec', () => {
    // Un lot « partiellement envoye » qu'on croirait complet serait pire qu'un echec franc.
    ouvrir({ ...BROUILLON, lot: 'l1', effectif: 3 });
    composant.envoyer();
    http.expectOne(`${api}/brouillons-envoi/b1/envoyer-lot/`).flush({
      envoyes: 2,
      echecs: [{ destinataires: ['c@essai.invalide'], motif: 'Adresse refusee' }],
    });
    fixture.detectChanges();

    expect(composant.brouillon()).not.toBeNull();
    expect(fixture.nativeElement.textContent).toContain('c@essai.invalide');
  });

  it('retire de la file un brouillon devenu inaccessible', () => {
    // Deja traite par un collegue, ou droits perdus : la fenetre ne doit pas rester bloquee
    // dessus indefiniment.
    service.signaler(['disparu']);
    fixture.detectChanges();
    http.expectOne(`${api}/brouillons-envoi/lots-a-relire/`).flush([]);
    fixture.detectChanges();

    expect(composant.brouillon()).toBeNull();
    expect(service.aRelire()).toEqual([]);
  });
});
