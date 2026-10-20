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

  it('l\'en-tête est placé dans la grille et stylé par son propre composant', () => {
    const header: HTMLElement = fixture.nativeElement.querySelector('app-admin-header');
    const style = getComputedStyle(header);
    expect(style.gridArea).toContain('header');
    expect(style.position).toBe('sticky');
    expect(style.display).toBe('flex');
  });

  it('une liste ouverte dans l\'en-tête affiche le fond, qui la referme au clic', () => {
    const userButton: HTMLElement = fixture.nativeElement.querySelector('.user-button');
    userButton.click();
    fixture.detectChanges();
    const fond: HTMLElement = fixture.nativeElement.querySelector('.dropdown-overlay');
    expect(fond).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.user-dropdown')).not.toBeNull();

    fond.click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.dropdown-overlay')).toBeNull();
    expect(fixture.nativeElement.querySelector('.user-dropdown')).toBeNull();
  });

  it('le bouton de l\'en-tête réduit le menu latéral sur desktop', () => {
    component.isMobile = false;
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.desktop-toggle').click();
    fixture.detectChanges();
    expect(component.sidebarCollapsed).toBeTrue();
  });
});
