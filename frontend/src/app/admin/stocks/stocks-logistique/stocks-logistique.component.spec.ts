import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { StocksLogistiqueComponent } from './stocks-logistique.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';
import { AppareilStock } from '../../../shared/models/stock.model';

/** Réservations, dotations types et appareils de la page Stocks. */
describe('StocksLogistiqueComponent', () => {
  let fixture: ComponentFixture<StocksLogistiqueComponent>;
  let composant: StocksLogistiqueComponent;
  let http: HttpTestingController;
  const api = `${environment.apiUrl}/stocks`;

  function ouvrir(vue: 'reservations' | 'dotations' | 'appareils') {
    TestBed.configureTestingModule({ imports: [StocksLogistiqueComponent], providers: fournisseursDeTest() });
    fixture = TestBed.createComponent(StocksLogistiqueComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    composant.vue = vue;
    composant.ngOnChanges();
  }

  it('dit où on en a, et met de côté ce qui est libre', () => {
    ouvrir('reservations');
    http.expectOne(r => r.url === `${api}/reservations/`).flush([]);
    composant.recherche = 'couverture';
    composant.chercher();
    http.expectOne(r => r.url === `${api}/disponibilite/` && r.params.get('recherche') === 'couverture').flush({ cherche: 'couverture', en_stock: true, quantite_demandee: null,
      articles: [{ article: 'a1', designation: 'Couverture de survie', reference: 'COUV', unite: 'unité', libre: '5',
        lieux: [{ depot: 'd1', depot_nom: 'Local', au_point: false, en_stock: '10', reserve: '5', libre: '5' }] }] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('10 en stock, dont 5 réservé(s)');

    composant.saisie('a1', 'd1').quantite = 3;
    composant.saisie('a1', 'd1').pour = 'Équipe Nord';
    composant.reserver('a1', 'd1');
    const envoi = http.expectOne(`${api}/reservations/`);
    expect(envoi.request.body).toEqual({ article: 'a1', depot: 'd1', quantite: 3, pour: 'Équipe Nord' });
    envoi.flush({ id: 'r1', article_designation: 'Couverture de survie', unite: 'unité', depot_nom: 'Local', quantite: '3.000', pour: 'Équipe Nord' });
    expect(composant.reservations.length).toBe(1);
    expect(composant.message).toContain('Mis de côté : 3 unité');
    http.match(() => true);
  });

  it('refuse de sortir une dotation sans dépôt, et montre ce qui manque', () => {
    ouvrir('dotations');
    const SAC = { id: 'l1', nom: 'Sac d’intervention', description: '', actif: true, lignes: [] };
    http.expectOne(`${api}/lots-types/`).flush([SAC]);
    composant.gesteLot(SAC, 'sortir');
    expect(composant.erreur).toContain('Choisissez d’abord le dépôt');

    composant.depotLot = 'd1';
    composant.gesteLot(SAC, 'sortir');
    http.expectOne(`${api}/lots-types/l1/sortir/`).flush({ detail: 'il manque 1 unité de Lampe frontale' }, { status: 400, statusText: 'Bad Request' });
    expect(composant.erreur).toContain('il manque 1 unité de Lampe frontale');
  });

  it('signale un contrôle en retard sans empêcher quoi que ce soit, et le note d’un geste', () => {
    ouvrir('appareils');
    const GROUPE = { id: 'ap1', designation: 'Groupe électrogène', numero: 'GE-2', etat: 'EN_SERVICE', etat_libelle: 'En service', depot: 'd1', depot_nom: 'Local',
      controle_libelle: 'Révision annuelle', controle_periodicite_mois: 12, controle_prochain_le: '2026-09-01', controle: 'en_retard', controles: [] } as unknown as AppareilStock;
    http.expectOne(`${api}/appareils/`).flush([GROUPE]);
    fixture.detectChanges();
    const page = fixture.nativeElement as HTMLElement;
    expect(page.querySelector('.pastille.rouge')!.textContent).toContain('en retard');
    expect(page.textContent).toContain('En service');               // en retard, mais toujours en service

    composant.controler(GROUPE, true);
    const envoi = http.expectOne(`${api}/appareils/ap1/controler/`);
    expect(envoi.request.body).toEqual({ conforme: true, commentaire: '' });
    envoi.flush({ ...GROUPE, controle: 'a_jour', controle_prochain_le: '2027-11-17' });
    expect(composant.appareils[0].controle).toBe('a_jour');
  });
});
