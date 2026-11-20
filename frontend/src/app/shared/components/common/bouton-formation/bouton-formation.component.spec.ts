import { TestBed } from '@angular/core/testing';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { AuthService } from '../../../../auth/services/auth.service';
import { BoutonFormationComponent } from './bouton-formation.component';

describe('BoutonFormationComponent', () => {
  let auth: AuthService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    auth = TestBed.inject(AuthService);
  });

  function rendu() {
    const fixture = TestBed.createComponent(BoutonFormationComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('n\'apparait pas sans accès à la démonstration', () => {
    spyOn(auth, 'canAccessDemo').and.returnValue(false);
    expect(rendu().querySelector('button')).toBeNull();
  });

  it('demande confirmation, puis passe en formation', () => {
    spyOn(auth, 'canAccessDemo').and.returnValue(true);
    spyOn(auth, 'getEnvironment').and.returnValue('PROD');
    const bascule = spyOn(auth, 'setEnvironment');
    const confirmation = spyOn(window, 'confirm').and.returnValue(false);
    const bouton = rendu().querySelector('button')!;
    expect(bouton.getAttribute('aria-pressed')).toBe('false');
    bouton.click();
    expect(bascule).not.toHaveBeenCalled();                      // « Annuler » : rien ne change
    confirmation.and.returnValue(true);
    bouton.click();
    expect(confirmation.calls.mostRecent().args[0]).toContain('Passer en formation');
    expect(bascule).toHaveBeenCalledWith('DEMO');
  });

  it('en formation, revient aux données réelles', () => {
    spyOn(auth, 'canAccessDemo').and.returnValue(true);
    spyOn(auth, 'getEnvironment').and.returnValue('DEMO');
    const bascule = spyOn(auth, 'setEnvironment');
    spyOn(window, 'confirm').and.returnValue(true);
    const bouton = rendu().querySelector('button')!;
    expect(bouton.classList).toContain('active');
    bouton.click();
    expect(bascule).toHaveBeenCalledWith('PROD');
  });
});
