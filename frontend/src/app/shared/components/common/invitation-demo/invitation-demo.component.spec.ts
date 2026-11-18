import { ComponentFixture, TestBed } from '@angular/core/testing';
import { InvitationDemoComponent } from './invitation-demo.component';
import { AuthService } from '../../../../auth/services/auth.service';

describe('InvitationDemoComponent', () => {
  let fixture: ComponentFixture<InvitationDemoComponent>;
  let auth: jasmine.SpyObj<AuthService>;

  function creer(accesDemo: boolean, zone: 'PROD' | 'DEMO') {
    sessionStorage.removeItem('invitation_demo_masquee');
    auth = jasmine.createSpyObj('AuthService', ['canAccessDemo', 'getEnvironment', 'setEnvironment']);
    auth.canAccessDemo.and.returnValue(accesDemo);
    auth.getEnvironment.and.returnValue(zone);
    TestBed.configureTestingModule({
      imports: [InvitationDemoComponent],
      providers: [{ provide: AuthService, useValue: auth }],
    });
    fixture = TestBed.createComponent(InvitationDemoComponent);
    fixture.detectChanges();
  }

  afterEach(() => sessionStorage.removeItem('invitation_demo_masquee'));

  it('invite en production un compte qui a accès à la démonstration, et y mène', () => {
    creer(true, 'PROD');
    const bouton = fixture.nativeElement.querySelector('.aller') as HTMLButtonElement;
    expect(bouton).toBeTruthy();
    bouton.click();
    expect(auth.setEnvironment).toHaveBeenCalledWith('DEMO');
  });

  it("ne s'affiche ni en démonstration ni pour un compte sans accès", () => {
    creer(true, 'DEMO');
    expect(fixture.nativeElement.querySelector('.invitation')).toBeNull();
    TestBed.resetTestingModule();
    creer(false, 'PROD');
    expect(fixture.nativeElement.querySelector('.invitation')).toBeNull();
  });

  it('se masque pour la session', () => {
    creer(true, 'PROD');
    (fixture.nativeElement.querySelector('.masquer') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.invitation')).toBeNull();
    expect(sessionStorage.getItem('invitation_demo_masquee')).toBe('1');
  });
});
