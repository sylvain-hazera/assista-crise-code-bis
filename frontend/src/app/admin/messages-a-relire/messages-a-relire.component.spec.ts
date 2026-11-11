import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { BrouillonsEnvoiService } from '../../core/brouillons-envoi.service';
import { environment } from '../../../environments/environment';
import { MessagesARelireComponent } from './messages-a-relire.component';

describe('MessagesARelireComponent', () => {
  let fixture: ComponentFixture<MessagesARelireComponent>;
  let composant: MessagesARelireComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const brouillon = (extra: Record<string, unknown> = {}) => ({
    id: 'b1', institution: 'i1', institution_nom: 'Reserve Essai', cree_par_nom: null,
    canal: 'EMAIL', statut: 'A_RELIRE', statut_libelle: 'À relire', sujet: 'Compte valide',
    corps: 'Bonjour', destinataires: ['x@essai.invalide'], segments: null,
    modifie_par_relecteur: false, erreur: '',
    date_creation: new Date().toISOString(), date_traitement: null, ...extra,
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MessagesARelireComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    fixture = TestBed.createComponent(MessagesARelireComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  function repondre(liste: unknown[]) {
    const requete = http.expectOne(r => r.url === `${api}/brouillons-envoi/`);
    expect(requete.request.params.get('statut')).toBe('A_RELIRE');
    requete.flush(liste);
    fixture.detectChanges();
  }

  it('ne demande que les brouillons a relire', () => {
    repondre([brouillon()]);
    expect(composant.brouillons().length).toBe(1);
  });

  it('dit explicitement quand il n\'y a rien', () => {
    repondre([]);
    expect(fixture.nativeElement.textContent).toContain('Aucun message en attente');
  });

  it('signale ce qui approche de l\'envoi automatique', () => {
    // Le delai cote serveur est de 24 h : au-dela de 18 h, on previent. C'est le seul endroit
    // de cette page ou le temps qui passe change quelque chose.
    const vieux = new Date(Date.now() - 20 * 3600000).toISOString();
    repondre([brouillon({ date_creation: vieux })]);
    expect(composant.presqueExpire(composant.brouillons()[0])).toBeTrue();
    expect(composant.heuresDepuis(vieux)).toBe(20);
  });

  it('un brouillon recent n\'est pas signale comme urgent', () => {
    repondre([brouillon()]);
    expect(composant.presqueExpire(composant.brouillons()[0])).toBeFalse();
  });

  it('« relire » remet le message dans la file du service, sans dupliquer l\'editeur', () => {
    repondre([brouillon()]);
    const service = TestBed.inject(BrouillonsEnvoiService);

    composant.relire(composant.brouillons()[0]);

    // C'est la fenetre montee dans la coquille qui s'ouvre : un second editeur ici
    // divergerait du premier a la premiere evolution.
    expect(service.aRelire()).toEqual(['b1']);
    expect(composant.brouillons().length).toBe(0);
  });

  it('une erreur de chargement est dite, pas avalee', () => {
    http.expectOne(r => r.url === `${api}/brouillons-envoi/`)
      .flush({}, { status: 500, statusText: 'Erreur' });
    fixture.detectChanges();
    expect(composant.erreur()).toContain('Impossible');
  });
});
