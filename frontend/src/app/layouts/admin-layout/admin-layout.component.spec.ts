import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { AdminLayoutComponent } from './admin-layout.component';

describe('AdminLayoutComponent', () => {
  let component: AdminLayoutComponent;
  let fixture: ComponentFixture<AdminLayoutComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AdminLayoutComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    })
    .compileComponents();

    fixture = TestBed.createComponent(AdminLayoutComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('ouvrir les notifications ferme le menu utilisateur', () => {
    component.showUserMenu = true;
    component.onNotificationsToggle(true);
    expect(component.showNotifications).toBeTrue();
    expect(component.showUserMenu).toBeFalse();
  });

  it('les styles du layout et du menu s\'appliquent à travers les composants enfants', () => {
    const sidebar: HTMLElement = fixture.nativeElement.querySelector('app-admin-sidebar');
    expect(getComputedStyle(sidebar).display).toBe('flex');
    expect(getComputedStyle(sidebar).gridArea).toContain('sidebar');

    component.isMobile = false;
    component.sidebarCollapsed = true;
    fixture.detectChanges();
    const label: HTMLElement = sidebar.querySelector('.sidebar-footer .nav-label')!;
    expect(sidebar.classList).toContain('collapsed');
    expect(getComputedStyle(label).overflow).toBe('hidden'); // opacity est animée (transition)
  });

  it('ouvrir le menu utilisateur ferme les notifications', () => {
    component.showNotifications = true;
    component.toggleUserMenu();
    expect(component.showUserMenu).toBeTrue();
    expect(component.showNotifications).toBeFalse();
  });
});
