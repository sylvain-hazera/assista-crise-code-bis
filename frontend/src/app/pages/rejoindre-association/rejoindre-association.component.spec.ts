import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { RejoindreAssociationComponent } from './rejoindre-association.component';
import { AuthService } from '../../auth/services/auth.service';
import { fournisseursDeTest } from '../../testing/test-providers';

/** Une association existante demande à rejoindre le réseau (26/11/2026). */
describe('RejoindreAssociationComponent', () => {
  let fixture: ComponentFixture<RejoindreAssociationComponent>;
  let composant: RejoindreAssociationComponent;
  let http: HttpTestingController;

  function ouvrir(connecte: boolean) {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting()], imports: [RejoindreAssociationComponent] });
    spyOn(TestBed.inject(AuthService), 'isLoggedIn').and.returnValue(connecte);
    fixture = TestBed.createComponent(RejoindreAssociationComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/associations/etendue/')).flush({ echelons: [{ code: 'COMMUNE', libelle: 'Commune du siège', territoire: '' }] });
    if (connecte) http.expectOne(r => r.method === 'GET' && r.url.endsWith('/associations/demandes/')).flush({ demande: null });
    fixture.detectChanges();
  }

  afterEach(() => http.match(() => true));

  it('demande de se connecter avant de déposer', () => {
    ouvrir(false);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Créer mon compte');
  });

  it('exige la commune choisie dans la liste, puis envoie la demande avec l\'échelon', () => {
    ouvrir(true);
    composant.nom = 'Floirac Citizen Band Amitié';
    composant.activite = 'Signaleurs radio';
    composant.envoyer();
    expect(composant.erreur).toContain('commune');
    composant.choisirCommune({ code: '33167', name: 'Floirac', codesPostaux: ['33270'], codePostal: '33270', codeDepartement: '33' });
    http.expectOne(r => r.url.endsWith('/associations/etendue/') && r.params.get('commune') === '33167').flush({ echelons: [] });
    composant.echelon = 'DEPARTEMENT';
    composant.envoyer();
    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/associations/demandes/'));
    expect(requete.request.body).toEqual(jasmine.objectContaining({ commune_code: '33167', echelon: 'DEPARTEMENT', agrement: '' }));
    requete.flush({ id: 'd1', nom: 'Floirac Citizen Band Amitié', statut: 'EN_ATTENTE', statut_libelle: 'En attente' });
    expect(composant.peutDeposer).toBeFalse();
  });
});
