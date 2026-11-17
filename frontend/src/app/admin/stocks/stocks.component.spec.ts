import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { StocksComponent } from './stocks.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { EtatStock } from '../../shared/models/stock.model';

/** Gestion des stocks : on enregistre des mouvements, jamais une quantité. */
describe('StocksComponent', () => {
  let fixture: ComponentFixture<StocksComponent>;
  let composant: StocksComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const ETAT: EtatStock = {
    institution: 'i1', institution_nom: 'Réserve des essais', valeur_totale: '105.00', jours_alerte_peremption: 30,
    alertes: { sous_seuil: 1, perimes: 0, bientot_perimes: 1, mal_ranges: 1 },
    depots: [
      { id: 'd1', institution: 'i1', nom: 'Local', adresse: '', commentaire: '', actif: true, latitude: null, longitude: null,
        froid_positif: false, froid_negatif: false, cuisson: 'AUCUNE' },
      { id: 'd2', institution: 'i1', nom: 'Camion', adresse: '', commentaire: '', actif: true, latitude: null, longitude: null,
        froid_positif: false, froid_negatif: false, cuisson: 'AUCUNE' },
    ],
    articles: [
      { id: 'a1', reference: 'COUV', designation: 'Couverture de survie', categorie: '', unite: 'unité', seuil_alerte: '20.000',
        perissable: false, prix_unitaire: '1.5000', code_barres: '3760001000017', description: '', actif: true, total: '70.000',
        par_depot: { d1: '55.000', d2: '15.000' }, lots: [], sous_seuil: false, perime: '0', bientot_perime: '0',
        prochaine_peremption: null, valeur: '105.00', conservation: 'AMBIANT', preparation: '', mal_range: [], reserve: '6.000', disponible: '64.000' },
      { id: 'a2', reference: 'MASQ', designation: 'Masque FFP2', categorie: '', unite: 'boîte', seuil_alerte: '10.000',
        perissable: true, prix_unitaire: null, code_barres: '', description: '', actif: true, total: '2.500',
        par_depot: { d1: '2.500' }, lots: [], sous_seuil: true, perime: '0', bientot_perime: '2.500',
        prochaine_peremption: '2026-12-01', valeur: null, conservation: 'FRAIS', preparation: 'A_RECHAUFFER',
        reserve: '0', disponible: '2.500', mal_range: [{ depot: 'd1', nom: 'Local', manques: ['à garder au frais, et ce lieu n\'a pas de réfrigérateur'] }] },
    ],
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [StocksComponent], providers: fournisseursDeTest() });
    fixture = TestBed.createComponent(StocksComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(`${api}/stocks/etat/`).flush(ETAT);
    http.match(() => true).forEach(r => r.flush([]));            // les crises
    fixture.detectChanges();
  });

  it('montre le stock, sa répartition et ses alertes', () => {
    const page = (fixture.nativeElement as HTMLElement).textContent!;

    expect(page).toContain('Couverture de survie');
    expect(page).toContain('Local : 55 · Camion : 15');
    expect(page).toContain('à réapprovisionner');
    expect(page).toContain('2,5 bientôt');
    expect(page).toContain('Local : à garder au frais');             // denrée rangée sans froid
    expect(page).toContain('À réchauffer');
    composant.alertesSeulement = true;
    expect(composant.lignes.map(a => a.reference)).toEqual(['MASQ']);
    composant.alertesSeulement = false;
    composant.recherche = 'couv';
    expect(composant.lignes.map(a => a.reference)).toEqual(['COUV']);
  });

  it('enregistre une sortie depuis la ligne de l’article, et dit ce qu’il reste dans le dépôt', () => {
    composant.ouvrirMouvement('SORTIE', ETAT.articles[1]);
    expect(composant.mouvement!.depot).toBe('d1');                // le seul dépôt qui en a
    expect(composant.disponible).toBe('2.500');
    expect(composant.mouvementComplet).toBeFalse();               // pas encore de quantité

    composant.mouvement!.quantite = 2;
    composant.mouvement!.motif = 'Dotation équipe Nord';
    composant.enregistrerMouvement();

    const envoi = http.expectOne(`${api}/stocks/mouvements/`);
    expect(envoi.request.body).toEqual({ article: 'a2', depot: 'd1', type: 'SORTIE', quantite: 2, motif: 'Dotation équipe Nord' });
    envoi.flush({ mouvements: [{}], stock: '0.500' }, { status: 201, statusText: 'Created' });
    http.expectOne(`${api}/stocks/etat/`).flush(ETAT);
    expect(composant.mouvement).toBeNull();
    expect(composant.message).toContain('Sortie enregistrée');
  });

  it('affiche le refus du serveur quand le compte n’y est pas', () => {
    composant.ouvrirMouvement('SORTIE', ETAT.articles[1]);
    composant.mouvement!.quantite = 99;
    composant.enregistrerMouvement();
    http.expectOne(`${api}/stocks/mouvements/`).flush({ detail: 'Il n\'y a que 2,5 boîte de « Masque FFP2 »' }, { status: 400, statusText: 'Bad Request' });

    expect(composant.erreur).toContain('Il n\'y a que 2,5');
    expect(composant.mouvement).not.toBeNull();                   // la saisie reste, à corriger
  });

  it('exige un dépôt d’arrivée différent pour un transfert, et une quantité comptée pour un inventaire', () => {
    composant.ouvrirMouvement('TRANSFERT', ETAT.articles[0]);
    composant.mouvement!.depot = 'd1';
    composant.mouvement!.quantite = 5;
    expect(composant.mouvementComplet).toBeFalse();
    composant.mouvement!.depot_destination = 'd2';
    expect(composant.mouvementComplet).toBeTrue();

    composant.ouvrirMouvement('INVENTAIRE', ETAT.articles[1]);
    composant.mouvement!.quantite = 0;                            // « j'ai compté zéro » est un inventaire valable
    expect(composant.mouvementComplet).toBeTrue();
    expect(composant.libelleQuantite).toBe('Quantité comptée');
  });

  it('saisit un inventaire d’un bloc : seules les lignes comptées partent', () => {
    composant.ouvrirInventaire(ETAT.depots[0]);
    http.expectOne(r => r.url === `${api}/stocks/inventaire/` && r.params.get('depot') === 'd1').flush({ depot: 'd1', depot_nom: 'Local', lignes: [
      { article: 'a1', reference: 'COUV', designation: 'Couverture de survie', unite: 'unité', lot: '', date_peremption: null, attendu: '55.000' },
      { article: 'a2', reference: 'MASQ', designation: 'Masque FFP2', unite: 'boîte', lot: 'L7', date_peremption: '2027-06-30', attendu: '2.500' }] });
    expect(composant.lignesComptees).toBe(0);

    composant.inventaire!.lignes[1].compte = 0;                    // « il n'y en a plus » est un compte
    composant.enregistrerInventaire();

    const envoi = http.expectOne(`${api}/stocks/inventaire/`);
    expect(envoi.request.body).toEqual({ depot: 'd1', comptes: [{ article: 'a2', quantite: 0, lot: 'L7', date_peremption: '2027-06-30' }] });
    envoi.flush({ comptees: 1, corrections: [{}] }, { status: 201, statusText: 'Created' });
    http.expectOne(`${api}/stocks/etat/`).flush(ETAT);
    expect(composant.message).toContain('1 ligne(s) comptée(s), 1 correction(s)');
  });

  it('retrouve un article par son code-barres ou sa référence, sans jamais l’exiger', () => {
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('dont 6 réservé(s)');

    composant.surCode('3760001000017');
    expect(composant.mouvement!.article).toBe('a1');
    expect(composant.message).toContain('Couverture de survie : 70 unité en stock');

    composant.surCode('masq');                                       // la référence sert aussi de code
    expect(composant.mouvement!.article).toBe('a2');

    composant.surCode('0000');
    expect(composant.erreur).toContain('Aucun article ne porte le code « 0000 »');
  });

  it('vérifie un fichier avant de le reprendre', () => {
    composant.ouvrirImport();
    composant.fichierImport = new File(['Réf.;Libellé\nA;B\n'], 'export.csv', { type: 'text/csv' });
    composant.importer(true);
    const verification = http.expectOne(`${api}/stocks/import/`);
    expect((verification.request.body as FormData).get('simuler')).toBe('1');
    verification.flush({ colonnes: ['reference', 'designation'], lignes: 1, articles_crees: 1, articles_existants: 0, depots_crees: 0,
      quantites_posees: 0, erreurs: [], simulation: true });
    expect(composant.bilanImport!.simulation).toBeTrue();

    composant.importer(false);
    const reprise = http.expectOne(`${api}/stocks/import/`);
    expect((reprise.request.body as FormData).get('simuler')).toBeNull();
    reprise.flush({ colonnes: [], lignes: 1, articles_crees: 1, articles_existants: 0, depots_crees: 0, quantites_posees: 0, erreurs: [], simulation: false });
    http.expectOne(`${api}/stocks/etat/`).flush(ETAT);
  });
});
