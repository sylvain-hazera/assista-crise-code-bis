import { ComponentFixture, TestBed } from '@angular/core/testing';

import { HomeComponent, lienDeLApplication } from './home.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('HomeComponent', () => {
  let component: HomeComponent;
  let fixture: ComponentFixture<HomeComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [HomeComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(HomeComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it("propose de télécharger l'application Android, à l'adresse où chaque version est déposée", () => {
    const lien: HTMLAnchorElement | null = fixture.nativeElement.querySelector('a.btn-appli');

    expect(lien).withContext('lien de téléchargement').not.toBeNull();
    expect(lien!.textContent).toContain("Télécharger l'application Android");
    // Les tests tournent sur localhost : c'est l'application Assista-Crise qui y est proposée.
    expect(lien!.getAttribute('href')).toBe('/mobile/assista-crise.apk');
    // Une application par marque : chaque domaine sert la sienne.
    expect(lienDeLApplication('app.reserve-resilience.org')).toBe('/mobile/reserve-resilience.apk');
    expect(lienDeLApplication('www.assista-crise.fr')).toBe('/mobile/assista-crise.apk');
    expect(lienDeLApplication('192.168.1.20')).toBe('/mobile/assista-crise.apk');
    expect(lien!.hasAttribute('download')).toBeTrue();
  });
});
