import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { OuvertAccueilComponent } from './ouvert-accueil.component';
import { fournisseursDeTest } from '../../testing/test-providers';

/** `/ouvert` : une seule adresse, des boutons vers chaque page, des lignes d'état en direct. */
describe('OuvertAccueilComponent', () => {
  it('propose les cinq pages, sans lien vers la connexion, avec leur état', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting(), provideRouter([])], imports: [OuvertAccueilComponent] });
    const fixture = TestBed.createComponent(OuvertAccueilComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/carte-ouverte/')).flush({
      cellules_orageuses: 3, repeteurs: 148, kp: 2.67, g: 0, g_libelle: 'aucun', occupation_canal: 8, couvertures: 1,
    });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const liens = Array.from(el.querySelectorAll('a.entree')).map(a => a.getAttribute('href'));
    expect(liens).toEqual(['/ouvert/carte', '/ouvert/carte?vue=propagation', '/ouvert/carte?vue=liaison', '/ouvert/reseau', '/ouvert/rejoindre']);
    const texte = el.textContent ?? '';
    expect(texte).toContain('3 cellules orageuses');
    expect(texte).toContain('Kp 2,7');
    expect(texte).toContain('148 répéteurs');
    expect(el.querySelector('a[href*="login"], a[href*="admin"]')).toBeNull();
  });

  it('garde ses boutons quand le résumé ne répond pas', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting(), provideRouter([])], imports: [OuvertAccueilComponent] });
    const fixture = TestBed.createComponent(OuvertAccueilComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/carte-ouverte/')).flush('', { status: 500, statusText: 'Erreur' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('a.entree').length).toBe(5);
  });
});
