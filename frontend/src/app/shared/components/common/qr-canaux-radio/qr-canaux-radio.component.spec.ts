import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { environment } from '../../../../../environments/environment';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { QrCanauxRadioComponent } from './qr-canaux-radio.component';

describe('QR code des canaux radio (25/11/2026)', () => {
  let http: HttpTestingController;

  function creer(entrees: Record<string, string>) {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(QrCanauxRadioComponent);
    Object.entries(entrees).forEach(([k, v]) => fixture.componentRef.setInput(k, v));
    fixture.detectChanges();
    return fixture;
  }

  it('crise : rien n’est demandé avant le clic, puis le QR et les canaux', () => {
    const fixture = creer({ crise: 'c1' });
    http.expectNone(() => true);
    fixture.componentInstance.afficher();
    http.expectOne(`${environment.apiUrl}/radio/lien-crise/?crise=c1`).flush({
      meshtastic_lien: 'https://meshtastic.org/e/?add=true#x', meshtastic: ['CriseGier', 'Rive'], meshcore: ['#crisegier'],
      qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1H0z"/></svg>',
    });
    fixture.detectChanges();
    const texte = (fixture.nativeElement as HTMLElement).textContent!;
    expect((fixture.nativeElement as HTMLElement).querySelector('.qr svg')).not.toBeNull();
    expect(texte).toContain('CriseGier, Rive');
    expect(texte).not.toContain('ne le montrez');
  });

  it('équipe : avertit que le QR contient la clé, montre les clés MeshCore à saisir', () => {
    const fixture = creer({ equipe: 'e1' });
    fixture.componentInstance.afficher();
    http.expectOne(`${environment.apiUrl}/teams/e1/lien-canaux/`).flush({
      meshtastic_lien: 'x', meshtastic: [{ role: 'equipe', nom: 'AC-ALPH' }],
      meshcore: [{ role: 'equipe', nom: 'AC-ALPH', cle_hex: 'ab'.repeat(16) }], qr_svg: '<svg></svg>', crise: null,
    });
    fixture.detectChanges();
    const texte = (fixture.nativeElement as HTMLElement).textContent!;
    expect(texte).toContain('ne le montrez qu’à ses membres'.replace('’', "'"));
    expect(texte).toContain('ab'.repeat(16));
  });
});
