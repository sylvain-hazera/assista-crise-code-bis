import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { AvisDonsComponent } from './avis-dons.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';

/** Les avis d'appels aux dons, lisibles de tous ; s'engager passe par une institution du réseau. */
describe('AvisDonsComponent', () => {
  let fixture: ComponentFixture<AvisDonsComponent>;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.removeItem('current_user');
    TestBed.configureTestingModule({ imports: [AvisDonsComponent], providers: fournisseursDeTest() });
    fixture = TestBed.createComponent(AvisDonsComponent);
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  it('dit ce qu’il faut, pour qui, ce qui est couvert, et renvoie vers une institution du réseau', () => {
    http.expectOne(`${environment.apiUrl}/dons/avis/`).flush({
      comment_aider: 'Passez par une association ou une mairie : elle rejoint le réseau gratuitement.',
      avis: [{ id: 'a1', titre: 'Familles sinistrées du feu', description: '', institution_nom: 'Mairie de La Teste', crise_nom: 'Feu', date_ouverture: null,
        pieces_voulues: 13, pieces_restantes: 12, portee_km: 100, portee: 'dans un rayon de 100 km', lignes: [
          { famille: 'PUERICULTURE', famille_libelle: 'Puériculture', formulation: 'Chauffe-biberon — pour 1 bébé', message: '', neuf_exige: false, reste: 0, couvert: true, urgent: false },
          { famille: 'LOISIRS', famille_libelle: 'Jeux, jouets et loisirs', formulation: 'Vélo — pour 1 fille', message: 'Elle avait un vélo rose.', neuf_exige: false, reste: 1, couvert: false, urgent: false },
          { famille: 'VETEMENTS', famille_libelle: 'Vêtements et chaussures', formulation: 'T-shirt, taille L — pour 3 hommes (12 pièces)', message: '', neuf_exige: false, reste: 11, couvert: false, urgent: true }] }],
    });
    fixture.detectChanges();
    const page = fixture.nativeElement as HTMLElement;

    expect(page.textContent).toContain('T-shirt, taille L — pour 3 hommes (12 pièces)');
    expect(page.textContent).toContain('« Elle avait un vélo rose. »');
    expect(page.querySelector('li.couvert')!.textContent).toContain('Chauffe-biberon');
    expect(page.textContent).toContain('rejoint le réseau gratuitement');
    expect(page.textContent).toContain('Appel lancé dans un rayon de 100 km');
    expect(page.querySelector('a[href="/register"]')).not.toBeNull();     // pas de compte : on invite à rejoindre le réseau
    expect(page.textContent).not.toContain('Voir les appels et s\'engager');
  });

  it('le dit quand aucun appel n’est ouvert', () => {
    http.expectOne(`${environment.apiUrl}/dons/avis/`).flush({ avis: [], comment_aider: '' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Aucun appel aux dons n\'est ouvert');
  });
});
