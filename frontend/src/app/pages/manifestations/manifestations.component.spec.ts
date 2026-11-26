import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { Manifestation, ManifestationsComponent } from './manifestations.component';
import { fournisseursDeTest } from '../../testing/test-providers';

/** Manifestations d'association : s'inscrire, liste d'attente, organiser (26/11/2026). */
describe('ManifestationsComponent', () => {
  let fixture: ComponentFixture<ManifestationsComponent>;
  let composant: ManifestationsComponent;
  let http: HttpTestingController;

  const demain = new Date(Date.now() + 86400000).toISOString();
  const apresDemain = new Date(Date.now() + 2 * 86400000).toISOString();
  const M: Manifestation = {
    id: 'm1', institution: 'a1', institution_nom: 'Radio-club', type: 'SIGNALISATION_RADIO', type_libelle: 'Dispositif de signalisation radio',
    titre: 'Course des 10 km', lieu: 'Parc', organisateur: 'Mairie', debut: demain, fin: apresDemain, statut: 'PUBLIEE',
    statut_libelle: 'Publiée', places: 1, occupes: 1, je_suis_inscrit: false, organise: false, consignes: '',
    postes: [{ id: 'p1', intitule: 'Carrefour', debut: demain, fin: apresDemain, places: 1, occupes: 1, attente: 0, remarque: '',
               mon_statut: null, mon_rang_attente: null }],
    documents: [],
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting()], imports: [ManifestationsComponent] });
    fixture = TestBed.createComponent(ManifestationsComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.method === 'GET' && r.url.endsWith('/manifestations/'))
      .flush({ manifestations: [M], associations_organisees: [], types: [] });
    fixture.detectChanges();
  });

  afterEach(() => http.match(() => true));

  it('liste les manifestations à venir', () => {
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Course des 10 km');
    expect(composant.organise).toBeFalse();
  });

  it('annonce la liste d\'attente quand le poste est complet', () => {
    composant.choisie = M;
    composant.inscrire(M.postes![0], 'inscrire');
    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/manifestations/postes/p1/'));
    expect(requete.request.body).toEqual({ geste: 'inscrire' });
    requete.flush({ ...M, postes: [{ ...M.postes![0], mon_statut: 'LISTE_ATTENTE', mon_rang_attente: 2 }] });
    expect(composant.message).toContain('n° 2');
  });

  it('crée une manifestation avec ses postes (bureau)', () => {
    composant.liste = { manifestations: [], associations_organisees: [{ id: 'a1', nom: 'Radio-club' }], types: [] };
    composant.creer();
    composant.brouillon!.titre = 'Exercice';
    composant.brouillon!.debut = '2027-03-01T08:00';
    composant.brouillon!.fin = '2027-03-01T12:00';
    composant.brouillon!.postes[0].intitule = 'Poste radio';
    composant.enregistrer();
    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/manifestations/'));
    expect(requete.request.body.institution).toBe('a1');
    expect(requete.request.body.postes).toEqual([{ intitule: 'Poste radio', places: 1 }]);
    requete.flush(M);
  });
});
