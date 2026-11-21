import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';

import { DepotEnregistreComponent, TEXTES_DEPOT } from './depot-enregistre.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';

function creer(type: string | null, connecte: boolean) {
  TestBed.configureTestingModule({
    providers: [
      ...fournisseursDeTest(),
      { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(type ? { type } : {}) } } },
    ],
    imports: [DepotEnregistreComponent],
  });
  spyOn(TestBed.inject(AuthService), 'getCurrentUser').and.returnValue(connecte ? ({ id: 'u' } as any) : null);
  const fixture = TestBed.createComponent(DepotEnregistreComponent);
  fixture.detectChanges();
  return fixture;
}

describe('DepotEnregistreComponent', () => {
  it("renvoie vers l'onglet « Mon espace » de ce qui vient d'être déposé", () => {
    const fixture = creer('offre', true);
    expect(fixture.componentInstance.texte).toBe(TEXTES_DEPOT.offre);
    const lien: HTMLAnchorElement = fixture.nativeElement.querySelector('a.btn-primary');
    expect(lien.textContent).toContain('Voir ce que je propose');
    expect(lien.getAttribute('href')).toContain('tab=offer');
  });

  it("sans compte, ne propose pas « Mon espace » mais le dit", () => {
    const fixture = creer('signalement', false);
    expect(fixture.nativeElement.querySelector('a.btn-primary')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Avec un compte');
  });

  it('un type inconnu retombe sur la demande', () => {
    expect(creer('nimporte', false).componentInstance.texte).toBe(TEXTES_DEPOT.demande);
  });
});
