import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { StocksCommandesComponent } from './stocks-commandes.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';
import { CommandeStock } from '../../../shared/models/stock.model';

/** Commandes aux fournisseurs : brouillon, commande passée, réception qui entre en stock. */
describe('StocksCommandesComponent', () => {
  let composant: StocksCommandesComponent;
  let http: HttpTestingController;
  const api = `${environment.apiUrl}/stocks`;
  const COMMANDE = {
    id: 'c1', numero: 'CF-2026-0001', tiers: 't1', tiers_nom: 'Protec SARL', statut: 'COMMANDEE', statut_libelle: 'Commandée',
    depot: 'd1', depot_nom: 'Local', date_commande: '2026-11-10', livraison_prevue: null, commentaire: '', total: '120.00',
    lignes: [{ id: 'l1', article: 'a1', article_designation: 'Couverture de survie', unite: 'unité', quantite: '100.000',
               prix_unitaire: '1.2000', quantite_recue: '60.000' }],
  } as CommandeStock;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [StocksCommandesComponent], providers: fournisseursDeTest() });
    const fixture = TestBed.createComponent(StocksCommandesComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(`${api}/commandes/`).flush([COMMANDE]);
    http.expectOne(`${api}/factures/`).flush([]);
    http.expectOne(`${api}/tiers/`).flush([]);
  });

  it('propose à la réception ce qui reste attendu, et prévient la page que le stock est entré', () => {
    const change = spyOn(composant.stockChange, 'emit');

    composant.ouvrirReception(COMMANDE);
    expect(composant.reception!.lignes[0].quantite).toBe(40);       // 100 commandés, 60 déjà reçus
    composant.reception!.lignes[0].lot = 'L2';
    composant.recevoir();

    const envoi = http.expectOne(`${api}/commandes/c1/recevoir/`);
    expect(envoi.request.body).toEqual({ depot: 'd1', receptions: [{ ligne: 'l1', quantite: 40, lot: 'L2' }] });
    envoi.flush({ ...COMMANDE, statut: 'RECUE', statut_libelle: 'Reçue' });
    expect(change).toHaveBeenCalled();
    expect(composant.commandes[0].statut).toBe('RECUE');
  });

  it('n’enregistre un brouillon qu’avec un fournisseur et des lignes complètes, et en dit le total', () => {
    composant.nouvelle();
    expect(composant.brouillonComplet).toBeFalse();
    composant.brouillon!.tiers = 't1';
    composant.brouillon!.lignes[0] = { article: 'a1', quantite: 10, prix_unitaire: 2.5 };
    expect(composant.brouillonComplet).toBeTrue();
    expect(composant.totalBrouillon).toBe(25);

    composant.enregistrer();
    const envoi = http.expectOne(`${api}/commandes/`);
    expect(envoi.request.body.lignes.length).toBe(1);
    envoi.flush({ ...COMMANDE, id: 'c2', numero: 'CF-2026-0002', statut: 'BROUILLON' });
    expect(composant.commandes.length).toBe(2);
  });
});
