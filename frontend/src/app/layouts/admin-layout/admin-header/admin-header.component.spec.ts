import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { AdminHeaderComponent } from './admin-header.component';
import { AuthService } from '../../../auth/services/auth.service';

describe('AdminHeaderComponent', () => {
  let component: AdminHeaderComponent;
  let fixture: ComponentFixture<AdminHeaderComponent>;
  let menus: boolean[];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AdminHeaderComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    })
    .compileComponents();

    fixture = TestBed.createComponent(AdminHeaderComponent);
    component = fixture.componentInstance;
    menus = [];
    component.menusOuvertsChange.subscribe(v => menus.push(v));
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('ouvrir les notifications ferme le menu utilisateur', () => {
    component.toggleUserMenu();
    component.onNotificationsToggle(true);
    expect(component.showNotifications).toBeTrue();
    expect(component.showUserMenu).toBeFalse();
  });

  it('ouvrir le menu utilisateur ferme les notifications', () => {
    component.onNotificationsToggle(true);
    component.toggleUserMenu();
    expect(component.showUserMenu).toBeTrue();
    expect(component.showNotifications).toBeFalse();
  });

  it('signale au layout l\'ouverture et la fermeture des listes', () => {
    component.toggleUserMenu();
    component.fermerMenus();
    expect(menus).toEqual([true, false]);
  });

  it('la déconnexion ferme les listes et prévient le layout', () => {
    let deconnexions = 0;
    component.deconnexion.subscribe(() => deconnexions++);
    component.toggleUserMenu();
    component.logout();
    expect(component.showUserMenu).toBeFalse();
    expect(deconnexions).toBe(1);
  });

  it('le bouton du menu latéral dépend du mode mobile', () => {
    let emis = 0;
    component.toggleSidebar.subscribe(() => emis++);
    fixture.componentRef.setInput('isMobile', false);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.mobile-menu-toggle')).toBeNull();
    fixture.nativeElement.querySelector('.desktop-toggle').click();

    fixture.componentRef.setInput('isMobile', true);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.desktop-toggle')).toBeNull();
    fixture.nativeElement.querySelector('.mobile-menu-toggle').click();
    expect(emis).toBe(2);
  });

  it('en zone DEMO, l\'hôte porte la classe `demo-mode`', () => {
    spyOn(TestBed.inject(AuthService), 'getEnvironment').and.returnValue('DEMO');
    fixture.detectChanges();
    expect(fixture.nativeElement.classList).toContain('demo-mode');
  });
});
