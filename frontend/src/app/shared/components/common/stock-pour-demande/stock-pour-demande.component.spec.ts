import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { StockPourDemandeComponent } from './stock-pour-demande.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';

/** Face à une demande de matériel : « on l'a en stock ? », puis « réserver pour cette demande ». */
describe('StockPourDemandeComponent', () => {
  let fixture: ComponentFixture<StockPourDemandeComponent>;
  let composant: StockPourDemandeComponent;
  let http: HttpTestingController;
  const api = `${environment.apiUrl}/stocks`;
  const TROUVE = { cherche: 'Pompe', en_stock: true, quantite_demandee: 1, articles: [{ article: 'a1', designation: 'Pompe vide-cave', reference: 'POMPE', unite: 'unité', libre: '2',
    lieux: [{ depot: 'd1', depot_nom: 'Local', au_point: false, en_stock: '3', reserve: '1', libre: '2' }] }] };

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [StockPourDemandeComponent], providers: fournisseursDeTest() });
    fixture = TestBed.createComponent(StockPourDemandeComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    composant.demande = 'dem1';
    composant.indice = 'Cave inondée';
    fixture.detectChanges();
  });

  it('cherche d’après ce que la demande réclame, dit où c’est, et réserve pour elle', () => {
    (fixture.nativeElement as HTMLElement).querySelector('button')!.click();      // « On l'a en stock ? »
    http.expectOne(r => r.url === `${api}/disponibilite/` && r.params.get('demande') === 'dem1').flush(TROUVE);
    fixture.detectChanges();
    const page = fixture.nativeElement as HTMLElement;
    expect(page.textContent).toContain('Local : 2 libre(s) — 1 déjà réservé(s)');

    composant.quantites['a1d1'] = 1;
    fixture.detectChanges();
    const reserver = Array.from(page.querySelectorAll('button')).find(b => b.textContent!.includes('Réserver pour cette demande'))!;
    reserver.click();
    const envoi = http.expectOne(`${api}/reservations/`);
    expect(envoi.request.body).toEqual({ article: 'a1', depot: 'd1', quantite: 1, demande: 'dem1' });
    envoi.flush({ quantite: '1.000', unite: 'unité', article_designation: 'Pompe vide-cave' });
    expect(composant.message).toContain('Réservé pour cette demande : 1 unité de Pompe vide-cave, dans Local');
  });

  it('laisse chercher par un mot quand la demande ne désigne aucun matériel', () => {
    composant.chercher();
    http.expectOne(r => r.params.get('demande') === 'dem1').flush({ cherche: '', en_stock: false, quantite_demandee: null, articles: [] });
    expect(composant.mot).toBe('Cave inondée');                       // le titre du dossier sert d'indice
    composant.mot = 'pompe';
    composant.chercher();
    http.expectOne(r => r.params.get('recherche') === 'pompe').flush(TROUVE);
    expect(composant.resultat!.articles.length).toBe(1);
  });
});
