import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';

import { RecevoirRapportComponent } from './recevoir-rapport.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';

/** Le lien reçu par courriel : le rapport part à l'adresse du lien, jamais à une autre. */
describe('RecevoirRapportComponent', () => {
  let fixture: ComponentFixture<RecevoirRapportComponent>;
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/rapports/recevoir/JETON-1/`;
  const REMISE = { rapport: 'Dossier DOS-2026-014 — Cave inondée', crise: 'Crue du Gier', adresse: 'j•••••@exemple.fr',
                   disponible_jusqu_au: '2026-11-23T10:00:00Z', deja_envoye: false };
  const texte = () => (fixture.nativeElement as HTMLElement).textContent!;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [RecevoirRapportComponent],
      providers: [...fournisseursDeTest(), { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ jeton: 'JETON-1' }) } } }],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RecevoirRapportComponent);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('montre quel rapport part à quelle adresse, puis l’envoie à la demande', () => {
    http.expectOne(url).flush(REMISE);
    fixture.detectChanges();
    expect(texte()).toContain('Dossier DOS-2026-014');
    expect(texte()).toContain('j•••••@exemple.fr');

    (fixture.nativeElement.querySelector('button') as HTMLButtonElement).click();
    const envoi = http.expectOne(url);
    expect(envoi.request.method).toBe('POST');
    envoi.flush({ ...REMISE, envoye: true, deja_envoye: true });
    fixture.detectChanges();
    expect(texte()).toContain('vient d\'être envoyé à j•••••@exemple.fr');
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });

  it('dit quand le lien est mort (crise close) et ne propose rien', () => {
    http.expectOne(url).flush({ error: "Ce lien n'est plus valable : la crise est close, ou le lien n'existe pas." },
      { status: 410, statusText: 'Gone' });
    fixture.detectChanges();
    expect(texte()).toContain('la crise est close');
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });
});
