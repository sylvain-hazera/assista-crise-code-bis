import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { ReleveGeorisquesComponent } from './releve-georisques.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';

describe('ReleveGeorisquesComponent', () => {
  it("affiche les servitudes d'utilité publique par catégorie, avec leur acte", () => {
    TestBed.configureTestingModule({ imports: [ReleveGeorisquesComponent], providers: fournisseursDeTest() });
    const http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ReleveGeorisquesComponent);
    fixture.detectChanges();
    http.expectOne(`${environment.apiUrl}/dossier-pcs/georisques/`).flush({
      commune_code: '33200', releve: true, releve_le: '2026-11-22', complet: true, rubriques: [], sismicite: '', radon: '',
      catnat: { nombre: 0, derniers: [] }, azi: [], tri: [], mouvements: [], cavites: 0,
      servitudes: [{ categorie: 'i4', libelle: 'Lignes électriques', nombre: 3,
                     actes: [{ nom: 'I4 ligne', url: 'https://data.geopf.fr/annexes/gpu/documents/x/y/I4_act.pdf' }] }],
    });
    fixture.detectChanges();
    const texte: string = fixture.nativeElement.textContent;
    expect(texte).toContain('Servitudes d\'utilité publique');
    expect(texte).toContain('Lignes électriques : 3 emprises');
    expect(fixture.nativeElement.querySelector('a[href$="I4_act.pdf"]')).not.toBeNull();
  });
});
