import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { StocksPretsComponent } from './stocks-prets.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';
import { PretMateriel } from '../../../shared/models/stock.model';

/** Prêts de matériel dans les deux sens, avec fiche d'état au départ et au retour. */
describe('StocksPretsComponent', () => {
  let fixture: ComponentFixture<StocksPretsComponent>;
  let composant: StocksPretsComponent;
  let http: HttpTestingController;
  const api = `${environment.apiUrl}/stocks`;
  const PRET = {
    id: 'p1', sens: 'CONSENTI', tiers: 't1', tiers_nom: 'M. Bernard', tiers_type: 'Particulier', article: 'a1', depot: 'd1',
    designation: 'Groupe électrogène', identification: 'SN-1', quantite: '2.000', quantite_rendue: null, unite: 'unité',
    date_debut: '2026-11-01', retour_prevu: '2026-11-05', date_retour: null, etat_depart: 'BON', etat_depart_libelle: 'Bon état',
    constat_depart: '', etat_retour: '', etat_retour_libelle: '', constat_retour: '', statut: 'EN_COURS', statut_libelle: 'En cours',
    crise: null, conditions: '', en_retard: true, photos: { depart: 0, retour: 0 },
  } as PretMateriel;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [StocksPretsComponent], providers: fournisseursDeTest() });
    fixture = TestBed.createComponent(StocksPretsComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(`${api}/prets/`).flush([PRET]);
    http.expectOne(`${api}/tiers/`).flush([{ id: 't1', nom: 'M. Bernard', type: 'PARTICULIER', actif: true }]);
    fixture.detectChanges();
  });

  it('signale les prêts en retard et remplit la fiche de retour', () => {
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('1 prêt(s) n\'ont pas été rendus');
    const change = spyOn(composant.stockChange, 'emit');

    composant.ouvrirRetour(PRET);
    composant.retour!.etat_retour = 'DEGRADE';
    composant.retour!.quantite_rendue = 1;
    composant.rendre();

    const envoi = http.expectOne(`${api}/prets/p1/rendre/`);
    expect(envoi.request.body).toEqual({ etat_retour: 'DEGRADE', constat_retour: '', quantite_rendue: 1 });
    envoi.flush({ ...PRET, statut: 'LITIGE', en_retard: false });
    expect(composant.message).toContain('avec réserve');
    expect(change).toHaveBeenCalled();                              // le stock a bougé
  });

  it('enregistre un prêt reçu hors stock sans exiger de dépôt, et dépose la photo au bon moment', () => {
    composant.ouvrir('RECU');
    composant.nouveau!.tiers = 't1';
    expect(composant.complet).toBeFalse();                          // ni article ni description
    composant.nouveau!.designation = 'Remorque bâchée';
    expect(composant.complet).toBeTrue();
    composant.enregistrer();
    const creation = http.expectOne(`${api}/prets/`);
    expect(creation.request.body.sens).toBe('RECU');
    expect(creation.request.body.article).toBeUndefined();
    creation.flush({ ...PRET, id: 'p2', sens: 'RECU', article: null, en_retard: false });

    const champ = { files: [new File(['x'], 'etat.jpg', { type: 'image/jpeg' })], value: 'etat.jpg' };
    composant.ajouterPhoto(PRET, { target: champ } as unknown as Event);
    const photo = http.expectOne(`${environment.apiUrl}/documents/`);
    expect((photo.request.body as FormData).get('moment_pret')).toBe('DEPART');   // le prêt court encore
    photo.flush({});
    expect(composant.prets.find(p => p.id === 'p1')!.photos.depart).toBe(1);
  });
});
