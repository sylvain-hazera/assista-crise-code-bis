import { ComponentFixture, TestBed } from '@angular/core/testing';

import { HomeComponent } from './home.component';
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
    expect(lien!.getAttribute('href')).toBe('/mobile/reserve-resilience.apk');
    expect(lien!.hasAttribute('download')).toBeTrue();
  });
});
