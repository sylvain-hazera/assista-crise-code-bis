import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { OuvertRejoindreComponent } from './ouvert-rejoindre.component';

describe('OuvertRejoindreComponent', () => {
  it('donne les réglages de la bande et l\'avertissement, sans aucune clé ni lien d\'administration', () => {
    TestBed.configureTestingModule({ providers: [provideRouter([])], imports: [OuvertRejoindreComponent] });
    const fixture = TestBed.createComponent(OuvertRejoindreComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const texte = el.textContent ?? '';
    expect(texte).toContain('869,525 MHz');
    expect(texte).toContain('27 dBm');
    expect(texte).toContain('ANFR');
    expect(texte.toLowerCase()).not.toContain('psk');
    expect(texte.toLowerCase()).not.toContain('clé');
    expect(el.querySelector('a[href*="admin"], a[href*="login"]')).toBeNull();
  });
});
