import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { RappelPlanIncompletComponent } from './rappel-plan-incomplet.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';

/** Un plan incomplet ne doit jamais empêcher de conduire une crise : le rappel dit ce qui
 * manque et où y revenir, sans rien bloquer et sans s'imposer. */
describe('RappelPlanIncompletComponent', () => {
  let fixture: ComponentFixture<RappelPlanIncompletComponent>;
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/dossier-pcs/`;
  const ZONES = { partie: 'Zones', message: "La commune n'est pas découpée en quartiers.", ou: 'Zones', route: '/admin/zones' };

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [RappelPlanIncompletComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RappelPlanIncompletComponent);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('dit que cela n’empêche rien, replié, puis montre où compléter dans un nouvel onglet', () => {
    http.expectOne(url).flush({ manques: [ZONES] });
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('incomplet sur 1 point');
    expect(element.textContent).toContain("Cela n'empêche rien");
    expect(element.querySelector('ul')).toBeNull();

    (element.querySelector('.entete') as HTMLButtonElement).click();
    fixture.detectChanges();
    const lien = element.querySelector('a') as HTMLAnchorElement;
    expect(lien.getAttribute('href')).toBe('/admin/zones');
    expect(lien.target).toBe('_blank');
  });

  it('se tait quand le plan est complet', () => {
    http.expectOne(url).flush({ manques: [] });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent!.trim()).toBe('');
  });

  it('se tait aussi quand le plan ne peut pas être lu : jamais une alerte de plus en crise', () => {
    http.expectOne(url).flush({ detail: 'refus' }, { status: 403, statusText: 'Forbidden' });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent!.trim()).toBe('');
  });
});
