import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { AdminLayoutComponent, LARGEUR_SIDEBAR } from './admin-layout.component';

const CLE_STOCKAGE_SIDEBAR = 'admin-sidebar-affichage';

function pointeur(type: string, clientX: number): PointerEvent {
  return new PointerEvent(type, { clientX, button: 0, pointerId: 1, bubbles: true });
}

describe('AdminLayoutComponent', () => {
  let component: AdminLayoutComponent;
  let fixture: ComponentFixture<AdminLayoutComponent>;

  beforeEach(async () => {
    localStorage.removeItem(CLE_STOCKAGE_SIDEBAR);
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
    component.etatSidebar = 'reduite';
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

  afterEach(() => localStorage.removeItem(CLE_STOCKAGE_SIDEBAR));

  describe('menu latéral sur grand écran', () => {
    let layout: HTMLElement;
    let poignee: HTMLElement;

    beforeEach(() => {
      component.isMobile = false;
      fixture.detectChanges();
      layout = fixture.nativeElement.querySelector('.admin-layout');
      poignee = fixture.nativeElement.querySelector('.poignee-sidebar');
    });

    function largeurGrille(): string {
      return layout.style.getPropertyValue('--sidebar-largeur');
    }

    it('le bouton de l\'en-tête masque le menu puis le réaffiche dans son état précédent', () => {
      component.basculerReduction();
      fixture.nativeElement.querySelector('.desktop-toggle').click();
      fixture.detectChanges();
      expect(component.etatSidebar).toBe('fermee');
      expect(largeurGrille()).toBe('0px');
      expect(fixture.nativeElement.querySelector('app-admin-sidebar').hasAttribute('inert')).toBeTrue();

      fixture.nativeElement.querySelector('.desktop-toggle').click();
      fixture.detectChanges();
      expect(component.etatSidebar).toBe('reduite');
    });

    it('le bouton du bas du menu réduit aux icônes puis rend les libellés', () => {
      fixture.nativeElement.querySelector('.reduction-btn').click();
      fixture.detectChanges();
      expect(component.etatSidebar).toBe('reduite');
      expect(largeurGrille()).toBe(`${LARGEUR_SIDEBAR.reduite}px`);

      fixture.nativeElement.querySelector('.reduction-btn').click();
      fixture.detectChanges();
      expect(largeurGrille()).toBe(`${LARGEUR_SIDEBAR.defaut}px`);
    });

    it('la poignée redimensionne en suivant le pointeur, dans les bornes, sans animation', () => {
      poignee.dispatchEvent(pointeur('pointerdown', 250));
      fixture.detectChanges();
      expect(layout.classList).toContain('redimensionnement');

      poignee.dispatchEvent(pointeur('pointermove', 320));
      fixture.detectChanges();
      expect(largeurGrille()).toBe('320px');

      poignee.dispatchEvent(pointeur('pointermove', 2000));
      fixture.detectChanges();
      expect(largeurGrille()).toBe(`${LARGEUR_SIDEBAR.max}px`);

      poignee.dispatchEvent(pointeur('pointerup', 2000));
      fixture.detectChanges();
      expect(layout.classList).not.toContain('redimensionnement');
    });

    it('glisser vers la gauche réduit aux icônes, puis ferme le menu', () => {
      component.largeurSidebar = 360;
      poignee.dispatchEvent(pointeur('pointerdown', 360));
      poignee.dispatchEvent(pointeur('pointermove', 180)); // bornée au minimum en passant
      poignee.dispatchEvent(pointeur('pointermove', 100));
      expect(component.etatSidebar).toBe('reduite');
      poignee.dispatchEvent(pointeur('pointermove', 10));
      poignee.dispatchEvent(pointeur('pointerup', 10));
      expect(component.etatSidebar).toBe('fermee');
      // La largeur d'avant le geste est gardée pour la réouverture.
      expect(component.largeurSidebar).toBe(360);
    });

    it('double-clic sur la poignée : largeur par défaut', () => {
      component.largeurSidebar = 380;
      poignee.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      expect(component.largeurSidebar).toBe(LARGEUR_SIDEBAR.defaut);
      expect(component.etatSidebar).toBe('etendue');
    });

    it('la poignée se règle au clavier', () => {
      poignee.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      expect(component.largeurSidebar).toBe(LARGEUR_SIDEBAR.defaut + 16);
      poignee.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
      expect(component.etatSidebar).toBe('reduite');
      poignee.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
      expect(component.etatSidebar).toBe('fermee');
    });

    it('l\'affichage du menu est retrouvé au rechargement', () => {
      poignee.dispatchEvent(pointeur('pointerdown', 250));
      poignee.dispatchEvent(pointeur('pointermove', 300));
      poignee.dispatchEvent(pointeur('pointerup', 300));

      const rechargement = TestBed.createComponent(AdminLayoutComponent).componentInstance;
      expect(rechargement.etatSidebar).toBe('etendue');
      expect(rechargement.largeurSidebar).toBe(300);
    });

    it('sur mobile, ni poignée ni bouton de réduction', () => {
      component.isMobile = true;
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.poignee-sidebar')).toBeNull();
      expect(fixture.nativeElement.querySelector('.reduction-btn')).toBeNull();
    });
  });
});
