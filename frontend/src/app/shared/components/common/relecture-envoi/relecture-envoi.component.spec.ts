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

  function ouvrir(brouillon: BrouillonEnvoi = BROUILLON) {
    service.signaler([brouillon.id]);
    fixture.detectChanges();
    http.expectOne(`${api}/brouillons-envoi/${brouillon.id}/`).flush(brouillon);
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
    http.expectNone(`${api}/brouillons-envoi/b1/envoyer/`);
  });

  it('envoie le texte relu et vide la file', () => {
    ouvrir();
    composant.corps.set('Texte reecrit : [LIEN_1]');
    composant.envoyer();

    const requete = http.expectOne(`${api}/brouillons-envoi/b1/envoyer/`);
    expect(requete.request.body.corps).toBe('Texte reecrit : [LIEN_1]');
    requete.flush({ ...BROUILLON, statut: 'ENVOYE' });

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
    http.expectNone(`${api}/brouillons-envoi/b1/envoyer/`);
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

  it('retire de la file un brouillon devenu inaccessible', () => {
    // Deja traite par un collegue, ou droits perdus : la fenetre ne doit pas rester bloquee
    // dessus indefiniment.
    service.signaler(['disparu']);
    fixture.detectChanges();
    http.expectOne(`${api}/brouillons-envoi/disparu/`)
      .flush({}, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(composant.brouillon()).toBeNull();
    expect(service.aRelire()).toEqual([]);
  });
});
